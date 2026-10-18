@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "CASE172_PYTHON=C:\Users\10742\AppData\Local\Programs\Python\Python310\python.exe"
if not exist "%CASE172_PYTHON%" set "CASE172_PYTHON=python"
if "%~1"=="" (
  "%CASE172_PYTHON%" tools\run_case172.py --ids P02
) else if /i "%~1"=="all" (
  "%CASE172_PYTHON%" tools\run_case172.py --all
) else (
  "%CASE172_PYTHON%" tools\run_case172.py --ids %*
)
set "CASE172_RESULT=%ERRORLEVEL%"
echo.
echo Run finished. Exit code: %CASE172_RESULT%
pause
exit /b %CASE172_RESULT%
