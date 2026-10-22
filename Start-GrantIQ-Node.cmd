@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>&1
if errorlevel 1 (
  echo Install Node.js 22.13+ or 24 with npm first. See README.md.
  pause
  exit /b 1
)
if not exist "node_modules\express" (
  echo Run npm ci once in this folder before using the launcher.
  pause
  exit /b 1
)
echo Keep this window open. After startup, open http://127.0.0.1:3000
echo Press Ctrl+C to stop GrantIQ before shutting down.
node --env-file-if-exists=.env.node node/server.js
if errorlevel 1 pause
endlocal
