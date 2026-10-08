"""From stored events to "saw -> decided -> did -> checked". Plain code, no model.

This is what the live decision strip shows and what a "why" answer rests on.
Every number comes from an event field or a stored reading.

events:   [{"id", "ts" (seconds), "time" "HH:MM:SS", "code", "a", "b"}, ...] oldest first
readings: [{"ts", "hum_pct", "gas_pct", "level_mm", "fan", "door", "uses"}, ...] oldest first
rules:    {slot: rule dict}  (what the board holds), optional
cfg:      thresholds from contract/room_logic.py DEFAULTS, optional
"""
from .words import SENSOR_NAMES, cap_first, duration, lower_first, number, rule_parts

DEFAULT_CFG = dict(VERIFY_S=60, VERIFY_HUM_DROP=80, VERIFY_GAS_DROP=5, GAS_BAD_S=10,
                   TAP_CONFIRM_S=45, TAP_CLEAR_S=10, CLEAN_USES=5)

# events that start a chain worth showing, newest wins
STARTERS = ("FAN_ON", "TAP_SUSPECTED", "TAP_CONFIRMED", "LOW_WATER", "CLEAN_DUE", "DRAIN_CHECK",
            "SENSOR_FAULT", "LINK_LOST", "AIR_SUPPRESSED", "RULE_FIRED")

QUESTION_WORDS = [
    (("fan", "vent", "exhaust"), ("FAN_ON", "FAN_FAULT")),
    (("steam", "shower", "held back", "hold back"), ("AIR_SUPPRESSED", "STEAM_GATE_ON")),
    (("clean",), ("CLEAN_DUE", "DRAIN_CHECK")),
    (("tap", "leak", "running"), ("TAP_CONFIRMED", "TAP_SUSPECTED")),
    (("water", "tank", "empty"), ("LOW_WATER", "TAP_CONFIRMED", "TAP_SUSPECTED")),
    (("air", "smell", "odour", "odor", "gas"), ("AIR_BAD", "AIR_SUPPRESSED")),
    (("drain",), ("DRAIN_CHECK",)),
    (("fault", "broken", "not working", "sensor"), ("FAN_FAULT", "SENSOR_FAULT", "LINK_LOST")),
    (("link", "board"), ("LINK_LOST",)),
    (("rule",), ("RULE_FIRED",)),
]


def _uses(n):
    return "1 use" if n == 1 else "%d uses" % n


def _ts(e):
    return float(e.get("ts", 0))


def _hhmm(e):
    return str(e.get("time", ""))[:5]


def _step(key, label, head, sub=""):
    return {"key": key, "label": label, "head": head, "sub": sub}


def _reading_at(readings, ts, within=15):
    best = None
    for r in readings:
        if r.get("ts", 0) <= ts + 1:
            best = r
        else:
            break
    if best is not None and ts - best.get("ts", 0) <= within:
        return best
    return None


def _before(events, i, codes, within):
    for j in range(i - 1, -1, -1):
        if _ts(events[i]) - _ts(events[j]) > within:
            return None
        if events[j]["code"] in codes:
            return events[j]
    return None


def _same_tick(events, i, codes, within=1.5):
    for j in range(len(events)):
        if j != i and events[j]["code"] in codes and abs(_ts(events[j]) - _ts(events[i])) <= within:
            return events[j]
    return None


def _after(events, i, codes, stop=()):
    for j in range(i + 1, len(events)):
        if events[j]["code"] in stop:
            return None
        if events[j]["code"] in codes:
            return events[j]
    return None


def pick_target(events, question=None):
    """The event a question is about, or the newest chain starter when there is no question."""
    if question:
        q = question.lower()
        for words, codes in QUESTION_WORDS:
            if any(w in q for w in words):
                for e in reversed(events):
                    if e["code"] in codes:
                        return e
    for e in reversed(events):
        if e["code"] in STARTERS:
            return e
    return None


