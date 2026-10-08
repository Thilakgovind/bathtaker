"""The text lines the room board and the laptop exchange. Reference implementation.

One line per message, ASCII, comma separated, ends with \\n, 115200 baud.
Integers only, so the firmware never formats floats.
docs/PROTOCOL.md is the human description; this file and its tests are the authority.
"""
from dataclasses import dataclass, asdict

PROTOCOL_VERSION = 1

STATES = ["FREE", "IN_USE", "VENTILATING", "NEEDS_CLEANING", "NO_WATER", "FAULT"]

# flags bitmask in the D line
FLAG_STEAM_GATE = 1       # steam detected, air alarm is being held back
FLAG_BASELINE_OK = 2      # the gas sensor's normal level has been learned
FLAG_LINK_OK = 4          # service board acknowledged within 3 s
FLAG_FAN_MANUAL = 8       # fan is under manual override
FLAG_TAP_SUSPECTED = 16
FLAG_AIR_BAD = 32

FAN_REASONS = {1: "humidity", 2: "air", 3: "rule", 4: "manual"}
SENSOR_IDS = {1: "ultrasonic", 2: "gas", 3: "humidity", 4: "door"}

EVENT_CODES = [
    "BOOT", "USE_START", "USE_END", "TAP_SUSPECTED", "TAP_CONFIRMED", "TAP_CLEARED",
    "LOW_WATER", "WATER_OK", "AIR_BAD", "AIR_OK", "STEAM_GATE_ON", "STEAM_GATE_OFF",
    "AIR_SUPPRESSED", "FAN_ON", "FAN_OFF", "FAN_VERIFIED", "FAN_FAULT", "CLEAN_DUE",
    "DRAIN_CHECK", "CLEANED", "SENSOR_FAULT", "SENSOR_OK", "LINK_LOST", "LINK_OK",
    "RULE_FIRED", "RULE_ADDED", "RULE_DELETED",
]


@dataclass
class Reading:
    ms: int
    door: int            # 0 open, 1 closed
    level_mm: int        # water depth, -1 if no valid echo
    level_rate: int      # mm per minute, negative = falling
    gas_raw: int         # 0..4095 from the ADC
    gas_pct: int         # percent of the learned normal level, 100 = normal, 0 = not learned yet
    hum: int             # %RH x 10, -1 if invalid
    temp: int            # deg C x 10, -1 if invalid
    fan: int             # 0 off, 1 on (what the room board is commanding)
    state: str
    uses: int            # uses since the last clean
    flags: int


@dataclass
class Event:
    ms: int
    seq: int
    code: str
    a: int = 0
    b: int = 0


def format_reading(r: Reading) -> str:
    return "D,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%d" % (
        r.ms, r.door, r.level_mm, r.level_rate, r.gas_raw, r.gas_pct, r.hum, r.temp,
        r.fan, r.state, r.uses, r.flags)


def format_event(e: Event) -> str:
    return "E,%d,%d,%s,%d,%d" % (e.ms, e.seq, e.code, e.a, e.b)


def parse_line(line: str):
    """Returns ("D", Reading) | ("E", Event) | ("H", dict) | ("A", dict) | ("R", str) | None.
    Anything unrecognised (boot noise, partial lines) returns None and must be ignored."""
    line = line.strip()
    if not line or "," not in line:
        return None
    p = line.split(",")
    try:
        if p[0] == "D" and len(p) == 13 and p[10] in STATES:
            n = [int(x) for x in p[1:10]]
            return ("D", Reading(n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7], n[8],
                                 p[10], int(p[11]), int(p[12])))
        if p[0] == "E" and len(p) == 6 and p[3] in EVENT_CODES:
            return ("E", Event(int(p[1]), int(p[2]), p[3], int(p[4]), int(p[5])))
        if p[0] == "H" and len(p) >= 4:
            return ("H", {"protocol": int(p[1]), "firmware": p[2], "board": p[3]})
        if p[0] == "A" and len(p) >= 3:
            return ("A", {"cmd": p[1], "ok": p[2] == "OK", "detail": ",".join(p[3:])})
        if p[0] == "R" and len(p) >= 3:
            return ("R", "RULE," + ",".join(p[1:]))
    except ValueError:
        return None
    return None


def reading_dict(r: Reading) -> dict:
    d = asdict(r)
    d["hum_pct"] = None if r.hum < 0 else r.hum / 10
    d["temp_c"] = None if r.temp < 0 else r.temp / 10
    d["steam_gate"] = bool(r.flags & FLAG_STEAM_GATE)
    d["baseline_ok"] = bool(r.flags & FLAG_BASELINE_OK)
    d["link_ok"] = bool(r.flags & FLAG_LINK_OK)
    d["fan_manual"] = bool(r.flags & FLAG_FAN_MANUAL)
    d["tap_suspected"] = bool(r.flags & FLAG_TAP_SUSPECTED)
    d["air_bad"] = bool(r.flags & FLAG_AIR_BAD)
    return d
