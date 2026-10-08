# Rules for the coding agent

Read `docs/ARCHITECTURE.md`, `docs/TASKS.md` and the doc for your task before writing code.
The task list says what is already built. Build on it; do not rewrite it.

1. **The contract is fixed.** `contract/protocol.py`, `contract/rules.py` and `contract/room_logic.py`
   define the behaviour of the board. The backend imports them; the firmware is a faithful port.
   If a change is truly needed, change the code, its test and its doc together, and say so.
2. **The laptop program's addresses are fixed** as listed in `docs/API.md`. The screen is built against them.
   To change one: change `backend/app/main.py`, its test and `docs/API.md` in the same step.
3. **The screen design is locked.** `docs/UI.md` and the `design/` folder say how it looks and what each part
   shows. Do not restyle, rename or rearrange it. Every sample value in the design is replaced by live data.
4. **Run the checks.** `python contract/test_contract.py` and `python -m pytest -q` must pass before and after
   your change. Add a test for every new decision the code makes.
5. **One task at a time.** Follow `docs/TASKS.md` in order. Finish a task's pass check before starting the next.
   Do not add features that are not in the task.
6. **The board decides, the laptop explains.** No decision that switches hardware may live only on the laptop.
   The language model never sends a command to a board and never decides a threshold.
7. **Numbers come from code.** Any number shown to a person is computed by code from stored readings or
   events. The model may phrase it, never produce it.
8. **Simulated data is labelled.** Every screen, export and saved file shows whether its data came from
   `BOARD` or `SIMULATED`. Simulated data never goes into results, slides or the README as a result.
9. **Say what was not tested.** End each task by writing `docs/reports/<task>.md` with: what you ran, what
   passed, what you could not test (for example anything needing the real board or a real model).
10. **Secrets.** No API keys in the repository. Read them from environment variables.
11. **Works offline.** No CDN links. Fonts and libraries are installed and bundled.
12. **Plain words in the UI.** No jargon; errors say what happened and what to do.
13. **Honest about the hardware.** One fan relay, four sensors. There is no valve, sprayer, light, camera or
    microphone. The air sensor shows that the air changed, not which gas. Low voltage only: never write code
    or docs that suggest switching mains with this relay.
14. **Do not claim novelty** in any text. See the claims section of `docs/ARCHITECTURE.md`.
