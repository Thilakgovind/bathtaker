"""Run:  python -m pytest contract -q     (or: python contract/test_contract.py)
These tests are the acceptance checks for the protocol, the rules and the room logic.
The firmware must reproduce the same event sequences on the real rig."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from board_sim import BoardSim
from protocol import Event, Reading, format_event, format_reading, parse_line
from rules import check_rule, decode_rule, encode_rule

FAST = dict(BASELINE_STABLE_S=10)


def ready():
    s = BoardSim(**FAST)
    s.run(40)                     # door open, quiet: learns the gas sensor's normal level
    assert s.logic.baseline, "normal level should be learned in a quiet room"
    return s


def test_protocol_round_trip():
    r = Reading(1500, 1, 212, -7, 934, 104, 612, 285, 0, "IN_USE", 3, 6)
    assert parse_line(format_reading(r)) == ("D", r)
    e = Event(1500, 9, "TAP_CONFIRMED", 12, 9)
    assert parse_line(format_event(e)) == ("E", e)
    assert parse_line("ets Jul 29 2019 12:21:46") is None
    assert parse_line("D,1,2,3") is None
    assert parse_line("E,1,2,NOT_A_CODE,0,0") is None
    assert parse_line("A,RULE,ERR,slot must be 1 to 8")[1]["ok"] is False


def test_use_is_counted():
    s = ready()
    s.scenario("door close"); a = s.codes(s.run(6))
    s.scenario("door open"); b = s.codes(s.run(2))
    assert "USE_START" in a and "USE_END" in b and s.logic.uses == 1


def test_a_brief_door_close_is_not_a_use():
    s = ready()
    s.scenario("door close"); s.run(1.5); s.scenario("door open"); s.run(2)
    assert s.logic.uses == 0


def test_tap_running_while_free_is_suspected_then_confirmed():
    s = ready()
    s.scenario("tap 20"); codes = s.codes(s.run(70))
    assert codes.index("TAP_SUSPECTED") < codes.index("TAP_CONFIRMED")
    s.scenario("tap 0"); assert "TAP_CLEARED" in s.codes(s.run(45))


def test_water_falling_while_in_use_raises_nothing():
    s = ready()
    s.scenario("door close"); s.scenario("tap 20"); codes = s.codes(s.run(70))
    assert "TAP_SUSPECTED" not in codes and "TAP_CONFIRMED" not in codes


def test_steam_starts_fan_and_fan_is_verified_and_air_alarm_is_held_back():
    s = ready()
    s.scenario("steam on"); a = s.codes(s.run(35))
    s.scenario("steam off"); b = s.codes(s.run(120))
    codes = a + b
    assert "STEAM_GATE_ON" in codes and "FAN_ON" in codes and "FAN_VERIFIED" in codes and "FAN_OFF" in codes
    assert "AIR_BAD" not in codes, "steam must not be reported as bad air"
    assert "AIR_SUPPRESSED" in codes, "the raw reading did cross the line; the gate held it back"
    assert "FAN_FAULT" not in codes


def test_unplugged_fan_is_caught():
    s = ready()
    s.scenario("fan unplug"); s.scenario("steam on"); s.run(20); s.scenario("steam off")
    codes = s.codes(s.run(90))
    assert "FAN_FAULT" in codes and s.logic.state == "FAULT"


def test_bad_air_after_uses_means_clean_now():
    s = ready()
    for _ in range(2):
        s.scenario("door close"); s.run(5); s.scenario("door open"); s.run(3)
    s.scenario("odour 0.7"); codes = s.codes(s.run(30))
    assert "AIR_BAD" in codes and "CLEAN_DUE" in codes and "DRAIN_CHECK" not in codes
    assert "FAN_ON" in codes
    later = s.codes(s.run(120))
    assert "FAN_VERIFIED" in codes + later and "AIR_OK" in later


def test_bad_air_with_no_uses_means_check_the_drain():
    s = ready()
    s.scenario("odour 0.7"); codes = s.codes(s.run(30))
    assert "DRAIN_CHECK" in codes and "CLEAN_DUE" not in codes


def test_cleaning_due_after_enough_uses_and_cleared_by_cleaned():
    s = ready()
    for _ in range(5):
        s.scenario("door close"); s.run(5); s.scenario("door open"); s.run(3)
    assert s.logic.state == "NEEDS_CLEANING"
    assert s.handle("CLEANED") == ["A,CLEANED,OK"]
    s.run(1); assert s.logic.uses == 0 and s.logic.state == "FREE"


def test_low_water():
    s = ready()
    s.scenario("drain 30"); assert "LOW_WATER" in s.codes(s.run(10)) and s.logic.state == "NO_WATER"


def test_lost_link_is_a_fault():
    s = ready()
    s.scenario("link down"); assert "LINK_LOST" in s.codes(s.run(6)) and s.logic.state == "FAULT"
    s.scenario("link up"); assert "LINK_OK" in s.codes(s.run(2))


FAN_AFTER_USE = {"name": "Fan after use", "trigger": {"type": "on_event", "event": "USE_END"}, "when": [],
                 "match": "all", "hold_seconds": 0, "action": {"type": "fan", "set": "on"}, "for_seconds": 30, "priority": 3}
FAN_IF_HUMID = {"name": "Fan when humid", "trigger": {"type": "while"},
                "when": [{"sensor": "humidity_pct", "is": "above", "value": 70}], "match": "all", "hold_seconds": 5,
                "action": {"type": "fan", "set": "on"}, "for_seconds": 0, "priority": 4}


def test_rule_round_trip_and_board_accepts_it():
    line = encode_rule(1, FAN_AFTER_USE)
    assert line == "RULE,1,3,ALL,0,FAN_ON,30,ON:USE_END,0,Fan after use"
    assert decode_rule(line) == (1, FAN_AFTER_USE)
    assert decode_rule(encode_rule(2, FAN_IF_HUMID)) == (2, FAN_IF_HUMID)
    s = ready()
    assert s.handle(line) == ["A,RULE,OK,1"]
    assert s.handle("RULES?")[-1] == "A,RULES,OK,1"


def test_rule_runs_fan_for_set_time_after_each_use():
    s = ready(); s.handle(encode_rule(1, FAN_AFTER_USE))
    s.scenario("door close"); s.run(5); s.scenario("door open")
    codes = s.codes(s.run(5))
    assert "RULE_FIRED" in codes and s.logic.fan
    s.run(40); assert not s.logic.fan


def test_checker_refuses_bad_rules():
    bad = dict(FAN_IF_HUMID, when=[{"sensor": "humidity_pct", "is": "above", "value": 150}])
    assert any("between 0 and 100" in p for p in check_rule(bad))
    assert check_rule(dict(FAN_IF_HUMID, when=[{"sensor": "smell", "is": "above", "value": 1}]))
    assert check_rule(dict(FAN_AFTER_USE, for_seconds=0))          # fan would never stop
    assert check_rule(dict(FAN_IF_HUMID, name="a,b"))
    assert check_rule(FAN_IF_HUMID) == []
    assert any("repeats" in p for p in check_rule(FAN_IF_HUMID, [FAN_IF_HUMID]))
    off = dict(FAN_IF_HUMID, name="Fan off when damp", action={"type": "fan", "set": "off"},
               when=[{"sensor": "humidity_pct", "is": "above", "value": 60}])
    assert any("clashes" in p for p in check_rule(off, [FAN_IF_HUMID]))
    apart = dict(off, when=[{"sensor": "humidity_pct", "is": "below", "value": 50}])
    assert check_rule(apart, [FAN_IF_HUMID]) == []                  # ranges never overlap, so no clash
    assert any("at most 8" in p for p in check_rule(dict(FAN_IF_HUMID, name="Nine"), [dict(FAN_IF_HUMID, name=str(i), hold_seconds=i) for i in range(8)]))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for f in fns:
        try:
            f(); print("  pass ", f.__name__)
        except AssertionError as e:
            failed += 1; print("  FAIL ", f.__name__, e)
    print("%d of %d checks pass" % (len(fns) - failed, len(fns)))
    sys.exit(1 if failed else 0)
