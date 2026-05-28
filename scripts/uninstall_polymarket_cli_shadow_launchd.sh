#!/usr/bin/env zsh
set -euo pipefail

LABEL="com.aquariusluo.polymarket.cli-shadow"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
rm -f "$TARGET_PLIST"

echo "uninstalled $LABEL"
