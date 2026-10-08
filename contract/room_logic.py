"""What the room board decides. Reference implementation in plain Python.

The firmware must behave the same way: same thresholds, same events, same order.
docs/BOARD_LOGIC.md explains each rule in words. The numbers below are starting
values to tune on the real rig, not measured facts.
"""
from collections import deque

DEFAULTS = dict(
    LOW_MM=40,               # below this the tank counts as empty
    MIN_USE_S=3,             # door must stay closed this long to count as a use
    SLOPE_WINDOW_S=20,       # window for the water-level slope
    TAP_RATE=6,              # mm/min of fall that counts as "water running"
    TAP_SUSPECT_S=15, TAP_CONFIRM_S=45, TAP_CLEAR_S=10,
    GAS_BAD_PCT=125, GAS_OK_PCT=112, GAS_BAD_S=10,
    BASELINE_STABLE_S=60,    # quiet time needed before the gas normal level is learned
    STEAM_RISE=50,           # humidity rise (x10) inside STEAM_WINDOW_S that means steam
    STEAM_WINDOW_S=30, STEAM_SETTLE=30, STEAM_MAX_S=900,
    HUM_ON=750, HUM_OFF=680, FAN_MIN_ON_S=20,
    VERIFY_S=60,             # how long after the fan starts before we judge it
    VERIFY_HUM_DROP=80,      # humidity (x10) must fall this much; set between "fan off" and "fan on" drops
    VERIFY_GAS_DROP=5,       # air percent must fall this much
    CLEAN_USES=5,
    SENSOR_TIMEOUT_S=3, LINK_TIMEOUT_S=3,
)