def build_chain(events, readings=None, target=None, now=None, rules=None, cfg=None):
    readings = readings or []
    rules = rules or {}
    c = dict(DEFAULT_CFG)
    c.update(cfg or {})
    if target is None:
        target = pick_target(events)
    if target is None:
        return None
    try:
        i = next(k for k, e in enumerate(events) if e.get("id") == target.get("id"))
    except StopIteration:
        return None
    code = events[i]["code"]

    # some events belong to a chain that starts at another event
    if code == "FAN_FAULT" or code == "FAN_VERIFIED":
        on = _before(events, i, ("FAN_ON",), 3600)
        if on:
            return build_chain(events, readings, on, now, rules, c)
    if code == "AIR_BAD" or (code in ("CLEAN_DUE", "DRAIN_CHECK") and events[i]["b"] != 1):
        on = _same_tick(events, i, ("FAN_ON",))
        if on and on["a"] == 2:
            return build_chain(events, readings, on, now, rules, c)
    if code == "STEAM_GATE_ON":
        sup = _after(events, i, ("AIR_SUPPRESSED",), stop=("STEAM_GATE_OFF",))
        on = _after(events, i, ("FAN_ON",), stop=("STEAM_GATE_OFF",))
        nxt = sup or on
        if nxt:
            return build_chain(events, readings, nxt, now, rules, c)
    if code == "TAP_SUSPECTED":
        conf = _after(events, i, ("TAP_CONFIRMED",), stop=("TAP_CLEARED",))
        if conf:
            return build_chain(events, readings, conf, now, rules, c)

    e = events[i]
    a, b, ts = e["a"], e["b"], _ts(e)
    r = _reading_at(readings, ts)
    ids = [e["id"]]
    steps, status, left = [], "open", None

    def add_ids(*evs):
        for x in evs:
            if x and x["id"] not in ids:
                ids.append(x["id"])

    if code == "FAN_ON":
        off = _after(events, i, ("FAN_OFF",), stop=("FAN_ON",))
        ver = _after(events, i, ("FAN_VERIFIED", "FAN_FAULT"), stop=("FAN_ON",))
        add_ids(off, ver)
        if a == 2:  # air
            ab = _same_tick(events, i, ("AIR_BAD",)) or _before(events, i, ("AIR_BAD",), 30)
            cd = _same_tick(events, i, ("CLEAN_DUE",))
            dc = _same_tick(events, i, ("DRAIN_CHECK",))
            add_ids(ab, cd, dc)
            pct = ab["a"] if ab else (r or {}).get("gas_pct")
            steps.append(_step("saw", "Saw",
                               "Air %s%% above normal" % (pct - 100) if pct else "The air changed",
                               ("Humidity steady at %s%%, so it is not steam" % number(r["hum_pct"]))
                               if r and r.get("hum_pct") is not None else "No steam in the room"))
            steps.append(_step("decided", "Decided", "The air is bad",
                               ("%s since the last clean, so cleaning is due" % _uses(cd["a"])) if cd else
                               "Nobody has used the room since it was cleaned, so check the drain" if dc else
                               "Above the line for %d s" % c["GAS_BAD_S"]))
            steps.append(_step("did", "Did", "Switched the fan on",
                               "Raised a cleaning job" if cd else "Raised a job to check the drain" if dc
                               else "To clear the air"))
            unit_ok = lambda n, s: "The air improved by %d points in %d s" % (n, s)
            back = lambda s: "The air came back to normal in %d s" % s
            fail = lambda n: "The air improved by only %d points in %d s. Check the fan" % (n, c["VERIFY_S"])
            need = "The air must improve by %d points within %d s" % (c["VERIFY_GAS_DROP"], c["VERIFY_S"])
        elif a == 1:  # humidity
            sg = _before(events, i, ("STEAM_GATE_ON",), 300)
            sup = _after(events, i, ("AIR_SUPPRESSED",), stop=("STEAM_GATE_OFF", "FAN_ON")) or \
                _before(events, i, ("AIR_SUPPRESSED",), 300)
            add_ids(sg, sup)
            hum = (r or {}).get("hum_pct")
            steps.append(_step("saw", "Saw",
                               "Humidity at %s%%" % number(hum) if hum is not None else "Humidity is high",
                               "It rose fast, so it is steam" if sg else "Above the fan line"))
            steps.append(_step("decided", "Decided", "Steam in the room" if sg else "Too humid",
                               "Held back the air alarm, because steam fools the air sensor" if sup
                               else "The fan should clear it"))
            steps.append(_step("did", "Did", "Switched the fan on", "To clear the humidity"))
            unit_ok = lambda n, s: "Humidity fell %s%% in %d s" % (number(n / 10), s)
            back = lambda s: "Humidity came back down in %d s" % s
            fail = lambda n: "Humidity fell only %s%% in %d s. Check the fan" % (number(n / 10), c["VERIFY_S"])
            need = "Humidity must fall %s%% within %d s" % (number(c["VERIFY_HUM_DROP"] / 10), c["VERIFY_S"])
        elif a == 3:  # a caretaker rule
            rf = _same_tick(events, i, ("RULE_FIRED",)) or _before(events, i, ("RULE_FIRED",), 5)
            add_ids(rf)
            slot = rf["a"] if rf else 0
            rule = rules.get(slot)
            parts = rule_parts(rule) if rule else None
            steps.append(_step("saw", "Saw", cap_first(parts["when"]) if parts else "A rule's condition came true",
                               "That is what your rule waits for"))
            steps.append(_step("decided", "Decided", "Rule %d applies" % slot if slot else "A rule applies",
                               '"%s"' % rule["name"] if rule else ""))
            steps.append(_step("did", "Did", "Switched the fan on",
                               "For %s" % parts["for"] if parts and parts["for"] else "While the rule stays true"))
            unit_ok = back = fail = need = None
        else:  # manual
            steps.append(_step("saw", "Saw", "A fan-on command from the laptop", ""))
            steps.append(_step("decided", "Decided", "Manual control", "The board's own fan control is paused"))
            steps.append(_step("did", "Did", "Switched the fan on", ""))
            unit_ok = back = fail = need = None

        if ver and ver["code"] == "FAN_VERIFIED" and unit_ok:
            status = "passed"
            steps.append(_step("checked", "Checked", "The fan worked",
                               unit_ok(ver["a"], ver["b"]) if ver["a"] > 0 else back(ver["b"])))
        elif ver and ver["code"] == "FAN_FAULT" and fail:
            status = "failed"
            steps.append(_step("checked", "Checked", "The fan did not work", fail(ver["b"])))
        elif off:
            status = "done"
            steps.append(_step("checked", "Checked", "Fan switched off", "It ran for %s" % duration(off["a"])))
        elif need:
            status = "checking"
            if now is not None:
                left = max(0, int(round(c["VERIFY_S"] - (now - ts))))
            steps.append(_step("checking", "Checking", "Did the fan work?", need))
        else:
            steps.append(_step("checking", "Checking", "Fan is running",
                               "Rule and manual runs are not checked against a reading"))

    elif code == "TAP_CONFIRMED" or code == "TAP_SUSPECTED":
        sus = e if code == "TAP_SUSPECTED" else _before(events, i, ("TAP_SUSPECTED",), 600)
        clr = _after(events, i, ("TAP_CLEARED",))
        add_ids(sus, clr)
        steps.append(_step("saw", "Saw", "Water falling %d mm a minute" % a,
                           "The door is open, so nobody is inside"))
        if code == "TAP_CONFIRMED":
            steps.append(_step("decided", "Decided", "A tap is left running, or there is a leak",
                               "%d mm lost so far" % b))
            steps.append(_step("did", "Did", "Raised an urgent job",
                               "The board cannot close the tap, so a person must"))
        else:
            steps.append(_step("decided", "Decided", "A tap may be left on",
                               "Watching for %d s before raising the alarm" % c["TAP_CONFIRM_S"]))
            steps.append(_step("did", "Did", "Raised a low-priority job", "Possible tap left running"))
        if clr:
            status = "passed"
            steps.append(_step("checked", "Checked", "Cleared", "The water level is steady again"))
        else:
            status = "checking"
            steps.append(_step("checking", "Checking", "Still watching",
                               "It clears when the level holds for %d s" % c["TAP_CLEAR_S"]))

    elif code == "LOW_WATER":
        ok = _after(events, i, ("WATER_OK",))
        add_ids(ok)
        steps.append(_step("saw", "Saw", "Water at %d mm" % a, "Under the low mark for 5 s"))
        steps.append(_step("decided", "Decided", "The tank is nearly empty", ""))
        steps.append(_step("did", "Did", "Raised a job: no water", "The door sign shows no water"))
        if ok:
            status = "passed"
            steps.append(_step("checked", "Checked", "Water is back", "Level is %d mm" % ok["a"]))
        else:
            status = "checking"
            steps.append(_step("checking", "Checking", "Waiting for a refill", ""))

    elif code in ("CLEAN_DUE", "DRAIN_CHECK"):
        cl = _after(events, i, ("CLEANED",))
        add_ids(cl)
        if code == "CLEAN_DUE" and b == 1:
            steps.append(_step("saw", "Saw", "%s since the last clean" % _uses(a),
                               "The count reached the cleaning line"))
            steps.append(_step("decided", "Decided", "Cleaning is due", ""))
            steps.append(_step("did", "Did", "Raised a cleaning job", "The door sign shows needs cleaning"))
        else:
            ab = _same_tick(events, i, ("AIR_BAD",))
            add_ids(ab)
            pct = ab["a"] if ab else (a if code == "DRAIN_CHECK" else None)
            steps.append(_step("saw", "Saw", "Air %d%% above normal" % (pct - 100) if pct else "The air changed",
                               "No steam in the room"))
            if code == "CLEAN_DUE":
                steps.append(_step("decided", "Decided", "The air is bad",
                                   "%s since the last clean, so cleaning is due" % _uses(a)))
                steps.append(_step("did", "Did", "Raised a cleaning job", ""))
            else:
                steps.append(_step("decided", "Decided", "The air is bad",
                                   "Nobody has used the room since it was cleaned, so it is not from use"))
                steps.append(_step("did", "Did", "Raised a job to check the drain", ""))
        if cl:
            status = "passed"
            steps.append(_step("checked", "Checked", "Marked as cleaned", "At %s" % _hhmm(cl)))
        else:
            status = "checking"
            steps.append(_step("checking", "Checking", "Waiting for the caretaker", ""))

    elif code == "SENSOR_FAULT":
        name = SENSOR_NAMES.get(a, "a")
        ok = _after(events, i, ("SENSOR_OK",))
        add_ids(ok)
        steps.append(_step("saw", "Saw", "No valid reading from the %s sensor" % name, "For 3 s"))
        steps.append(_step("decided", "Decided", "Sensor fault", "Its decisions are paused, not guessed"))
        steps.append(_step("did", "Did", "Raised an urgent job", "The door sign shows a fault"))
        status = "passed" if ok else "checking"
        steps.append(_step("checked" if ok else "checking", "Checked" if ok else "Checking",
                           "The sensor is back" if ok else "Waiting for a valid reading", ""))

    elif code == "LINK_LOST":
        ok = _after(events, i, ("LINK_OK",))
        add_ids(ok)
        steps.append(_step("saw", "Saw", "No answer from the fan board", "For 3 s"))
        steps.append(_step("decided", "Decided", "The link is lost", ""))
        steps.append(_step("did", "Did", "Raised an urgent job",
                           "The fan board switches the fan off by itself when the link is silent"))
        status = "passed" if ok else "checking"
        steps.append(_step("checked" if ok else "checking", "Checked" if ok else "Checking",
                           "The link is back" if ok else "Waiting for the fan board", ""))

    elif code == "AIR_SUPPRESSED":
        sg = _before(events, i, ("STEAM_GATE_ON",), 900)
        off = _after(events, i, ("STEAM_GATE_OFF",))
        add_ids(sg, off)
        steps.append(_step("saw", "Saw", "Air reading %d%% above normal" % (a - 100),
                           "At the same time humidity was rising fast"))
        steps.append(_step("decided", "Decided", "It is steam, not bad air", "Steam fools this kind of air sensor"))
        steps.append(_step("did", "Did", "Held back the air alarm", "No cleaning job was raised"))
        status = "passed" if off else "checking"
        steps.append(_step("checked" if off else "checking", "Checked" if off else "Checking",
                           "The steam cleared" if off else "Watching until the steam clears", ""))

    elif code == "RULE_FIRED":
        rule = rules.get(a)
        on = _same_tick(events, i, ("FAN_ON",))
        if on and on["a"] == 3:
            return build_chain(events, readings, on, now, rules, c)
        parts = rule_parts(rule) if rule else None
        steps.append(_step("saw", "Saw", cap_first(parts["when"]) if parts else "A rule's condition came true",
                           "That is what your rule waits for"))
        steps.append(_step("decided", "Decided", "Rule %d applies" % a, '"%s"' % rule["name"] if rule else ""))
        if rule and rule["action"]["type"] == "job":
            steps.append(_step("did", "Did", "Raised a job", '"%s"' % rule["action"]["text"]))
            steps.append(_step("checking", "Checking", "Waiting for the caretaker", ""))
            status = "checking"
        else:
            steps.append(_step("did", "Did", "Applied the rule's fan setting", parts["do"] if parts else ""))
            steps.append(_step("checking", "Checking", "Rule runs are not checked against a reading", ""))
    else:
        return None

    return {"event_id": e["id"], "time": _hhmm(e), "code": code, "steps": steps, "status": status,
            "seconds_left": left, "event_ids": ids, "decided_by": "board"}


def chain_text(chain):
    """A plain answer built only from the chain. Used when no model is available, and as the facts for one."""
    if not chain:
        return "Nothing has happened yet that needs an explanation."
    out = []
    for s in chain["steps"]:
        head = lower_first(s["head"])
        sub = (" (" + lower_first(s["sub"]) + ")") if s["sub"] else ""
        if s["key"] == "saw":
            out.append("At %s the board saw this: %s%s." % (chain["time"], head, sub))
        elif s["key"] == "decided":
            out.append("It decided: %s%s." % (head, sub))
        elif s["key"] == "did":
            out.append("It then %s%s." % (head, sub))
        elif s["key"] == "checked":
            out.append("Check: %s%s." % (head, sub))
        else:
            left = chain.get("seconds_left")
            tail = " %d s left." % left if left is not None else ""
            out.append("Still checking: %s%s.%s" % (head.rstrip("?"), sub, tail))
    return " ".join(out)
