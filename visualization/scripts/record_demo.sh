#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <demo-id> [output.mp4] [port] [compare|gasl]"
  exit 1
fi

DEMO_ID="$1"
OUTPUT="${2:-demo-${DEMO_ID}.mp4}"
PORT="${3:-5050}"
RUN_MODE="${4:-compare}"

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ "${RUN_MODE}" == "gasl" ]]; then
  URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&replay=1&mode=gasl&cinematic=1"
else
  URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&compare=1&cinematic=1"
fi
exec "${ROOT_DIR}/visualization/scripts/record_viewer_url.sh" "${URL}" "${OUTPUT}"
