#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${PYTHON:-}" ]; then
    if [ -x ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="$(command -v python3)"
    fi
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5050}"
FULL_GRAPH="${DEMO_FULL_GRAPH:-haiqu_graphs/v1/haiqu_engineering_controls/haiqu_engineering_controls_graph.graphml}"
SUBSET_MAX_NODES="${DEMO_SUBSET_MAX_NODES:-1500}"
SUBSET_GRAPH="${DEMO_SUBSET_GRAPH:-.viz_cache/graphs/haiqu_engineering_controls_topdeg${SUBSET_MAX_NODES}.graphml}"

mkdir -p .viz_cache/graphs .viz_runs

if [ ! -f "$FULL_GRAPH" ]; then
    echo "Missing full graph: $FULL_GRAPH" >&2
    exit 1
fi

generate_subset() {
    FULL_GRAPH="$FULL_GRAPH" SUBSET_GRAPH="$SUBSET_GRAPH" DEMO_SUBSET_MAX_NODES="$SUBSET_MAX_NODES" "$PYTHON" - <<'PY'
from pathlib import Path
import os
import networkx as nx
from visualization.graph_loader import GraphLoader
full_graph = Path(os.environ["FULL_GRAPH"])
subset_graph = Path(os.environ["SUBSET_GRAPH"])
max_nodes = int(os.environ["DEMO_SUBSET_MAX_NODES"])
loader = GraphLoader(str(full_graph))
subset = loader.top_degree_subgraph(max_nodes)
subset_graph.parent.mkdir(parents=True, exist_ok=True)
nx.write_graphml(subset, subset_graph)
print(f"subset_nodes={subset.number_of_nodes()} subset_edges={subset.number_of_edges()} path={subset_graph}")
PY
}

if [ ! -f "$SUBSET_GRAPH" ] || [ "$FULL_GRAPH" -nt "$SUBSET_GRAPH" ]; then
    echo "Generating demo subset graph: $SUBSET_GRAPH"
    generate_subset
fi

if [ -f .viz_runs/demo_viz.pid ]; then
    old_pid="$(cat .viz_runs/demo_viz.pid || true)"
    if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
        kill "${old_pid}" || true
        sleep 1
    fi
fi

pkill -f "visualization.examples.demo --no-debug --host ${HOST} --port ${PORT}" || true
sleep 1

run_id="demo_viz_$(date +%Y%m%d-%H%M%S)"
log=".viz_runs/${run_id}.log"

setsid "$PYTHON" -m visualization.examples.demo \
    --no-debug \
    --host "$HOST" \
    --port "$PORT" \
    "$SUBSET_GRAPH" \
    > "$log" 2>&1 < /dev/null &

pid="$!"
echo "$pid" > .viz_runs/demo_viz.pid
echo "$log" > .viz_runs/demo_viz.lastlog

for _ in 1 2 3 4 5; do
    if ss -ltn "( sport = :${PORT} )" | tail -n +2 | grep -q ":${PORT}"; then
        break
    fi
    sleep 1
done

echo "PID: $pid"
echo "URL: http://${HOST}:${PORT}"
echo "Render graph: $SUBSET_GRAPH"
echo "Log: $log"
