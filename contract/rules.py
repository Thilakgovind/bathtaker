"""Caretaker rules: the shape, the checker, and the compact line sent to the board.

The language model may only fill in this shape. Everything here is plain code.
"""

# laptop name -> (board code, min, max, unit shown to people, scale to board integer)
SENSORS = {
    "door":                  ("DOOR", 0, 1, "open/closed", 1),
    "water_level_mm":        ("LEVEL", 0, 400, "mm", 1),
    "water_rate_mm_per_min": ("RATE", -200, 200, "mm/min", 1),
    "air_percent":           ("GAS", 50, 400, "% of normal", 1),
    "humidity_pct":          ("HUM", 0, 100, "%", 10),
    "temperature_c":         ("TEMP", 0, 60, "C", 10),
    "uses":                  ("USES", 0, 999, "uses", 1),
    "occupied_seconds":      ("OCC_S", 0, 7200, "s", 1),
    "free_seconds":          ("FREE_S", 0, 7200, "s", 1),
}
OPS = {"below": "LT", "above": "GT", "equals": "EQ"}
TRIGGER_EVENTS = ["USE_START", "USE_END", "CLEANED", "TAP_CONFIRMED", "AIR_BAD", "LOW_WATER"]
MAX_RULES = 8
BOARD_TO_NAME = {v[0]: k for k, v in SENSORS.items()}
OP_TO_NAME = {v: k for k, v in OPS.items()}


def check_rule(rule: dict, existing: list | None = None) -> list[str]:
    """Returns a list of problems in plain words. Empty list = the rule is acceptable."""
    problems = []
    existing = existing or []
    name = str(rule.get("name", "")).strip()
    if not (1 <= len(name) <= 40):
        problems.append("The rule needs a name of 1 to 40 characters.")
    if "," in name:
        problems.append("The rule name cannot contain a comma.")

    trig = rule.get("trigger") or {"type": "while"}
    if trig.get("type") not in ("while", "on_event"):
        problems.append("The trigger must be 'while' or 'on_event'.")
    elif trig["type"] == "on_event" and trig.get("event") not in TRIGGER_EVENTS:
        problems.append("Unknown trigger event. Allowed: " + ", ".join(TRIGGER_EVENTS) + ".")

    when = rule.get("when") or []
    if len(when) > 3:
        problems.append("A rule can have at most 3 conditions.")
    if trig.get("type") == "while" and not when:
        problems.append("A 'while' rule needs at least one condition.")
    for c in when:
        s = c.get("sensor")
        if s not in SENSORS:
            problems.append("Unknown sensor '%s'. Allowed: %s." % (s, ", ".join(SENSORS)))
            continue
        if c.get("is") not in OPS:
            problems.append("The comparison for %s must be below, above or equals." % s)
        _, lo, hi, unit, _ = SENSORS[s]
        v = c.get("value")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            problems.append("The value for %s must be a number." % s)
        elif not (lo <= v <= hi):
            problems.append("%s must be between %s and %s %s; got %s." % (s, lo, hi, unit, v))
    if rule.get("match", "all") not in ("all", "any"):
        problems.append("match must be 'all' or 'any'.")

    for key, hi in (("hold_seconds", 600), ("for_seconds", 3600)):
        v = rule.get(key, 0)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= hi):
            problems.append("%s must be between 0 and %d." % (key, hi))

    act = rule.get("action") or {}
    if act.get("type") == "fan":
        if act.get("set") not in ("on", "off"):
            problems.append("A fan action must set the fan 'on' or 'off'.")
    elif act.get("type") == "job":
        text = str(act.get("text", "")).strip()
        if not (1 <= len(text) <= 60) or "," in text:
            problems.append("A job action needs a text of 1 to 60 characters with no comma.")
    else:
        problems.append("The action must be a fan action or a job action.")
    if trig.get("type") == "on_event" and act.get("type") == "fan" and not rule.get("for_seconds"):
        problems.append("A fan rule started by an event needs for_seconds, or the fan would never stop.")

    pr = rule.get("priority", 5)
    if not isinstance(pr, int) or isinstance(pr, bool) or not (1 <= pr <= 8):
        problems.append("priority must be a whole number from 1 to 8.")

    if problems:
        return problems
    if len(existing) >= MAX_RULES:
        problems.append("The board holds at most %d rules. Delete one first." % MAX_RULES)
    for other in existing:
        if _same(rule, other):
            problems.append("This repeats the existing rule '%s'." % other.get("name"))
        clash = _clash(rule, other)
        if clash:
            problems.append(clash)
    return problems


