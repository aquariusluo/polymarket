#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_CONF="$PROJECT_DIR/launchd/com.aquariusluo.polymarket.cli-shadow.newsyslog.conf"
TARGET_CONF="/etc/newsyslog.d/com.aquariusluo.polymarket.cli-shadow.conf"
RENDERED_CONF="$PROJECT_DIR/tmp/com.aquariusluo.polymarket.cli-shadow.newsyslog.rendered.conf"

mkdir -p "$PROJECT_DIR/tmp"
sed "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" "$SOURCE_CONF" > "$RENDERED_CONF"

echo "rendered=$RENDERED_CONF"
echo "installing to $TARGET_CONF (requires sudo)"
sudo install -m 644 "$RENDERED_CONF" "$TARGET_CONF"

echo "installed $TARGET_CONF"
echo "validate with: sudo newsyslog -n -f /etc/newsyslog.conf"
echo "force rotate once with: sudo newsyslog -F /etc/newsyslog.conf"
