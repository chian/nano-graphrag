#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <demo-id> [output.mp4] [port]"
  exit 1
fi

DEMO_ID="$1"
OUTPUT="${2:-demo-${DEMO_ID}.mp4}"
PORT="${3:-5052}"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
RES="${RES:-1600x900}"
DURATION="${DURATION:-12}"

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&replay=1&mode=gasl"

cleanup() {
  if [[ -n "${CHROME_PID:-}" ]]; then kill "${CHROME_PID}" 2>/dev/null || true; fi
  if [[ -n "${XVFB_PID:-}" ]]; then kill "${XVFB_PID}" 2>/dev/null || true; fi
}
trap cleanup EXIT

Xvfb "${DISPLAY_NUM}" -screen 0 "${RES}x24" -nolisten tcp >/tmp/xvfb-demo.log 2>&1 &
XVFB_PID=$!
sleep 1

DISPLAY="${DISPLAY_NUM}" chromium \
  --no-first-run \
  --disable-infobars \
  --window-size="${RES/x/,}" \
  "${URL}" >/tmp/chromium-demo.log 2>&1 &
CHROME_PID=$!

sleep 2

ffmpeg -y \
  -video_size "${RES}" \
  -f x11grab \
  -i "${DISPLAY_NUM}.0" \
  -t "${DURATION}" \
  -c:v libx264 \
  -preset veryfast \
  -crf 23 \
  -pix_fmt yuv420p \
  "${OUTPUT}"

echo "Wrote ${OUTPUT}"
