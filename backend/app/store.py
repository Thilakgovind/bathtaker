"""History in one SQLite file. Every row carries its source: BOARD or SIMULATED."""
import os
import sqlite3
import threading
import time

from protocol import reading_dict  # contract/protocol.py

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY, ts REAL, session INTEGER, source TEXT, ms INTEGER, door INTEGER, level_mm INTEGER,
  level_rate INTEGER, gas_raw INTEGER, gas_pct INTEGER, hum INTEGER, temp INTEGER, fan INTEGER, state TEXT,
  uses INTEGER, flags INTEGER);
CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts REAL, session INTEGER, source TEXT, ms INTEGER, seq INTEGER, code TEXT,
  a INTEGER, b INTEGER, UNIQUE(session, seq, code, ms));
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS closed(key TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def hhmmss(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


class Store:
    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            row = self.db.execute("SELECT value FROM meta WHERE key='session'").fetchone()
            self.session = int(row["value"]) if row else 0
        self._last_saved = 0.0
        self.offset = None               # wall clock minus board clock, learned from each reading
        self.latest = None               # the newest reading, kept in memory for the live screen
        with self.lock:
            row = self.db.execute("SELECT ms FROM readings WHERE session = ? ORDER BY id DESC LIMIT 1",
                                  (self.session,)).fetchone()
        self._last_ms = row["ms"] if row else None

    def _new_session(self):
        """The board restarted: its clock and its event numbers start again."""
        self.session += 1
        self._last_ms = None
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('session', ?)", (str(self.session),))

    # ---- writing ----
    def add_reading(self, r, ts, source):
        """Keeps every reading in memory as 'latest'; stores about one a second."""
        d = reading_dict(r)
        d.update(ts=ts, time=hhmmss(ts), source=source)
        self.latest = d
        self.offset = ts - r.ms / 1000.0
        with self.lock:
            if self._last_ms is not None and r.ms < self._last_ms - 2000:
                self._new_session()      # the board's clock went backwards: it restarted
            self._last_ms = r.ms
            if ts - self._last_saved < 0.9:
                return d
            self._last_saved = ts
            self.db.execute(
                "INSERT INTO readings(ts, session, source, ms, door, level_mm, level_rate, gas_raw, gas_pct, hum,"
                " temp, fan, state, uses, flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, self.session, source, r.ms, r.door, r.level_mm, r.level_rate, r.gas_raw, r.gas_pct, r.hum,
                 r.temp, r.fan, r.state, r.uses, r.flags))
            self.db.commit()
        return d

    def add_event(self, e, now, source):
        """Returns the stored event as a dict, or None if this exact event was already stored.
        The time comes from the board's own clock, so events re-sent after a reconnect keep their real time."""
        ts = now
        if self.offset is not None:
            ts = min(now, self.offset + e.ms / 1000.0)
        with self.lock:
            if e.code == "BOOT":
                seen = self.db.execute("SELECT 1 FROM events WHERE session = ? AND code = 'BOOT' AND seq = ? AND ms = ?",
                                       (self.session, e.seq, e.ms)).fetchone()
                if seen:
                    return None
                self._new_session()
            cur = self.db.execute(
                "INSERT OR IGNORE INTO events(ts, session, source, ms, seq, code, a, b) VALUES(?,?,?,?,?,?,?,?)",
                (ts, self.session, source, e.ms, e.seq, e.code, e.a, e.b))
            self.db.commit()
            if cur.rowcount == 0:
                return None
            return {"id": cur.lastrowid, "ts": ts, "time": hhmmss(ts), "session": self.session, "source": source,
                    "code": e.code, "a": e.a, "b": e.b, "seq": e.seq, "ms": e.ms}

    def close_key(self, key):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO closed(key, ts) VALUES(?, ?)", (key, time.time()))
            self.db.commit()

    def closed_keys(self):
        with self.lock:
            return {r["key"] for r in self.db.execute("SELECT key FROM closed")}

    # ---- reading ----
    def events(self, since=0.0, until=None, limit=2000):
        until = until if until is not None else time.time() + 1
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM (SELECT * FROM events WHERE ts >= ? AND ts <= ? ORDER BY ts DESC, id DESC LIMIT ?)"
                " ORDER BY ts, session, seq", (since, until, limit)).fetchall()
        return [dict(r, time=hhmmss(r["ts"])) for r in rows]

    def session_events(self, limit=3000):
        """Events since the board last started. Jobs and the decision strip are built from these."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM (SELECT * FROM events WHERE session = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (self.session, limit)).fetchall()
        return [dict(r, time=hhmmss(r["ts"])) for r in rows]

    def readings(self, since=0.0, until=None, limit=8000):
        until = until if until is not None else time.time() + 1
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM (SELECT * FROM readings WHERE ts >= ? AND ts <= ? ORDER BY id DESC LIMIT ?)"
                " ORDER BY id", (since, until, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["time"] = hhmmss(d["ts"])
            d["hum_pct"] = None if d["hum"] is None or d["hum"] < 0 else d["hum"] / 10
            d["temp_c"] = None if d["temp"] is None or d["temp"] < 0 else d["temp"] / 10
            out.append(d)
        return out
