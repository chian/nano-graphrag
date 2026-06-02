#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <run-id> <qid> [graph-path] [full-graph-path] [output.mp4] [port]"
  exit 1
fi

RUN_ID="$1"
QID="$2"
GRAPH_PATH="${3:-}"
FULL_GRAPH_PATH="${4:-}"
OUTPUT="${5:-demo-${RUN_ID}-${QID}.mp4}"
PORT="${6:-5050}"

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
QUERY="$(
  RUN_ID="$RUN_ID" \
  QID="$QID" \
  GRAPH_PATH="$GRAPH_PATH" \
  FULL_GRAPH_PATH="$FULL_GRAPH_PATH" \
  python3 - <<'PY'
import os
from urllib.parse import urlencode

params = {
    "run_id": os.environ["RUN_ID"],
    "qid": os.environ["QID"],
    "replay": "1",
    "mode": "gasl",
    "cinematic": "1",
}
graph_path = os.environ.get("GRAPH_PATH", "").strip()
full_graph_path = os.environ.get("FULL_GRAPH_PATH", "").strip()
if graph_path:
    params["graph_path"] = graph_path
if full_graph_path:
    params["full_graph_path"] = full_graph_path
print(urlencode(params))
PY
)"
URL="http://127.0.0.1:${PORT}/?${QUERY}"

exec "${ROOT_DIR}/visualization/scripts/record_viewer_url.sh" "${URL}" "${OUTPUT}"
