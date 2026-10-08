# Protocol: room board <-> laptop

`contract/protocol.py` and its tests are the authority. This page explains them.

- USB serial, 115200 baud, 8N1. One message per line, ASCII, ends with `\n`.
- Fields are separated by commas. All numbers are integers.
- The laptop must ignore any line it does not recognise (boot text, half lines).
- `ms` is the board's uptime in milliseconds. The laptop stamps wall-clock time when a line arrives.
  A `BOOT` event, or `ms` going backwards, starts a new session.

## Board -> laptop

### Hello
`H,<protocol>,<firmware>,<board>` - sent at boot and in answer to `HELLO?`. Example: `H,1,0.3,ROOM`

### Data, every 500 ms
`D,ms,door,level_mm,level_rate,gas_raw,gas_pct,hum,temp,fan,state,uses,flags`

| Field | Meaning |
| --- | --- |
| door | 0 open, 1 closed |
| level_mm | water depth in mm; -1 if the ultrasonic sensor gave no valid echo |
| level_rate | mm per minute over the last 20 s; negative means falling |
| gas_raw | 0 to 4095 from the ADC |
| gas_pct | percent of the learned normal level; 100 is normal; 0 means not learned yet |
| hum | relative humidity x 10; -1 if invalid |
| temp | degrees C x 10; -1 if invalid |
| fan | 0 or 1: what the room board is commanding |
| state | FREE, IN_USE, VENTILATING, NEEDS_CLEANING, NO_WATER, FAULT |
| uses | uses since the last clean |
| flags | bit 1 steam gate on, 2 normal level learned, 4 link to service board ok, 8 fan manual, 16 tap suspected, 32 air bad |

Example: `D,71500,0,212,-12,934,104,612,285,0,FREE,3,22`

### Events, when they happen
`E,ms,seq,CODE,a,b` - `seq` rises by one per event, so a gap means a lost line.

| Code | a | b |
| --- | --- | --- |
| BOOT | | |
| USE_START | | |
| USE_END | seconds the door was closed | uses so far |
| TAP_SUSPECTED | fall rate, mm/min | |
| TAP_CONFIRMED | fall rate, mm/min | mm lost so far |
| TAP_CLEARED | | |
| LOW_WATER / WATER_OK | level, mm | |
| STEAM_GATE_ON / STEAM_GATE_OFF | humidity x 10 | |
| AIR_SUPPRESSED | air percent that would have raised the alarm | |
| AIR_BAD | air percent | uses so far |
| AIR_OK | air percent | |
| FAN_ON | reason: 1 humidity, 2 air, 3 rule, 4 manual | |
| FAN_OFF | seconds it ran | |
| FAN_VERIFIED | how far the reading fell | seconds |
| FAN_FAULT | reason the fan was started | how far the reading fell |
| CLEAN_DUE | uses | 1 = by count, 2 = bad air after uses |
| DRAIN_CHECK | air percent | |
| CLEANED | | |
| SENSOR_FAULT / SENSOR_OK | 1 ultrasonic, 2 gas, 3 humidity, 4 door | |
| LINK_LOST / LINK_OK | | |
| RULE_FIRED / RULE_ADDED / RULE_DELETED | slot | |

### Answers
`A,<command>,OK[,detail]` or `A,<command>,ERR,<reason>`

### Rule listing
`R,<slot>,...` - same fields as a `RULE` command, one line per stored rule, then `A,RULES,OK,<count>`.

## Laptop -> board

| Command | Effect |
| --- | --- |
| `PING` | `A,PING,OK` |
| `HELLO?` | an `H` line. Send this right after opening the port |
| `CLEANED` | resets uses, cleaning flags and a latched fault; emits `CLEANED` |
| `FAN,AUTO` / `FAN,ON` / `FAN,OFF` | manual override; `AUTO` returns control to the board |
| `RULE,slot,priority,ALL\|ANY,hold_s,action,for_s,trigger,n,(sensor,op,value)xn,name` | stores a rule in slot 1 to 8 |
| `DEL,slot` | deletes a rule |
| `RULES?` | lists stored rules |
| `CFG,KEY,value` | changes one threshold (keys are in `contract/room_logic.py`) |
| `CFG?` | lists all thresholds |
| `LOG?` | re-sends the last 50 events |

Rule fields: `action` is `FAN_ON`, `FAN_OFF` or `JOB:<text>`; `trigger` is `WHILE` or `ON:<event>`;
`sensor` is one of DOOR, LEVEL, RATE, GAS, HUM, TEMP, USES, OCC_S, FREE_S; `op` is LT, GT or EQ.
HUM and TEMP values are x 10. Example, "run the fan for 30 s after every use":

    RULE,1,3,ALL,0,FAN_ON,30,ON:USE_END,0,Fan after use

Build these lines with `contract/rules.py: encode_rule`. Never by hand in application code.

## Room board <-> service board (ESP-NOW)

Fixed-size packets, peers set by MAC address in the firmware.

| Direction | Fields |
| --- | --- |
| Room -> service, every 500 ms and on change | packet number (uint32), fan (0/1), resting state (0/1) |
| Service -> room, on every packet | packet number echoed, relay state (0/1) |

The service board returns the relay to the resting state if no packet arrives for 3 s.
The room board sets the "link ok" flag from the acknowledgements, and measures the round trip.
A three-wire serial link (GPIO 17 to 16, 16 to 17, GND to GND) is the backup; same packet contents as text.
