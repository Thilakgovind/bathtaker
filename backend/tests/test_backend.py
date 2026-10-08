"""Checks for the laptop program and the agent. Run from the project folder:  python -m pytest -q

Everything here runs against the pretend board, so all data in these tests is made up.
No test needs Ollama: the agent's model path is exercised only when Ollama is running.
"""
import os
import socket
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "contract")):
    if p not in sys.path:
        sys.path.insert(0, p)

import agent  # noqa: E402
from agent.chain import build_chain, chain_text  # noqa: E402
from backend.app.insights import notices, shift_facts  # noqa: E402
from backend.app.jobs import build_jobs  # noqa: E402
from backend.app.replay import replay  # noqa: E402
from board_sim import BoardSim  # noqa: E402
from protocol import PROTOCOL_VERSION, parse_line, reading_dict  # noqa: E402
from rules import check_rule  # noqa: E402

FAN_AFTER_USE = {"name": "Fan after use", "trigger": {"type": "on_event", "event": "USE_END"}, "when": [],
                 "match": "all", "hold_seconds": 0, "action": {"type": "fan", "set": "on"}, "for_seconds": 30,
                 "priority": 4}


class Play:
    """Runs the pretend board in memory and keeps its output in the shapes the backend stores."""

    def __init__(self):
        self.sim = BoardSim(BASELINE_STABLE_S=15)
        self.events, self.readings = [], []

    def run(self, seconds, do=None):
        if do:
            assert self.sim.scenario(do).startswith("ok"), do
        for line in self.sim.run(seconds):
            kind, x = parse_line(line)
            ts = x.ms / 1000
            if kind == "E":
                self.events.append({"id": len(self.events) + 1, "ts": ts, "time": time.strftime(
                    "%H:%M:%S", time.gmtime(ts)), "code": x.code, "a": x.a, "b": x.b})
            else:
                d = reading_dict(x)
                d.update(ts=ts, source="SIMULATED", session=1)
                self.readings.append(d)
        return self

    def use(self, n=1):
        for _ in range(n):
            self.run(6, "door close").run(5, "door open")
        return self

    def codes(self):
        return [e["code"] for e in self.events]


def test_bad_air_after_uses_raises_cleaning_and_explains_itself():
    p = Play().run(40).use(2).run(140, "odour 0.7")
    assert {"AIR_BAD", "CLEAN_DUE", "FAN_ON"} <= set(p.codes())
    air = next(e for e in p.events if e["code"] == "AIR_BAD")
    # the job, with its number taken from the event
    upto = [e for e in p.events if e["ts"] <= air["ts"] + 1]
    jobs = build_jobs(upto)
    assert [j["key"] for j in jobs] == ["clean"]
    assert "%d%% above normal after 2 uses" % (air["a"] - 100) in jobs[0]["reason"]
    # the decision strip while the fan check is still running
    chain = build_chain(upto, p.readings, now=air["ts"] + 20)
    assert [s["key"] for s in chain["steps"]] == ["saw", "decided", "did", "checking"]
    assert chain["steps"][0]["head"] == "Air %d%% above normal" % (air["a"] - 100)
    assert "2 uses since the last clean" in chain["steps"][1]["sub"]
    assert chain["status"] == "checking" and 35 <= chain["seconds_left"] <= 41
    # and after the check
    done = build_chain(p.events, p.readings, next(e for e in p.events if e["code"] == "FAN_ON"))
    assert done["status"] == "passed" and done["steps"][3]["head"] == "The fan worked"


def test_steam_is_not_reported_as_bad_air():
    p = Play().run(40).run(35, "steam on").run(150, "steam off")
    assert "STEAM_GATE_ON" in p.codes() and "AIR_BAD" not in p.codes()
    assert build_jobs(p.events) == []
    fan_on = next(e for e in p.events if e["code"] == "FAN_ON")
    chain = build_chain(p.events, p.readings, fan_on)
    assert chain["steps"][1]["head"] == "Steam in the room"
    assert chain["status"] == "passed"


