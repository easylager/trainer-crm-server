#!/usr/bin/env bash
# Back-compat wrapper — stops all dev tunnels.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/dev_stop_tunnel.sh"
