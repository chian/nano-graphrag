"""
Flask web server for graph visualization.

Provides:
- Interactive graph viewer
- WebSocket support for real-time GASL updates
- REST API for graph operations
"""

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

from .graph_loader import GraphLoader, find_graphs_in_directory, build_color_map
from .query_engine import RagQueryEngine, GaslQueryEngine
from .demo_catalog import get_demo_catalog, get_demo, build_trace_demo_from_artifacts


# Server-side unlock: password → API key, never exposed to the browser.
# Override either via environment variables.
_SERVER_PASSWORD: str = os.environ.get("VIZ_PASSWORD", "slama")
_SERVER_API_KEY: str = os.environ.get("VIZ_API_KEY", "")

# Global state
_current_loader: Optional[GraphLoader] = None
_full_loader: Optional[GraphLoader] = None   # full graph used for queries
_rag_engine: Optional[RagQueryEngine] = None
_gasl_engine: Optional[GaslQueryEngine] = None
_gasl_state: Dict[str, Any] = {
    'active': False,
    'current_command': None,
    'highlighted_nodes': [],
    'highlighted_edges': [],
    'history': []
}

_AUTO_SUBSET_ENABLED = os.environ.get("VIZ_AUTO_SUBSET", "1").strip().lower() not in {"0", "false", "no"}
_AUTO_SUBSET_THRESHOLD = int(os.environ.get("VIZ_SUBSET_THRESHOLD", "4000"))
_AUTO_SUBSET_MAX_NODES = int(os.environ.get("VIZ_SUBSET_MAX_NODES", "1500"))


def _load_render_and_query_graphs(
    graph_path: str,
    full_graph_path: Optional[str] = None,
) -> tuple[GraphLoader, GraphLoader]:
    """Load a reduced render graph and a full query graph.

    If an explicit reduced render graph is supplied, respect it.
    Otherwise, when the full graph is large, derive a top-degree subset in memory
    for rendering only while keeping the full graph for query execution.
    """
    full_loader = GraphLoader(full_graph_path or graph_path)
    if graph_path and full_graph_path and graph_path != full_graph_path:
        return GraphLoader(graph_path), full_loader

    if _AUTO_SUBSET_ENABLED and full_loader.stats and full_loader.stats.num_nodes > _AUTO_SUBSET_THRESHOLD:
        subset_graph = full_loader.top_degree_subgraph(_AUTO_SUBSET_MAX_NODES)
        render_loader = GraphLoader.from_graph(
            subset_graph,
            graphml_path=f"{full_loader.graphml_path}#topdeg{_AUTO_SUBSET_MAX_NODES}",
        )
        print(
            f"  Render graph auto-subset: {render_loader.stats.num_nodes} nodes, "
            f"{render_loader.stats.num_edges} edges "
            f"(from full {full_loader.stats.num_nodes} nodes)"
        )
        return render_loader, full_loader

    return full_loader, full_loader


