# The seam between the agent and the backend

The agent is a plain Python package in `agent/` at the top of the repository. It needs no board, no database
and no web server, so it can be built and scored alone. The backend imports it and calls four functions.
Do not change these signatures without changing the backend and its tests in the same step.
The package exists and is tested without a model; the Qwen path has not been run yet (docs/TASKS.md, L1).

```python
# agent/__init__.py

def status() -> dict:
    """{"model": "qwen2.5:3b", "ready": bool, "detail": str}"""

def draft_rule(sentence: str, existing: list[dict]) -> dict:
    """Turn a sentence into a rule in the shape defined in contract/rules.py.
    Returns {"rule": dict | None,          # None when nothing usable was produced
             "by": "pattern" | "model" | "none",
             "problems": list[str],        # from contract.rules.check_rule, in plain words
             "notes": list[str],           # gentle warnings, e.g. a number that was not in the sentence
             "parts": dict | None,         # the rule in plain words: when, do, for, hold, sentence, kind
             "ms": int}
    Order: pattern parser, then the model, one retry with the problems, then give up.
    Never returns a rule that fails check_rule without listing its problems."""

def explain(question: str, events: list[dict], readings: list[dict],
            rules: dict | None = None, now: float | None = None, cfg: dict | None = None) -> dict:
    """Answer "why did X happen" from stored events.
    events:   [{"id": int, "time": "HH:MM:SS", "code": str, "a": int, "b": int}, ...] oldest first
    readings: [{"time": "HH:MM:SS", "level_mm": int, "hum_pct": float, "gas_pct": int, "fan": int}, ...]
    events also carry "ts" (seconds). rules is {slot: rule} from the board; cfg holds its thresholds.
    Returns {"answer": str, "event_ids": list[int], "by": "model" | "template", "ms": int,
             "chain": dict | None}     # saw / decided / did / checked, built by agent/chain.py
    Code finds the event chain and supplies every number. The model only words it."""

def shift_report(facts: dict) -> dict:
    """facts holds figures already computed by the backend, for example
    {"from": "09:00", "to": "13:00", "uses": 14, "jobs_opened": 5, "jobs_closed": 4,
     "fan_minutes": 22, "water_lost_mm": 31, "faults": 1}
    Returns {"text": str, "by": "model" | "template", "ms": int}"""
```

Rules for the agent package:

- Import the rule shape and checker from `contract/rules.py`. Do not copy them.
- With Ollama stopped, every function still returns within a second, marked `pattern`, `template` or `none`.
- A model call that takes longer than 45 s (set with `CARETAKER_TIMEOUT`) is abandoned and the template is
  returned. The backend warms the model up when it starts, because the first answer after a load is the slow one.
- Command line for testing alone:
  `python -m agent status`, `python -m agent rule "turn the fan on when humidity is above 70"` and
  `python -m agent eval eval/sentences.txt` (prints what the pattern reader and the full pipeline made of each
  sentence, with counts of rule / caught by the checker / refused; a person marks which are correct).
- Sample events for the explainer come from the pretend board: run `python contract/board_sim.py`,
  play a scenario, and save the `E` lines. The structure is identical to the real board's.
