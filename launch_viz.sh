#!/bin/bash
# Launch the graph visualization server
# Usage: ./launch_viz.sh [optional_graph_path]

cd "$(dirname "$0")"

PYTHON="/Users/chia/miniconda3/bin/python"
PORT=5050
URL="http://127.0.0.1:$PORT"

# Open browser after a short delay (in background)
(sleep 2 && open "$URL") &

# Check if a graph path was provided
if [ -n "$1" ]; then
    echo "Starting visualization with: $1"
    echo "Opening browser at $URL"
    $PYTHON -m visualization.examples.demo --port $PORT "$1"
else
    echo "Starting visualization (auto-detecting sample graph)..."
    echo "Opening browser at $URL"
    $PYTHON -m visualization.examples.demo --port $PORT
fi
