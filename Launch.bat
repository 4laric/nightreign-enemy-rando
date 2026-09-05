@echo off
REM Launch.bat - double-click launcher for the rando GUI on Windows.
REM Uses pythonw (no console) instead of python (console). Brief cmd
REM flash on launch is normal — Windows opens a cmd window to run
REM the batch, but pythonw inherits no console of its own so the
REM batch window closes immediately.

cd /d "%~dp0"

REM Try pythonw first (preferred — no console). Fall back to python
REM if pythonw isn't on PATH (some minimal Python installs).
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" pythonw "oops_rando_gui.py" %*
) else (
    REM Last resort: use python. Will leave a console open but
    REM at least the GUI runs.
    start "" python "oops_rando_gui.py" %*
)
