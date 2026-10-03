@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "STUDIO_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if exist ".venv\Scripts\python.exe" set "STUDIO_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" set "STUDIO_PYTHON=python"
echo HYX Scene Studio: http://127.0.0.1:8877/
echo Keep this window open. Start CARLA map10 before previewing a scenario.
"%STUDIO_PYTHON%" -m scene_studio.server
pause
