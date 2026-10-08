"""Events -> the caretaker's job list. Rebuilt from the stored events every time, so a restart loses nothing.

Every number in a reason comes from an event field. The board decides what is wrong; this file only words it.
"""
from agent.words import SENSOR_NAMES


def build_jobs(events, rules=None, closed=None):
    """events: this session's events, oldest first. rules: {slot: rule} from the board.
    closed: keys a person marked as done. Returns open jobs, most urgent first."""
    rules = rules or {}
    closed = closed or set()
    jobs = {}                            # key -> job
    last_air = None                      # the latest AIR_BAD event, for the cleaning reason

    def open_job(key, e, title, priority, reason, closes_with, can_mark_done=False):
        old = jobs.get(key)
        jobs[key] = {
            "key": key, "title": title, "priority": priority, "reason": reason,
            "since": old["since"] if old else e["ts"], "since_time": old["since_time"] if old else e["time"],
            "event_ids": (old["event_ids"] if old else []) + [e["id"]],
            "closes_with": closes_with, "can_mark_done": can_mark_done, "code": e["code"],
        }

    def close(key, e=None):
        jobs.pop(key, None)

    for e in events:
        code, a, b = e["code"], e["a"], e["b"]
        if code == "BOOT":
            jobs.clear()                 # the board restarted: its own state is clean again
        elif code == "AIR_BAD":
            last_air = e
        elif code == "FAN_FAULT":
            how = ("humidity fell only %g%%" % (b / 10)) if a == 1 else ("the air improved by only %d points" % b)
            open_job("fan", e, "Check the fan", 1,
                     "The fan was switched on but %s in 60 s." % how, "the next fan check that passes, or Mark as cleaned")
        elif code == "FAN_VERIFIED":
            close("fan")
        elif code == "SENSOR_FAULT":
            name = SENSOR_NAMES.get(a, "a")
            open_job("sensor%d" % a, e, "Check the %s sensor" % name, 1,
                     "The %s sensor has given no valid reading for 3 s." % name, "a valid reading")
        elif code == "SENSOR_OK":
            close("sensor%d" % a)
        elif code == "LINK_LOST":
            open_job("link", e, "Check the fan board", 1, "The fan board has not answered for 3 s.",
                     "the fan board answering again")
        elif code == "LINK_OK":
            close("link")
        elif code == "TAP_SUSPECTED":
            open_job("tap", e, "Possible tap left running", 4,
                     "Water is falling at %d mm a minute with nobody inside." % a, "the water level holding steady")
        elif code == "TAP_CONFIRMED":
            open_job("tap", e, "Tap left running or leak", 1,
                     "Water has fallen %d mm, at %d mm a minute, with nobody inside." % (b, a),
                     "the water level holding steady")
        elif code == "TAP_CLEARED":
            close("tap")
        elif code == "LOW_WATER":
            open_job("water", e, "No water", 2, "The water level is %d mm, under the low mark." % a,
                     "the tank being refilled")
        elif code == "WATER_OK":
            close("water")
        elif code == "DRAIN_CHECK":
            open_job("drain", e, "Check the drain", 2,
                     "The air is %d%% above normal and nobody has used the room since it was cleaned." % (a - 100),
                     "Mark as cleaned")
        elif code == "CLEAN_DUE":
            if b == 1:
                reason = "Used %d times since the last clean." % a
            elif last_air is not None:
                reason = "The air is %d%% above normal after %d %s since the last clean." % (
                    last_air["a"] - 100, a, "use" if a == 1 else "uses")
            else:
                reason = "The air changed after %d uses since the last clean." % a
            open_job("clean", e, "Clean the washroom", 3, reason, "Mark as cleaned")
        elif code == "CLEANED":
            close("clean"); close("drain"); close("fan")
        elif code == "RULE_FIRED":
            rule = rules.get(a)
            if rule and rule.get("action", {}).get("type") == "job":
                key = "rule%d" % a
                open_job(key, e, rule["action"]["text"], max(1, min(8, rule.get("priority", 4))),
                         "Your rule \"%s\" fired." % rule["name"], "Mark done", can_mark_done=True)
                jobs[key]["mark_key"] = "%s@%d" % (key, e["id"])
        elif code == "RULE_DELETED":
            close("rule%d" % a)

    out = [j for j in jobs.values() if j.get("mark_key") not in closed]
    out.sort(key=lambda j: (j["priority"], j["since"]))
    return out
