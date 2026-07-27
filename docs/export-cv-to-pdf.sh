#!/usr/bin/env bash
# Generates PDFs from the four canonical CV HTML files using Chrome headless.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CVS=(
  "cv-max-vasilenko-techlead-python-ru-2026"
  "cv-max-vasilenko-techlead-python-en-2026"
  "cv-max-vasilenko-senior-python-ru-2026"
  "cv-max-vasilenko-senior-python-en-2026"
)

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

for base in "${CVS[@]}"; do
  SRC="${SCRIPT_DIR}/${base}.html"
  OUT="${SCRIPT_DIR}/${base}.pdf"
  if [[ ! -f "$SRC" ]]; then
    echo "Source not found: $SRC" >&2
    exit 1
  fi
  echo "Writing: $OUT"
  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --no-pdf-header-footer \
    --print-to-pdf="$OUT" \
    "file://${SRC}"
done

echo "Done."
