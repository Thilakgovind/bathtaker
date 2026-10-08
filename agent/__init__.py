"""The caretaker agent. A plain Python package: no board, no database, no web server.

Four jobs, as fixed pipelines (docs/RULES_AND_AGENT.md):
    status()        is the local model there
    draft_rule()    a sentence -> a rule in the fixed shape (pattern first, then the model)
    explain()       "why did X happen" from stored events (code builds the chain, the model only rewords)
    shift_report()  a few sentences from figures the backend already counted

The guard: the model never sends a command and never invents a number. Its output is either a filled
rule shape that the checker must accept, or a rewording whose numbers must all appear in the facts.
With Ollama stopped every function still answers, marked "pattern", "template" or "none".
"""
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "contract")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rules import SENSORS, TRIGGER_EVENTS, check_rule  # noqa: E402  (contract/rules.py)

from . import ollama, patterns  # noqa: E402
from .chain import build_chain, chain_text, pick_target  # noqa: E402
from .words import rule_parts  # noqa: E402

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "can_do": {"type": "boolean"},
        "reason": {"type": "string"},
        "name": {"type": "string"},
        "trigger": {"type": "object",
                    "properties": {"type": {"enum": ["while", "on_event"]}, "event": {"enum": TRIGGER_EVENTS + [""]}},
                    "required": ["type", "event"]},
        "when": {"type": "array", "items": {
            "type": "object",
            "properties": {"sensor": {"enum": list(SENSORS)}, "is": {"enum": ["below", "above", "equals"]},
                           "value": {"type": "number"}},
            "required": ["sensor", "is", "value"]}},
        "match": {"enum": ["all", "any"]},
        "hold_seconds": {"type": "number"},
        "action": {"type": "object",
                   "properties": {"type": {"enum": ["fan", "job"]}, "set": {"enum": ["on", "off", ""]},
                                  "text": {"type": "string"}},
                   "required": ["type", "set", "text"]},
        "for_seconds": {"type": "number"},
        "priority": {"type": "integer"},
    },
    "required": ["can_do", "reason", "name", "trigger", "when", "match", "hold_seconds", "action",
                 "for_seconds", "priority"],
}

RULE_SYSTEM = """You turn one sentence from a washroom caretaker into one rule for a small controller.
Answer with JSON only, in the given shape.

What the controller has:
- Sensors (name: range): """ + "; ".join("%s: %s to %s %s" % (k, v[1], v[2], v[3]) for k, v in SENSORS.items()) + """
  door is 0 when open and 1 when closed. air_percent is percent of this room's normal air, 100 is normal.
  occupied_seconds counts while the door is closed. free_seconds counts while it is open.
- Triggers: "while" (true as long as the conditions hold) or "on_event" with event one of """ + ", ".join(TRIGGER_EVENTS) + """.
- Actions: switch the one exhaust fan on or off, or raise a job (a short text) for the caretaker.
- There is NO window, light, sprayer, valve, lock, camera, clock or calendar. It cannot identify people.

Rules for you:
- Use only numbers that are in the sentence. Convert minutes and hours to seconds.
- If the sentence asks for something the controller cannot do, or gives no usable condition or number,
  set can_do to false and say why in "reason" in one short sentence. Still fill the other fields with defaults.
- A fan rule started by an event needs for_seconds above 0.
- name: at most 40 characters, no comma. Job text: at most 60 characters, no comma.
- priority 4 unless the sentence says it is urgent (2) or minor (6).

Examples:
"Turn the fan on when humidity is above 70" ->
{"can_do":true,"reason":"","name":"Fan when humid","trigger":{"type":"while","event":""},"when":[{"sensor":"humidity_pct","is":"above","value":70}],"match":"all","hold_seconds":0,"action":{"type":"fan","set":"on","text":""},"for_seconds":0,"priority":4}
"After every use, if humidity is above 60, run the fan for 3 minutes" ->
{"can_do":true,"reason":"","name":"Fan after humid use","trigger":{"type":"on_event","event":"USE_END"},"when":[{"sensor":"humidity_pct","is":"above","value":60}],"match":"all","hold_seconds":0,"action":{"type":"fan","set":"on","text":""},"for_seconds":180,"priority":4}
"Tell me if water is falling faster than 10 mm a minute while nobody is inside" ->
{"can_do":true,"reason":"","name":"Water falling while free","trigger":{"type":"while","event":""},"when":[{"sensor":"water_rate_mm_per_min","is":"below","value":-10},{"sensor":"door","is":"equals","value":0}],"match":"all","hold_seconds":0,"action":{"type":"job","set":"","text":"Water is falling with nobody inside"},"for_seconds":0,"priority":3}
"Open the window when it smells" ->
{"can_do":false,"reason":"There is no window to open. I can switch the fan or raise a job.","name":"","trigger":{"type":"while","event":""},"when":[],"match":"all","hold_seconds":0,"action":{"type":"job","set":"","text":""},"for_seconds":0,"priority":4}
"""

