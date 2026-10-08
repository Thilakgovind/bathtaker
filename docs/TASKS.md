# What is done and what is left

One task at a time. Each task has a pass check. Do not start the next task until the check passes.
Give the coding agent one task block at a time, together with `AGENTS.md`.

## Done

| Part | Where | State |
| --- | --- | --- |
| Message format, rule checker, reference room logic, pretend board | `contract/` | 15 checks pass (`python contract/test_contract.py`) |
| Board programs | `firmware/room`, `firmware/service` | Compile for ESP32. Decisions match the reference in a replay check. **Not confirmed on the real rig.** |
| Laptop program: cable, history, jobs, decision chain, rules, notices, report | `backend/` | 12 checks pass against the pretend board (`python -m pytest -q backend`), on Python 3.11, 3.12 and 3.13 on Linux. 11 of them also passed on this Windows laptop; the 12th is new. **Not run on the real board.** |
| Agent: pattern reader, rule writer, explainer, shift report | `agent/` | Works with no model (tested). **The Qwen path has never been run**: no model was available where it was written. |
| Screen design | Paper file, `design/` | Locked. See `docs/UI.md`. |
| The screen (tasks F1 to F4) | `frontend/` | Built and checked in a real browser against the pretend board: live room side, rule badge, approve, why, report, status, notices, missing board, small window. See `docs/reports/F2_F3_F4.md`. **Checked with no model and not on the real board.** |

Do not rewrite the parts above. If one of them is wrong, fix that one place and add a test for it.

## Left to do

Order: L1 (Qwen), then L2 (the real board), then F5 and L3 if time allows.
S0 and F1 to F4 are finished; their reports are in `docs/reports/`.

After any change in `frontend/src`, run `npm run build` in `frontend/` so the backend serves the new screen.

### L1. Qwen on this laptop
Install Ollama, `ollama pull qwen2.5:3b`, then `python -m agent status` must say ready.
Run `python -m agent eval eval/sentences.txt` and save the output as `docs/reports/qwen_eval.txt`.
A person marks each "full" line as right or wrong. Only then quote any count.
- **Pass:** "After every use, if humidity is above 60, run the fan for 3 minutes" becomes a rule marked "model"
  that the checker accepts; "Open the window when it smells" is refused with a reason; with the model running,
  "Why did the fan run?" comes back marked "model" and contains no number that is not in the template answer.
  If a prompt in `agent/__init__.py` needs changing, change it, rerun the eval, and note both results.

### L2. The real board
Close the Arduino Serial Monitor. `run_board.bat COM5` (your port). The strip must read LIVE FROM THE BOARD.
- **Pass:** each of these changes the screen: close and open the door magnet; lower the water; breathe on the
  humidity sensor; bring the test smell to the air sensor after one use; Approve a rule and see the board
  answer. Write what happened for each in `docs/reports/real_board.md`, including anything that did not work.
  Unplug the USB cable and plug it back: the screen recovers by itself.

### F5. Panels (if time allows)
Jobs and Rules panels, then Timeline, as in `docs/UI.md`.
- **Pass:** a rule can be deleted from the Rules panel and disappears from the board's list; a rule job can be
  marked done from the Jobs panel.

### L3. Before the demo
1. Every number on a slide comes from a run on the real rig, written down in `docs/reports/`.
2. Freeze the code two hours before. Record a video of the full demo.
3. Start Ollama and wait for "Qwen ready" before judges arrive. Have the no-model path ready as the fallback.
