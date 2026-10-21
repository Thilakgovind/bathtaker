"""Start the laptop program.

    python -m backend --port COM5                       the real room board
    python -m backend --port socket://localhost:5555    the pretend board (made-up data)
    python -m backend                                   no board: the screen says "not connected"

Then open http://localhost:8000
"""
import argparse
import os

import uvicorn

from .app.main import create_app


def main():
    ap = argparse.ArgumentParser(description="Washroom caretaker: laptop program")
    ap.add_argument("--port", default=os.environ.get("CARETAKER_PORT"),
                    help="Serial port of the room board (COM5, /dev/ttyUSB0) or socket://localhost:5555")
    ap.add_argument("--http", type=int, default=int(os.environ.get("PORT", "8000")),
                    help="Web port (default 8000, or $PORT)")
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"),
                    help="Host to bind (default 127.0.0.1 or 0.0.0.0 when $PORT is set)")
    ap.add_argument("--db", default=None, help="Database file (default data/caretaker.db)")
    a = ap.parse_args()
    print("Board port:", a.port or "none chosen")
    print("Open http://localhost:%d" % a.http)
    uvicorn.run(create_app(a.port, a.db), host=a.host, port=a.http, log_level="warning")


if __name__ == "__main__":
    main()