REWORD_SYSTEM = """You reword facts from a washroom controller for the caretaker.
Write 2 or 3 short plain sentences. Use only the facts given. Do not add, change or round any number or time.
Do not give advice that is not in the facts. No lists, no headings."""


def status():
    """{"model": "qwen2.5:3b", "ready": bool, "detail": str}"""
    return ollama.status()


def warm_up():
    """Load the model and let it read the long rule instructions once, so the first real answer is quick.
    Returns the seconds it took, or None when the model is not running or did not answer."""
    if not ollama.status(max_age=0)["ready"]:
        return None
    t0 = time.time()
    raw = ollama.chat(RULE_SYSTEM, "Sentence: Turn the fan on when humidity is above 70", schema=RULE_SCHEMA,
                      timeout=180)
    return round(time.time() - t0, 1) if raw is not None else None


def _clean_rule(d):
    """Model output -> the rule shape (drops the helper fields, coerces whole numbers)."""
    def whole(v):
        return int(v) if isinstance(v, float) and v == int(v) else v
    trig = d.get("trigger") or {}
    trigger = {"type": "on_event", "event": trig.get("event")} if trig.get("type") == "on_event" else {"type": "while"}
    act = d.get("action") or {}
    action = {"type": "fan", "set": act.get("set")} if act.get("type") == "fan" else \
        {"type": "job", "text": str(act.get("text", "")).replace(",", " ").strip()[:60]}
    return {
        "name": str(d.get("name", "")).replace(",", " ").strip()[:40],
        "trigger": trigger,
        "when": [{"sensor": c.get("sensor"), "is": c.get("is"), "value": whole(c.get("value"))}
                 for c in (d.get("when") or []) if isinstance(c, dict)],
        "match": d.get("match", "all"),
        "hold_seconds": whole(d.get("hold_seconds", 0)),
        "action": action,
        "for_seconds": whole(d.get("for_seconds", 0)),
        "priority": d.get("priority", 4),
    }


def _numbers(text):
    return {m.lstrip("0") or "0" for m in re.findall(r"\d+(?:\.\d+)?", text)}


def _unseen_numbers(rule, sentence):
    """Numbers in the rule that the sentence does not contain (also allowing minutes/hours turned to seconds)."""
    said = set()
    for n in re.findall(r"\d+(?:\.\d+)?", sentence):
        v = float(n)
        said.update({v, v * 60, v * 3600, -v})
    notes = []
    for c in rule.get("when", []):
        v = c.get("value")
        if isinstance(v, (int, float)) and c.get("sensor") != "door" and float(v) not in said:
            notes.append("The value %s for %s was not in your sentence. Check it." % (v, c.get("sensor")))
    for key in ("hold_seconds", "for_seconds"):
        v = rule.get(key) or 0
        if v and float(v) not in said:
            notes.append("%s = %s was not in your sentence. Check it." % (key, v))
    return notes


PLAIN_NAMES = {"water_rate_mm_per_min": "The water level change", "water_level_mm": "The water level",
               "humidity_pct": "Humidity", "air_percent": "The air reading", "temperature_c": "The temperature",
               "occupied_seconds": "The time the door is closed", "free_seconds": "The time the room is free",
               "hold_seconds": "The hold time", "for_seconds": "The run time"}


def _plain(text):
    """The checker speaks in field names. People should not have to."""
    for key, words in PLAIN_NAMES.items():
        text = text.replace(key, words)
    return text.replace(" %;", "%;").replace("; got", ". You gave")


