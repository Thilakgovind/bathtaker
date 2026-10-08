"""Listen to a board (or the pretend board) and say whether it speaks the protocol.

    python contract/check_serial.py COM5
    python contract/check_serial.py socket://localhost:5555  20

Needs pyserial:  pip install pyserial
"""
import sys
import time

import serial

from protocol import parse_line


def main(url, seconds=10.0):
    ser = serial.serial_for_url(url, baudrate=115200, timeout=1)
    ser.write(b"HELLO?\n")
    good = bad = 0
    hello = last = None
    events = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        raw = ser.readline().decode("ascii", "ignore").strip()
        if not raw:
            continue
        got = parse_line(raw)
        if got is None:
            bad += 1
            continue
        good += 1
        if got[0] == "H":
            hello = got[1]
        elif got[0] == "D":
            last = got[1]
        elif got[0] == "E":
            events.append(got[1].code)
    ser.close()
    print("hello:        ", hello or "none received")
    print("good lines:   ", good, "  unrecognised lines:", bad)
    print("data rate:    ", "%.1f lines/s" % (good / seconds))
    print("last reading: ", last)
    print("events seen:  ", events or "none")
    ok = hello is not None and last is not None and good / seconds >= 1.5
    print("RESULT:", "PASS" if ok else "FAIL (need a hello line and at least 1.5 good lines a second)")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    sys.exit(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10.0))
