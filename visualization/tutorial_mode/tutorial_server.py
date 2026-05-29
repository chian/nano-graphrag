"""
Separate tutorial visualization server.

Purpose:
- serve a dedicated instructional tutorial page
- keep the main demo server untouched
- replay a trace-backed GASL workflow lesson on its own port
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from visualization.graph_loader import GraphLoader, find_graphs_in_directory, build_color_map
from visualization.server import _load_render_and_query_graphs
from visualization.tutorial_mode.tutorial_demo_catalog import get_demo_catalog, get_demo


_current_loader: Optional[GraphLoader] = None
_full_loader: Optional[GraphLoader] = None


def create_app(graph_path: Optional[str] = None, full_graph_path: Optional[str] = None) -> Flask:
    global _current_loader, _full_loader

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent),
        static_folder=str(Path(__file__).parent.parent / "static"),
    )
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "tutorial-viz-secret")
    socketio = SocketIO(app, cors_allowed_origins="*")
    app.socketio = socketio

    if graph_path:
        _current_loader, _full_loader = _load_render_and_query_graphs(graph_path, full_graph_path)

    @app.route("/")
    def index():
        return render_template("tutorial_viewer.html")

    @app.route("/api/graph")
    def get_graph():
        if _current_loader is None or _current_loader.graph is None:
            return jsonify({"error": "No graph loaded"}), 404
        return jsonify(_current_loader.to_vis_format())

    @app.route("/api/graph/load", methods=["POST"])
    def load_graph():
        global _current_loader, _full_loader
        data = request.json or {}
        path = data.get("path")
        full_path = data.get("full_graph_path") or path
        if not path:
            return jsonify({"error": "No path provided"}), 400
        try:
            _current_loader, _full_loader = _load_render_and_query_graphs(path, full_path)
            return jsonify({
                "success": True,
                "stats": {
                    "num_nodes": _current_loader.stats.num_nodes,
                    "num_edges": _current_loader.stats.num_edges,
                },
                "graph_path": path,
                "full_graph_path": full_path,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/demos")
    def list_demos():
        demos = []
        for demo in get_demo_catalog():
            demos.append({
                "id": demo["id"],
                "title": demo["title"],
                "question": demo["question"],
                "metrics": demo["metrics"],
                "why_gasl_wins": demo["why_gasl_wins"],
                "rag_blind_spot": demo["rag_blind_spot"],
            })
        return jsonify({"demos": demos})

    @app.route("/api/demos/<demo_id>")
    def get_demo_payload(demo_id: str):
        demo = get_demo(demo_id)
        if demo is None:
            return jsonify({"error": f"Unknown demo: {demo_id}"}), 404
        return jsonify(demo)

    @app.route("/api/node/<node_id>")
    def get_node(node_id: str):
        if _current_loader is None:
            return jsonify({"error": "No graph loaded"}), 404
        details = _current_loader.get_node_details(node_id)
        if details is None:
            return jsonify({"error": "Node not found"}), 404
        return jsonify(details)

    @app.route("/api/search")
    def search():
        if _current_loader is None:
            return jsonify({"results": []})
        q = request.args.get("q", "")
        limit = int(request.args.get("limit", 20))
        return jsonify({"results": _current_loader.search_nodes(q, limit)})

    @app.route("/api/graphs/list")
    def list_graphs():
        base_path = request.args.get("path", ".")
        try:
            return jsonify({"graphs": find_graphs_in_directory(base_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/colors")
    def get_colors():
        if _current_loader is None or _current_loader.stats is None:
            return jsonify({})
        return jsonify(build_color_map(list(_current_loader.stats.entity_types.keys())))

    @socketio.on("connect")
    def handle_connect():
        emit("connected", {"status": "connected"})

    return app


def run_server(
    graph_path: Optional[str] = None,
    full_graph_path: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 5056,
    debug: bool = False,
):
    app = create_app(graph_path=graph_path, full_graph_path=full_graph_path)
    print(f"Tutorial server: http://{host}:{port}")
    app.socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_path")
    parser.add_argument("--full-graph-path", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5056)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run_server(args.graph_path, full_graph_path=args.full_graph_path, host=args.host, port=args.port, debug=args.debug)
