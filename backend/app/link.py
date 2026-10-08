"""The cable to the room board. One thread owns the port: it reads every line and writes every command.

The same code path serves the real board ("COM5") and the pretend board ("socket://localhost:5555").
Nothing here decides anything about the washroom: it only moves lines.
"""
import threading
import time

import serial

from protocol import parse_line  # contract/protocol.py


class BoardLink:
    """Holds a worker thread instead of being one, so no name here can collide with Python's own
    threading internals. (A private method name did exactly that on Python 3.13.)"""

    def __init__(self, port, on_message, baud=115200):
        self._thread = threading.Thread(target=self._run, daemon=True, name="board-link")
        self.port = port                 # None means "no port chosen"
        self.baud = baud
        self.on_message = on_message     # called with (kind, payload, wall_time) for D, E and H lines
        self.connected = False
        self.connections = 0             # counts every successful open, so "a new connection" is unambiguous
        self.hello = None                # {"protocol", "firmware", "board"} once the board has said hello
        self.last_line_at = 0.0
        self.error = "" if port else "No port chosen. Start with --port COM5 (or the pretend board address)."
        self._ser = None
        self._write_lock = threading.Lock()   # one command at a time
        self._pending = None                  # {"cmd", "done": Event, "answer", "rules": []}
        self._quit = threading.Event()

    # ---- facts about the link ----
    @property
    def source(self):
        """Every stored row carries this. "SIMULATED" data must never be used as a result."""
        if not self.hello:
            return "UNKNOWN"
        return "SIMULATED" if str(self.hello.get("firmware", "")).lower().startswith("sim") else "BOARD"

    def info(self):
        return {"connected": self.connected, "port": self.port, "source": self.source, "hello": self.hello,
                "connection": self.connections,
                "silent_for_s": round(time.time() - self.last_line_at, 1) if self.last_line_at else None,
                "error": self.error}

    # ---- the reading thread ----
    def start(self):
        self._thread.start()

    def stop(self, wait=3.0):
        """Ask the reader to finish and wait for it. Safe to call when it was never started."""
        self._quit.set()
        if self._thread.is_alive():
            self._thread.join(wait)

    def is_alive(self):
        return self._thread.is_alive()

    def _run(self):
        while not self._quit.is_set():
            if not self.port:
                time.sleep(0.5)
                continue
            try:
                self._ser = serial.serial_for_url(self.port, self.baud, timeout=0.5)
                self.connected, self.error, self.hello = True, "", None
                self.connections += 1
                self._notify("LINK", self.info())
                self._ser.write(b"HELLO?\n")
                asked = time.time()
                while not self._quit.is_set():
                    raw = self._ser.readline()
                    if not raw:
                        if self.hello is None and time.time() - asked > 3:
                            self._ser.write(b"HELLO?\n")
                            asked = time.time()
                        continue
                    self.last_line_at = time.time()
                    self._process_line(raw.decode("ascii", "ignore"))
            except (serial.SerialException, OSError, ValueError) as e:
                self.error = "Cannot reach the board on %s: %s" % (self.port, e)
            finally:
                was = self.connected
                self.connected = False
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None
                if self._pending:
                    self._pending["done"].set()
                if was:
                    self._notify("LINK", self.info())
            self._quit.wait(1.0)             # try again every second; the backend never needs a restart

    def _notify(self, kind, payload):
        try:
            self.on_message(kind, payload, time.time())
        except Exception:                    # a bug upstream must not kill the reader
            pass

    def _process_line(self, line):
        parsed = parse_line(line)
        if parsed is None:
            return                           # boot text, half lines, the '#' sentences for people
        kind, payload = parsed
        if kind == "H":
            self.hello = payload
            self._notify("LINK", self.info())
        elif kind in ("D", "E"):
            self._notify(kind, payload)
        elif kind == "R":
            if self._pending is not None:
                self._pending["rules"].append(payload)
        elif kind == "A":
            p = self._pending
            if p is not None and payload["cmd"].upper() == p["cmd"]:
                p["answer"] = payload
                p["done"].set()

    # ---- commands ----
    def send(self, line, wait=3.0):
        """Send one command line and wait for the board's answer.
        Returns {"ok", "detail", "rules": [...]} or {"ok": False, "detail": why} if silent or not connected."""
        cmd = line.split(",")[0].strip().upper().rstrip("?")
        with self._write_lock:
            if not self.connected or self._ser is None:
                return {"ok": False, "detail": "The board is not connected.", "rules": []}
            self._pending = {"cmd": cmd, "done": threading.Event(), "answer": None, "rules": []}
            try:
                self._ser.write((line.strip() + "\n").encode("ascii", "ignore"))
            except (serial.SerialException, OSError) as e:
                self._pending = None
                return {"ok": False, "detail": "Could not write to the board: %s" % e, "rules": []}
            p = self._pending
            p["done"].wait(wait)
            self._pending = None
            if p["answer"] is None:
                return {"ok": False, "detail": "The board did not answer within %g s." % wait, "rules": p["rules"]}
            return {"ok": p["answer"]["ok"], "detail": p["answer"]["detail"], "rules": p["rules"]}
