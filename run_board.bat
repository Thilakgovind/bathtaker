@echo off
rem Starts the laptop program on the real room board.  Usage:  run_board.bat COM5
cd /d "%~dp0"
if "%1"=="" (
  echo Usage: run_board.bat COM5
  echo Find the port name in the Arduino IDE under Tools, Port. Close the Serial Monitor first.
  pause
  exit /b
)
python -m pip install -q -r requirements.txt
start http://localhost:8000
python -m backend --port %1
