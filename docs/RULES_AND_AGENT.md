# Caretaker rules and the agent

## The rule shape (the only thing the model may produce)

```json
{
  "name": "Fan when humid",
  "trigger": { "type": "while" },
  "when": [ { "sensor": "humidity_pct", "is": "above", "value": 70 } ],
  "match": "all",
  "hold_seconds": 5,
  "action": { "type": "fan", "set": "on" },
  "for_seconds": 0,
  "priority": 4
}
```

| Field | Allowed |
| --- | --- |
| trigger | `{"type":"while"}` or `{"type":"on_event","event":E}` with E in USE_START, USE_END, CLEANED, TAP_CONFIRMED, AIR_BAD, LOW_WATER |
| when | 0 to 3 conditions (at least 1 for a `while` rule) |
| sensor | door (0 open, 1 closed), water_level_mm, water_rate_mm_per_min, air_percent, humidity_pct, temperature_c, uses, occupied_seconds, free_seconds |
| is | below, above, equals |
| match | all, any |
| hold_seconds | 0 to 600: the conditions must stay true this long before the rule fires |
| action | `{"type":"fan","set":"on"\|"off"}` or `{"type":"job","text":"..."}` (raises a job for the caretaker) |
| for_seconds | 0 to 3600: 0 means "for as long as the conditions are true" |
| priority | 1 (wins) to 8 |

Ranges, the checker, the clash test and the compact board line are all in `contract/rules.py`.

## The pipeline for a new rule

1. **Sentence in.** Typed or spoken.
2. **Draft.** Pattern parser first. If it does not match, the model. The UI shows which one wrote the draft.
3. **Check.** `check_rule(rule, existing)`. Problems are shown in plain words. A rule with problems cannot be uploaded.
4. **Replay.** Run the draft against stored history (the last 2 hours by default) with the reference logic and
   show how often it would have fired, as bars on the rule badge. Label the data source.
5. **Approve.** A person clicks. Nothing reaches the board without this.
6. **Upload.** `encode_rule` then send; wait for `A,RULE,OK`. Show an error if the board refuses or is silent.
7. **Confirm.** `RULES?` and show what the board actually holds. The board is the truth, not the database.

## The agent: three jobs, one guard

The agent is a router with three fixed pipelines. It is not a free tool-using loop: a 3-billion-parameter
local model is not reliable enough for that, and the design does not need it.

| Job | Input | The model does | Code does |
| --- | --- | --- | --- |
| Rule writer | A sentence, the sensor list with ranges, three worked examples | Fills the rule shape as JSON | Validates JSON, runs the checker, retries once with the problems, then falls back to "I could not turn that into a rule" |
| Explainer ("why did the fan come on?") | The question | Picks which event the question is about from a short list, then phrases the answer | Finds the event chain (cause -> action -> verification) by code; supplies every number; attaches event ids |
| Shift report | A time range | Writes 3 to 5 sentences | Computes every figure: uses, jobs raised and closed, fan run time, water lost in mm, faults |

**The guard.** The model never produces a number, a time or a command. It receives facts and returns wording
or a filled shape. Every answer shown to a person lists the event ids it rests on, and each id opens the timeline.
If the model is slow (over 45 s, set with `CARETAKER_TIMEOUT`) or returns something that fails validation, the code's plain template is shown
instead, marked "template".

### Routing
Code decides the job (`agent.route`): a line starting with why/what happened/when did goes to the explainer;
"report", "summary" or "shift" to the shift report; "what needs me" to the status answer; anything with
when/if/after/turn/run/tell me to the rule writer. The model is never asked to choose.

### Pattern parser (works with no model)
Fixed shapes, numbers as digits:

- `turn|switch|run the fan on|off when|if <sensor> is above|below|over|under <number> [for <n> seconds|minutes]`
- `run the fan for <n> seconds|minutes after every use | after cleaning`
- `tell me|alert me when|if <sensor> is above|below <number> [for <n> seconds|minutes]` (either order)
- `tell me if the door is closed for more than <n> minutes`
- `tell me when the room has been used more than <n> times`, `ask for cleaning after <n> uses`
- `tell me if the tap is left running`

The code is `agent/patterns.py`. On the 30 test sentences it produces 12 rules and catches 2 out-of-range
values; the other 16 go to the model, or are refused when no model is running.

Sensor words: humidity, air, water level, water, temperature, uses, door.

### Model settings
Ollama `/api/chat`, `format` set to the rule's JSON schema, temperature 0, `keep_alive` 30m.
Send one warm-up request when the backend starts, and show "model ready" or "model not running" in the UI.

## Measuring the rule writer

`eval/sentences.txt` holds 30 sentences with the expected outcome. Before any prompt tuning, freeze this file.
Score each sentence as correct rule, wrong rule, or refused; report the model and the pattern parser side by side.
Ask someone outside the team for 10 unseen sentences and report that score separately.
A wrong rule that the checker then refuses counts as "caught", and is reported in its own column.
