"""Sentence -> rule with fixed patterns. Works with no model. Returns None when nothing fits: never a guess."""
import re

SENSOR_WORDS = [  # longest first
    ("water level", "water_level_mm"), ("humidity", "humidity_pct"), ("temperature", "temperature_c"),
    ("air", "air_percent"), ("water", "water_level_mm"), ("uses", "uses"),
]
SHORT = {"humidity_pct": "humidity", "air_percent": "air", "water_level_mm": "water", "temperature_c": "temperature",
         "uses": "uses"}
UNIT = {"humidity_pct": "%", "air_percent": "%", "water_level_mm": " mm", "temperature_c": " C", "uses": ""}
NUM = r"(-?\d+(?:\.\d+)?)"
SENSOR = r"(?:the\s+)?(water level|humidity|temperature|air|water|uses)"
CMP = r"(?:is|goes|gets|rises|falls|drops|stays)?\s*(above|over|more than|higher than|below|under|less than|lower than)"
HOLD = r"(?:\s+for\s+(?:more than\s+)?" + NUM + r"\s*(seconds?|secs?|s|minutes?|mins?|m))?"
DUR = NUM + r"\s*(seconds?|secs?|s|minutes?|mins?|m)"


def _num(text):
    v = float(text)
    return int(v) if v == int(v) else v


def _seconds(n, unit):
    return int(round(float(n) * (60 if unit.startswith("m") else 1)))


def _sensor(word):
    return dict(SENSOR_WORDS)[word]


def _op(word):
    return "above" if word in ("above", "over", "more than", "higher than") else "below"


def _name(text):
    return text.replace(",", "")[:40].strip()


def _fmt(v):
    return ("%g" % v) if isinstance(v, float) else str(v)


def parse(sentence):
    s = re.sub(r"\s+", " ", sentence.strip().lower().rstrip(".!")).replace("%", "").replace(" percent", "")
    s = s.replace("°", " ").replace(" degrees", "")

    # run the fan for N after every use | after cleaning
    m = re.fullmatch(r"(?:please )?(?:run|turn on|switch on|start|keep) the fan (?:on )?for " + DUR +
                     r" (?:after|when) (every use|each use|every visit|each visit|a use ends|cleaning|every clean|"
                     r"the room is cleaned)", s)
    if m:
        secs = _seconds(m.group(1), m.group(2))
        clean = "clean" in m.group(3)
        return {"name": "Fan after cleaning" if clean else "Fan after use",
                "trigger": {"type": "on_event", "event": "CLEANED" if clean else "USE_END"},
                "when": [], "match": "all", "hold_seconds": 0,
                "action": {"type": "fan", "set": "on"}, "for_seconds": secs, "priority": 4}

    # turn the fan on|off when <sensor> is above|below N [for T]
    m = re.fullmatch(r"(?:please )?(?:turn|switch|run|put|keep) the fan (on|off) (?:when|if|while) " + SENSOR +
                     r"\s*" + CMP + r"\s*" + NUM + r"(?: mm| c)?" + HOLD, s) or \
        re.fullmatch(r"(?:when|if|while) " + SENSOR + r"\s*" + CMP + r"\s*" + NUM + r"(?: mm| c)?" + HOLD +
                     r",? (?:turn|switch|run|put) the fan (on|off)", s)
    if m:
        g = m.groups()
        if g[0] in ("on", "off"):
            setting, word, cmp_word, value, hold_n, hold_u = g
        else:
            word, cmp_word, value, hold_n, hold_u, setting = g
        sensor, op = _sensor(word), _op(cmp_word)
        v = _num(value)
        return {"name": _name("Fan %s when %s %s %s" % (setting, SHORT[sensor], op, _fmt(v))),
                "trigger": {"type": "while"}, "when": [{"sensor": sensor, "is": op, "value": v}], "match": "all",
                "hold_seconds": _seconds(hold_n, hold_u) if hold_n else 0,
                "action": {"type": "fan", "set": setting}, "for_seconds": 0, "priority": 4}

    # tell me when <sensor> is above|below N [for T]   (either order)
    tell = r"(?:please )?(?:tell me|alert me|warn me|notify me|let me know|raise a job)"
    m = re.fullmatch(tell + r" (?:when|if) " + SENSOR + r"\s*" + CMP + r"\s*" + NUM + r"(?: mm| c)?" + HOLD, s) or \
        re.fullmatch(r"(?:when|if) " + SENSOR + r"\s*" + CMP + r"\s*" + NUM + r"(?: mm| c)?" + HOLD + r",? " + tell, s)
    if m:
        word, cmp_word, value, hold_n, hold_u = m.groups()
        sensor, op = _sensor(word), _op(cmp_word)
        v = _num(value)
        text = "%s %s %s%s" % (SHORT[sensor].capitalize(), op, _fmt(v), UNIT[sensor])
        return {"name": _name(text), "trigger": {"type": "while"},
                "when": [{"sensor": sensor, "is": op, "value": v}], "match": "all",
                "hold_seconds": _seconds(hold_n, hold_u) if hold_n else 0,
                "action": {"type": "job", "text": text}, "for_seconds": 0, "priority": 5}

    # tell me if the door is/has been closed for more than N minutes
    m = re.fullmatch(tell + r" (?:when|if) the door (?:is|has been|stays) closed for (?:more than |over )?" + DUR, s)
    if m:
        secs = _seconds(m.group(1), m.group(2))
        return {"name": "Door closed too long", "trigger": {"type": "while"},
                "when": [{"sensor": "occupied_seconds", "is": "above", "value": secs}], "match": "all",
                "hold_seconds": 0, "action": {"type": "job", "text": "Door closed for a long time: check the room"},
                "for_seconds": 0, "priority": 3}

    # tell me when the room has been used more than N times | ask for cleaning after N uses
    m = re.fullmatch(tell + r" (?:when|if) (?:the room|it) (?:has been|is) used more than (\d+) times", s)
    if m:
        n = int(m.group(1))
        return {"name": "Used more than %d times" % n, "trigger": {"type": "while"},
                "when": [{"sensor": "uses", "is": "above", "value": n}], "match": "all", "hold_seconds": 0,
                "action": {"type": "job", "text": "Used more than %d times: clean the washroom" % n},
                "for_seconds": 0, "priority": 4}
    m = re.fullmatch(r"(?:please )?(?:ask for cleaning|clean|raise a cleaning job|tell me to clean) "
                     r"(?:after|every) (\d+) uses?", s)
    if m:
        n = int(m.group(1))
        uses = "1 use" if n == 1 else "%d uses" % n
        return {"name": "Clean after " + uses, "trigger": {"type": "while"},
                "when": [{"sensor": "uses", "is": "above", "value": n - 1}], "match": "all", "hold_seconds": 0,
                "action": {"type": "job", "text": "Clean the washroom: " + uses},
                "for_seconds": 0, "priority": 4}

    # tell me if the tap is left running
    if re.fullmatch(tell + r" (?:when|if) (?:the|a) tap is (?:left )?(?:running|on|open)", s):
        return {"name": "Tap left running", "trigger": {"type": "on_event", "event": "TAP_CONFIRMED"},
                "when": [], "match": "all", "hold_seconds": 0,
                "action": {"type": "job", "text": "Tap left running: close it"}, "for_seconds": 0, "priority": 2}
    return None