def draft_rule(sentence, existing=None):
    """Sentence -> {"rule", "by", "problems", "notes", "parts", "ms"}. See docs/AGENT_INTERFACE.md."""
    t0 = time.time()
    existing = existing or []

    def done(rule, by, problems, notes=None):
        problems = [_plain(x) for x in problems]
        return {"rule": rule, "by": by, "problems": problems, "notes": [_plain(x) for x in (notes or [])],
                "parts": rule_parts(rule) if rule else None, "ms": int((time.time() - t0) * 1000)}

    rule = patterns.parse(sentence)
    if rule is not None:
        return done(rule, "pattern", check_rule(rule, existing))

    if not ollama.status()["ready"]:
        return done(None, "none", ["I could not turn that into a rule. Try a shape like: "
                                   "\"turn the fan on when humidity is above 70\" or "
                                   "\"run the fan for 30 seconds after every use\"."])
    problems, last = [], None
    for attempt in range(2):
        user = "Sentence: " + sentence
        if attempt and problems:
            user += "\nYour last answer had these problems, fix them: " + " ".join(problems)
        raw = ollama.chat(RULE_SYSTEM, user, schema=RULE_SCHEMA)
        if raw is None:
            return done(None, "none", ["The model did not answer in time. Try a simpler sentence."])
        try:
            d = json.loads(raw)
        except ValueError:
            problems = ["The answer was not valid JSON."]
            continue
        if not d.get("can_do", True):
            return done(None, "model", [str(d.get("reason") or "That is not something this system can do.")])
        last = _clean_rule(d)
        problems = check_rule(last, existing)
        if not problems:
            return done(last, "model", [], _unseen_numbers(last, sentence))
    return done(last, "model", problems or ["I could not turn that into a rule."])


def explain(question, events, readings=None, rules=None, now=None, cfg=None):
    """Why did X happen. Returns {"answer", "event_ids", "by", "ms", "chain"}."""
    t0 = time.time()
    target = pick_target(events, question)
    chain = build_chain(events, readings or [], target, now, rules, cfg) if target else None
    facts = chain_text(chain)
    answer, by = facts, "template"
    if chain and ollama.status()["ready"]:
        raw = ollama.chat(REWORD_SYSTEM, "Question: %s\nFacts: %s" % (question, facts))
        if raw and len(raw) < 700 and _numbers(raw) <= _numbers(facts):
            answer, by = raw.strip(), "model"
    return {"answer": answer, "event_ids": chain["event_ids"] if chain else [], "by": by,
            "ms": int((time.time() - t0) * 1000), "chain": chain}


def _plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def report_text(f):
    """The plain shift report. Every figure is read from the facts."""
    out = ["From %s to %s the washroom was used %s." % (f.get("from", "?"), f.get("to", "?"),
                                                         _plural(f.get("uses", 0), "time"))]
    out.append("%s raised and %s closed." % (_plural(f.get("jobs_opened", 0), "job was", "jobs were"),
                                             _plural(f.get("jobs_closed", 0), "was", "were")))
    if f.get("cleans"):
        out.append("It was marked as cleaned %s." % _plural(f["cleans"], "time"))
    out.append("The fan ran for %s in total." % _plural(f.get("fan_minutes", 0), "minute"))
    if f.get("fan_checks_passed") or f.get("fan_checks_failed"):
        out.append("The fan check passed %s and failed %s." % (_plural(f.get("fan_checks_passed", 0), "time"),
                                                               _plural(f.get("fan_checks_failed", 0), "time")))
    if f.get("steam_held"):
        out.append("Steam held back the air alarm %s." % _plural(f["steam_held"], "time"))
    if f.get("water_lost_mm"):
        out.append("%d mm of water was lost to a tap left running or a leak." % f["water_lost_mm"])
    out.append("%s recorded." % _plural(f.get("faults", 0), "fault was", "faults were"))
    if f.get("open_jobs"):
        out.append("Still open: %s." % "; ".join(f["open_jobs"]))
    return " ".join(out)


def shift_report(facts):
    """{"text", "by", "ms"}"""
    t0 = time.time()
    text, by = report_text(facts), "template"
    if ollama.status()["ready"]:
        raw = ollama.chat(REWORD_SYSTEM.replace("2 or 3", "3 to 5"), "Write the shift handover.\nFacts: " + text)
        if raw and len(raw) < 900 and _numbers(raw) <= _numbers(text):
            text, by = raw.strip(), "model"
    return {"text": text, "by": by, "ms": int((time.time() - t0) * 1000)}


def route(text):
    """Which job a typed line is for: "why" | "report" | "status" | "rule". Decided by code, not the model."""
    q = text.strip().lower()
    if re.match(r"(why|what happened|what caused|when did|how come|explain)\b", q):
        return "why"
    if re.search(r"\b(report|summary|handover|shift)\b", q):
        return "report"
    if re.search(r"what needs me|needs me|what should i do|what do i need|anything to do|to do now|status", q):
        return "status"
    if re.search(r"\b(when|if|after|while|turn|switch|run|tell me|alert|warn|notify|ask for|every)\b", q):
        return "rule"
    return "why" if q.endswith("?") else "rule"