def test_unplugged_fan_raises_a_fault_job():
    p = Play().run(40).run(1, "fan unplug").run(35, "steam on").run(90, "steam off")
    assert "FAN_FAULT" in p.codes()
    jobs = build_jobs(p.events)
    assert jobs[0]["key"] == "fan" and jobs[0]["priority"] == 1 and "humidity fell only" in jobs[0]["reason"]
    chain = build_chain(p.events, p.readings, next(e for e in p.events if e["code"] == "FAN_FAULT"))
    assert chain["status"] == "failed" and chain["steps"][3]["head"] == "The fan did not work"


def test_tap_left_running_opens_then_clears():
    p = Play().run(40).run(70, "tap 20")
    jobs = build_jobs(p.events)
    assert jobs[0]["title"] == "Tap left running or leak" and jobs[0]["priority"] == 1
    chain = build_chain(p.events, p.readings)
    assert "cannot close the tap" in chain["steps"][2]["sub"]      # the board has no valve: say so
    p.run(40, "tap 0")
    assert "TAP_CLEARED" in p.codes() and build_jobs(p.events) == []


def test_low_water_job_and_boot_clears_jobs():
    p = Play().run(20).run(15, "drain 30")
    assert [j["key"] for j in build_jobs(p.events)] == ["water"]
    boot = {"id": 999, "ts": p.events[-1]["ts"] + 5, "time": "00:00:00", "code": "BOOT", "a": 0, "b": 0}
    assert build_jobs(p.events + [boot]) == []


def test_rule_job_can_be_marked_done():
    rule = {"name": "Door closed too long", "action": {"type": "job", "text": "Check the room"}, "priority": 3}
    ev = [{"id": 7, "ts": 10.0, "time": "00:00:10", "code": "RULE_FIRED", "a": 2, "b": 0}]
    jobs = build_jobs(ev, {2: rule})
    assert jobs[0]["title"] == "Check the room" and jobs[0]["can_mark_done"]
    assert build_jobs(ev, {2: rule}, closed={jobs[0]["mark_key"]}) == []


def test_replay_counts_what_the_board_would_have_done():
    p = Play().run(20).use(3).run(40)
    res = replay(FAN_AFTER_USE, p.readings, p.events)
    assert res["count"] == 3 and res["fan_seconds"] == 90 and res["sources"] == ["SIMULATED"]
    humid = {"name": "Fan when humid", "trigger": {"type": "while"},
             "when": [{"sensor": "humidity_pct", "is": "above", "value": 70}], "match": "all", "hold_seconds": 0,
             "action": {"type": "fan", "set": "on"}, "for_seconds": 0, "priority": 4}
    assert replay(humid, p.readings, p.events)["count"] == 0
    q = Play().run(20).run(40, "steam on").run(60, "steam off")
    assert replay(humid, q.readings, q.events)["count"] == 1


def test_notice_offers_a_rule_the_checker_accepts():
    ev = [{"id": i, "ts": float(i), "time": "", "code": "AIR_BAD", "a": 131, "b": 5} for i in (1, 2)]
    ns = notices(ev, clean_uses=5)
    n = next(x for x in ns if x["rule"])
    assert "after 4 uses instead of 5" in n["text"] and check_rule(n["rule"], []) == []
    assert notices(ev, 5, dismissed={n["id"]}) == []
    assert notices(ev[:1], 5) == []


def test_agent_without_a_model_still_answers(monkeypatch):
    monkeypatch.setattr(agent.ollama, "status", lambda max_age=5.0: {"model": "x", "ready": False, "detail": "off"})
    r = agent.draft_rule("Run the fan for 30 seconds after every use", [])
    assert r["by"] == "pattern" and r["problems"] == [] and r["rule"]["for_seconds"] == 30
    assert r["parts"]["when"] == "a use ends" and r["parts"]["for"] == "30 s"
    bad = agent.draft_rule("Turn the fan on when humidity is above 150", [])
    assert bad["rule"] is not None and "between 0 and 100" in bad["problems"][0]
    none = agent.draft_rule("Open the window when it smells", [])
    assert none["rule"] is None and none["by"] == "none"
    again = agent.draft_rule("Run the fan for 30 seconds after every use", [r["rule"]])
    assert any("repeats" in x for x in again["problems"])
    for text, kind in [("Why did the fan run?", "why"), ("Write my shift report", "report"),
                       ("What needs me?", "status"), ("turn the fan on when humidity is above 70", "rule")]:
        assert agent.route(text) == kind


