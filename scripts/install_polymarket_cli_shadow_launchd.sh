#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="/Users/aquariusluo/projects/polymarket"
LABEL="com.aquariusluo.polymarket.cli-shadow"
SOURCE_PLIST="$PROJECT_DIR/launchd/$LABEL.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$LABEL.plist"

mkdir -p "$TARGET_DIR" "$PROJECT_DIR/tmp"
chmod +x "$PROJECT_DIR/scripts/run_polymarket_cli_shadow.sh"
chmod +x "$PROJECT_DIR/scripts/run_polymarket_cli_monitor.py"
cp "$SOURCE_PLIST" "$TARGET_PLIST"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "installed $LABEL"
echo "plist=$TARGET_PLIST"
echo "stdout=$PROJECT_DIR/tmp/polymarket-cli-shadow.out.log"
echo "stderr=$PROJECT_DIR/tmp/polymarket-cli-shadow.err.log"
