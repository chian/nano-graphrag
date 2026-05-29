from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template

from visualization.tutorial_mode.compare_scene_catalog import get_compare_scenes, get_scene


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent),
        static_folder=str(Path(__file__).parent.parent / "static"),
    )

    @app.route("/")
    def index():
        return render_template("compare_scene_viewer.html")

    @app.route("/api/scenes")
    def list_scenes():
        return jsonify({"scenes": get_compare_scenes()})

    @app.route("/api/scenes/<scene_id>")
    def get_scene_payload(scene_id: str):
        scene = get_scene(scene_id)
        if scene is None:
            return jsonify({"error": f"Unknown scene: {scene_id}"}), 404
        return jsonify(scene)

    return app


def run_server(host: str = "127.0.0.1", port: int = 5058, debug: bool = False):
    app = create_app()
    print(f"Compare scene server: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5058)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, debug=args.debug)

