#!/bin/bash
# Launch the GASL/RAG visualization server.
#
# Usage:
#   ./launch_viz.sh                    # auto-detect a sample graph, bind to localhost
#   ./launch_viz.sh <graph.graphml>    # load a specific graph
#
# Environment overrides:
#   HOST=0.0.0.0   bind to all interfaces (e.g. for Tailscale access)
#   PORT=5050      change the port
#   PYTHON=...     pin a specific interpreter; defaults to .venv if present

set -e
cd "$(dirname "$0")"

# Pick a Python: prefer .venv, fall back to system python3
if [ -z "$PYTHON" ]; then
    if [ -x ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="$(command -v python3)"
    fi
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5050}"

echo "Python:   $PYTHON"
echo "Bind:     $HOST:$PORT"

if [ -n "$1" ]; then
    echo "Graph:    $1"
    exec "$PYTHON" -m visualization.examples.demo --host "$HOST" --port "$PORT" "$1"
else
    echo "Graph:    auto-detect"
    exec "$PYTHON" -m visualization.examples.demo --host "$HOST" --port "$PORT"
fi
