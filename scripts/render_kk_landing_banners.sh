#!/usr/bin/env bash
# Баннеры лендинга /kk из design/kk-landing-banners/banners.html: 400×320 CSS, рендер ×3 → webp 1200×960.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
SRC="$PWD/design/kk-landing-banners/banners.html"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for name in friends-league favorite-teams monthly-crowns; do
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=3 \
    --window-size=400,320 --virtual-time-budget=4000 --user-data-dir="$TMP/profile" --screenshot="$TMP/$name.png" "file://$SRC#$name" 2>/dev/null
  cwebp -quiet -q 90 "$TMP/$name.png" -o "static/landing/kk/$name.webp"
done
