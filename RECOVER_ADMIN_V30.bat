@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-v30.ps1" -ResetAdmin
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo V30 administrator recovery did not complete. Keep this window open and copy the diagnostic output.
)
pause
exit /b %EXIT_CODE%
