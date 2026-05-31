#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.aquariusluo.polymarket.cli-shadow"
TMP_DIR="$PROJECT_DIR/tmp"
DB_PATH="$PROJECT_DIR/data/app.db"
MONITOR_LOG="$TMP_DIR/polymarket-cli-monitor.jsonl"
OUT_LOG="$TMP_DIR/polymarket-cli-shadow.out.log"
ERR_LOG="$TMP_DIR/polymarket-cli-shadow.err.log"

NOW_EPOCH="$(date +%s)"
FAIL=0
WARN=0
OUTPUT_JSON=0
if [[ "${1:-}" == "--json" ]]; then
  OUTPUT_JSON=1
fi
CHECK_LINES=()
PYTHON_BIN="$(command -v python3 || true)"
PYTHON_MISSING=0
if [[ -z "$PYTHON_BIN" && -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_MISSING=1
fi

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
  echo "Polymarket Shadow Healthcheck"
  echo "project=$PROJECT_DIR"
  echo "time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
fi

if [[ "$PYTHON_MISSING" -eq 1 ]]; then
  print_check "FAIL" "Python" "neither python3 nor .venv/bin/python found"
  WARN=$((WARN + 1))
  FAIL=$((FAIL + 1))
fi

# 1) launchd status
LAUNCH_OUT="$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null || true)"
if [[ -z "$LAUNCH_OUT" ]]; then
  print_check "WARN" "LaunchAgent" "launchctl entry not found"
  WARN=$((WARN + 1))
else
  LAST_EXIT="$(echo "$LAUNCH_OUT" | sed -nE 's/^[[:space:]]*last exit code = ([0-9-]+).*/\1/p' | head -n1)"
  STATE="$(echo "$LAUNCH_OUT" | sed -nE 's/^[[:space:]]*state = (.*)$/\1/p' | head -n1)"
  STATE="${STATE:-unknown}"
  LAST_EXIT="${LAST_EXIT:-unknown}"
  if [[ "$STATE" != "running" ]]; then
    if [[ "$LAST_EXIT" == "0" || "$LAST_EXIT" == "unknown" ]]; then
      print_check "PASS" "LaunchAgent" "state=$STATE (interval mode), last_exit_code=$LAST_EXIT"
    else
      print_check "WARN" "LaunchAgent" "state=$STATE, last_exit_code=$LAST_EXIT"
      WARN=$((WARN + 1))
    fi
  elif [[ "$LAST_EXIT" != "0" && "$LAST_EXIT" != "unknown" ]]; then
    print_check "WARN" "LaunchAgent" "state=$STATE, last_exit_code=$LAST_EXIT"
    WARN=$((WARN + 1))
  else
    print_check "PASS" "LaunchAgent" "state=$STATE, last_exit_code=$LAST_EXIT"
  fi
fi

# 2) monitor log freshness
if [[ ! -f "$MONITOR_LOG" ]]; then
  print_check "WARN" "MonitorLog" "missing $MONITOR_LOG"
  WARN=$((WARN + 1))
else
  LAST_TS="$(tail -n 200 "$MONITOR_LOG" | rg '"timestamp"' | tail -n1 | sed -n 's/.*"timestamp": *"\([^"]*\)".*/\1/p' || true)"
  if [[ -z "$LAST_TS" ]]; then
    print_check "WARN" "MonitorLog" "no parseable timestamp found"
    WARN=$((WARN + 1))
  elif [[ "$PYTHON_MISSING" -eq 1 ]]; then
    print_check "WARN" "MonitorLog" "python unavailable; freshness check skipped"
    WARN=$((WARN + 1))
  else
    LAST_EPOCH="$("$PYTHON_BIN" - <<'PY' "$LAST_TS"
import datetime, sys
ts = sys.argv[1]
try:
    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    print(int(dt.timestamp()))
except Exception:
    print(-1)
PY
)"
    if [[ "$LAST_EPOCH" -lt 0 ]]; then
      print_check "WARN" "MonitorLog" "unparseable timestamp=$LAST_TS"
      WARN=$((WARN + 1))
    else
      AGE_MIN=$(( (NOW_EPOCH - LAST_EPOCH) / 60 ))
      if [[ "$AGE_MIN" -gt 10 ]]; then
        print_check "WARN" "MonitorLog" "last event is ${AGE_MIN}m old"
        WARN=$((WARN + 1))
      else
        print_check "PASS" "MonitorLog" "last event age=${AGE_MIN}m"
      fi
    fi
  fi
fi

# 3) recent failures
if [[ -f "$MONITOR_LOG" ]]; then
  RECENT_FAILS="$(tail -n 500 "$MONITOR_LOG" | rg -c 'monitor_failed|step_timeout|daily_prune_failed|processing_error' || true)"
  RECENT_FAILS="${RECENT_FAILS:-0}"
  if [[ "$RECENT_FAILS" -gt 5 ]]; then
    print_check "WARN" "FailureBurst" "recent_fail_events=$RECENT_FAILS (>5)"
    WARN=$((WARN + 1))
  else
    print_check "PASS" "FailureBurst" "recent_fail_events=$RECENT_FAILS"
  fi
else
  print_check "WARN" "FailureBurst" "monitor log missing"
  WARN=$((WARN + 1))
fi

# 4) db progression snapshot
if [[ ! -f "$DB_PATH" ]]; then
  print_check "WARN" "Database" "missing $DB_PATH"
  WARN=$((WARN + 1))
elif [[ "$PYTHON_MISSING" -eq 1 ]]; then
  print_check "WARN" "Database" "python unavailable; db checks skipped"
  WARN=$((WARN + 1))
else
  DB_STATS="$("$PYTHON_BIN" - <<'PY' "$DB_PATH"
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db, timeout=3)
cur = conn.cursor()
queries = [
("job_runs_24h", "select count(*) from job_runs where started_at >= datetime('now','-1 day')"),
("leaders", "select count(*) from leaders"),
("signals", "select count(*) from signals"),
("sim_orders", "select count(*) from sim_orders"),
("positions", "select count(*) from positions"),
]
for name, q in queries:
    try:
        cur.execute(q)
        print(f"{name}={cur.fetchone()[0]}")
    except Exception:
        print(f"{name}=ERR")
conn.close()
PY
)"
  if [[ "$OUTPUT_JSON" -eq 0 ]]; then
    echo "$DB_STATS" | sed 's/^/[INFO] DB - /'
  fi
  JOBS_24H="$(echo "$DB_STATS" | sed -n 's/^job_runs_24h=\(.*\)$/\1/p')"
  if [[ -n "$JOBS_24H" && "$JOBS_24H" != "ERR" ]]; then
    if [[ "$JOBS_24H" -lt 200 ]]; then
      print_check "WARN" "Database" "job_runs_24h=$JOBS_24H (<200)"
      WARN=$((WARN + 1))
    else
      print_check "PASS" "Database" "job_runs_24h=$JOBS_24H"
    fi
  else
    print_check "WARN" "Database" "cannot read job_runs_24h"
    WARN=$((WARN + 1))
  fi
fi

# 5) log size control
MAX_BYTES=$((200 * 1024 * 1024))
for f in "$OUT_LOG" "$ERR_LOG" "$MONITOR_LOG"; do
  if [[ -f "$f" ]]; then
    SIZE="$(stat -f%z "$f" 2>/dev/null || echo 0)"
    if [[ "$SIZE" -gt "$MAX_BYTES" ]]; then
      print_check "WARN" "LogSize" "$(basename "$f") size=$SIZE (>200MB)"
      WARN=$((WARN + 1))
    else
      print_check "PASS" "LogSize" "$(basename "$f") size=$SIZE"
    fi
  else
    print_check "WARN" "LogSize" "$(basename "$f") missing"
    WARN=$((WARN + 1))
  fi
done

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
  if [[ "$PYTHON_MISSING" -eq 1 ]]; then
    printf '{"project":"%s","summary":"%s","fail":%d,"warn":%d,"checks":[]}\n' \
      "$PROJECT_DIR" "$SUMMARY_STATUS" "$FAIL" "$WARN"
  else
    "$PYTHON_BIN" - "$PROJECT_DIR" "$SUMMARY_STATUS" "$FAIL" "$WARN" "${CHECK_LINES[@]}" <<'PY'
import json, sys
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
  fi
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
