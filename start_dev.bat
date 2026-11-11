@echo off
setlocal
echo =====================================================================
echo   ProcureIQ Agent - Launching Backend + Frontend
echo =====================================================================

echo [*] Starting FastAPI Backend on http://localhost:8000 ...
start "ProcureIQ Backend (FastAPI)" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [*] Starting Vite React UI on http://localhost:5175 ...
start "ProcureIQ Frontend (React)" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 5175"

echo.
echo   Web UI           : http://localhost:5175
echo   Backend Swagger  : http://localhost:8000/docs
echo   Health Status    : http://localhost:8000/health
echo.
pause

