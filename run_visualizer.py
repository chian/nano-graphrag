#!/usr/bin/env python3
"""
Quick start script for the graph visualization server.

Usage:
    python run_visualizer.py                    # Auto-detect a sample graph
    python run_visualizer.py /path/to/graph.graphml  # Load specific graph
    python run_visualizer.py --help             # Show all options
"""

import sys
from pathlib import Path

# Add the repo to path
sys.path.insert(0, str(Path(__file__).parent))

# Run the demo
from visualization.examples.demo import main

if __name__ == '__main__':
    main()
