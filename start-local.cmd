@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'" || goto failed
    py -3 -m venv .venv || goto failed
)
".venv\Scripts\python.exe" -c "import vrc_parsers; assert vrc_parsers.__version__ == '0.2.1'" >nul 2>&1
if errorlevel 1 (
    echo First start: installing this project and dependencies. Internet access is required.
    ".venv\Scripts\python.exe" -m pip install . || goto failed
)
".venv\Scripts\python.exe" -m vrc_parsers.web %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Install Python 3.11+ and see docs\LOCAL_USE.md.
pause
exit /b 1