def test_explanation_uses_only_numbers_from_the_events(monkeypatch):
    monkeypatch.setattr(agent.ollama, "status", lambda max_age=5.0: {"model": "x", "ready": False, "detail": "off"})
    p = Play().run(40).use(2).run(140, "odour 0.7")
    res = agent.explain("Why did the fan run?", p.events, p.readings)
    assert res["by"] == "template" and res["event_ids"]
    air = next(e for e in p.events if e["code"] == "AIR_BAD")
    assert "air %d%% above normal" % (air["a"] - 100) in res["answer"]
    assert chain_text(None).startswith("Nothing has happened")
    facts = shift_facts(p.events, 0, p.events[-1]["ts"], build_jobs(p.events))
    assert facts["uses"] == 2 and facts["cleans"] == 0
    assert "used 2 times" in agent.shift_report(facts)["text"]


def test_link_starts_and_stops_cleanly_with_no_board():
    """Guards against clashing with Python's own thread internals, which differ between versions."""
    from backend.app.link import BoardLink
    seen = []
    link = BoardLink("socket://localhost:%d" % free_port(), lambda kind, payload, ts: seen.append(kind))
    link.start()
    wait_for(lambda: link.error, what="the link to report that nothing is listening")
    assert not link.connected and link.send("PING")["ok"] is False
    link.stop()
    assert not link.is_alive()
    idle = BoardLink(None, lambda *a: None)
    assert "No port chosen" in idle.error
    idle.stop()


# ---------------------------------------------------------------- the whole chain, over the cable code path

class FastBoard:
    """The pretend board on a TCP port, running faster than real time so the test is short."""

    def __init__(self, port, speed=40):
        self.port, self.speed = port, speed
        self.sim = BoardSim(BASELINE_STABLE_S=15)
        self.lock = threading.Lock()
        self.alive = True
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(1)
        self.srv.settimeout(0.2)
        self.conn = None
        threading.Thread(target=self._serve, daemon=True).start()

    def do(self, text):
        with self.lock:
            assert self.sim.scenario(text).startswith("ok")

    def _serve(self):
        while self.alive:
            try:
                self.conn, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            self.conn.settimeout(0.005)
            buf = b""
            try:
                self.conn.sendall(("H,%d,sim-0.1,ROOM\n" % PROTOCOL_VERSION).encode())
                while self.alive:
                    with self.lock:
                        lines = self.sim.step()
                        try:
                            buf += self.conn.recv(4096)
                        except socket.timeout:
                            pass
                        while b"\n" in buf:
                            cmd, buf = buf.split(b"\n", 1)
                            lines += self.sim.handle(cmd.decode("ascii", "ignore"))
                    self.conn.sendall(("\n".join(lines) + "\n").encode())
                    time.sleep(self.sim.dt / self.speed)
            except OSError:
                pass
            finally:
                try:
                    self.conn.close()
                except OSError:
                    pass

    def stop(self):
        self.alive = False
        for s in (self.conn, self.srv):
            try:
                s and s.close()
            except OSError:
                pass


