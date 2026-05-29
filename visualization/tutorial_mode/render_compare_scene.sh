#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <scene-id> [output.mp4] [port]"
  exit 1
fi

SCENE_ID="$1"
OUTPUT="${2:-${SCENE_ID}.mp4}"
PORT="${3:-5058}"
DISPLAY_NUM="${DISPLAY_NUM:-:98}"
RES="${RES:-1600x900}"
USER_DATA_DIR="$(mktemp -d /tmp/nanographrag-compare.XXXXXX)"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"

DURATION="$($PYTHON - <<PY
from visualization.tutorial_mode.compare_scene_catalog import get_scene
scene = get_scene("$SCENE_ID")
dur = sum(frame.get("duration_ms", 0) for frame in scene["frames"]) / 1000.0 + 2.5
print(int(round(dur)))
PY
)"

cleanup() {
  if [[ -n "${CHROME_PID:-}" ]]; then kill "${CHROME_PID}" 2>/dev/null || true; fi
  if [[ -n "${XVFB_PID:-}" ]]; then kill "${XVFB_PID}" 2>/dev/null || true; fi
  if [[ -n "${SERVER_PID:-}" ]]; then kill "${SERVER_PID}" 2>/dev/null || true; fi
  rm -rf "${USER_DATA_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

Xvfb "${DISPLAY_NUM}" -screen 0 "${RES}x24" -nolisten tcp >/tmp/xvfb-compare.log 2>&1 &
XVFB_PID=$!
sleep 1

cd "$ROOT_DIR"
setsid "$PYTHON" -m visualization.tutorial_mode.compare_scene_server \
  --host 127.0.0.1 \
  --port "$PORT" \
  >/tmp/compare-server.log 2>&1 &
SERVER_PID=$!

for _ in 1 2 3 4 5 6 7 8; do
  if ss -ltn "( sport = :${PORT} )" | tail -n +2 | grep -q ":${PORT}"; then
    break
  fi
  sleep 1
done

URL="http://127.0.0.1:${PORT}/?scene=${SCENE_ID}"

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
  --window-size="${RES/x/,}" >/tmp/chromium-compare.log 2>&1 &
CHROME_PID=$!

sleep 2

ffmpeg -y \
  -nostdin \
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
