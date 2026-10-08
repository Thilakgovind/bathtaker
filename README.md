# Washroom Caretaker (working title)

A small washroom node that senses, decides and acts by itself, checks that its action worked, explains why,
and lets a caretaker change its rules in plain words with no internet.

- **Room board (ESP32):** door, water level, humidity and air sensors. It decides and keeps working with the
  laptop unplugged.
- **Fan board (ESP32):** one relay and a 5 V fan.
- **Laptop program:** reads the board over USB, keeps history, builds the job list, explains decisions, and
  sends a rule to the board only after a person approves it.
- **Agent:** turns a sentence into a rule, answers "why", writes a shift report. Local model through Ollama,
  with a no-model fallback for everything.

## Try it without hardware (made-up data)

Needs Python 3.10 or newer. On Windows double-click `run_pretend.bat`, or by hand:

    python -m pip install -r requirements.txt
    python contract/board_sim.py                              (window 1: the pretend board)
    python -m backend --port socket://localhost:5555          (window 2: the laptop program)

Open http://localhost:8000. In the pretend board's window type `door close`, `door open`, `tap 20`,
`steam on`, `steam off`, `odour 0.8`, `fan unplug`, `drain 30`.

Everything the pretend board produces is made up. The screen says so. Never use it in results or slides.

## Run it on the real board

Upload `firmware/service/service.ino` to the fan board and `firmware/room/room.ino` to the room board.
Close the Arduino Serial Monitor (only one program can hold the port), then:

    run_board.bat COM5          (or: python -m backend --port COM5)

## Check it

    python contract/test_contract.py      the board's behaviour
    python -m pytest -q                   the laptop program and the agent, against the pretend board
    python -m agent eval eval/sentences.txt    what the rule writer makes of 30 test sentences

## Where things are

    contract/     message format, rule checker, reference room logic, pretend board
    firmware/     the two board programs
    backend/      the laptop program (docs/API.md lists its addresses)
    agent/        the agent, usable alone: python -m agent rule "turn the fan on when humidity is above 70"
    design/       the locked screen design: picture, exported layout, images
    frontend/     the screen (not built yet: docs/TASKS.md, tasks F1 to F5)
    docs/         architecture, protocol, board logic, API, screen, tasks, wiring diagrams
    eval/         test sentences for the rule writer
    data/         the history database (created on first run)

## What has and has not been tested

- Tested: the reference logic, the laptop program and the agent's no-model path, all against the pretend board.
- Compiled but not confirmed on hardware: the two board programs. Their thresholds are starting values.
- Never run: the Qwen path of the agent, anything on Windows, anything on the real rig.

## Limits to state honestly

- Hobby sensors, a model room and a bucket. Not a safety device; no health or hygiene claims.
- The air sensor shows that the air changed, not which gas.
- The board learns "normal air" in its first quiet minute. If the air is already bad then, that becomes normal.
- The board cannot stop water: it can only raise a job and sound a buzzer.
- No camera and no microphone in the washroom.
