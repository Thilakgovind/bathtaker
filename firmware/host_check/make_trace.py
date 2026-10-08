"""Writes trace.txt (inputs) and expected.txt (events) from the Python reference,
so the C++ logic can be checked against it:  see run.sh in this folder."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "contract"))
from board_sim import BoardSim
from room_logic import RoomLogic
from rules import encode_rule

here = os.path.dirname(__file__)
trace = open(os.path.join(here, "trace.txt"), "w")
orig_update, orig_cleaned, orig_manual = RoomLogic.update, RoomLogic.cleaned, RoomLogic.set_manual
orig_add, orig_del = RoomLogic.add_rule, RoomLogic.delete_rule
now = [0.0]

def update(self, t, door, level, gas, hum, temp, link_ok=True):
    now[0] = t
    trace.write("U %.3f %d %d %d %d %d %d %d %d\n" % (t, door, level is not None, level if level is not None else -1,
                                                     gas, hum is not None, hum if hum is not None else -1,
                                                     temp if temp is not None else -1, link_ok))
    return orig_update(self, t, door, level, gas, hum, temp, link_ok)

def cleaned(self, t):
    trace.write("C %.3f\n" % t); return orig_cleaned(self, t)

def set_manual(self, mode):
    trace.write("M %s\n" % mode); return orig_manual(self, mode)

def add_rule(self, t, slot, rule):
    trace.write("R %.3f %s\n" % (t, encode_rule(slot, rule).replace(" ", "~"))); return orig_add(self, t, slot, rule)

def delete_rule(self, t, slot):
    trace.write("X %.3f %d\n" % (t, slot)); return orig_del(self, t, slot)

RoomLogic.update, RoomLogic.cleaned, RoomLogic.set_manual = update, cleaned, set_manual
RoomLogic.add_rule, RoomLogic.delete_rule = add_rule, delete_rule

s = BoardSim(seed=3)
lines = []
def run(sec): lines.extend(s.run(sec))
def do(cmd): s.scenario(cmd)

run(90)                                            # quiet: learn the normal air level
do("door close"); run(1.5); do("door open"); run(3) # too short to count
for _ in range(2):
    do("door close"); run(6); do("door open"); run(4)
do("tap 20"); run(80); do("tap 0"); run(40)          # tap left running while free
do("door close"); do("tap 20"); run(70); do("tap 0"); do("door open"); run(30)   # falling while in use
do("steam on"); run(35); do("steam off"); run(200)   # steam, fan works
do("fan unplug"); do("steam on"); run(20); do("steam off"); run(120); do("fan plug"); run(400)  # fan fault
do("odour 0.7"); run(40); run(150)                   # bad air after uses
lines.extend(s.handle("CLEANED")); run(120)
do("odour 0.7"); run(40); run(150)                   # bad air with no uses
lines.extend(s.handle("CLEANED")); run(30)
for _ in range(5):
    do("door close"); run(5); do("door open"); run(3)  # cleaning due by count
lines.extend(s.handle("CLEANED")); run(10)
do("drain 30"); run(12); do("drain 200"); run(30)     # low water and back
do("link down"); run(8); do("link up"); run(5)
s.level_valid = False; run(6); s.level_valid = True; run(6)   # ultrasonic gives no echo
lines.extend(s.handle("FAN,ON")); run(10); lines.extend(s.handle("FAN,OFF")); run(5); lines.extend(s.handle("FAN,AUTO")); run(10)

# ---- caretaker rules ----
def rule(slot, r): lines.extend(s.handle(encode_rule(slot, r)))
W = {"type": "while"}
rule(1, {"name": "Fan after use", "trigger": {"type": "on_event", "event": "USE_END"}, "when": [], "match": "all",
         "hold_seconds": 0, "action": {"type": "fan", "set": "on"}, "for_seconds": 30, "priority": 3})
rule(2, {"name": "Door closed too long", "trigger": W, "when": [{"sensor": "occupied_seconds", "is": "above", "value": 10}],
         "match": "all", "hold_seconds": 0, "action": {"type": "job", "text": "Check on the person inside"}, "for_seconds": 0, "priority": 2})
do("door close"); run(5); do("door open"); run(45)            # rule 1 runs the fan 30 s
do("door close"); run(16); do("door open"); run(40)           # rule 2 raises a job, then rule 1 again
rule(3, {"name": "Fan when damp", "trigger": W, "when": [{"sensor": "humidity_pct", "is": "above", "value": 66.5}],
         "match": "all", "hold_seconds": 5, "action": {"type": "fan", "set": "on"}, "for_seconds": 0, "priority": 4})
rule(4, {"name": "Quiet while occupied", "trigger": W, "when": [{"sensor": "door", "is": "equals", "value": 1},
         {"sensor": "humidity_pct", "is": "below", "value": 90}], "match": "all", "hold_seconds": 0,
         "action": {"type": "fan", "set": "off"}, "for_seconds": 0, "priority": 4})
do("steam on"); run(12); do("steam off"); run(30)             # rule 3 turns the fan on
do("door close"); run(20); do("door open"); run(60)           # rule 4 ties with rule 3: off wins while occupied
rule(5, {"name": "Low water or bad air", "trigger": W, "when": [{"sensor": "water_level_mm", "is": "below", "value": 100},
         {"sensor": "air_percent", "is": "above", "value": 140}], "match": "any", "hold_seconds": 3,
         "action": {"type": "job", "text": "Look at the washroom"}, "for_seconds": 20, "priority": 6})
do("drain 80"); run(40); do("drain 200"); run(20)
rule(6, {"name": "After cleaning", "trigger": {"type": "on_event", "event": "CLEANED"}, "when": [{"sensor": "uses", "is": "above", "value": 0}],
         "match": "all", "hold_seconds": 0, "action": {"type": "fan", "set": "on"}, "for_seconds": 15, "priority": 1})
lines.extend(s.handle("CLEANED")); run(25)
lines.extend(s.handle("DEL,3")); lines.extend(s.handle("DEL,4")); run(20)
lines.extend(s.handle("RULES?"))

trace.close()
with open(os.path.join(here, "expected.txt"), "w") as f:
    for l in lines:
        if l.startswith("E,") or l.startswith("R,"):
            f.write(l + "\n")
print("steps:", sum(1 for _ in open(os.path.join(here, "trace.txt"))), " events:", sum(1 for l in lines if l.startswith("E,")))
