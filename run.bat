@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)

rem Brings an existing .venv up to requirements.txt (e.g. pwfauth 1.0.1 -> 1.1.0).
rem Nothing is downloaded when it already matches.
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" app.py
