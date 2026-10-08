@echo off
rem Starts the pretend board (made-up data) and the laptop program, then opens the screen.
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "Pretend board: made-up data" cmd /k python contract\board_sim.py
timeout /t 2 >nul
start http://localhost:8000
python -m backend --port socket://localhost:5555