def wait_for(check, seconds=8.0, what=""):
    end = time.time() + seconds
    while time.time() < end:
        v = check()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out waiting for " + what)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_cable_to_screen_and_back(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    monkeypatch.setattr(agent.ollama, "status", lambda max_age=5.0: {"model": "x", "ready": False, "detail": "off"})
    monkeypatch.setattr(agent, "warm_up", lambda: None)

    port = free_port()
    board = FastBoard(port)
    app = create_app("socket://localhost:%d" % port, str(tmp_path / "t.db"))
    hub = app.state.hub
    with TestClient(app) as web:
        # the board is heard, and its data is labelled as made up
        st = wait_for(lambda: (lambda s: s if s["reading"] and s["link"]["hello"] else None)(web.get("/api/state").json()),
                      what="a reading")
        assert st["link"]["connected"] and st["link"]["source"] == "SIMULATED" and st["state_word"] == "Free"
        wait_for(lambda: hub.rules_at > 0, what="the first sync with the board")
        # the board must first learn this room's normal air; until then it cannot call the air bad
        wait_for(lambda: web.get("/api/state").json()["reading"]["baseline_ok"], what="normal air to be learned")

        # a live message reaches a screen
        with web.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert wait_for(lambda: ws.receive_json()["type"] == "reading", what="a pushed reading")

        # sentence -> rule -> approve -> board, and the board is asked what it really holds
        draft = web.post("/api/rules/draft", json={"sentence": "Run the fan for 30 seconds after every use"}).json()
        assert draft["by"] == "pattern" and draft["problems"] == [] and draft["slot"] == 1
        assert draft["line"] == "RULE,1,4,ALL,0,FAN_ON,30,ON:USE_END,0,Fan after use"
        up = web.post("/api/rules/upload", json={"rule": draft["rule"]}).json()
        assert up["ok"] and up["steps"] == {"drafted": True, "approved": True, "sent": True, "board_ok": True}
        rules = web.get("/api/rules?refresh=true").json()["rules"]
        assert [r["slot"] for r in rules] == [1] and rules[0]["parts"]["for"] == "30 s"
        again = web.post("/api/rules/upload", json={"rule": draft["rule"]}).json()
        assert not again["ok"] and "repeats" in again["detail"]

        # the board then obeys the rule by itself
        board.do("door close")
        wait_for(lambda: any(e["code"] == "USE_START" for e in web.get("/api/events").json()), what="a use to start")
        board.do("door open")
        wait_for(lambda: any(e["code"] == "RULE_FIRED" for e in web.get("/api/events").json()), what="the rule to fire")
        chain = wait_for(lambda: web.get("/api/decision").json(), what="a decision")
        assert chain["steps"][1]["head"] == "Rule 1 applies" and chain["steps"][0]["head"] == "A use ends"
        why = web.post("/api/ask", json={"text": "Why did the fan run?"}).json()
        assert why["kind"] == "why" and "rule 1 applies" in why["answer"]

        # bad air raises the cleaning job; Mark as cleaned goes to the board and closes it
        time.sleep(1.0)
        board.do("odour 0.8")
        job = wait_for(lambda: next((j for j in web.get("/api/jobs").json() if j["key"] == "clean"), None),
                       seconds=12, what="the cleaning job")
        assert "above normal after 1 use " in job["reason"]
        assert web.post("/api/ask", json={"text": "What needs me?"}).json()["jobs"]
        assert web.post("/api/jobs/clean/done").json()["ok"]
        wait_for(lambda: not any(j["key"] == "clean" for j in web.get("/api/jobs").json()), what="the job to close")
        assert web.post("/api/command", json={"cmd": "RULE,1,1"}).status_code == 400      # only whitelisted commands

        # pull the cable: the screen says so; plug it back: it recovers without a restart
        n_events = len(web.get("/api/events").json())
        board.stop()
        wait_for(lambda: not web.get("/api/state").json()["link"]["connected"], what="the disconnect to be noticed")
        assert web.post("/api/command", json={"cmd": "CLEANED"}).status_code == 503
        board = FastBoard(port)
        wait_for(lambda: web.get("/api/state").json()["link"]["connected"], seconds=10, what="the reconnect")
        wait_for(lambda: web.get("/api/rules?refresh=true").json()["rules"] == [], what="the new board's empty rule list")
        assert web.get("/api/jobs").json() == []                    # a restarted board starts clean
        assert len(web.get("/api/events").json()) >= n_events       # history is kept
        assert web.delete("/api/rules/1").json()["ok"]
        report = web.get("/api/report").json()
        assert report["by"] == "template" and report["facts"]["uses"] == 1
    board.stop()
