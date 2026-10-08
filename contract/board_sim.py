"""A pretend room board. It speaks the real protocol, so the laptop software can be
built and tested before the hardware works.

    python contract/board_sim.py                 serves the protocol on TCP port 5555
    backend connects with pyserial:  serial.serial_for_url("socket://localhost:5555")

While it runs, type scenario commands in this terminal:
    door close | door open | tap 20 | tap 0 | steam on | steam off | odour 0.6 | odour 0
    fan unplug | fan plug | link down | link up | drain 300 (set level mm) | quit

EVERYTHING THIS PRODUCES IS MADE-UP DATA. Never use it in results or slides.
The physics numbers are invented; only the protocol and the decision logic are real.
"""
import random
import socket
import sys
import threading
import time

from protocol import PROTOCOL_VERSION, Event, Reading, format_event, format_reading
from room_logic import RoomLogic
from rules import decode_rule, encode_rule

AMBIENT_HUM = 60.0


class BoardSim:
    def __init__(self, seed=1, dt=0.5, **cfg):
        self.rng = random.Random(seed)
        self.dt = dt
        self.t = 0.0
        self.logic = RoomLogic(**cfg)
        self.door_closed = False
        self.level = 220.0           # mm of water
        self.tap = 0.0               # mm per minute leaving the tank
        self.hum = AMBIENT_HUM
        self.temp = 28.5
        self.temp_target = 28.5
        self.steam = 0.0             # %RH per second added
        self.odour = 0.0             # 0 = clean air
        self.fan_works = True
        self.link_ok = True
        self.level_valid = True
        self.log = []                # every E line ever produced

    def step(self):
        """Advance one tick. Returns the protocol lines the board would print."""
        dt = self.dt
        self.t += dt
        self.level = max(0.0, self.level - self.tap * dt / 60.0)
        blowing = self.logic.fan and self.fan_works
        self.hum += dt * (self.steam - 0.002 * (self.hum - AMBIENT_HUM) - (0.05 * (self.hum - AMBIENT_HUM) if blowing else 0))
        self.hum = min(98.0, max(20.0, self.hum))
        self.odour = max(0.0, self.odour - dt * self.odour * (0.03 if blowing else 0.0005))
        gas = 900 * (1 + 0.6 * self.odour) + 12 * (self.hum - AMBIENT_HUM) + self.rng.gauss(0, 5)
        level = round(self.level + self.rng.gauss(0, 0.6)) if self.level_valid else None
        self.temp += (self.temp_target - self.temp) * min(1.0, dt * 0.25)   # warms or cools over a few seconds
        hum = round(self.hum * 10)
        temp = round(self.temp * 10)
        self.logic.update(self.t, self.door_closed, level, int(gas), hum, temp, self.link_ok)
        lg = self.logic
        ms = int(self.t * 1000)
        out = []
        for (t, seq, code, a, b) in lg.collect():
            line = format_event(Event(int(t * 1000), seq, code, a, b))
            out.append(line); self.log.append(line)
        out.append(format_reading(Reading(ms, int(self.door_closed), -1 if level is None else level, lg.level_rate,
                                          int(gas), lg.gas_pct, hum, temp, int(lg.fan), lg.state, lg.uses,
                                          lg.flags(self.link_ok))))
        return out

    def run(self, seconds):
        lines = []
        for _ in range(int(seconds / self.dt)):
            lines += self.step()
        return lines

    def codes(self, lines):
        return [l.split(",")[3] for l in lines if l.startswith("E,")]

    # ---- commands from the laptop ----
    def handle(self, line):
        p = line.strip().split(",")
        cmd = p[0].upper()
        lg = self.logic
        try:
            if cmd == "PING":
                return ["A,PING,OK"]
            if cmd == "HELLO?":
                return ["H,%d,sim-0.1,ROOM" % PROTOCOL_VERSION]
            if cmd == "CLEANED":
                lg.cleaned(self.t); return ["A,CLEANED,OK"]
            if cmd == "FAN" and p[1].upper() in ("AUTO", "ON", "OFF"):
                lg.set_manual(p[1].upper()); return ["A,FAN,OK,%s" % p[1].upper()]
            if cmd == "RULE":
                slot, rule = decode_rule(line.strip())
                if not (1 <= slot <= 8):
                    return ["A,RULE,ERR,slot must be 1 to 8"]
                lg.add_rule(self.t, slot, rule); return ["A,RULE,OK,%d" % slot]
            if cmd == "DEL":
                lg.delete_rule(self.t, int(p[1])); return ["A,DEL,OK,%s" % p[1]]
            if cmd == "RULES?":
                out = ["R," + encode_rule(s, r)[5:] for s, r in sorted(lg.rules.items())]
                return out + ["A,RULES,OK,%d" % len(lg.rules)]
            if cmd == "CFG" and p[1] in lg.cfg:
                lg.cfg[p[1]] = int(p[2]); return ["A,CFG,OK,%s,%s" % (p[1], p[2])]
            if cmd == "CFG?":
                return ["A,CFG,OK," + ";".join("%s=%s" % kv for kv in sorted(lg.cfg.items()))]
            if cmd == "LOG?":
                return self.log[-50:] + ["A,LOG,OK,%d" % min(50, len(self.log))]
        except (ValueError, IndexError, KeyError) as e:
            return ["A,%s,ERR,%s" % (cmd, type(e).__name__)]
        return ["A,%s,ERR,unknown command" % cmd]

    # ---- scenario controls (the "hands" in the pretend washroom) ----
    def scenario(self, text):
        w = text.strip().lower().split()
        if not w:
            return ""
        try:
            if w[0] == "door":
                self.door_closed = (w[1] == "close")
            elif w[0] == "tap":
                self.tap = float(w[1])
            elif w[0] == "steam":
                self.steam = 1.5 if w[1] == "on" else 0.0
            elif w[0] == "odour":
                self.odour = float(w[1])
            elif w[0] == "fan":
                self.fan_works = (w[1] == "plug")
            elif w[0] == "link":
                self.link_ok = (w[1] == "up")
            elif w[0] == "temp":
                self.temp_target = float(w[1])
            elif w[0] == "drain":
                self.level = float(w[1])
            else:
                return "unknown: " + text
        except (IndexError, ValueError):
            return "bad command: " + text
        return "ok: " + text


