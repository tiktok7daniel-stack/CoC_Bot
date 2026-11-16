@echo off
REM One-click Windows build: dist\CoC_Bot_v4\CoC_Bot_v4.exe
chcp 65001 >nul
cd /d "%~dp0\..\.."
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m pip install -q -r src\requirements.txt pyinstaller || goto :fail
if not exist src\configs_build.py copy src\configs.template.py src\configs_build.py >nul
%PY% -c "import sys; sys.path.insert(0, 'src'); from qt_ui.generate_ico import main; main()" || goto :fail
%PY% -m PyInstaller --noconfirm --clean --distpath dist --workpath build scripts\qt_build\CoC_Bot_v4.spec || goto :fail
echo.
echo Done: dist\CoC_Bot_v4\CoC_Bot_v4.exe
pause
exit /b 0
:fail
echo Build failed - see the messages above.
pause
exit /b 1
