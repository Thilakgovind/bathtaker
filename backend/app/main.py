"""The web side of the laptop program. REST for questions and actions, one WebSocket for live data.

Start it with:  python -m backend --port COM5          (real board)
                python -m backend --port socket://localhost:5555   (pretend board)
docs/API.md lists every address with an example.
"""
import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ROOT
from .insights import notices, shift_facts
from .jobs import build_jobs
from .link import BoardLink
from .replay import replay
from .store import Store, hhmmss

import agent
from agent.chain import build_chain
from agent.words import event_title, rule_parts
from rules import MAX_RULES, check_rule, decode_rule, encode_rule  # contract/rules.py
from room_logic import DEFAULTS  # contract/room_logic.py

STATE_WORDS = {"FREE": "Free", "IN_USE": "In use", "VENTILATING": "Clearing the air",
               "NEEDS_CLEANING": "Needs cleaning", "NO_WATER": "No water", "FAULT": "Fault"}


class Hub:
    """Everything the endpoints share."""

    def __init__(self, port, db_path):
        self.store = Store(db_path)
        self.rules = {}                  # slot -> rule, as the board last reported them
        self.rules_at = 0.0
        self.cfg = dict(DEFAULTS)        # thresholds; replaced by the board's own values when it answers CFG?
        self.clients = set()
        self.loop = None
        self.link = BoardLink(port, self.on_message)
        self._synced_for = None

    # ---- lines from the board ----
    def on_message(self, kind, payload, ts):
        if kind == "D":
            d = self.store.add_reading(payload, ts, self.link.source)
            self.push({"type": "reading", "reading": d})
        elif kind == "E":
            ev = self.store.add_event(payload, ts, self.link.source)
            if ev:
                ev["title"] = event_title(ev["code"], ev["a"], ev["b"], self.rules)
                self.push({"type": "event", "event": ev})
                if ev["code"] in ("RULE_ADDED", "RULE_DELETED", "BOOT"):
                    threading.Thread(target=self.refresh_rules, daemon=True).start()
        elif kind == "LINK":
            self.push({"type": "link", "link": payload})
            if payload["connected"] and payload["hello"] and self._synced_for != payload["connection"]:
                self._synced_for = payload["connection"]
                threading.Thread(target=self.sync, daemon=True).start()

    def sync(self):
        """After every (re)connection: fetch the board's recent events, its rules and its thresholds."""
        time.sleep(1.2)                  # let one reading arrive, so event times can be worked out
        self.link.send("LOG?", wait=4)
        self.refresh_rules()
        ans = self.link.send("CFG?")
        if ans["ok"]:
            for pair in ans["detail"].replace(",", ";").split(";"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    try:
                        self.cfg[k.strip()] = int(v)
                    except ValueError:
                        pass
        self.push({"type": "synced"})

    def refresh_rules(self):
        ans = self.link.send("RULES?")
        if not ans["ok"]:
            return False
        found = {}
        for line in ans["rules"]:
            try:
                slot, rule = decode_rule(line)
                found[slot] = rule
            except (ValueError, IndexError, KeyError):
                continue
        self.rules, self.rules_at = found, time.time()
        self.push({"type": "rules"})
        return True

    # ---- live push ----
    def push(self, message):
        if self.loop is None or not self.clients:
            return
        asyncio.run_coroutine_threadsafe(self._send_all(message), self.loop)

    async def _send_all(self, message):
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)

    # ---- views built from stored history ----
    def session_events(self):
        evs = self.store.session_events()
        for e in evs:
            e["title"] = event_title(e["code"], e["a"], e["b"], self.rules)
        return evs

    def jobs(self):
        return build_jobs(self.store.session_events(), self.rules, self.store.closed_keys())

    def state(self):
        link = self.link.info()
        r = self.store.latest if link["connected"] else None
        stale = bool(link["connected"] and link["silent_for_s"] is not None and link["silent_for_s"] > 3)
        jobs = self.jobs()
        evs = self.store.session_events()
        last_clean = next((e for e in reversed(evs) if e["code"] == "CLEANED"), None)
        last_use = next((e for e in reversed(evs) if e["code"] == "USE_END"), None)
        return {
            "link": link, "stale": stale, "reading": r,
            "state_word": STATE_WORDS.get(r["state"]) if r else None,
            "headline_reason": jobs[0]["reason"] if jobs else None,
            "jobs_open": len(jobs),
            "last_cleaned": {"ts": last_clean["ts"], "time": last_clean["time"]} if last_clean else None,
            "last_use_ended": {"ts": last_use["ts"], "time": last_use["time"]} if last_use else None,
            "model": agent.status(), "now": time.time(), "rules_count": len(self.rules),
        }

    def chain(self, event_id=None, question=None):
        evs = self.store.session_events()
        now = time.time()
        readings = self.store.readings(since=now - 3600)
        target = None
        if event_id is not None:
            target = next((e for e in evs if e["id"] == event_id), None)
            if target is None:
                return None
        return build_chain(evs, readings, target, now, self.rules, self.cfg)

    def free_slot(self):
        return next((s for s in range(1, MAX_RULES + 1) if s not in self.rules), None)

    def replay(self, rule, minutes):
        now = time.time()
        since = now - minutes * 60
        res = replay(rule, self.store.readings(since=since), self.store.events(since=since))
        res["minutes_asked"] = minutes
        res["fired_times"] = [hhmmss(t) for t in res["fired"]]
        return res

    def draft(self, sentence, minutes=120):
        res = agent.draft_rule(sentence, list(self.rules.values()))
        if res["rule"] and not res["problems"]:
            slot = self.free_slot()
            res["slot"] = slot
            res["line"] = encode_rule(slot or 0, res["rule"])
            res["replay"] = self.replay(res["rule"], minutes)
            if slot is None:
                res["problems"] = ["The board holds at most %d rules. Delete one first." % MAX_RULES]
        res["sentence"] = sentence
        return res


