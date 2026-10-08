# What the room board decides

`contract/room_logic.py` is the reference. The firmware must produce the same events in the same order
for the same inputs. Every number here is a starting value to tune on the real rig; none is measured.

## Pins (proposed, test in the first hour)

| Board | Part | Pin |
| --- | --- | --- |
| Room | OLED SDA / SCL | GPIO 21 / 22 |
| Room | Temperature and humidity data | GPIO 4 |
| Room | Magnetic sensor DO (door) | GPIO 32 |
| Room | Ultrasonic Trig / Echo (Echo through 1 k + 2 k divider) | GPIO 19 / 18 |
| Room | MQ-135 AO (through 1 k + 2 k divider) | GPIO 34 |
| Service | Relay IN | GPIO 26 |
| Both | Wired-link backup TX / RX | GPIO 17 / 16 |

Do not use GPIO 0, 2, 5, 12, 15 (boot behaviour). GPIO 34 is input only and stays usable with the radio on.

## Sampling

- Loop tick every 100 ms. Data line every 500 ms.
- Ultrasonic: one ping per tick with a 25 ms timeout; median of the last five; water level = sensor height - distance.
- Gas: average of 8 ADC reads per tick.
- Humidity sensor: read no faster than it allows (2 s for the common types); reuse the last value in between.
- Door: debounce 50 ms.

## Decisions

| Decision | In words | Thresholds (CFG keys) |
| --- | --- | --- |
| Use | The door stays closed long enough to count, then opens | MIN_USE_S 3 |
| Water slope | Straight-line fit of the level over a window, in mm per minute. The window restarts when the door opens, so water used during a visit is never counted as a tap left running | SLOPE_WINDOW_S 20 |
| Tap suspected | Water falling while the door is open | TAP_RATE 6, TAP_SUSPECT_S 15 |
| Tap confirmed | Still falling | TAP_CONFIRM_S 45 |
| Tap cleared | Stopped falling for a while, or the door closed | TAP_CLEAR_S 10 |
| Low water | Level under the low mark for 5 s; clears 10 mm above it | LOW_MM 40 |
| Steam gate on | Humidity rose fast inside the window | STEAM_RISE 50 (x10), STEAM_WINDOW_S 30 |
| Steam gate off | Humidity back near where it started for 10 s, or the time limit | STEAM_SETTLE 30 (x10), STEAM_MAX_S 900 |
| Normal air level | Learned only when the door is open, the fan is off, there is no steam and humidity is steady | BASELINE_STABLE_S 60 |
| Air bad | Air percent above the line long enough, and the steam gate is off | GAS_BAD_PCT 125, GAS_BAD_S 10 |
| Air suppressed | Same reading, but the steam gate is on: logged, no alarm | |
| Air ok | Air percent back under the lower line long enough | GAS_OK_PCT 112 |
| Clean due | Enough uses, or air bad after at least one use | CLEAN_USES 5 |
| Drain check | Air bad with zero uses since the last clean | |
| Fan on (automatic) | Humidity above the upper line (stays on until below the lower line), or air bad | HUM_ON 750, HUM_OFF 680 |
| Fan minimum run | Once on, stays on this long | FAN_MIN_ON_S 20 |
| Fan verified | The reading that started the fan fell enough within the check time, or the fan switched off because it fell | VERIFY_S 60, VERIFY_HUM_DROP 80 (x10), VERIFY_GAS_DROP 5 |
| Fan fault | It did not fall enough. Text for people: "fan fault, or the source is still present" | |
| Sensor fault | No valid reading for 3 s | SENSOR_TIMEOUT_S 3 |
| Link lost | No acknowledgement from the service board for 3 s | LINK_TIMEOUT_S 3 |

Who controls the fan: manual override beats caretaker rules; rules beat the automatic control.
Among active fan rules the lowest priority number wins, and on a tie "off" wins.

State shown on the door sign, most serious first:
FAULT, NO_WATER, NEEDS_CLEANING, VENTILATING, IN_USE, FREE.

## Tuning these on the real rig (do this before the demo)

1. **VERIFY_HUM_DROP.** Steam the box, start the fan, note the humidity fall in 60 s. Repeat with the fan
   unplugged. Set the value between the two. If the two falls are close, this check cannot work on your rig; say so.
2. **TAP_RATE.** Note the slope reading with still water for a minute. Set the value well above that noise.
3. **GAS_BAD_PCT.** Note the air percent with clean air for a few minutes, then with the test source. Set the line between.
4. **STEAM_RISE.** Note how fast humidity rises with the hot-water cup, and how much it wanders without it.

## Storage and display

- Rules and thresholds are saved in the board's own storage and restored at boot.
- The last 50 events are kept in memory for `LOG?`.
- OLED: the door sign (state in large letters) alternates every 3 s with the last event in words.

## Fail-safes

- No valid echo: level is -1, rules that use the level do not fire, a sensor fault is raised.
- A rule never fires on a missing reading.
- The relay toggles at most once a second.
- Service board silent: the room board raises LINK_LOST; the service board has already gone to the resting state.
