"""Things the laptop notices in the history, and the figures for a shift report. Counting only: no model.

A notice is a pattern found by code, with the events it rests on and, when it helps, a draft rule
the caretaker can approve. The agent never acts on a notice by itself.
"""
import time

OPENERS = ("FAN_FAULT", "SENSOR_FAULT", "LINK_LOST", "TAP_CONFIRMED", "LOW_WATER", "DRAIN_CHECK", "CLEAN_DUE")
CLOSERS = ("FAN_VERIFIED", "SENSOR_OK", "LINK_OK", "TAP_CLEARED", "WATER_OK", "CLEANED")


def notices(events, clean_uses=5, dismissed=None):
    """events: the last day or so, oldest first."""
    dismissed = dismissed or set()
    out = []

    # the air turns bad before the cleaning count is reached, more than once
    early = [e for e in events if e["code"] == "AIR_BAD" and 2 <= e["b"] <= clean_uses]
    if len(early) >= 2:
        m = min(e["b"] for e in early)
        target = m - 1                       # ask for cleaning one use earlier than the earliest bad-air use
        if target >= 1:
            uses = sorted({e["b"] for e in early})
            where = "use %d" % uses[0] if len(uses) == 1 else "uses %s" % " and ".join(str(u) for u in uses)
            uses_words = "1 use" if target == 1 else "%d uses" % target
            out.append({
                "id": "clean-earlier-%d" % target,
                "text": "The air changed right after %s, %d times in the last 24 hours. "
                        "Ask for cleaning after %d %s instead of %d?" % (
                            where, len(early), target, "use" if target == 1 else "uses", clean_uses),
                "sentence": "Ask for cleaning after " + uses_words,
                "rule": {"name": "Clean after " + uses_words, "trigger": {"type": "while"},
                         "when": [{"sensor": "uses", "is": "above", "value": target - 1}], "match": "all",
                         "hold_seconds": 0, "action": {"type": "job", "text": "Clean the washroom: " + uses_words},
                         "for_seconds": 0, "priority": 4},
                "event_ids": [e["id"] for e in early],
            })

    faults = [e for e in events if e["code"] == "FAN_FAULT"]
    if len(faults) >= 2:
        out.append({"id": "fan-failing-%d" % len(faults),
                    "text": "The fan failed its check %d times in the last 24 hours. Have the fan looked at." % len(faults),
                    "sentence": None, "rule": None, "event_ids": [e["id"] for e in faults]})

    held = [e for e in events if e["code"] == "AIR_SUPPRESSED"]
    if held:
        out.append({"id": "steam-held-%d" % len(held),
                    "text": "Steam was held back from raising a false air alarm %s in the last 24 hours." % (
                        "once" if len(held) == 1 else "%d times" % len(held)),
                    "sentence": None, "rule": None, "event_ids": [e["id"] for e in held]})
    return [n for n in out if n["id"] not in dismissed]


def shift_facts(events, since, until, open_jobs=None):
    """Every figure in a shift report, counted from events."""
    tap_loss, current = 0, 0
    for e in events:
        if e["code"] == "TAP_CONFIRMED":
            current = max(current, e["b"])
        elif e["code"] == "TAP_CLEARED":
            tap_loss += current
            current = 0
    tap_loss += current
    count = lambda *codes: sum(1 for e in events if e["code"] in codes)
    return {
        "from": time.strftime("%H:%M", time.localtime(since)), "to": time.strftime("%H:%M", time.localtime(until)),
        "uses": count("USE_END"),
        "jobs_opened": count(*OPENERS), "jobs_closed": count(*CLOSERS),
        "cleans": count("CLEANED"),
        "fan_minutes": int(round(sum(e["a"] for e in events if e["code"] == "FAN_OFF") / 60)),
        "fan_checks_passed": count("FAN_VERIFIED"), "fan_checks_failed": count("FAN_FAULT"),
        "steam_held": count("AIR_SUPPRESSED"),
        "water_lost_mm": tap_loss,
        "faults": count("FAN_FAULT", "SENSOR_FAULT", "LINK_LOST"),
        "open_jobs": [j["title"] for j in (open_jobs or [])],
    }
