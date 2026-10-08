# The laptop program's addresses

Base address: `http://localhost:8000`. JSON in, JSON out. The code is `backend/app/main.py`; its tests are
`backend/tests/test_backend.py`. Change an address only together with this page and a test.

Every reading and event carries `source`: `BOARD` or `SIMULATED`. The screen must always show it.
Simulated data never goes into results or slides.

## Live data

### `GET /api/state`
```json
{
  "link": {"connected": true, "port": "COM5", "source": "BOARD", "hello": {"protocol": 1, "firmware": "0.2", "board": "ROOM"},
           "connection": 1, "silent_for_s": 0.4, "error": ""},
  "stale": false,
  "reading": {"state": "NEEDS_CLEANING", "door": 0, "level_mm": 212, "level_rate": 0, "gas_pct": 131, "hum_pct": 62.0,
              "temp_c": 28.5, "fan": 1, "uses": 5, "steam_gate": false, "baseline_ok": true, "link_ok": true,
              "fan_manual": false, "tap_suspected": false, "air_bad": true, "time": "12:43:10", "ts": 1791400000.1,
              "source": "BOARD", "ms": 71500, "gas_raw": 1180, "hum": 620, "temp": 285, "flags": 38},
  "state_word": "Needs cleaning",
  "headline_reason": "The air is 31% above normal after 5 uses since the last clean.",
  "jobs_open": 1,
  "last_cleaned": {"ts": 1791395000.0, "time": "11:31:02"},
  "last_use_ended": {"ts": 1791399900.0, "time": "12:41:40"},
  "model": {"model": "qwen2.5:3b", "ready": true, "detail": "Model ready"},
  "rules_count": 2, "now": 1791400000.5
}
```
- `reading` is `null` when not connected. `link.error` then says why in plain words.
- `gas_pct` is percent of this room's normal air: 100 is normal, so "31% above normal" is `gas_pct - 100`.
  It is `0` while `baseline_ok` is false: the board is still learning normal air (its first quiet minute).
  Show "Learning this room's normal air" then, not a number.
- `level_mm` is `-1` and `hum_pct` is `null` when that sensor gave no valid reading.
- `state_word`: Free, In use, Clearing the air, Needs cleaning, No water, Fault.

### `WS /ws`
First message `{"type":"hello","state":{...}}`, then as things happen:
`{"type":"reading","reading":{...}}` about twice a second, `{"type":"event","event":{...}}`,
`{"type":"link","link":{...}}`, `{"type":"rules"}`, `{"type":"jobs"}`, `{"type":"synced"}`.
On `event`, `rules`, `jobs` or `synced`, fetch `/api/jobs`, `/api/decision` and `/api/notices` again.

### `GET /api/readings?minutes=10&max_points=600`
Stored readings, oldest first, about one a second, thinned to `max_points`.

### `GET /api/events?minutes=120&limit=300`
```json
[{"id": 41, "ts": 1791399990.0, "time": "12:43:01", "code": "AIR_BAD", "a": 131, "b": 5, "seq": 17, "session": 3,
  "source": "BOARD", "title": "Air changed"}]
```
`title` is the plain line for the event strip. Codes and their `a`/`b` fields are in `docs/PROTOCOL.md`.

### `POST /api/command`
`{"cmd":"CLEANED"}` or `{"cmd":"FAN","value":"AUTO"}` (`AUTO`, `ON`, `OFF`). Anything else is refused with 400.
503 with a plain reason when the board is not connected or does not answer.

## Jobs, decisions, notices

### `GET /api/jobs`
Open jobs, most urgent first (priority 1 is most urgent).
```json
[{"key": "clean", "title": "Clean the washroom", "priority": 3,
  "reason": "The air is 31% above normal after 5 uses since the last clean.",
  "since": 1791399990.0, "since_time": "12:43:01", "event_ids": [42], "closes_with": "Mark as cleaned",
  "can_mark_done": false, "code": "CLEAN_DUE"}]
```
Keys: `fan`, `sensor1`..`sensor4`, `link`, `tap`, `water`, `drain`, `clean`, `rule<slot>`.

### `POST /api/jobs/{key}/done`
- Jobs that close with "Mark as cleaned" (`clean`, `drain`): sends `CLEANED` to the board.
- Rule jobs: marked done on the laptop.
- All others answer 409: they close by themselves when the board reports the problem gone.

### `GET /api/decision`
The newest thing the board decided by itself. `null` until something has happened. This feeds the strip
"The board decided this by itself".
```json
{"event_id": 43, "time": "12:43", "code": "FAN_ON", "decided_by": "board", "status": "checking", "seconds_left": 22,
 "event_ids": [43, 41, 42],
 "steps": [
  {"key": "saw", "label": "Saw", "head": "Air 31% above normal", "sub": "Humidity steady at 62%, so it is not steam"},
  {"key": "decided", "label": "Decided", "head": "The air is bad", "sub": "5 uses since the last clean, so cleaning is due"},
  {"key": "did", "label": "Did", "head": "Switched the fan on", "sub": "Raised a cleaning job"},
  {"key": "checking", "label": "Checking", "head": "Did the fan work?", "sub": "The air must improve by 5 points within 60 s"}]}
```
`status`: `checking`, `passed`, `failed`, `done` or `open`. The last step's `key` is `checked` once the check has
an outcome. `seconds_left` is only set while a fan check is running.

