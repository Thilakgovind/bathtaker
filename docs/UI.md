# The screen: locked design and what each part shows

The design is locked. Do not redesign it; build it.

- **Source of truth:** the Paper file "Washroom Caretaker", artboard "Room screen v3, photo and blue agent".
- **Copies in this folder:** `design/room_screen_final.jpg` (how it must look), `design/room_screen.jsx`
  (exported layout with exact sizes, spacing and colours as Tailwind classes), and the three pictures
  `design/washroom_stage.jpg`, `design/caretaker_hero.jpg`, `design/agent_blue.jpg`.
- Every text and number in the design is a **sample**. Replace each one with live data as listed below.
  Never ship a hard-coded sample value.
- The three pictures are generated images, not photos of the real rig. Do not present them as the rig.

## Look

| Token | Value | Use |
| --- | --- | --- |
| porcelain | `#FFFFFF` | page, text on dark |
| ink | `#000000` | text, hairlines, black pills |
| quiet | `#B8B8B8` | second headline line |
| tag | `#FFD400` | the one loud colour: job tag, progress, source label, lanyard |
| cobalt | `#1B2CFF` | the agent chat block and its accents |
| glass | white at 14% + `backdrop-filter: blur(26px) saturate(150%)`, 1 px border white at 38% | sensor tiles |
| dark glass | `#0A0E0C` at 50% + blur 30 px | the decision strip |

- **Fonts:** grotesk = Switzer, serif = Boska or Zodiak (all from Fontshare; put the downloaded `.woff2` files in
  `frontend/src/assets/fonts/`). Until those files are there, use `@fontsource-variable/inter-tight` and
  `@fontsource/cormorant-garamond`, which the design was drawn with. One CSS variable per role, so the swap is
  one line. No CDN links: the demo must work with no internet.
- Canvas is 1440 x 900, scaled as one piece to fit the window (`useFit` in `App.tsx`), so it never scrolls
  sideways. It is a laptop screen for a demo; a separate phone layout was not built.
- Motion only where it mirrors the room: the fan glyph turns while `fan` is 1, progress bars move, new events
  slide into the strip. Respect "reduce motion".
- Sentence case in glass and chat; capitals with tight tracking in the grid band, as drawn.

## Room side (left 1000 px)

| Part in the design | Shows | From |
| --- | --- | --- |
| Headline line 1, "NEEDS CLEANING" | `state_word` in capitals. Not connected: "NOT CONNECTED". No reading yet: "WAITING FOR THE BOARD" | `GET /api/state`, then `/ws` readings |
| Headline line 2, "WASHROOM 01" | the room name (one constant) | config |
| Nav: ( ROOM ) JOBS n RULES n | `jobs_open` in the yellow pill and `rules_count` beside RULES. They are counts, not links yet: the panels below are not built. TIMELINE was dropped from the nav until its panel exists | state |
| MARK AS CLEANED pill | sends `{"cmd":"CLEANED"}`. Disabled when not connected | `POST /api/command` |
| Big number cell, "31 %" | `gas_pct - 100`, floor at 0. Label "( AIR ABOVE NORMAL )". While `baseline_ok` is false: a dash, with "LEARNING THIS ROOM'S NORMAL AIR" on the line under it | reading |
| Line under the number | air bad: "CHANGED n MIN AGO" + ", NO STEAM" or ", STEAM IN THE ROOM" (`steam_gate`). Otherwise "NORMAL" | time of the last `AIR_BAD` event; reading |
| Yellow tag | the most urgent job: `title` in capitals, `reason`, and "( WHY THIS JOB )" which opens `GET /api/why?event_id=<last of event_ids>`. No open job: hide the tag | `GET /api/jobs` |
| "5 USES" | `reading.uses` + " USES" (or "1 USE"). Caption: "since the last clean, 1 h 12 min ago" from `last_cleaned`, else "since the board started" | state |
| Decision strip | `steps` of the decision: label, head, sub. Header right: `time` + ", no laptop or internet needed". Step 4 label in yellow while `status` is `checking`, with a bar filled by `seconds_left` out of 60. `null`: hide the strip | `GET /api/decision`, refetch on every event |
| Water tank tile | `level_mm` + " mm"; glyph fill height from `level_mm` (0 to 300). Sub: "Steady, no tap left on", or "Falling n mm a minute" when `level_rate` <= -6, or "Tap may be left on" when `tap_suspected`. `-1`: "No reading" | reading |
| Humidity tile | `hum_pct` + " %". Sub: "No steam in the room" or "Steam in the room" (`steam_gate`). `null`: "No reading" | reading |
| Exhaust fan tile | "On" or "Off". Sub and bar from the decision when it is a fan chain: "Checking it worked" with the bar, "Worked" (`passed`), "Did not work" (`failed`). `fan_manual`: "Manual" | reading + decision |
| Door tile | "Vacant" or "Engaged" (`door`). Sub: "Free for n min" from `last_use_ended`, or "In use" | reading + state |
| Bottom strip | first the source in yellow: "PRETEND BOARD, SAMPLE DATA" (`SIMULATED`), "LIVE FROM THE BOARD ON COM5" (`BOARD`), or "BOARD NOT CONNECTED" in red. Then the last events as `time` + `title` in capitals, newest on the right | state + `GET /api/events?minutes=30&limit=8` + `/ws` events |

