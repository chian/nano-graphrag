#!/usr/bin/env bash
set -euo pipefail

unset NANOGRAPHRAG_LLM_TRANSPORT
unset NANOGRAPHRAG_SHIM_TOKEN
unset NANOGRAPHRAG_SHIM_URL

exec "$@"