### `GET /api/why?event_id=43`
`{"chain": {...as above...}, "answer": "At 12:43 the board saw this: ...", "by": "template"}`. For "Why?" links.

### `GET /api/notices` and `POST /api/notices/{id}/dismiss`
Patterns found by counting, never by the model.
```json
[{"id": "clean-earlier-4",
  "text": "The air changed right after use 5, 2 times in the last 24 hours. Ask for cleaning after 4 uses instead of 5?",
  "sentence": "Ask for cleaning after 4 uses", "rule": {...a rule...}, "event_ids": [12, 41]}]
```
"Draft that rule" posts `sentence` to `/api/rules/draft`. `rule` is `null` for notices that only inform.

## Rules

### `POST /api/rules/draft`  body `{"sentence": "...", "minutes": 120}`
```json
{"sentence": "Run the fan for 30 seconds after every use",
 "rule": {"name": "Fan after use", "trigger": {"type": "on_event", "event": "USE_END"}, "when": [], "match": "all",
          "hold_seconds": 0, "action": {"type": "fan", "set": "on"}, "for_seconds": 30, "priority": 4},
 "by": "pattern", "problems": [], "notes": [],
 "parts": {"when": "a use ends", "do": "fan on", "for": "30 s", "hold": null, "kind": "fan",
           "sentence": "When a use ends, turn the fan on for 30 s."},
 "slot": 3, "line": "RULE,3,4,ALL,0,FAN_ON,30,ON:USE_END,0,Fan after use",
 "replay": {"count": 6, "fan_seconds": 180, "fired": [1791393000.0], "fired_times": ["10:52:11"],
            "from": 1791392800.0, "to": 1791400000.0, "points": 7100, "sources": ["BOARD"], "minutes_asked": 120},
 "ms": 2}
```
- `by`: `pattern` (fixed shapes, no model), `model` (Qwen), or `none` (nothing usable). Show which one wrote it.
- `problems` not empty: show them, and do not offer Approve. `rule` can still be present (for example a value
  out of range) or `null` (the model said the system cannot do it; `problems[0]` is the reason).
- `notes`: gentle warnings, for example a number in the rule that was not in the sentence.
- `replay`: what the board would have done over stored history. `fired` gives the bar positions between
  `from` and `to`. If `sources` contains `SIMULATED`, say so next to it.

### `POST /api/rules/check` and `POST /api/rules/replay`  body `{"rule": {...}, "slot": 3, "minutes": 120}`
For "Change it": check an edited rule and replay it again.

### `POST /api/rules/upload`  body `{"rule": {...}, "slot": 3}`
Call this only when a person presses Approve. The steps map onto the four dots on the badge.
```json
{"ok": true, "slot": 3, "steps": {"drafted": true, "approved": true, "sent": true, "board_ok": true},
 "line": "RULE,3,...", "board_holds": {"when": "a use ends", "do": "fan on", "for": "30 s", "sentence": "..."},
 "detail": "The board saved the rule in slot 3."}
```
On failure `ok` is false and `detail` says why (not connected, the board was silent, or the checker's problems).

### `GET /api/rules?refresh=true` and `DELETE /api/rules/{slot}`
What the board holds now (the board is the truth, not the laptop): `{"rules": [{"slot", "rule", "parts", "line",
"fired_count", "last_fired"}], "max": 8, "connected": true}`.

## The agent

### `POST /api/ask`  body `{"text": "..."}`
One box for everything. Code decides which job the line is for and the answer says so in `kind`:

| `kind` | When | The rest of the answer |
| --- | --- | --- |
| `why` | starts with why / what happened / when did, or ends with "?" | `answer`, `by` (`model` or `template`), `chain`, `event_ids` |
| `report` | mentions report, summary, shift, handover | `text`, `by`, `facts` |
| `status` | "what needs me", "what should I do" | `text`, `jobs` |
| `rule` | anything else | exactly the `/api/rules/draft` answer |

### `GET /api/report?hours=8`
`{"text": "From 05:00 to 13:00 the washroom was used 14 times. ...", "by": "template", "facts": {...}}`

### `GET /api/agent/status`
`{"model": "qwen2.5:3b", "ready": false, "detail": "Model not running. Start Ollama to use it."}`

## What the model may and may not do

- It never sends a command. Only `/api/rules/upload`, `/api/command` and `/api/jobs/{key}/done` reach the board,
  and each needs a person's click.
- It never invents a number. A rule must pass the checker; a reworded answer is thrown away (and the plain
  template shown) if it contains any number that is not in the facts.
- With Ollama stopped everything still works, marked `pattern` or `template`.
