# Graph Visualization Package

Interactive visualization tools for nano-graphrag knowledge graphs.

## Features

1. **Interactive Graph Viewer** - Web-based navigation with search, filtering, and zoom
2. **GASL Execution Visualizer** - Real-time visualization of GASL commands
3. **Export & Recording** - Save execution history for replay and video creation

## Installation

```bash
# Install required packages
pip install flask flask-socketio networkx requests

# Or use the requirements file
pip install -r visualization/requirements.txt
```

## Quick Start

### Start the Visualization Server

```bash
# From the nano-graphrag directory:

# Option 1: With a specific graph
python -m visualization.examples.demo /path/to/graph.graphml

# Option 2: Auto-detect sample graph from ASM_595
python -m visualization.examples.demo

# Option 3: List available graphs
python -m visualization.examples.demo --list

# Option 4: Just show graph stats
python -m visualization.examples.demo --stats-only
```

Then open http://127.0.0.1:5050 in your browser.

### Using in Python

```python
from visualization import GraphLoader, run_server

# Load and explore a graph
loader = GraphLoader("/path/to/graph.graphml")
print(f"Nodes: {loader.stats.num_nodes}")
print(f"Edges: {loader.stats.num_edges}")

# Search for nodes
results = loader.search_nodes("bacteria")
for r in results:
    print(f"  {r['id']} [{r['entity_type']}]")

# Get subgraph around a node
subgraph = loader.get_subgraph("PSEUDOMONAS AERUGINOSA", depth=2)

# Start visualization server
run_server(graph_path="/path/to/graph.graphml", port=5050)
```

## Interactive Viewer Controls

- **Click** a node to see details
- **Double-click** to focus on that node's neighborhood
- **Search** using the search box in the sidebar
- **Filter** by entity type using the chips
- **Adjust importance** using the slider to hide low-importance nodes
- **Physics toggle** to enable/disable force-directed layout

## GASL Real-time Visualization

Integrate with GASL execution to visualize operations in real-time:

```python
from visualization.gasl_hooks import GASLVisualizer, GASLExecutorHook

# Create visualizer
visualizer = GASLVisualizer(server_url="http://127.0.0.1:5050")

# Use in context manager
with visualizer.session():
    # Your GASL execution
    visualizer.on_command_start("FIND nodes WHERE entity_type='PATHOGEN'")
    visualizer.on_nodes_found(['NODE1', 'NODE2', 'NODE3'])
    visualizer.on_command_complete("FIND", result_count=3)

# Or create hooks for the executor
visualizer, hook = create_visualizer_for_executor()
# Pass hook to your GASL executor
```

### Recording & Replay

```python
# Record execution
visualizer.save_execution("my_execution.json")

# Load and replay
visualizer.load_execution("my_execution.json")
visualizer.replay_execution(speed=2.0)  # 2x speed
```

## API Reference

### GraphLoader

- `load(path)` - Load a GraphML file
- `to_vis_format()` - Convert to vis.js JSON format
- `search_nodes(query)` - Search nodes by ID or description
- `get_subgraph(node_id, depth)` - Extract neighborhood subgraph
- `get_node_details(node_id)` - Get full node information

### GASLVisualizer

- `start()` / `stop()` - Control visualizer
- `on_command_start(command)` - Signal command start
- `on_command_complete(type, count)` - Signal completion
- `on_nodes_found(node_ids)` - Highlight found nodes
- `on_edges_found(edges)` - Highlight found edges
- `on_path_traversal(path)` - Animate path traversal
- `save_execution(path)` / `load_execution(path)` - Recording
- `replay_execution(speed)` - Replay recorded execution

## REST API Endpoints

When the server is running:

- `GET /api/graph` - Get full graph in vis.js format
- `POST /api/graph/load` - Load a new graph file
- `GET /api/graph/subgraph/<node_id>` - Get neighborhood subgraph
- `GET /api/search?q=query` - Search for nodes
- `GET /api/node/<node_id>` - Get node details
- `GET /api/stats` - Get graph statistics
- `GET /api/graphs/list?path=dir` - List available graphs

## File Structure

```
visualization/
├── __init__.py           # Package exports
├── graph_loader.py       # GraphML loading and conversion
├── server.py             # Flask web server
├── gasl_hooks.py         # GASL integration hooks
├── requirements.txt      # Python dependencies
├── templates/
│   └── viewer.html       # Interactive web viewer
├── static/
│   └── styles.css        # Additional styles
└── examples/
    └── demo.py           # Demo script
```

## Color Scheme

Entity types are color-coded:

- **PATHOGEN** - Red (#e74c3c)
- **ANTIMICROBIAL** - Blue (#3498db)
- **RESISTANCE_MECHANISM** - Orange (#e67e22)
- **DIAGNOSTIC_TEST** - Purple (#9b59b6)
- **BIOMARKER** - Teal (#1abc9c)
- **SPECIMEN** - Gray (#95a5a6)
- **METHOD** - Yellow (#f39c12)
- **GENE** - Green (#27ae60)

## Tips for Video Creation

1. Start the server and load your graph
2. Use the GASL visualizer to record your execution
3. Replay the execution at desired speed
4. Use screen recording software to capture the visualization
5. The recorded JSON can be edited to adjust timing

For best results:
- Disable physics after initial layout stabilizes
- Use the importance filter to reduce visual clutter
- Focus on specific subgraphs for clearer visualization
