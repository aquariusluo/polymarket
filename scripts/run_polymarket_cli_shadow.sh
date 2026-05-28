#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="/Users/aquariusluo/projects/polymarket"
LOCK_DIR="$PROJECT_DIR/tmp/polymarket-cli-shadow.lock"
PID_FILE="$LOCK_DIR/pid"

mkdir -p "$PROJECT_DIR/tmp"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [[ -f "$PID_FILE" ]] \
    && kill -0 "$(cat "$PID_FILE")" 2>/dev/null \
    && ps -p "$(cat "$PID_FILE")" -o command= | grep -Fq "run_polymarket_cli_shadow.sh"; then
    echo "shadow-run already active; skipping $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  fi
  echo "removing stale shadow-run lock $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo "$$" > "$PID_FILE"
trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$PROJECT_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DATA_SOURCE="polymarket_cli"
export DB_PATH="${DB_PATH:-data/app.db}"
export TRADE_FETCH_LIMIT="${TRADE_FETCH_LIMIT:-5}"
export RUN_LOOP_MAX_ITERATIONS="${RUN_LOOP_MAX_ITERATIONS:-1}"
export RUN_LOOP_SLEEP_SECONDS="${RUN_LOOP_SLEEP_SECONDS:-0}"
export PYTHONUNBUFFERED="1"

exec "$PROJECT_DIR/.venv/bin/python" -m app.main shadow-run