def _key(rule):
    return (rule.get("trigger", {"type": "while"}).get("type"), rule.get("trigger", {}).get("event"),
            tuple(sorted((c["sensor"], c["is"], c["value"]) for c in rule.get("when", []))),
            rule.get("match", "all"), rule["action"].get("type"), rule["action"].get("set"),
            rule["action"].get("text"), rule.get("for_seconds", 0), rule.get("hold_seconds", 0))


def _same(a, b):
    try:
        return _key(a) == _key(b)
    except Exception:
        return False


def _interval(c):
    lo, hi = SENSORS[c["sensor"]][1], SENSORS[c["sensor"]][2]
    if c["is"] == "below":
        return (lo, c["value"])
    if c["is"] == "above":
        return (c["value"], hi)
    return (c["value"], c["value"])


def _clash(a, b):
    """Two 'while' fan rules with opposite settings, same priority, that can be true together."""
    for r in (a, b):
        if r.get("trigger", {"type": "while"}).get("type") != "while" or r["action"].get("type") != "fan":
            return None
    if a["action"]["set"] == b["action"]["set"] or a.get("priority", 5) != b.get("priority", 5):
        return None
    if a.get("match", "all") != "all" or b.get("match", "all") != "all":
        return "This may clash with '%s' (opposite fan setting, same priority). Give one a higher priority." % b.get("name")
    # all-of rules: they can be true together unless some shared sensor has ranges that do not overlap
    for ca in a["when"]:
        for cb in b["when"]:
            if ca["sensor"] == cb["sensor"]:
                (alo, ahi), (blo, bhi) = _interval(ca), _interval(cb)
                if ahi < blo or bhi < alo or (ahi == blo and "equals" not in (ca["is"], cb["is"])) \
                        or (bhi == alo and "equals" not in (ca["is"], cb["is"])):
                    return None
    return "This clashes with '%s': both can be true at once and they set the fan opposite ways at the same priority." % b.get("name")


def encode_rule(slot: int, rule: dict) -> str:
    """RULE,slot,priority,ALL|ANY,hold_s,action,for_s,trigger,n,(sensor,op,value)*n,name"""
    trig = rule.get("trigger") or {"type": "while"}
    t = "WHILE" if trig["type"] == "while" else "ON:" + trig["event"]
    act = rule["action"]
    a = ("FAN_ON" if act["set"] == "on" else "FAN_OFF") if act["type"] == "fan" else "JOB:" + act["text"].strip()
    parts = ["RULE", str(slot), str(rule.get("priority", 5)), rule.get("match", "all").upper(),
             str(int(rule.get("hold_seconds", 0))), a, str(int(rule.get("for_seconds", 0))), t,
             str(len(rule.get("when", [])))]
    for c in rule.get("when", []):
        code, _, _, _, scale = SENSORS[c["sensor"]]
        parts += [code, OPS[c["is"]], str(int(round(c["value"] * scale)))]
    parts.append(rule["name"].strip())
    return ",".join(parts)


def decode_rule(line: str) -> tuple[int, dict]:
    p = line.strip().split(",")
    if p[0] != "RULE":
        raise ValueError("not a rule line")
    slot, prio, match, hold, a, for_s, t, n = int(p[1]), int(p[2]), p[3].lower(), int(p[4]), p[5], int(p[6]), p[7], int(p[8])
    when = []
    for i in range(n):
        code, op, val = p[9 + 3 * i], p[10 + 3 * i], int(p[11 + 3 * i])
        name = BOARD_TO_NAME[code]
        scale = SENSORS[name][4]
        when.append({"sensor": name, "is": OP_TO_NAME[op], "value": val / scale if scale != 1 else val})
    name = p[9 + 3 * n]
    trig = {"type": "while"} if t == "WHILE" else {"type": "on_event", "event": t[3:]}
    act = {"type": "fan", "set": "on" if a == "FAN_ON" else "off"} if a.startswith("FAN_") else {"type": "job", "text": a[4:]}
    return slot, {"name": name, "trigger": trig, "when": when, "match": match, "hold_seconds": hold,
                  "action": act, "for_seconds": for_s, "priority": prio}
