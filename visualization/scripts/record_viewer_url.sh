#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <viewer-url> [output.mp4]"
  exit 1
fi

URL="$1"
OUTPUT="${2:-demo.mp4}"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
RES="${RES:-1600x900}"
DURATION="${DURATION:-18}"
USER_DATA_DIR="$(mktemp -d /tmp/nanographrag-chrome.XXXXXX)"

cleanup() {
  if [[ -n "${CHROME_PID:-}" ]]; then kill "${CHROME_PID}" 2>/dev/null || true; fi
  if [[ -n "${XVFB_PID:-}" ]]; then kill "${XVFB_PID}" 2>/dev/null || true; fi
  if [[ -n "${USER_DATA_DIR:-}" && -d "${USER_DATA_DIR}" ]]; then rm -rf "${USER_DATA_DIR}" 2>/dev/null || true; fi
}
trap cleanup EXIT

Xvfb "${DISPLAY_NUM}" -screen 0 "${RES}x24" -nolisten tcp >/tmp/xvfb-demo.log 2>&1 &
XVFB_PID=$!
sleep 1

DISPLAY="${DISPLAY_NUM}" chromium \
  --no-first-run \
  --disable-infobars \
  --app="${URL}" \
  --kiosk \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --ozone-platform=x11 \
  --user-data-dir="${USER_DATA_DIR}" \
  --window-size="${RES/x/,}" >/tmp/chromium-demo.log 2>&1 &
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
