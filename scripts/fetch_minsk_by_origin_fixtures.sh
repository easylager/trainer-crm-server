#!/usr/bin/env bash
# Save ledlife/junost origin HTML through local BY egress (tinyproxy). Run from repo root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .local/by-egress-proxy.env 2>/dev/null || true
: "${BY_EGRESS_LOCAL_PASSWORD:?run: bash scripts/local_by_egress_proxy.sh setup}"
PROXY="http://byegress:${BY_EGRESS_LOCAL_PASSWORD}@127.0.0.1:${BY_EGRESS_LOCAL_PORT:-8888}"

fetch() {
  local url="$1" out="$2"
  curl -fsS --max-time 30 --proxy "$PROXY" "$url" -o "$out"
  if grep -q '403 Forbidden' "$out" 2>/dev/null; then
    echo "fetch_minsk_by_origin_fixtures: 403 for $url — VPN off? tinyproxy running?" >&2
    exit 1
  fi
  echo "wrote $out ($(wc -c <"$out") bytes)"
}

fetch "https://ledlife.by/massovye_kataniya/" "$ROOT/data/fixtures/minsk-ledlife/massovye_kataniya-live.html"
fetch "https://ledlife.by/stoimost_uslug/" "$ROOT/data/fixtures/minsk-ledlife/stoimost_uslug-live.html"
fetch "https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/" "$ROOT/data/fixtures/minsk-junost/junost-origin-live.html"
