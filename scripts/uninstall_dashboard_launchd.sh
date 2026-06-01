#!/usr/bin/env zsh
set -euo pipefail

API_LABEL="com.aquariusluo.polymarket.dashboard-api"
WEB_LABEL="com.aquariusluo.polymarket.dashboard-web"
TARGET_DIR="$HOME/Library/LaunchAgents"

for label in "$API_LABEL" "$WEB_LABEL"; do
  target_plist="$TARGET_DIR/$label.plist"
  launchctl bootout "gui/$(id -u)" "$target_plist" 2>/dev/null || true
  rm -f "$target_plist"
done

for port in 8000 5173; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "warning: port $port is still listening after uninstall"
  fi
done

echo "uninstalled $API_LABEL and $WEB_LABEL"