## Agent side (right 440 px)

| Part in the design | Shows | From |
| --- | --- | --- |
| Header right, "Qwen, offline" | `model.ready`: "Qwen ready, no internet needed". Otherwise "Model off: fixed patterns only" | state |
| Serif headline | fixed: "I watch the room. You make the call." | |
| Line under it | the first notice's `text`. No notice: "Nothing unusual in the last 24 hours." | `GET /api/notices` |
| "Draft that rule" | only when the notice has a `rule`: posts its `sentence` to the draft address and shows the badge | `POST /api/rules/draft` |
| "Show me the last time" | opens the "why" of the notice's latest event. "Not now" dismisses the notice | `GET /api/why`, `POST /api/notices/{id}/dismiss` |
| Blue block wordmark | the project name (one constant). It sits behind the chat | config |
| Black bubble | the sentence the caretaker typed | |
| Rule badge | glyph: fan for `parts.kind` = `fan`, a clipboard for `job`. "( RULE 0n )" from `slot`. Name from `rule.name` in serif. Chips: `parts.when`, `parts.do`, `parts.for` (and `parts.hold` if set). "Barcode": one bar per `replay.fired`, placed between `replay.from` and `replay.to`. Caption: "Tested: n runs in the last <span actually covered>", plus ", sample data" when `replay.sources` has `SIMULATED` | draft answer |
| Line beside the badge | no problems: "No clash with your n other rules" (`rules_count`). Problems: the first problem, in yellow, and no Approve button | draft answer |
| Four steps | Drafted, Approved by you, Sent to the board, Board said OK: fill each dot from `steps` in the upload answer | `POST /api/rules/upload` |
| "Approve and send to board" | uploads the drafted rule. On failure show `detail` | upload |
| "Change it" | puts the sentence back in the type box | |
| Quick asks | send their own text to `POST /api/ask` | ask |
| Type box | `POST /api/ask` with the typed text. Show `by` on every answer: "pattern", "model" or "template" | ask |

Answers that are not rules (`kind` = `why`, `report`, `status`) take the badge's place as a white card in the
same style. A `why` card shows the four steps; the sentence is shown only when the model reworded it. Every
card carries a small "by" label. Before anything is typed, the block shows three example sentences to tap.

The code: `frontend/src/useRoom.ts` (live data), `components/GridBand.tsx`, `components/Stage.tsx`,
`components/AgentSide.tsx`, with shapes in `api.ts`.

## Panels not drawn in Paper

Build these as simple panels in the same style (white, hairlines, the same type), opened from the nav:

- **Jobs:** `GET /api/jobs`. One row per job: priority, title, reason, since. Button "Mark done" when
  `can_mark_done` or `closes_with` is "Mark as cleaned"; otherwise show "Closes by itself: <closes_with>".
- **Rules:** `GET /api/rules`. One small badge per rule with its sentence, times fired, last fired, and Delete.
- **Timeline:** `GET /api/readings` and `GET /api/events`. Water level, humidity and air on one time axis with
  event markers. This one is optional: build it last.

## Things the screen must never do

- Show a number that did not come from the laptop program.
- Hide the data source.
- Say the system closed a valve, sprayed anything, or identified a gas or a person. It has one fan relay, and
  the air sensor only shows that the air changed.
- Send anything to the board without a click.
