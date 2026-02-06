#!/usr/bin/env python3
"""
Demo script for the graph visualization package.

This script demonstrates how to use the visualization tools with
actual graphs from the ASM_595 dataset.

Usage:
    # Basic usage - starts the server with a sample graph
    python -m visualization.examples.demo

    # With a specific graph file
    python -m visualization.examples.demo /path/to/graph.graphml

    # List available graphs
    python -m visualization.examples.demo --list

    # Demo GASL visualization
    python -m visualization.examples.demo --gasl-demo
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from visualization import GraphLoader, run_server
from visualization.graph_loader import find_graphs_in_directory


# Default paths to look for graphs
DEFAULT_GRAPH_DIRS = [
    "ASM_595",
    "mmwr-test/graphrag_cache",
]


def find_sample_graph() -> str:
    """Find a sample graph file to use for demo."""
    base_path = Path(__file__).parent.parent.parent

    # Try to find graphs in default locations
    for dir_name in DEFAULT_GRAPH_DIRS:
        dir_path = base_path / dir_name
        if dir_path.exists():
            graphs = find_graphs_in_directory(str(dir_path), "**/*graph.graphml")
            if graphs:
                # Return the first one found
                return graphs[0]

    return None


def list_available_graphs(base_path: str = None):
    """List all available graphs in the project."""
    if base_path is None:
        base_path = Path(__file__).parent.parent.parent

    print("\nSearching for GraphML files...\n")

    total_found = 0
    for dir_name in DEFAULT_GRAPH_DIRS:
        dir_path = Path(base_path) / dir_name
        if dir_path.exists():
            graphs = find_graphs_in_directory(str(dir_path), "**/*graph.graphml")
            if graphs:
                print(f"=== {dir_name} ({len(graphs)} graphs) ===")
                for i, g in enumerate(graphs[:10]):
                    # Show relative path
                    rel_path = Path(g).relative_to(base_path)
                    print(f"  {i+1}. {rel_path}")
                if len(graphs) > 10:
                    print(f"  ... and {len(graphs) - 10} more")
                print()
                total_found += len(graphs)

    if total_found == 0:
        print("No GraphML files found in default locations.")
        print("Try running with a specific path: python -m visualization.examples.demo /path/to/graph.graphml")


def demo_graph_loading():
    """Demonstrate graph loading and basic operations."""
    print("\n=== Graph Loading Demo ===\n")

    graph_path = find_sample_graph()
    if not graph_path:
        print("No sample graph found. Please provide a path.")
        return

    print(f"Loading graph: {graph_path}\n")

    # Load the graph
    loader = GraphLoader(graph_path)

    # Print stats
    print(f"Nodes: {loader.stats.num_nodes}")
    print(f"Edges: {loader.stats.num_edges}")
    print(f"Connected Components: {loader.stats.connected_components}")
    print(f"Average Importance: {loader.stats.avg_importance:.2f}")

    print("\nEntity Types:")
    for entity_type, count in sorted(loader.stats.entity_types.items(), key=lambda x: -x[1]):
        print(f"  {entity_type}: {count}")

    print("\nRelation Types:")
    for rel_type, count in sorted(loader.stats.relation_types.items(), key=lambda x: -x[1])[:10]:
        print(f"  {rel_type}: {count}")

    # Search demo
    print("\n=== Search Demo ===")
    results = loader.search_nodes("pseudo", limit=5)
    print("\nSearch for 'pseudo':")
    for r in results:
        print(f"  - {r['id']} [{r['entity_type']}] (importance: {r['importance']:.2f})")

    # Subgraph demo
    if results:
        center_node = results[0]['id']
        print(f"\n=== Subgraph Demo (centered on '{center_node}') ===")
        subgraph = loader.get_subgraph(center_node, depth=2, max_nodes=20)
        print(f"Subgraph has {len(subgraph['nodes'])} nodes and {len(subgraph['edges'])} edges")


def demo_gasl_visualization():
    """Demonstrate GASL visualization hooks."""
    print("\n=== GASL Visualization Demo ===\n")
    print("This demo simulates GASL command execution with visualization.\n")

    from visualization.gasl_hooks import GASLVisualizer
    import time

    graph_path = find_sample_graph()
    if not graph_path:
        print("No sample graph found.")
        return

    # Load the graph
    loader = GraphLoader(graph_path)

    # Get some sample nodes
    sample_nodes = list(loader.graph.nodes())[:20]

    print("Starting visualization server in background...")
    print("Open http://127.0.0.1:5050 in your browser\n")

    # Note: In a real scenario, the server would be started separately
    # For this demo, we'll just show how the visualizer works

    visualizer = GASLVisualizer(auto_delay=0.5)

    print("Simulating GASL execution...\n")

    with visualizer.session():
        # Simulate FIND command
        print("1. FIND nodes WHERE entity_type='PATHOGEN'")
        visualizer.on_command_start("FIND nodes WHERE entity_type='PATHOGEN'")

        pathogens = [n for n in sample_nodes if
                     loader.graph.nodes[n].get('entity_type') == 'PATHOGEN'][:5]
        if pathogens:
            visualizer.on_nodes_found(pathogens)
            print(f"   Found: {pathogens}")

        visualizer.on_command_complete("FIND", len(pathogens))
        time.sleep(1)

        # Simulate GRAPHWALK
        if len(sample_nodes) >= 3:
            path = sample_nodes[:3]
            print(f"\n2. GRAPHWALK from '{path[0]}'")
            visualizer.on_command_start(f"GRAPHWALK {path[0]} MAX_DEPTH 2")
            visualizer.on_path_traversal(path)
            visualizer.on_command_complete("GRAPHWALK", len(path))

        print("\nSimulation complete!")

    # Save execution for replay
    if visualizer._execution_history:
        save_path = Path(__file__).parent / "demo_execution.json"
        visualizer.save_execution(str(save_path))
        print(f"\nExecution saved to: {save_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Graph Visualization Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start server with a sample graph
  python -m visualization.examples.demo

  # Start server with a specific graph
  python -m visualization.examples.demo /path/to/graph.graphml

  # List available graphs
  python -m visualization.examples.demo --list

  # Run GASL visualization demo
  python -m visualization.examples.demo --gasl-demo

  # Change port
  python -m visualization.examples.demo --port 8080
        """
    )

    parser.add_argument(
        'graph_path',
        nargs='?',
        help='Path to a GraphML file to visualize'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available graph files'
    )
    parser.add_argument(
        '--gasl-demo',
        action='store_true',
        help='Run GASL visualization demonstration'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5050,
        help='Port for the visualization server (default: 5050)'
    )
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--no-debug',
        action='store_true',
        help='Disable debug mode'
    )
    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Only show graph statistics, don\'t start server'
    )

    args = parser.parse_args()

    if args.list:
        list_available_graphs()
        return

    if args.gasl_demo:
        demo_gasl_visualization()
        return

    if args.stats_only:
        demo_graph_loading()
        return

    # Find or use specified graph
    graph_path = args.graph_path
    if not graph_path:
        graph_path = find_sample_graph()
        if graph_path:
            print(f"Using sample graph: {graph_path}")

    if graph_path and not Path(graph_path).exists():
        print(f"Error: Graph file not found: {graph_path}")
        sys.exit(1)

    # Start the server
    print(f"\nStarting visualization server...")
    print(f"Open http://{args.host}:{args.port} in your browser\n")

    if graph_path:
        print(f"Pre-loading graph: {graph_path}")

    run_server(
        graph_path=graph_path,
        host=args.host,
        port=args.port,
        debug=not args.no_debug
    )


if __name__ == '__main__':
    main()
