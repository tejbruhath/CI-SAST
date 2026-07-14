#!/usr/bin/env bash
set -euo pipefail

# Sentriq local dev launcher.
# Starts backend + frontend in the foreground. Ctrl+C stops both.
# deps.compose.yml services (Postgres/Redis) are started if missing and left running.

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/ci-utils"
FRONTEND_DIR="${PROJECT_ROOT}/sentriq-frontend"
VENV_PYTHON="${BACKEND_DIR}/.venv/bin/python"
DEPS_COMPOSE="${PROJECT_ROOT}/deps.compose.yml"

# ---- ensure deps are running ----
RUNNING_SERVICES=$(docker compose -f "${DEPS_COMPOSE}" ps --services --filter "status=running" 2>/dev/null || true)
if [[ "${RUNNING_SERVICES}" != *"postgres"* ]] || [[ "${RUNNING_SERVICES}" != *"redis"* ]]; then
  echo "[sentriq] Starting Postgres + Redis via deps.compose.yml..."
  docker compose -f "${DEPS_COMPOSE}" up -d
else
  echo "[sentriq] Postgres + Redis already running."
fi

# ---- sanity checks ----
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[sentriq] ERROR: virtual env not found at ${BACKEND_DIR}/.venv"
  exit 1
fi

cd "${BACKEND_DIR}"
echo "[sentriq] Running migrations (if any)..."
"${VENV_PYTHON}" manage.py migrate

# ---- start backend ----
echo "[sentriq] Starting backend on http://0.0.0.0:8000"
"${VENV_PYTHON}" manage.py runserver 0.0.0.0:8000 &
BACKEND_PID=$!

# ---- start celery worker ----
# Scans are dispatched with run_scan.delay(); without a worker they sit in Redis
# forever and the scan never leaves "queued".
echo "[sentriq] Starting Celery worker..."
"${BACKEND_DIR}/.venv/bin/celery" -A ciutils worker --loglevel=info --concurrency=2 &
WORKER_PID=$!

# ---- start frontend ----
cd "${FRONTEND_DIR}"
echo "[sentriq] Starting frontend dev server..."
npm run dev &
FRONTEND_PID=$!

# ---- cleanup on exit / ctrl-c ----
cleanup() {
  echo ""
  echo "[sentriq] Shutting down frontend, worker and backend..."
  for pid in "${FRONTEND_PID}" "${WORKER_PID}" "${BACKEND_PID}"; do
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  echo "[sentriq] Done. Postgres + Redis are still running."
}
trap cleanup EXIT INT TERM

# ---- wait for both ----
wait "${BACKEND_PID}"
wait "${FRONTEND_PID}"