class Command(BaseModel):
    cmd: str
    value: str | None = None


class Sentence(BaseModel):
    sentence: str
    minutes: int = 120


class RuleBody(BaseModel):
    rule: dict
    slot: int | None = None
    minutes: int = 120


class Ask(BaseModel):
    text: str


def create_app(port=None, db_path=None):
    hub = Hub(port, db_path or os.path.join(ROOT, "data", "caretaker.db"))

    @asynccontextmanager
    async def lifespan(_app):
        hub.loop = asyncio.get_running_loop()
        hub.link.start()
        threading.Thread(target=agent.warm_up, daemon=True).start()
        yield
        hub.link.stop()

    app = FastAPI(title="Washroom caretaker", version="0.1", lifespan=lifespan)
    app.state.hub = hub

    # ---- live state ----
    @app.get("/api/state")
    def get_state():
        return hub.state()

    @app.get("/api/readings")
    def get_readings(minutes: float = 10, max_points: int = 600):
        rows = hub.store.readings(since=time.time() - minutes * 60)
        step = max(1, len(rows) // max(1, max_points))
        return rows[::step]

    @app.get("/api/events")
    def get_events(minutes: float = 120, limit: int = 300):
        evs = hub.store.events(since=time.time() - minutes * 60, limit=limit)
        for e in evs:
            e["title"] = event_title(e["code"], e["a"], e["b"], hub.rules)
        return evs

    @app.post("/api/command")
    def post_command(c: Command):
        cmd = c.cmd.strip().upper()
        if cmd == "CLEANED":
            line = "CLEANED"
        elif cmd == "FAN" and (c.value or "").upper() in ("AUTO", "ON", "OFF"):
            line = "FAN," + c.value.upper()
        else:
            raise HTTPException(400, "Allowed commands: CLEANED, or FAN with value AUTO, ON or OFF.")
        ans = hub.link.send(line)
        if not ans["ok"]:
            raise HTTPException(503, ans["detail"])
        return {"ok": True, "sent": line, "detail": ans["detail"]}

    # ---- jobs, decisions, notices ----
    @app.get("/api/jobs")
    def get_jobs():
        return hub.jobs()

    @app.post("/api/jobs/{key}/done")
    def job_done(key: str):
        job = next((j for j in hub.jobs() if j["key"] == key), None)
        if job is None:
            raise HTTPException(404, "That job is not open.")
        if job["closes_with"] == "Mark as cleaned":
            ans = hub.link.send("CLEANED")
            if not ans["ok"]:
                raise HTTPException(503, ans["detail"])
            return {"ok": True, "how": "Sent CLEANED to the board."}
        if job.get("can_mark_done"):
            hub.store.close_key(job["mark_key"])
            hub.push({"type": "jobs"})
            return {"ok": True, "how": "Marked done."}
        raise HTTPException(409, "This job closes by itself: it needs %s." % job["closes_with"])

    @app.get("/api/decision")
    def get_decision():
        """The newest thing the board decided by itself, as saw -> decided -> did -> checked."""
        return hub.chain()

    @app.get("/api/why")
    def get_why(event_id: int):
        chain = hub.chain(event_id=event_id)
        if chain is None:
            raise HTTPException(404, "There is no explanation for that event.")
        return {"chain": chain, "answer": agent.chain_text(chain), "by": "template"}

    @app.get("/api/notices")
    def get_notices():
        evs = hub.store.events(since=time.time() - 86400)
        return notices(evs, hub.cfg.get("CLEAN_USES", 5), hub.store.closed_keys())

    @app.post("/api/notices/{notice_id}/dismiss")
    def dismiss_notice(notice_id: str):
        hub.store.close_key(notice_id)
        return {"ok": True}

    # ---- rules ----
    @app.get("/api/rules")
    def get_rules(refresh: bool = False):
        if refresh or time.time() - hub.rules_at > 10:
            hub.refresh_rules()
        fired = [e for e in hub.store.session_events() if e["code"] == "RULE_FIRED"]
        out = []
        for slot, rule in sorted(hub.rules.items()):
            mine = [e for e in fired if e["a"] == slot]
            out.append({"slot": slot, "rule": rule, "parts": rule_parts(rule), "line": encode_rule(slot, rule),
                        "fired_count": len(mine), "last_fired": mine[-1]["time"] if mine else None})
        return {"rules": out, "max": MAX_RULES, "from_board_at": hub.rules_at or None,
                "connected": hub.link.connected}

    @app.post("/api/rules/draft")
    def draft_rule(s: Sentence):
        return hub.draft(s.sentence, s.minutes)

    @app.post("/api/rules/check")
    def check(body: RuleBody):
        others = [r for slot, r in hub.rules.items() if slot != body.slot]
        problems = check_rule(body.rule, others)
        return {"problems": problems, "parts": None if problems else rule_parts(body.rule)}

    @app.post("/api/rules/replay")
    def post_replay(body: RuleBody):
        problems = check_rule(body.rule, [])
        if problems:
            raise HTTPException(400, " ".join(problems))
        return hub.replay(body.rule, body.minutes)

    @app.post("/api/rules/upload")
    def upload(body: RuleBody):
        """Called only when a person presses Approve. Nothing else in this program sends a rule."""
        steps = {"drafted": True, "approved": True, "sent": False, "board_ok": False}
        slot = body.slot or hub.free_slot()
        if slot is None or not (1 <= slot <= MAX_RULES):
            return {"ok": False, "steps": steps, "detail": "No free slot. Delete a rule first."}
        others = [r for s, r in hub.rules.items() if s != slot]
        problems = check_rule(body.rule, others)
        if problems:
            return {"ok": False, "steps": steps, "detail": " ".join(problems), "problems": problems}
        line = encode_rule(slot, body.rule)
        ans = hub.link.send(line)
        steps["sent"] = ans["detail"] != "The board is not connected."
        if not ans["ok"]:
            return {"ok": False, "steps": steps, "detail": ans["detail"], "line": line}
        hub.refresh_rules()
        held = hub.rules.get(slot)
        steps["board_ok"] = held is not None
        return {"ok": steps["board_ok"], "steps": steps, "slot": slot, "line": line,
                "board_holds": rule_parts(held) if held else None,
                "detail": "The board saved the rule in slot %d." % slot if held else
                          "The board answered OK but does not list the rule."}

    @app.delete("/api/rules/{slot}")
    def delete_rule(slot: int):
        ans = hub.link.send("DEL,%d" % slot)
        if not ans["ok"]:
            raise HTTPException(503, ans["detail"])
        hub.refresh_rules()
        return {"ok": True}

    # ---- the agent ----
    @app.get("/api/agent/status")
    def agent_status():
        return agent.status()

    @app.get("/api/report")
    def get_report(hours: float = 8):
        now = time.time()
        since = now - hours * 3600
        facts = shift_facts(hub.store.events(since=since), since, now, hub.jobs())
        res = agent.shift_report(facts)
        res["facts"] = facts
        return res

    @app.post("/api/ask")
    def ask(a: Ask):
        """One box for everything. Code decides which job the line is for."""
        kind = agent.route(a.text)
        if kind == "why":
            evs = hub.store.session_events()
            now = time.time()
            res = agent.explain(a.text, evs, hub.store.readings(since=now - 3600), hub.rules, now, hub.cfg)
            res["kind"] = "why"
            return res
        if kind == "report":
            res = get_report()
            res["kind"] = "report"
            return res
        if kind == "status":
            jobs = hub.jobs()
            st = hub.state()
            if not st["link"]["connected"]:
                text = "The board is not connected, so I cannot see the room."
            elif jobs:
                text = "%d %s you now. " % (len(jobs), "thing needs" if len(jobs) == 1 else "things need")
                text += " ".join("%d. %s: %s" % (i + 1, j["title"], j["reason"]) for i, j in enumerate(jobs))
            else:
                text = "Nothing needs you right now. The washroom is: %s." % (st["state_word"] or "unknown").lower()
            return {"kind": "status", "text": text, "jobs": jobs, "by": "template"}
        res = hub.draft(a.text)
        res["kind"] = "rule"
        return res

    # ---- live socket ----
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        hub.clients.add(sock)
        try:
            await sock.send_json({"type": "hello", "state": hub.state()})
            while True:
                await sock.receive_text()        # the page sends nothing we need; this notices a closed tab
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(sock)

    # ---- the screen ----
    dist = os.path.join(ROOT, "frontend", "dist")
    design = os.path.join(ROOT, "design")
    if os.path.isdir(design):
        app.mount("/design", StaticFiles(directory=design), name="design")
    if os.path.isfile(os.path.join(dist, "index.html")):
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        def plumbing_page():
            return PLUMBING_PAGE

    return app


PLUMBING_PAGE = """<!doctype html><meta charset="utf-8"><title>Washroom caretaker: plumbing check</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}
pre{background:#f3f3f3;padding:1rem;overflow:auto;border-radius:8px}h1{font-size:1.4rem}</style>
<h1>Plumbing check, not the real screen</h1>
<p>The real screen is not built yet (no <code>frontend/dist</code>). This page only proves the laptop program
is running and hearing the board. Data marked SIMULATED is made up.</p>
<h2>State</h2><pre id="s">waiting</pre><h2>Jobs</h2><pre id="j"></pre>
<h2>Latest decision</h2><pre id="d"></pre><h2>Last events</h2><pre id="e"></pre>
<script>
async function tick(){
  const j=u=>fetch(u).then(r=>r.json());
  const s=await j('/api/state');const r=s.reading;
  document.getElementById('s').textContent=(s.link.connected?'Connected to '+s.link.port+' | source '+s.link.source:
    'NOT CONNECTED. '+s.link.error)+'\\n'+(r?['state '+r.state,'door '+(r.door?'closed':'open'),'water '+r.level_mm+' mm',
    'air '+r.gas_pct+'%','humidity '+r.hum_pct+'%','fan '+(r.fan?'on':'off'),'uses '+r.uses].join(' | '):'no reading yet')+
    '\\nmodel: '+s.model.detail;
  document.getElementById('j').textContent=(await j('/api/jobs')).map(x=>x.priority+'  '+x.title+': '+x.reason).join('\\n')||'none';
  const d=await j('/api/decision');
  document.getElementById('d').textContent=d?d.steps.map(x=>x.label+': '+x.head+(x.sub?' ('+x.sub+')':'')).join('\\n'):'none yet';
  document.getElementById('e').textContent=(await j('/api/events?minutes=30&limit=15')).reverse().map(x=>x.time+'  '+x.title).join('\\n');
}
tick();setInterval(tick,1500);
</script>"""
