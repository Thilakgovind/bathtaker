# Architecture

## The idea in one line
The room board senses and decides. The service board acts. The laptop explains, keeps history and
lets the caretaker write rules. The system keeps working with the laptop unplugged.

## Pieces

| Piece | Runs on | Stack | Job |
| --- | --- | --- | --- |
| Room firmware | ESP32 A | Arduino framework, C++ | Read 4 sensors, run the room logic and the caretaker rules, drive the door sign, keep an event log, talk to the laptop over USB and to the service board over ESP-NOW |
| Service firmware | ESP32 B | Arduino framework, C++ | Switch the fan relay, acknowledge, go to the resting state if the link is silent for 3 s |
| Backend | Laptop | Python 3.10+, FastAPI, uvicorn, pyserial, sqlite3 (standard library) | Read the board, store readings and events, build the job list, check and upload rules, host the agent, serve the web app |
| Frontend | Browser | React 18, Vite, TypeScript, Tailwind v4, uPlot for live charts | Room view, jobs, timeline, rules, ask, bench |
| Agent | Inside the backend | Ollama (`qwen2.5:3b` by default) behind a small provider interface | Fill the rule shape from a sentence, explain events, write a shift report |
| Contract | `contract/` | Plain Python, no packages | Protocol, rule checker, reference room logic, pretend board, tests |

## Data flow

    sensors -> room board -> (decides) -> ESP-NOW -> service board -> relay -> fan
                   |  USB serial, one text line per message (docs/PROTOCOL.md)
                   v
               backend -> SQLite (readings, events, jobs, rules, chats)
                   |  REST + one WebSocket
                   v
               frontend
                   ^
               agent (only the backend calls it; it never reaches a board)

## Decisions already made (do not reopen without a reason)

- **Logic lives on the room board.** The laptop is optional at run time.
- **Text line protocol, integers only.** Easy to print from firmware, easy to read in a serial monitor.
- **The backend imports `contract/`** for parsing, rule checking and rule encoding. One source of truth.
- **The pretend board is reached through the same serial code path**: `serial.serial_for_url("socket://localhost:5555")`
  for the simulator, `COM5` (or similar) for the real board. No separate "sim mode" inside the backend.
- **SQLite, one file**, `data/caretaker.db`. Every row carries `source` = `BOARD` or `SIMULATED`.
- **WebSocket for live data**, REST for everything else.
- **One built frontend served by FastAPI.** One program to start, one address to open.
- **Model is replaceable and optional.** A pattern parser covers rule writing when no model is available.
  A cloud provider can be added behind the same interface with the key in an environment variable.
- **Arduino core version matters for ESP-NOW.** The receive-callback signature changed between
  Arduino-ESP32 core 2.x and 3.x. Check the installed core before writing the link code.

## Folder layout

    contract/            protocol, rules, room logic, pretend board, tests          (done)
    firmware/room/       room.ino + room_logic.h                                    (done, not confirmed on the rig)
    firmware/service/    service.ino                                                (done, not confirmed on the rig)
    backend/app/         link (cable), store (history), jobs, replay, insights, main (addresses)   (done)
    backend/tests/       checks against the pretend board                           (done)
    agent/               patterns, chain (saw/decided/did/checked), words, ollama   (done; Qwen path never run)
    design/              the locked screen: picture, exported layout, three images
    frontend/            Vite project; `npm run build` writes frontend/dist, which the backend serves   (to build)
    docs/                these documents; docs/reports/ for what each task ran and could not test
    eval/                test sentences for the rule writer, expected outcomes
    data/                database (created on first run, git-ignored)
    run_pretend.bat      pretend board + laptop program + browser
    run_board.bat COM5   laptop program on the real board + browser

## Three tiers: build them in this order

| Tier | Contains | If time runs out |
| --- | --- | --- |
| Core | Sensors printing, room logic on the board, relay and fan, backend link and store, Room and Jobs screens | This alone is a complete demo |
| Plus | Service board over ESP-NOW, timeline with event chains, rules with checker, replay and upload, pattern parser | Drop ESP-NOW first (put the relay on the room board) |
| Showcase | Model-written rules, "why" answers, shift report, bench screen that runs the measurements, night theme | Drop any of these without breaking the rest |

Code freeze two hours before the demo. Record a video of the working system at the freeze.

## What we can and cannot claim

- Say: "Existing smart-washroom systems sense and alert, and building automation verifies its own actions,
  but no low-cost washroom node we could find explains why it acted, checks that its action worked, and lets
  the caretaker rewrite its rules in plain language without internet."
- Never say "first", "novel" or "nobody has done this".
- Verify-after-act is standard in building automation (fault detection and diagnostics). Humidity correction
  of gas sensors is an established method. We apply both in a setting where prototypes skip them.
- The gas sensor shows that the air changed, not which gas. The demo is a model room and a bucket.
- No percentage, saving or accuracy figure that was not measured on the real rig.
