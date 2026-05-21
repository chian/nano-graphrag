#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <direct|shim> <command...>" >&2
  exit 2
fi

MODE="$1"
shift

case "$MODE" in
  direct)
    unset NANOGRAPHRAG_LLM_TRANSPORT
    unset NANOGRAPHRAG_SHIM_TOKEN
    unset NANOGRAPHRAG_SHIM_URL
    ;;
  shim)
    mapfile -t SHIM < <(
      python3 - <<'PY'
import json
from pathlib import Path
p = Path.home()/".claude"/"settings.json"
data = json.loads(p.read_text())
base = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
if base.endswith("/argoapi"):
    base = base[:-8]
if base and not base.endswith("/v1"):
    base = base.rstrip("/") + "/v1"
print(base)
PY
    )
    export NANOGRAPHRAG_LLM_TRANSPORT=shim
    export NANOGRAPHRAG_SHIM_URL="${SHIM[0]}"
    ;;
  *)
    echo "Unknown transport mode: $MODE" >&2
    exit 2
    ;;
esac

exec "$@"