class RoomLogic:
    def __init__(self, **cfg):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(cfg)
        self.seq = 0
        self.events = []                 # (t, seq, code, a, b) since the last collect()
        self.state = "FREE"
        self.fan = False
        self.uses = 0
        self.level_rate = 0
        self.gas_pct = 0
        self.baseline = None
        self.manual = None               # None = automatic, True/False = override
        self.rules = {}                  # slot -> rule dict (laptop form, see rules.py)
        self._rule_rt = {}               # slot -> runtime
        self._door = False
        self._closed_at = None
        self._use_started = False
        self._opened_at = 0.0
        self._levels = deque()
        self._hums = deque()
        self._tap_since = None; self._tap_level0 = None
        self.tap_suspected = False; self._tap_confirmed = False; self._tap_clear_since = None
        self._low_since = None; self.low_water = False
        self.gate = False; self._gate_ref = None; self._gate_at = None; self._gate_settle = None
        self._suppressed_logged = False
        self._base_since = None; self._base_sum = 0.0; self._base_n = 0
        self._gas_hi_since = None; self._gas_lo_since = None
        self.air_bad = False
        self.needs_cleaning = False; self.drain_check = False; self._clean_logged = False
        self._hum_latch = False
        self._fan_on_at = None; self._fan_reason = 0; self._verify = None
        self.fault = False
        self._sensor_bad = {}            # id -> since
        self._sensor_fault = set()
        self._link_bad_since = None; self.link_lost = False
        self._first = True

    # ---------- helpers ----------
    def _emit(self, t, code, a=0, b=0):
        self.seq += 1
        self.events.append((t, self.seq, code, int(a), int(b)))

    def collect(self):
        out, self.events = self.events, []
        return out

    def _slope(self):
        """Least-squares slope of the water level in mm per minute."""
        if len(self._levels) < 6:
            return 0
        t0 = self._levels[0][0]
        span = self._levels[-1][0] - t0
        if span < self.cfg["SLOPE_WINDOW_S"] * 0.6:
            return 0
        n = len(self._levels)
        sx = sum(t - t0 for t, _ in self._levels); sy = sum(v for _, v in self._levels)
        sxx = sum((t - t0) ** 2 for t, _ in self._levels); sxy = sum((t - t0) * v for t, v in self._levels)
        den = n * sxx - sx * sx
        return 0 if den == 0 else round((n * sxy - sx * sy) / den * 60)

    def _sensor(self, t, sid, ok):
        if ok:
            self._sensor_bad.pop(sid, None)
            if sid in self._sensor_fault:
                self._sensor_fault.discard(sid); self._emit(t, "SENSOR_OK", sid)
        else:
            since = self._sensor_bad.setdefault(sid, t)
            if t - since >= self.cfg["SENSOR_TIMEOUT_S"] and sid not in self._sensor_fault:
                self._sensor_fault.add(sid); self._emit(t, "SENSOR_FAULT", sid)

    # ---------- commands ----------
    def cleaned(self, t):
        self.uses = 0; self.needs_cleaning = False; self.drain_check = False; self._clean_logged = False
        self.fault = False
        self._emit(t, "CLEANED")
        self._rule_event(t, "CLEANED")

    def set_manual(self, mode):          # "AUTO" | "ON" | "OFF"
        self.manual = None if mode == "AUTO" else (mode == "ON")

    def add_rule(self, t, slot, rule):
        self.rules[slot] = rule
        self._rule_rt[slot] = {"true_since": None, "active_until": None, "active": False, "armed": True}
        self._emit(t, "RULE_ADDED", slot)

    def delete_rule(self, t, slot):
        if self.rules.pop(slot, None) is not None:
            self._rule_rt.pop(slot, None); self._emit(t, "RULE_DELETED", slot)

    # ---------- rules ----------
    def _values(self, t, level, hum, temp):
        return {
            "door": 1 if self._door else 0,
            "water_level_mm": level, "water_rate_mm_per_min": self.level_rate,
            "air_percent": self.gas_pct or None,
            "humidity_pct": None if hum is None else hum / 10,
            "temperature_c": None if temp is None else temp / 10,
            "uses": self.uses,
            "occupied_seconds": (t - self._closed_at) if (self._door and self._closed_at is not None) else 0,
            "free_seconds": 0 if self._door else (t - self._opened_at),
        }

    def _conditions(self, rule, vals):
        res = []
        for c in rule.get("when", []):
            v = vals.get(c["sensor"])
            if v is None:
                return False             # a rule never fires on a missing reading
            res.append(v < c["value"] if c["is"] == "below" else v > c["value"] if c["is"] == "above" else v == c["value"])
        if not res:
            return True
        return all(res) if rule.get("match", "all") == "all" else any(res)

    def _rule_event(self, t, code):
        for slot, rule in sorted(self.rules.items()):
            trig = rule.get("trigger") or {"type": "while"}
            if trig["type"] == "on_event" and trig["event"] == code and self._conditions(rule, self._last_vals):
                rt = self._rule_rt[slot]
                rt["active"] = True; rt["active_until"] = t + rule.get("for_seconds", 0)
                self._emit(t, "RULE_FIRED", slot)

    def _run_rules(self, t, vals):
        for slot, rule in sorted(self.rules.items()):
            rt = self._rule_rt[slot]
            trig = rule.get("trigger") or {"type": "while"}
            if trig["type"] == "on_event":
                if rt["active"] and t >= rt["active_until"]:
                    rt["active"] = False
                continue
            ok = self._conditions(rule, vals)
            if not ok:
                rt["true_since"] = None; rt["active"] = False; rt["armed"] = True
                continue
            if rt["true_since"] is None:
                rt["true_since"] = t
            if not rt["active"] and rt["armed"] and t - rt["true_since"] >= rule.get("hold_seconds", 0):
                rt["active"] = True; rt["armed"] = False
                rt["active_until"] = (t + rule["for_seconds"]) if rule.get("for_seconds") else None
                self._emit(t, "RULE_FIRED", slot)
            if rt["active"] and rt["active_until"] is not None and t >= rt["active_until"]:
                rt["active"] = False     # stays off until the condition goes false and true again
        best = None
        for slot, rule in sorted(self.rules.items()):
            if self._rule_rt[slot]["active"] and rule["action"]["type"] == "fan":
                want = rule["action"]["set"] == "on"
                pr = rule.get("priority", 5)
                if best is None or pr < best[0] or (pr == best[0] and not want):
                    best = (pr, want)    # on a tie, "off" wins
        return None if best is None else best[1]

    # ---------- one step ----------
    def update(self, t, door_closed, level_mm, gas_raw, hum, temp, link_ok=True):
        """level_mm, hum, temp are None when the sensor gave no valid reading."""
        c = self.cfg
        if self._first:
            self._first = False; self._opened_at = t; self._emit(t, "BOOT"); self._last_vals = {}
        self._sensor(t, 1, level_mm is not None)
        self._sensor(t, 3, hum is not None)

        # door and uses
        if door_closed and not self._door:
            self._closed_at = t; self._use_started = False
        if door_closed and not self._use_started and t - self._closed_at >= c["MIN_USE_S"]:
            self._use_started = True; self._emit(t, "USE_START")
            self._door = True; self._last_vals = self._values(t, level_mm, hum, temp); self._rule_event(t, "USE_START")
        if not door_closed and self._door:
            self._opened_at = t
            self._levels.clear()         # water used while the room was occupied must not count as a tap left running
        ended = (not door_closed) and self._door and self._use_started
        self._door = door_closed
        if ended:
            self._use_started = False; self.uses += 1
            self._emit(t, "USE_END", t - self._closed_at, self.uses)
            self._last_vals = self._values(t, level_mm, hum, temp); self._rule_event(t, "USE_END")

        # water level and slope
        if level_mm is not None:
            self._levels.append((t, level_mm))
            while self._levels and t - self._levels[0][0] > c["SLOPE_WINDOW_S"]:
                self._levels.popleft()
        self.level_rate = self._slope() if level_mm is not None else 0

        # tap left running: water falling while the room is free
        running = (not door_closed) and level_mm is not None and self.level_rate <= -c["TAP_RATE"]
        if running:
            self._tap_clear_since = None
            if self._tap_since is None:
                self._tap_since = t; self._tap_level0 = level_mm
            if not self.tap_suspected and t - self._tap_since >= c["TAP_SUSPECT_S"]:
                self.tap_suspected = True; self._emit(t, "TAP_SUSPECTED", -self.level_rate)
            if self.tap_suspected and not self._tap_confirmed and t - self._tap_since >= c["TAP_CONFIRM_S"]:
                self._tap_confirmed = True
                self._emit(t, "TAP_CONFIRMED", -self.level_rate, self._tap_level0 - level_mm)
                self._last_vals = self._values(t, level_mm, hum, temp); self._rule_event(t, "TAP_CONFIRMED")
        else:
            if self.tap_suspected:
                if self._tap_clear_since is None:
                    self._tap_clear_since = t
                if door_closed or t - self._tap_clear_since >= c["TAP_CLEAR_S"]:
                    self.tap_suspected = False; self._tap_confirmed = False; self._tap_since = None
                    self._emit(t, "TAP_CLEARED")
            else:
                self._tap_since = None

        # low water
        if level_mm is not None:
            if level_mm < c["LOW_MM"]:
                if self._low_since is None:
                    self._low_since = t
                if not self.low_water and t - self._low_since >= 5:
                    self.low_water = True; self._emit(t, "LOW_WATER", level_mm)
                    self._last_vals = self._values(t, level_mm, hum, temp); self._rule_event(t, "LOW_WATER")
            else:
                self._low_since = None
                if self.low_water and level_mm >= c["LOW_MM"] + 10:
                    self.low_water = False; self._emit(t, "WATER_OK", level_mm)

        # steam gate: a fast humidity rise means steam, so the air alarm is held back
        hum_stable = False
        if hum is not None:
            self._hums.append((t, hum))
            while self._hums and t - self._hums[0][0] > c["STEAM_WINDOW_S"]:
                self._hums.popleft()
            lo = min(v for _, v in self._hums)
            hum_stable = (max(v for _, v in self._hums) - lo) < 20
            if not self.gate and hum - lo >= c["STEAM_RISE"]:
                self.gate = True; self._gate_ref = lo; self._gate_at = t; self._gate_settle = None
                self._suppressed_logged = False; self._emit(t, "STEAM_GATE_ON", hum)
            elif self.gate:
                if hum <= self._gate_ref + c["STEAM_SETTLE"]:
                    if self._gate_settle is None:
                        self._gate_settle = t
                else:
                    self._gate_settle = None
                if (self._gate_settle is not None and t - self._gate_settle >= 10) or t - self._gate_at >= c["STEAM_MAX_S"]:
                    self.gate = False; self._emit(t, "STEAM_GATE_OFF", hum)

        # gas sensor: learn its normal level only in quiet moments
        quiet = (not door_closed) and (not self.fan) and (not self.gate) and hum_stable and \
                (self.baseline is None or self.gas_pct < c["GAS_OK_PCT"])
        if quiet:
            if self._base_since is None:
                self._base_since = t; self._base_sum = 0.0; self._base_n = 0
            self._base_sum += gas_raw; self._base_n += 1
            if t - self._base_since >= c["BASELINE_STABLE_S"]:
                mean = self._base_sum / self._base_n
                self.baseline = mean if self.baseline is None else 0.8 * self.baseline + 0.2 * mean
                self._base_since = None
        else:
            self._base_since = None
        self.gas_pct = round(100 * gas_raw / self.baseline) if self.baseline else 0

        # air alarm
        if self.baseline and self.gas_pct >= c["GAS_BAD_PCT"]:
            self._gas_lo_since = None
            if self._gas_hi_since is None:
                self._gas_hi_since = t
            if t - self._gas_hi_since >= c["GAS_BAD_S"]:
                if self.gate:
                    if not self._suppressed_logged:
                        self._suppressed_logged = True; self._emit(t, "AIR_SUPPRESSED", self.gas_pct)
                elif not self.air_bad:
                    self.air_bad = True; self._emit(t, "AIR_BAD", self.gas_pct, self.uses)
                    self._last_vals = self._values(t, level_mm, hum, temp); self._rule_event(t, "AIR_BAD")
                    if self.uses > 0:
                        if not self._clean_logged:
                            self.needs_cleaning = True; self._clean_logged = True; self._emit(t, "CLEAN_DUE", self.uses, 2)
                    elif not self.drain_check:
                        self.drain_check = True; self._emit(t, "DRAIN_CHECK", self.gas_pct)
        else:
            self._gas_hi_since = None
            if self.air_bad and self.baseline and self.gas_pct <= c["GAS_OK_PCT"]:
                if self._gas_lo_since is None:
                    self._gas_lo_since = t
                if t - self._gas_lo_since >= c["GAS_BAD_S"]:
                    self.air_bad = False; self._emit(t, "AIR_OK", self.gas_pct)
            else:
                self._gas_lo_since = None    # the reading went back up: start the count again

        # cleaning due by number of uses
        if self.uses >= c["CLEAN_USES"] and not self._clean_logged:
            self.needs_cleaning = True; self._clean_logged = True; self._emit(t, "CLEAN_DUE", self.uses, 1)

        # caretaker rules
        vals = self._values(t, level_mm, hum, temp); self._last_vals = vals
        rule_fan = self._run_rules(t, vals)

        # fan: manual beats rules, rules beat the automatic humidity/air control
        if hum is not None:
            if hum >= c["HUM_ON"]:
                self._hum_latch = True
            elif hum <= c["HUM_OFF"]:
                self._hum_latch = False
        reason = 4 if self.manual is not None else 3 if rule_fan is not None else 1 if self._hum_latch else 2 if self.air_bad else 0
        want = self.manual if self.manual is not None else rule_fan if rule_fan is not None else (self._hum_latch or self.air_bad)
        if self.fan and not want and self.manual is None and t - self._fan_on_at < c["FAN_MIN_ON_S"]:
            want = True                  # minimum run time, so the relay does not chatter
        if want and not self.fan:
            self.fan = True; self._fan_on_at = t; self._fan_reason = reason
            self._emit(t, "FAN_ON", reason)
            self._verify = ("hum", hum) if (reason == 1 and hum is not None) else ("gas", self.gas_pct) if reason == 2 else None
        elif self.fan and not want:
            self.fan = False; self._emit(t, "FAN_OFF", t - self._fan_on_at)
            if self._verify:             # it switched off because the reading came down: that is the proof
                self._verify = None; self.fault = False; self._emit(t, "FAN_VERIFIED", 0, t - self._fan_on_at)
        # act, then verify
        if self.fan and self._verify and t - self._fan_on_at >= c["VERIFY_S"]:
            kind, v0 = self._verify
            now = hum if kind == "hum" else self.gas_pct
            need = c["VERIFY_HUM_DROP"] if kind == "hum" else c["VERIFY_GAS_DROP"]
            self._verify = None
            if now is not None and v0 - now >= need:
                self.fault = False; self._emit(t, "FAN_VERIFIED", v0 - now, c["VERIFY_S"])
            else:
                self.fault = True; self._emit(t, "FAN_FAULT", self._fan_reason, 0 if now is None else v0 - now)

        # link to the service board
        if link_ok:
            self._link_bad_since = None
            if self.link_lost:
                self.link_lost = False; self._emit(t, "LINK_OK")
        else:
            if self._link_bad_since is None:
                self._link_bad_since = t
            if not self.link_lost and t - self._link_bad_since >= c["LINK_TIMEOUT_S"]:
                self.link_lost = True; self._emit(t, "LINK_LOST")

        # one state for the door sign, most serious first
        if self.fault or self._sensor_fault or self.link_lost:
            self.state = "FAULT"
        elif self.low_water:
            self.state = "NO_WATER"
        elif self.needs_cleaning or self.drain_check:
            self.state = "NEEDS_CLEANING"
        elif self.fan:
            self.state = "VENTILATING"
        elif door_closed:
            self.state = "IN_USE"
        else:
            self.state = "FREE"

    def flags(self, link_ok=True):
        return (1 if self.gate else 0) | (2 if self.baseline else 0) | (4 if link_ok and not self.link_lost else 0) | \
               (8 if self.manual is not None else 0) | (16 if self.tap_suspected else 0) | (32 if self.air_bad else 0)