def serve(port=5555):
    sim = BoardSim(BASELINE_STABLE_S=15)
    sim.handle("RULE,8,1,ANY,0,FAN_ON,0,WHILE,1,TEMP,GT,370,Fan when hot")   # same built-in rule as the real board
    lock = threading.Lock()
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen(1)
    print("Pretend board on socket://localhost:%d  (made-up data). Type 'temp 38', 'odour 0.8', 'tap 20', 'steam on' ..." % port)

    def keys():
        for line in sys.stdin:
            if line.strip() == "quit":
                import os; os._exit(0)
            with lock:
                print(sim.scenario(line))
    threading.Thread(target=keys, daemon=True).start()

    while True:
        conn, _ = srv.accept()
        conn.settimeout(0.01)
        buf = b""
        try:
            conn.sendall(("H,%d,sim-0.1,ROOM\n" % PROTOCOL_VERSION).encode())
            while True:
                t0 = time.time()
                with lock:
                    lines = sim.step()
                    try:
                        buf += conn.recv(4096)
                    except socket.timeout:
                        pass
                    while b"\n" in buf:
                        cmd, buf = buf.split(b"\n", 1)
                        lines += sim.handle(cmd.decode("ascii", "ignore"))
                conn.sendall(("\n".join(lines) + "\n").encode())
                time.sleep(max(0, sim.dt - (time.time() - t0)))
        except (BrokenPipeError, ConnectionResetError, OSError):
            conn.close()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 5555)
