#!/usr/bin/env bash
# Generates PDF from docs/cv-max-vasilenko-fintech-2026.html using Chrome/Chromium headless.
# Requires Google Chrome (macOS default path below) or chromium in PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/cv-max-vasilenko-fintech-2026.html"
OUT="${SCRIPT_DIR}/cv-max-vasilenko-fintech-2026.pdf"

if [[ ! -f "$SRC" ]]; then
  echo "Source not found: $SRC" >&2
  exit 1
fi

# file:// URL must be absolute
SRC_URL="file://${SRC}"

pick_chrome() {
  if [[ "$(uname)" == "Darwin" ]]; then
    local MAC_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if [[ -x "$MAC_CHROME" ]]; then
      echo "$MAC_CHROME"
      return 0
    fi
  fi
  if command -v google-chrome-stable &>/dev/null; then
    echo "google-chrome-stable"
    return 0
  fi
  if command -v chromium &>/dev/null; then
    echo "chromium"
    return 0
  fi
  if command -v chromium-browser &>/dev/null; then
    echo "chromium-browser"
    return 0
  fi
  return 1
}

CHROME="$(pick_chrome)" || {
  echo "Chrome/Chromium not found. Install Chrome or use: open the HTML → Print → Save as PDF." >&2
  exit 1
}

echo "Using: $CHROME"
echo "Writing: $OUT"

exec "$CHROME" \
  --headless=new \
  --disable-gpu \
  --no-pdf-header-footer \
  --print-to-pdf="$OUT" \
  "$SRC_URL"

echo "Done."