def create_app(graph_path: Optional[str] = None,
               full_graph_path: Optional[str] = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        graph_path: Optional path to initially load a graph

    Returns:
        Configured Flask application
    """
    global _current_loader, _full_loader, _rag_engine, _gasl_engine

    app = Flask(__name__,
                template_folder=str(Path(__file__).parent / 'templates'),
                static_folder=str(Path(__file__).parent / 'static'))

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'graphviz-secret-key')

    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*")
    app.socketio = socketio

    # Load initial graph if provided
    if graph_path:
        _current_loader, _full_loader = _load_render_and_query_graphs(graph_path, full_graph_path)
        if full_graph_path:
            print(f"  Query graph: {full_graph_path} "
                  f"({_full_loader.stats.num_nodes} nodes, {_full_loader.stats.num_edges} edges)")
        _rag_engine = RagQueryEngine(_full_loader)
        _gasl_engine = GaslQueryEngine(_full_loader, socketio)

    # ============== Routes ==============

    @app.route('/')
    def index():
        """Serve the main visualization page."""
        return render_template('viewer.html')

    @app.route('/api/graph')
    def get_graph():
        """Get the current graph in vis.js format."""
        if _current_loader is None or _current_loader.graph is None:
            return jsonify({'error': 'No graph loaded'}), 404

        # Get query parameters for filtering
        entity_types = request.args.get('entity_types', '')
        min_salience = float(request.args.get('min_salience', 0.0))

        filter_types = entity_types.split(',') if entity_types else None

        data = _current_loader.to_vis_format(
            highlight_nodes=_gasl_state.get('highlighted_nodes', []),
            highlight_edges=_gasl_state.get('highlighted_edges', []),
            filter_entity_types=filter_types,
            min_salience=min_salience
        )
        return jsonify(data)

    @app.route('/api/graph/load', methods=['POST'])
    def load_graph():
        """Load a new graph from a file path."""
        global _current_loader, _full_loader, _rag_engine, _gasl_engine

        data = request.json
        path = data.get('path')
        full_graph_path = data.get('full_graph_path') or path

        if not path:
            return jsonify({'error': 'No path provided'}), 400

        try:
            _current_loader, _full_loader = _load_render_and_query_graphs(path, full_graph_path)
            _rag_engine = RagQueryEngine(_full_loader)
            _gasl_engine = GaslQueryEngine(_full_loader, socketio)
            return jsonify({
                'success': True,
                'stats': {
                    'num_nodes': _current_loader.stats.num_nodes,
                    'num_edges': _current_loader.stats.num_edges,
                    'entity_types': dict(_current_loader.stats.entity_types),
                    'relation_types': dict(_current_loader.stats.relation_types)
                },
                'graph_path': path,
                'full_graph_path': full_graph_path,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/demos')
    def list_demos():
        """Return the curated demo catalog."""
        demos = []
        for demo in get_demo_catalog():
            demos.append({
                'id': demo['id'],
                'title': demo['title'],
                'question': demo['question'],
                'why_gasl_wins': demo['why_gasl_wins'],
                'rag_blind_spot': demo['rag_blind_spot'],
                'metrics': demo['metrics'],
            })
        return jsonify({'demos': demos})

    @app.route('/api/demos/<demo_id>')
    def get_demo_payload(demo_id: str):
        """Return a single demo with graph paths and replay events."""
        demo = get_demo(demo_id)
        if demo is None:
            return jsonify({'error': f'Unknown demo: {demo_id}'}), 404
        return jsonify(demo)

    @app.route('/api/artifact-demo')
    def get_artifact_demo():
        """Build an on-demand replay payload from committed run artifacts."""
        run_id = request.args.get('run_id', '').strip()
        qid = request.args.get('qid', '').strip()
        graph_path = request.args.get('graph_path', '').strip() or None
        full_graph_path = request.args.get('full_graph_path', '').strip() or None
        title = request.args.get('title', '').strip() or None

        if not run_id or not qid:
            return jsonify({'error': 'run_id and qid are required'}), 400

        try:
            demo = build_trace_demo_from_artifacts(
                qid=qid,
                run_id=run_id,
                graph_path=graph_path,
                full_graph_path=full_graph_path,
                title=title,
            )
            return jsonify(demo)
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/query', methods=['POST'])
    def run_query():
        """Answer a question using RAG (Mode 1) or GASL (Mode 2).

        Requires a user-supplied OpenAI-compatible API key in the
        Authorization header: `Authorization: Bearer <key>`.
        The key is used per-request and never persisted server-side.
        """
        global _rag_engine, _gasl_engine

        if _current_loader is None or _current_loader.graph is None:
            return jsonify({'error': 'No graph loaded'}), 404

        # Resolve API key: password in body takes priority over Bearer header.
        password = (request.json or {}).get('password', '')
        if password and password == _SERVER_PASSWORD:
            api_key = _SERVER_API_KEY
        else:
            auth = request.headers.get('Authorization', '')
            api_key = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
        if not api_key:
            return jsonify({
                'error': 'Wrong password or no API key. Provide the unlock password.'
            }), 401

        data = request.json or {}
        question = data.get('question', '').strip()
        mode = data.get('mode', 'rag').lower()
        model = (data.get('model') or 'gpt-5.4-mini').strip()
        reasoning_effort = data.get('reasoning_effort') or None
        if reasoning_effort not in (None, 'low', 'medium', 'high'):
            reasoning_effort = None

        if not question:
            return jsonify({'error': 'No question provided'}), 400

        if mode == 'rag':
            if _rag_engine is None:
                _rag_engine = RagQueryEngine(_current_loader)
            result = _rag_engine.query(question)
            answer_obj = _rag_engine.generate_answer(
                question, result['context'], api_key=api_key, model=model,
                reasoning_effort=reasoning_effort)
            return jsonify({
                'mode': 'rag',
                'nodes': result['nodes'],
                'neighbor_nodes': result['neighbor_nodes'],
                'edges': result['edges'],
                'answer': answer_obj['text'],
                'usage': answer_obj['usage'],
                'model': model,
            })

        elif mode == 'gasl':
            if _gasl_engine is None:
                _gasl_engine = GaslQueryEngine(_current_loader, socketio)
            job_id = str(uuid.uuid4())
            t = threading.Thread(
                target=_gasl_engine.run,
                args=(question, job_id),
                kwargs={'api_key': api_key, 'model': model,
                        'reasoning_effort': reasoning_effort},
                daemon=True,
            )
            t.start()
            return jsonify({'mode': 'gasl', 'job_id': job_id})

        else:
            return jsonify({'error': f'Unknown mode: {mode}'}), 400

    @app.route('/api/graph/subgraph/<node_id>')
    def get_subgraph(node_id: str):
        """Get a subgraph centered on a node."""
        if _current_loader is None:
            return jsonify({'error': 'No graph loaded'}), 404

        depth = int(request.args.get('depth', 2))
        max_nodes = int(request.args.get('max_nodes', 100))

        try:
            data = _current_loader.get_subgraph(node_id, depth, max_nodes)
            return jsonify(data)
        except ValueError as e:
            return jsonify({'error': str(e)}), 404

    @app.route('/api/search')
    def search():
        """Search for nodes."""
        if _current_loader is None:
            return jsonify({'results': []})

        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 20))

        results = _current_loader.search_nodes(query, limit)
        return jsonify({'results': results})

    @app.route('/api/node/<node_id>')
    def get_node(node_id: str):
        """Get detailed info about a node."""
        if _current_loader is None:
            return jsonify({'error': 'No graph loaded'}), 404

        details = _current_loader.get_node_details(node_id)
        if details is None:
            return jsonify({'error': 'Node not found'}), 404

        return jsonify(details)

    @app.route('/api/graphs/list')
    def list_graphs():
        """List available graphs in a directory."""
        base_path = request.args.get('path', '.')

        try:
            graphs = find_graphs_in_directory(base_path)
            return jsonify({'graphs': graphs})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/stats')
    def get_stats():
        """Get current graph statistics."""
        if _current_loader is None or _current_loader.stats is None:
            return jsonify({'error': 'No graph loaded'}), 404

        return jsonify({
            'num_nodes': _current_loader.stats.num_nodes,
            'num_edges': _current_loader.stats.num_edges,
            'entity_types': dict(_current_loader.stats.entity_types),
            'relation_types': dict(_current_loader.stats.relation_types),
            'avg_salience': _current_loader.stats.avg_salience,
            'connected_components': _current_loader.stats.connected_components
        })

    @app.route('/api/colors')
    def get_colors():
        """Return the color map for all entity types in the loaded graph."""
        if _current_loader is None or _current_loader.stats is None:
            return jsonify({})
        entity_types = list(_current_loader.stats.entity_types.keys())
        return jsonify(build_color_map(entity_types))

    @app.route('/api/gasl/state')
    def get_gasl_state():
        """Get current GASL visualization state."""
        return jsonify(_gasl_state)

    @app.route('/api/gasl/highlight', methods=['POST'])
    def set_highlight():
        """Set nodes/edges to highlight (for GASL visualization)."""
        global _gasl_state

        data = request.json
        _gasl_state['highlighted_nodes'] = data.get('nodes', [])
        _gasl_state['highlighted_edges'] = data.get('edges', [])

        # Broadcast update via WebSocket
        socketio.emit('gasl_update', _gasl_state)

        return jsonify({'success': True})

    # ============== WebSocket Events ==============

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        emit('connected', {'status': 'connected'})
        # Send current state
        if _current_loader and _current_loader.stats:
            emit('graph_loaded', {
                'num_nodes': _current_loader.stats.num_nodes,
                'num_edges': _current_loader.stats.num_edges
            })

    @socketio.on('request_graph')
    def handle_request_graph(data):
        """Handle graph request via WebSocket."""
        if _current_loader is None:
            emit('error', {'message': 'No graph loaded'})
            return

        filter_types = data.get('entity_types')
        min_salience = data.get('min_salience', 0.0)

        graph_data = _current_loader.to_vis_format(
            highlight_nodes=_gasl_state.get('highlighted_nodes', []),
            highlight_edges=_gasl_state.get('highlighted_edges', []),
            filter_entity_types=filter_types,
            min_salience=min_salience
        )
        emit('graph_data', graph_data)

    @socketio.on('focus_node')
    def handle_focus_node(data):
        """Handle focus on a specific node."""
        node_id = data.get('node_id')
        depth = data.get('depth', 2)

        if _current_loader is None:
            emit('error', {'message': 'No graph loaded'})
            return

        try:
            subgraph = _current_loader.get_subgraph(node_id, depth)
            emit('subgraph_data', subgraph)
        except ValueError as e:
            emit('error', {'message': str(e)})

    return app


def run_server(graph_path: Optional[str] = None,
               full_graph_path: Optional[str] = None,
               host: str = '127.0.0.1',
               port: int = 5050,
               debug: bool = True):
    """
    Run the visualization server.

    Args:
        graph_path: Optional path to a GraphML file to load initially (used for viz)
        full_graph_path: Optional path to the full graph used for queries (falls back to graph_path)
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug mode
    """
    app = create_app(graph_path, full_graph_path=full_graph_path)
    print(f"\n{'='*60}")
    print(f"  Graph Visualization Server")
    print(f"{'='*60}")
    print(f"  URL: http://{host}:{port}")
    if graph_path:
        print(f"  Loaded: {graph_path}")
    print(f"{'='*60}\n")

    app.socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


# GASL Integration Functions

def gasl_highlight_nodes(node_ids: List[str], command: str = ""):
    """
    Highlight nodes during GASL execution.

    This function is called by GASL hooks to update the visualization.
    """
    global _gasl_state

    _gasl_state['highlighted_nodes'] = node_ids
    _gasl_state['current_command'] = command
    _gasl_state['history'].append({
        'type': 'highlight_nodes',
        'nodes': node_ids,
        'command': command
    })

    # Emit via WebSocket if app is running
    # This requires the app instance to be accessible


def gasl_highlight_edges(edges: List[tuple], command: str = ""):
    """
    Highlight edges during GASL execution.

    edges: List of (source, target) tuples
    """
    global _gasl_state

    _gasl_state['highlighted_edges'] = [list(e) for e in edges]
    _gasl_state['current_command'] = command
    _gasl_state['history'].append({
        'type': 'highlight_edges',
        'edges': edges,
        'command': command
    })


def gasl_clear_highlights():
    """Clear all highlights."""
    global _gasl_state

    _gasl_state['highlighted_nodes'] = []
    _gasl_state['highlighted_edges'] = []
    _gasl_state['current_command'] = None


def gasl_set_active(active: bool):
    """Set whether GASL execution is active."""
    global _gasl_state
    _gasl_state['active'] = active
