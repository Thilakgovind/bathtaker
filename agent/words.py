"""Plain words for rules and events. No model here: every word and number comes from code."""

EVENT_TRIGGER_WORDS = {
    "USE_START": "a use starts", "USE_END": "a use ends", "CLEANED": "the room is marked as cleaned",
    "TAP_CONFIRMED": "a tap is left running", "AIR_BAD": "the air turns bad", "LOW_WATER": "the water runs low",
}
SENSOR_NAMES = {1: "water level", 2: "air", 3: "humidity", 4: "door"}


def number(v):
    """70.0 -> '70', 62.5 -> '62.5'."""
    return ("%g" % v) if isinstance(v, float) else str(v)


def duration(seconds):
    s = int(round(seconds))
    if s >= 120 and s % 60 == 0:
        return "%d min" % (s // 60)
    if s == 60:
        return "1 min"
    return "%d s" % s


def condition(c):
    s, op, v = c["sensor"], c["is"], c["value"]
    cmp = {"below": "below", "above": "above", "equals": "exactly"}[op]
    if s == "door":
        return "the door is closed" if (op == "equals" and v == 1) or (op == "above" and v == 0) else "the door is open"
    if s == "humidity_pct":
        return "humidity is %s %s%%" % (cmp, number(v))
    if s == "water_level_mm":
        return "the water level is %s %s mm" % (cmp, number(v))
    if s == "water_rate_mm_per_min":
        if op == "below" and v < 0:
            return "water is falling faster than %s mm a minute" % number(-v)
        return "the water level change is %s %s mm a minute" % (cmp, number(v))
    if s == "air_percent":
        return "the air is %s %s%% of normal" % (cmp, number(v))
    if s == "temperature_c":
        return "the temperature is %s %s °C" % (cmp, number(v))
    if s == "uses":
        if op == "above":
            return "the room has been used at all" if v == 0 else \
                "the room has been used more than %s %s" % (number(v), "time" if v == 1 else "times")
        return "the number of uses is %s %s" % (cmp, number(v))
    if s == "occupied_seconds":
        return "the door has been closed for %s %s" % ("more than" if op == "above" else cmp, duration(v))
    if s == "free_seconds":
        return "the room has been free for %s %s" % ("more than" if op == "above" else cmp, duration(v))
    return "%s is %s %s" % (s, cmp, number(v))


def rule_parts(rule):
    """The pieces the screen shows as tappable parts, plus one full sentence."""
    trig = rule.get("trigger") or {"type": "while"}
    conds = [condition(c) for c in rule.get("when", [])]
    joiner = " and " if rule.get("match", "all") == "all" else " or "
    if trig["type"] == "on_event":
        when = EVENT_TRIGGER_WORDS.get(trig.get("event"), str(trig.get("event")))
        if conds:
            when += ", if " + joiner.join(conds)
    else:
        when = joiner.join(conds)
    act = rule.get("action") or {}
    if act.get("type") == "fan":
        do = "fan " + str(act.get("set"))
        do_sentence = "turn the fan " + str(act.get("set"))
    else:
        do = 'job "%s"' % act.get("text", "")
        do_sentence = 'raise the job "%s"' % act.get("text", "")
    for_s = rule.get("for_seconds") or 0
    hold_s = rule.get("hold_seconds") or 0
    sentence = "When " + when
    if hold_s:
        sentence += " for " + duration(hold_s)
    sentence += ", " + do_sentence
    if for_s and act.get("type") == "fan":
        sentence += " for " + duration(for_s)
    return {"when": when, "do": do, "for": duration(for_s) if for_s else None,
            "hold": duration(hold_s) if hold_s else None, "sentence": sentence + ".",
            "kind": "fan" if act.get("type") == "fan" else "job"}


def event_title(code, a=0, b=0, rules=None):
    """Short line for the event strip and the timeline."""
    rules = rules or {}
    name = (rules.get(a) or {}).get("name", "rule %d" % a)
    t = {
        "BOOT": "Board started",
        "USE_START": "Use started",
        "USE_END": "Use %d ended" % b,
        "TAP_SUSPECTED": "Tap may be left on",
        "TAP_CONFIRMED": "Tap left running",
        "TAP_CLEARED": "Water steady again",
        "LOW_WATER": "Water low",
        "WATER_OK": "Water is back",
        "AIR_BAD": "Air changed",
        "AIR_OK": "Air back to normal",
        "STEAM_GATE_ON": "Steam detected",
        "STEAM_GATE_OFF": "Steam cleared",
        "AIR_SUPPRESSED": "Air alarm held back (steam)",
        "FAN_ON": "Fan switched on",
        "FAN_OFF": "Fan switched off",
        "FAN_VERIFIED": "Fan check passed",
        "FAN_FAULT": "Fan check failed",
        "CLEAN_DUE": "Cleaning asked for",
        "DRAIN_CHECK": "Drain check asked for",
        "CLEANED": "Marked as cleaned",
        "SENSOR_FAULT": "%s sensor fault" % SENSOR_NAMES.get(a, "A").capitalize(),
        "SENSOR_OK": "%s sensor is back" % SENSOR_NAMES.get(a, "A").capitalize(),
        "LINK_LOST": "Fan board not answering",
        "LINK_OK": "Fan board is back",
        "RULE_FIRED": "Rule fired: %s" % name,
        "RULE_ADDED": "Rule saved in slot %d" % a,
        "RULE_DELETED": "Rule deleted from slot %d" % a,
    }
    return t.get(code, code)


def lower_first(s):
    return s[:1].lower() + s[1:] if s else s


def cap_first(s):
    return s[:1].upper() + s[1:] if s else s
