#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

read_token_and_url() {
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path.home()/".claude"/"settings.json"
data = json.loads(p.read_text())
helper = data.get("apiKeyHelper", "")
token = helper[5:] if helper.startswith("echo ") else ""
base = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
if base.endswith("/argoapi"):
    base = base[:-8]
if base and not base.endswith("/v1"):
    base = base.rstrip("/") + "/v1"
print(token)
print(base)
PY
}

mapfile -t SHIM < <(read_token_and_url)
export NANOGRAPHRAG_LLM_TRANSPORT=shim
export NANOGRAPHRAG_SHIM_TOKEN="${SHIM[0]}"
export NANOGRAPHRAG_SHIM_URL="${SHIM[1]}"

exec "$@"
