"""Try a draft rule on stored history before a person approves it.

Uses the reference room logic's own rule code (contract/room_logic.py), so the answer is what the board
would have done. The result always carries the data source: a replay on SIMULATED data is only a preview.
"""
from room_logic import RoomLogic  # contract/room_logic.py


def replay(rule, readings, events):
    """readings and events: stored rows, oldest first, covering the same time range.
    Returns {"fired": [ts...], "count", "fan_seconds", "from", "to", "points", "sources"}."""
    if not readings:
        return {"fired": [], "count": 0, "fan_seconds": 0, "from": None, "to": None, "points": 0, "sources": []}
    lg = RoomLogic()
    lg.add_rule(0.0, 1, rule)
    lg.collect()
    fired, fan_seconds = [], 0.0
    is_fan = rule["action"]["type"] == "fan" and rule["action"].get("set") == "on"
    ev = list(events)
    ei = 0
    door_closed_at = None
    door_opened_at = readings[0]["ts"]
    prev_door = 0
    prev_ts = readings[0]["ts"]
    last_session = readings[0].get("session")
    for r in readings:
        t = r["ts"]
        if r.get("session") != last_session:      # the board restarted in between: start counting afresh
            last_session = r.get("session")
            door_closed_at, door_opened_at, prev_door = None, t, 0
            lg._rule_rt[1] = {"true_since": None, "active_until": None, "active": False, "armed": True}
        if r["door"] and not prev_door:
            door_closed_at = t
        if not r["door"] and prev_door:
            door_opened_at = t
        prev_door = r["door"]
        vals = {
            "door": r["door"],
            "water_level_mm": None if r["level_mm"] is None or r["level_mm"] < 0 else r["level_mm"],
            "water_rate_mm_per_min": r["level_rate"],
            "air_percent": r["gas_pct"] or None,
            "humidity_pct": r.get("hum_pct"),
            "temperature_c": r.get("temp_c"),
            "uses": r["uses"],
            "occupied_seconds": (t - door_closed_at) if (r["door"] and door_closed_at is not None) else 0,
            "free_seconds": 0 if r["door"] else (t - door_opened_at),
        }
        lg._last_vals = vals
        while ei < len(ev) and ev[ei]["ts"] <= t:
            lg._rule_event(ev[ei]["ts"], ev[ei]["code"])
            ei += 1
        was_active = lg._rule_rt[1]["active"]
        lg._run_rules(t, vals)
        if is_fan and was_active:
            fan_seconds += min(t - prev_ts, 5.0)   # gaps in the history do not count as fan time
        prev_ts = t
        for (et, _seq, code, _a, _b) in lg.collect():
            if code == "RULE_FIRED":
                fired.append(et)
    if is_fan and (rule.get("trigger") or {}).get("type") == "on_event":
        fan_seconds = len(fired) * (rule.get("for_seconds") or 0)   # exact: each firing runs for the set time
    return {"fired": fired, "count": len(fired), "fan_seconds": int(round(fan_seconds)),
            "from": readings[0]["ts"], "to": readings[-1]["ts"], "points": len(readings),
            "sources": sorted({r["source"] for r in readings})}
