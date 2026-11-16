@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -c "import PySide6" 2>nul || (
  echo Installing the new interface (PySide6) - first time only...
  %PY% -m pip install -q "PySide6>=6.6"
)
%PY% src\main.py --gui
if errorlevel 1 pause
