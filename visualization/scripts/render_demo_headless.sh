#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <demo-id> [output.mp4] [port] [gasl|compare]"
  exit 1
fi

DEMO_ID="$1"
OUTPUT="${2:-demo-${DEMO_ID}.mp4}"
PORT="${3:-5050}"
RUN_MODE="${4:-gasl}"
WINDOW="${WINDOW:-1600,900}"
TOTAL_MS="${TOTAL_MS:-18000}"
INTERVAL_MS="${INTERVAL_MS:-750}"

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FPS=$(awk "BEGIN { printf \"%.6f\", 1000 / ${INTERVAL_MS} }")
FRAMES=$(( TOTAL_MS / INTERVAL_MS ))
TMP_DIR="$(mktemp -d /tmp/nanographrag-demo-frames.XXXXXX)"

cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

if [[ "${RUN_MODE}" == "compare" ]]; then
  URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&compare=1&cinematic=1"
else
  URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&replay=1&mode=gasl&cinematic=1"
fi

echo "Rendering ${DEMO_ID} (${FRAMES} frames at every ${INTERVAL_MS}ms)"

for ((i=0; i<FRAMES; i++)); do
  BUDGET=$(( (i + 1) * INTERVAL_MS ))
  FRAME_PATH="${TMP_DIR}/frame_$(printf '%03d' "${i}").png"
  PROFILE_DIR="$(mktemp -d /tmp/nanographrag-chrome.XXXXXX)"
  /snap/bin/chromium \
    --headless \
    --no-sandbox \
    --disable-gpu \
    --ozone-platform=x11 \
    --user-data-dir="${PROFILE_DIR}" \
    --window-size="${WINDOW}" \
    --virtual-time-budget="${BUDGET}" \
    --screenshot="${FRAME_PATH}" \
    "${URL}" >/dev/null 2>&1
  rm -rf "${PROFILE_DIR}"
done

ffmpeg -y \
  -framerate "${FPS}" \
  -i "${TMP_DIR}/frame_%03d.png" \
  -c:v libx264 \
  -preset slow \
  -crf 20 \
  -pix_fmt yuv420p \
  "${OUTPUT}" >/dev/null 2>&1

echo "Wrote ${OUTPUT}"
