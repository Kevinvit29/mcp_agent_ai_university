@echo off
setlocal
cd /d "%~dp0"
docker compose exec -T backend python -m app.system_bootstrap --status
echo.
pause
