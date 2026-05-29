#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <demo-id> [output.mp4] [port]"
  exit 1
fi

DEMO_ID="$1"
OUTPUT="${2:-tutorial-${DEMO_ID}.mp4}"
PORT="${3:-5056}"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
RES="${RES:-1600x900}"
USER_DATA_DIR="$(mktemp -d /tmp/nanographrag-tutorial.XXXXXX)"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
FULL_GRAPH="${DEMO_FULL_GRAPH:-$ROOT_DIR/haiqu_graphs/v1/haiqu_engineering_controls/haiqu_engineering_controls_graph.graphml}"
SUBSET_GRAPH="${DEMO_SUBSET_GRAPH:-$ROOT_DIR/.viz_cache/graphs/haiqu_engineering_controls_topdeg1500.graphml}"

DURATION="$($PYTHON - <<PY
from visualization.tutorial_mode.tutorial_demo_catalog import get_demo
demo=get_demo("$DEMO_ID")
dur=sum(step.get("delay_ms",0) for step in demo["replay"])/1000.0 + 6.0
print(int(round(dur)))
PY
)"

cleanup() {
  if [[ -n "${CHROME_PID:-}" ]]; then kill "${CHROME_PID}" 2>/dev/null || true; fi
  if [[ -n "${XVFB_PID:-}" ]]; then kill "${XVFB_PID}" 2>/dev/null || true; fi
  if [[ -n "${SERVER_PID:-}" ]]; then kill "${SERVER_PID}" 2>/dev/null || true; fi
  if [[ -n "${USER_DATA_DIR:-}" && -d "${USER_DATA_DIR}" ]]; then rm -rf "${USER_DATA_DIR}" 2>/dev/null || true; fi
}
trap cleanup EXIT

Xvfb "${DISPLAY_NUM}" -screen 0 "${RES}x24" -nolisten tcp >/tmp/xvfb-tutorial.log 2>&1 &
XVFB_PID=$!
sleep 1

cd "$ROOT_DIR"
setsid "$PYTHON" -m visualization.tutorial_mode.tutorial_server \
  "$SUBSET_GRAPH" \
  --full-graph-path "$FULL_GRAPH" \
  --host 127.0.0.1 \
  --port "$PORT" \
  >/tmp/tutorial-server.log 2>&1 &
SERVER_PID=$!

for _ in 1 2 3 4 5 6 7 8; do
  if ss -ltn "( sport = :${PORT} )" | tail -n +2 | grep -q ":${PORT}"; then
    break
  fi
  sleep 1
done

URL="http://127.0.0.1:${PORT}/?demo=${DEMO_ID}&replay=1&cinematic=1"

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
  --window-size="${RES/x/,}" >/tmp/chromium-tutorial.log 2>&1 &
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
