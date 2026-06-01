#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
TMP_DIR="$PROJECT_DIR/tmp"
API_LABEL="com.aquariusluo.polymarket.dashboard-api"
WEB_LABEL="com.aquariusluo.polymarket.dashboard-web"
API_LOG="$TMP_DIR/dashboard-api.log"
WEB_LOG="$TMP_DIR/dashboard-web.log"

FAIL=0
WARN=0
OUTPUT_JSON=0
if [[ "${1:-}" == "--json" ]]; then
  OUTPUT_JSON=1
fi
CHECK_LINES=()

print_check() {
  local level="$1"
  local title="$2"
  local detail="$3"
  CHECK_LINES+=("$level|$title|$detail")
  if [[ "$OUTPUT_JSON" -eq 0 ]]; then
    echo "[$level] $title - $detail"
  fi
}

if [[ "$OUTPUT_JSON" -eq 0 ]]; then
  echo "Polymarket Dashboard Healthcheck"
  echo "project=$PROJECT_DIR"
  echo "time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
fi

check_launchd() {
  local label="$1"
  local name="$2"
  local out
  out="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null || true)"
  if [[ -z "$out" ]]; then
    print_check "FAIL" "$name LaunchAgent" "not loaded: $label"
    FAIL=$((FAIL + 1))
    return
  fi
  local state
  state="$(echo "$out" | sed -nE 's/^[[:space:]]*state = (.*)$/\1/p' | head -n1)"
  state="${state:-unknown}"
  if [[ "$state" != "running" ]]; then
    print_check "WARN" "$name LaunchAgent" "state=$state"
    WARN=$((WARN + 1))
  else
    print_check "PASS" "$name LaunchAgent" "state=running"
  fi
}

check_http() {
  local url="$1"
  local title="$2"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
  if [[ "$code" == "200" ]]; then
    print_check "PASS" "$title" "status=200"
  elif [[ "$code" == "000" ]]; then
    print_check "FAIL" "$title" "status=000 (connection failed)"
    FAIL=$((FAIL + 1))
  else
    print_check "WARN" "$title" "status=$code"
    WARN=$((WARN + 1))
  fi
}

check_port() {
  local port="$1"
  local title="$2"
  local out
  out="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$out" ]]; then
    print_check "FAIL" "$title" "port $port not listening"
    FAIL=$((FAIL + 1))
  else
    local proc
    proc="$(echo "$out" | awk 'NR>1{print $1"/"$2; exit}')"
    print_check "PASS" "$title" "listening on $port ($proc)"
  fi
}

check_log_tail() {
  local file="$1"
  local title="$2"
  local pattern="$3"
  if [[ ! -f "$file" ]]; then
    print_check "WARN" "$title" "missing $file"
    WARN=$((WARN + 1))
    return
  fi
  local size
  size="$(stat -f%z "$file" 2>/dev/null || echo 0)"
  if [[ "$size" -eq 0 ]]; then
    print_check "WARN" "$title" "empty log"
    WARN=$((WARN + 1))
    return
  fi
  local err_count
  err_count="$(tail -n 120 "$file" | rg -c "$pattern" || true)"
  err_count="${err_count:-0}"
  if [[ "$err_count" -gt 0 ]]; then
    print_check "WARN" "$title" "recent error-like lines=$err_count"
    WARN=$((WARN + 1))
  else
    print_check "PASS" "$title" "no recent error-like lines"
  fi
}

check_launchd "$API_LABEL" "API"
check_launchd "$WEB_LABEL" "Web"
check_port 8000 "API Port"
check_port 5173 "Web Port"
check_http "http://127.0.0.1:8000/api/overview" "API Endpoint"
check_http "http://127.0.0.1:5173/" "Web Local URL"
check_http "http://127.0.0.1:5173/api/overview" "Web Proxy /api"
check_log_tail "$API_LOG" "API Log" 'Traceback|ERROR:|Exception|Address already in use|ModuleNotFoundError|RuntimeError'
check_log_tail "$WEB_LOG" "Web Log" 'ECONNREFUSED|ECONNRESET|ENOTFOUND|ERR_MODULE_NOT_FOUND|failed to load|http proxy error|error when starting dev server'

SUMMARY_STATUS="PASS"
EXIT_CODE=0
if [[ "$FAIL" -gt 0 ]]; then
  SUMMARY_STATUS="FAIL"
  EXIT_CODE=2
elif [[ "$WARN" -gt 0 ]]; then
  SUMMARY_STATUS="PASS_WITH_WARNINGS"
  EXIT_CODE=1
fi

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  python3 - "$PROJECT_DIR" "$SUMMARY_STATUS" "$FAIL" "$WARN" "${CHECK_LINES[@]}" <<'PY'
import json
import sys

project = sys.argv[1]
summary = sys.argv[2]
fail = int(sys.argv[3])
warn = int(sys.argv[4])
checks = []
for raw in sys.argv[5:]:
    level, title, detail = raw.split("|", 2)
    checks.append({"level": level, "title": title, "detail": detail})
print(json.dumps({
    "project": project,
    "summary": summary,
    "fail": fail,
    "warn": warn,
    "checks": checks,
}, ensure_ascii=False))
PY
else
  echo
  if [[ "$SUMMARY_STATUS" == "FAIL" ]]; then
    echo "SUMMARY: FAIL=$FAIL WARN=$WARN"
  elif [[ "$SUMMARY_STATUS" == "PASS_WITH_WARNINGS" ]]; then
    echo "SUMMARY: PASS with WARN=$WARN"
  else
    echo "SUMMARY: PASS"
  fi
fi

exit "$EXIT_CODE"
