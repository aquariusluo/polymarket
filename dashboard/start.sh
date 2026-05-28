#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="$PROJECT_ROOT/dashboard/web"

echo "Starting Polymarket Dashboard..."

# Start FastAPI backend (port 8000)
cd "$PROJECT_ROOT"
"$PROJECT_ROOT/.venv/bin/uvicorn" dashboard.api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

# Start Vite dev server (port 5173)
cd "$WEB_DIR"
npm run dev &
WEB_PID=$!

cleanup() {
  echo "Shutting down..."
  kill "$API_PID" 2>/dev/null
  kill "$WEB_PID" 2>/dev/null
  wait "$API_PID" "$WEB_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "API:  http://localhost:8000/docs"
echo "Web:  http://localhost:5173"
echo "Press Ctrl+C to stop both servers."

wait
