#!/usr/bin/env bash
set -euo pipefail

echo "[ProcureIQ] Applying Alembic database migrations..."
python -m alembic upgrade head

if [ "${RUN_SEED_ON_BOOT:-true}" = "true" ]; then
  echo "[ProcureIQ] Seeding/verifying Tool Registry..."
  PYTHONPATH=/app python /app/scripts/seed_tools.py
fi

echo "[ProcureIQ] Launching Uvicorn (env=${ENVIRONMENT:-production}, workers=${UVICORN_WORKERS:-1})..."
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${UVICORN_WORKERS:-1}"
