#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_LOG="$PROJECT_DIR/tmp/dashboard-api.log"
WEB_LOG="$PROJECT_DIR/tmp/dashboard-web.log"

mkdir -p "$PROJECT_DIR/tmp"
: > "$API_LOG"
: > "$WEB_LOG"

cd "$PROJECT_DIR"

if [[ ! -x ".venv/bin/uvicorn" ]]; then
  echo "missing .venv/bin/uvicorn"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found in PATH"
  exit 1
fi

wait_for_http() {
  local url="$1"
  local expected="$2"
  local attempts="${3:-10}"
  local delay="${4:-1}"
  local code=""
  local i=1
  while [[ "$i" -le "$attempts" ]]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
    if [[ "$code" == "$expected" ]]; then
      echo "$code"
      return 0
    fi
    sleep "$delay"
    i=$((i + 1))
  done
  echo "$code"
  return 1
}

API_OLD_PID="$(lsof -ti tcp:8000 | head -n1 || true)"
if [[ -n "${API_OLD_PID}" ]]; then
  kill "${API_OLD_PID}" >/dev/null 2>&1 || true
  sleep 1
fi

WEB_OLD_PID="$(lsof -ti tcp:5173 | head -n1 || true)"
if [[ -n "${WEB_OLD_PID}" ]]; then
  kill "${WEB_OLD_PID}" >/dev/null 2>&1 || true
  sleep 1
fi

nohup .venv/bin/uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8000 >"$API_LOG" 2>&1 &
API_PID=$!

nohup npm --prefix dashboard/web run dev -- --host 0.0.0.0 --port 5173 >"$WEB_LOG" 2>&1 &
WEB_PID=$!

API_CODE="$(wait_for_http 'http://127.0.0.1:8000/api/portfolio' '200' 15 1 || true)"
WEB_CODE="$(wait_for_http 'http://127.0.0.1:5173/api/portfolio' '200' 20 1 || true)"

echo "api_pid=$API_PID api_status=$API_CODE log=$API_LOG"
echo "web_pid=$WEB_PID web_proxy_status=$WEB_CODE log=$WEB_LOG"

if [[ "$API_CODE" != "200" || "$WEB_CODE" != "200" ]]; then
  echo "startup check failed; inspect logs:"
  echo "  tail -n 80 $API_LOG"
  echo "  tail -n 80 $WEB_LOG"
  exit 1
fi

echo "dashboard ready:"
echo "  http://127.0.0.1:5173"
echo "  http://$(ipconfig getifaddr en0 2>/dev/null || echo '<your-lan-ip>'):5173"
