"""
GASL Execution Hooks for Real-time Visualization.

This module provides hooks that can be integrated into the GASL executor
to provide real-time visualization of graph operations.

Usage:
    from visualization.gasl_hooks import GASLVisualizer

    visualizer = GASLVisualizer(port=5050)
    visualizer.start()

    # In your GASL executor, call these at appropriate points:
    visualizer.on_command_start("FIND nodes WHERE entity_type='PATHOGEN'")
    visualizer.on_nodes_found(['NODE1', 'NODE2', 'NODE3'])
    visualizer.on_command_complete("FIND", result_count=3)
"""

import time
import json
import threading
import requests
from typing import List, Tuple, Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from contextlib import contextmanager


@dataclass
class VisualizationEvent:
    """A single visualization event to be sent to the viewer."""
    event_type: str
    timestamp: float
    data: Dict[str, Any]


@dataclass
class ExecutionStep:
    """Record of a single GASL execution step for replay."""
    step_id: int
    command: str
    highlighted_nodes: List[str] = field(default_factory=list)
    highlighted_edges: List[Tuple[str, str]] = field(default_factory=list)
    result_summary: str = ""
    duration_ms: float = 0
    timestamp: float = field(default_factory=time.time)


class GASLVisualizer:
    """
    Real-time GASL execution visualizer.

    Connects to the visualization server and sends updates as GASL
    commands are executed, allowing users to see graph operations
    in real-time.
    """

    def __init__(self,
                 server_url: str = "http://127.0.0.1:5050",
                 auto_delay: float = 0.5,
                 record_execution: bool = True):
        """
        Initialize the GASL visualizer.

        Args:
            server_url: URL of the visualization server
            auto_delay: Delay between visualization updates (seconds)
            record_execution: Whether to record execution for replay
        """
        self.server_url = server_url.rstrip('/')
        self.auto_delay = auto_delay
        self.record_execution = record_execution

        self._active = False
        self._current_command = None
        self._highlighted_nodes: List[str] = []
        self._highlighted_edges: List[Tuple[str, str]] = []

        # Execution recording
        self._execution_history: List[ExecutionStep] = []
        self._step_counter = 0
        self._command_start_time = 0

        # Event queue for async updates
        self._event_queue: Queue = Queue()
        self._update_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the visualizer."""
        self._active = True
        self._update_server_state()
        print(f"GASL Visualizer started. Server: {self.server_url}")

    def stop(self):
        """Stop the visualizer."""
        self._active = False
        self.clear_highlights()
        self._update_server_state()
        print("GASL Visualizer stopped.")

    @contextmanager
    def session(self):
        """Context manager for visualization session."""
        self.start()
        try:
            yield self
        finally:
            self.stop()

    def on_command_start(self, command: str):
        """
        Called when a GASL command starts execution.

        Args:
            command: The GASL command being executed
        """
        self._current_command = command
        self._command_start_time = time.time()
        self._update_server_state()

        if self.auto_delay > 0:
            time.sleep(self.auto_delay / 2)

    def on_command_complete(self, command_type: str, result_count: int = 0):
        """
        Called when a GASL command completes.

        Args:
            command_type: Type of command (FIND, PROCESS, etc.)
            result_count: Number of results
        """
        duration = (time.time() - self._command_start_time) * 1000

        if self.record_execution:
            step = ExecutionStep(
                step_id=self._step_counter,
                command=self._current_command or command_type,
                highlighted_nodes=list(self._highlighted_nodes),
                highlighted_edges=list(self._highlighted_edges),
                result_summary=f"{command_type}: {result_count} results",
                duration_ms=duration
            )
            self._execution_history.append(step)
            self._step_counter += 1

        if self.auto_delay > 0:
            time.sleep(self.auto_delay / 2)

    def on_nodes_found(self, node_ids: List[str]):
        """
        Called when nodes are found/selected by a command.

        Args:
            node_ids: List of node IDs that were found
        """
        self._highlighted_nodes = node_ids
        self._update_server_state()

        if self.auto_delay > 0:
            time.sleep(self.auto_delay)

    def on_edges_found(self, edges: List[Tuple[str, str]]):
        """
        Called when edges are found/traversed by a command.

        Args:
            edges: List of (source, target) tuples
        """
        self._highlighted_edges = edges
        self._update_server_state()

        if self.auto_delay > 0:
            time.sleep(self.auto_delay)

    def on_path_traversal(self, path: List[str]):
        """
        Called during path traversal (e.g., GRAPHWALK).

        Highlights nodes and edges along the path progressively.

        Args:
            path: List of node IDs in the path
        """
        for i in range(len(path)):
            self._highlighted_nodes = path[:i+1]

            if i > 0:
                edges = [(path[j], path[j+1]) for j in range(i)]
                self._highlighted_edges = edges

            self._update_server_state()

            if self.auto_delay > 0:
                time.sleep(self.auto_delay / 2)

    def on_subgraph_operation(self, nodes: List[str], edges: List[Tuple[str, str]]):
        """
        Called for subgraph operations.

        Args:
            nodes: Nodes in the subgraph
            edges: Edges in the subgraph
        """
        self._highlighted_nodes = nodes
        self._highlighted_edges = edges
        self._update_server_state()

        if self.auto_delay > 0:
            time.sleep(self.auto_delay)

    def highlight_nodes(self, node_ids: List[str], animate: bool = True):
        """
        Highlight specific nodes.

        Args:
            node_ids: Nodes to highlight
            animate: Whether to animate the transition
        """
        if animate and self._highlighted_nodes:
            # Gradual transition
            self._highlighted_nodes = node_ids
            self._update_server_state()
        else:
            self._highlighted_nodes = node_ids
            self._update_server_state()

    def highlight_edges(self, edges: List[Tuple[str, str]]):
        """
        Highlight specific edges.

        Args:
            edges: List of (source, target) tuples
        """
        self._highlighted_edges = edges
        self._update_server_state()

    def clear_highlights(self):
        """Clear all highlights."""
        self._highlighted_nodes = []
        self._highlighted_edges = []
        self._current_command = None
        self._update_server_state()

    def _update_server_state(self):
        """Send current state to the visualization server."""
        try:
            data = {
                'nodes': self._highlighted_nodes,
                'edges': [list(e) for e in self._highlighted_edges],
                'active': self._active,
                'command': self._current_command
            }
            requests.post(
                f"{self.server_url}/api/gasl/highlight",
                json=data,
                timeout=1
            )
        except requests.exceptions.RequestException:
            # Server not available, silently ignore
            pass

    # ============== Execution Recording & Replay ==============

    def get_execution_history(self) -> List[ExecutionStep]:
        """Get the recorded execution history."""
        return self._execution_history

    def save_execution(self, filepath: str):
        """
        Save execution history to a file.

        Args:
            filepath: Path to save the execution record
        """
        data = {
            'version': '1.0',
            'total_steps': len(self._execution_history),
            'steps': [
                {
                    'step_id': s.step_id,
                    'command': s.command,
                    'highlighted_nodes': s.highlighted_nodes,
                    'highlighted_edges': s.highlighted_edges,
                    'result_summary': s.result_summary,
                    'duration_ms': s.duration_ms,
                    'timestamp': s.timestamp
                }
                for s in self._execution_history
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"Execution saved to {filepath}")

    def load_execution(self, filepath: str) -> List[ExecutionStep]:
        """
        Load execution history from a file.

        Args:
            filepath: Path to the execution record

        Returns:
            List of execution steps
        """
        with open(filepath) as f:
            data = json.load(f)

        self._execution_history = [
            ExecutionStep(
                step_id=s['step_id'],
                command=s['command'],
                highlighted_nodes=s['highlighted_nodes'],
                highlighted_edges=[tuple(e) for e in s['highlighted_edges']],
                result_summary=s['result_summary'],
                duration_ms=s['duration_ms'],
                timestamp=s['timestamp']
            )
            for s in data['steps']
        ]

        return self._execution_history

    def replay_execution(self,
                        speed: float = 1.0,
                        step_callback: Optional[Callable[[ExecutionStep], None]] = None):
        """
        Replay a recorded execution.

        Args:
            speed: Replay speed multiplier (1.0 = original speed)
            step_callback: Optional callback for each step
        """
        if not self._execution_history:
            print("No execution history to replay")
            return

        print(f"Replaying {len(self._execution_history)} steps...")
        self._active = True
        self._update_server_state()

        for step in self._execution_history:
            self._current_command = step.command
            self._highlighted_nodes = step.highlighted_nodes
            self._highlighted_edges = step.highlighted_edges
            self._update_server_state()

            if step_callback:
                step_callback(step)

            # Wait based on original duration
            delay = step.duration_ms / 1000 / speed
            if delay > 0:
                time.sleep(min(delay, 2.0))  # Cap at 2 seconds

        self.clear_highlights()
        self._active = False
        self._update_server_state()
        print("Replay complete")


class GASLExecutorHook:
    """
    Hook class that can be passed to the GASL executor for automatic visualization.

    This provides a cleaner interface for integrating with the existing
    GASL executor architecture.
    """

    def __init__(self, visualizer: GASLVisualizer):
        """
        Initialize the executor hook.

        Args:
            visualizer: The GASLVisualizer instance to use
        """
        self.visualizer = visualizer

    def pre_execute(self, command: str, variables: Dict[str, Any]):
        """Called before command execution."""
        self.visualizer.on_command_start(command)

    def post_execute(self, command_type: str, result: Any, variables: Dict[str, Any]):
        """Called after command execution."""
        # Extract highlighted elements from result
        if hasattr(result, '__len__'):
            result_count = len(result)
        else:
            result_count = 1 if result else 0

        self.visualizer.on_command_complete(command_type, result_count)

    def on_find_nodes(self, node_ids: List[str]):
        """Called when FIND returns nodes."""
        self.visualizer.on_nodes_found(node_ids)

    def on_find_edges(self, edges: List[Dict[str, Any]]):
        """Called when FIND returns edges."""
        edge_tuples = [(e.get('source'), e.get('target')) for e in edges]
        self.visualizer.on_edges_found(edge_tuples)

    def on_graphwalk(self, paths: List[List[str]]):
        """Called during GRAPHWALK."""
        for path in paths:
            self.visualizer.on_path_traversal(path)

    def on_subgraph(self, nodes: List[str], edges: List[Tuple[str, str]]):
        """Called when creating a subgraph."""
        self.visualizer.on_subgraph_operation(nodes, edges)


def create_visualizer_for_executor(server_url: str = "http://127.0.0.1:5050",
                                   auto_delay: float = 0.3) -> Tuple[GASLVisualizer, GASLExecutorHook]:
    """
    Convenience function to create a visualizer and hook for GASL executor.

    Args:
        server_url: URL of the visualization server
        auto_delay: Delay between updates

    Returns:
        Tuple of (visualizer, hook)
    """
    visualizer = GASLVisualizer(server_url=server_url, auto_delay=auto_delay)
    hook = GASLExecutorHook(visualizer)
    return visualizer, hook
