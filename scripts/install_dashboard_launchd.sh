#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"
API_LABEL="com.aquariusluo.polymarket.dashboard-api"
WEB_LABEL="com.aquariusluo.polymarket.dashboard-web"
NPM_BIN="$(command -v npm || true)"
NODE_BIN="$(command -v node || true)"

mkdir -p "$TARGET_DIR" "$PROJECT_DIR/tmp"
: > "$PROJECT_DIR/tmp/dashboard-api.log"
: > "$PROJECT_DIR/tmp/dashboard-web.log"

if [[ ! -x "$PROJECT_DIR/.venv/bin/uvicorn" ]]; then
  echo "missing $PROJECT_DIR/.venv/bin/uvicorn"
  exit 1
fi

if [[ -z "$NPM_BIN" ]]; then
  echo "npm not found in PATH"
  exit 1
fi

if [[ -z "$NODE_BIN" ]]; then
  echo "node not found in PATH"
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/dashboard/web/node_modules/vite/bin/vite.js" ]]; then
  echo "missing $PROJECT_DIR/dashboard/web/node_modules/vite/bin/vite.js"
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

render_and_load() {
  local label="$1"
  local source_plist="$PROJECT_DIR/launchd/$label.plist"
  local target_plist="$TARGET_DIR/$label.plist"
  sed \
    -e "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" \
    -e "s|{{NPM_BIN}}|$NPM_BIN|g" \
    -e "s|{{NODE_BIN}}|$NODE_BIN|g" \
    "$source_plist" > "$target_plist"
  if rg -F -q '{{PROJECT_DIR}}' "$target_plist" || rg -F -q '{{NPM_BIN}}' "$target_plist" || rg -F -q '{{NODE_BIN}}' "$target_plist"; then
    echo "unrendered placeholders remain in $target_plist"
    exit 1
  fi
  launchctl bootout "gui/$(id -u)" "$target_plist" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$target_plist"
  launchctl kickstart -k "gui/$(id -u)/$label"
}

render_and_load "$API_LABEL"
render_and_load "$WEB_LABEL"

API_CODE="$(wait_for_http 'http://127.0.0.1:8000/api/overview' '200' 15 1 || true)"
WEB_CODE="$(wait_for_http 'http://127.0.0.1:5173/' '200' 20 1 || true)"

echo "installed $API_LABEL and $WEB_LABEL"
echo "api_status=$API_CODE web_status=$WEB_CODE"
echo "url_local=http://127.0.0.1:5173"
echo "url_lan=http://$(ipconfig getifaddr en0 2>/dev/null || echo '<your-lan-ip>'):5173"
echo "api_log=$PROJECT_DIR/tmp/dashboard-api.log"
echo "web_log=$PROJECT_DIR/tmp/dashboard-web.log"
