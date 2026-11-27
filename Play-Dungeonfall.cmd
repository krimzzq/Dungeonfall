@echo off
setlocal
cd /d "%~dp0"
set "DF_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%DF_PYTHON%" (
    py -3.14 -m venv .venv
    if errorlevel 1 goto failed
)
"%DF_PYTHON%" -c "from importlib.metadata import version; assert version('pygame-ce') == '2.5.8'" >NUL 2>&1
if errorlevel 1 (
    "%DF_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
"%DF_PYTHON%" main.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Dungeonfall could not start. See the error above.
pause
exit /b 1
