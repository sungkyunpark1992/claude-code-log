"""Local web server for serving generated HTML files with API support."""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, send_file


def create_app(projects_dir: Path) -> Flask:
    """Create Flask app that serves HTML files from projects_dir."""
    app = Flask(__name__)

    @app.route("/")
    def index() -> Response:
        index_file = projects_dir / "index.html"
        if index_file.exists():
            return send_file(index_file)  # type: ignore[return-value]
        abort(404)

    @app.route("/<path:filepath>")
    def serve_file(filepath: str) -> Response:
        target = (projects_dir / filepath).resolve()
        # Security: prevent path traversal outside projects_dir
        if not str(target).startswith(str(projects_dir.resolve())):
            abort(403)
        if target.exists() and target.is_file():
            return send_file(target)  # type: ignore[return-value]
        abort(404)

    # --- API endpoints (Phase 2~4) ---

    @app.route("/api/sessions/<session_id>/title", methods=["PUT"])
    def update_title(session_id: str) -> Response:
        return jsonify({"status": "not_implemented"}), 501  # type: ignore[return-value]

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id: str) -> Response:
        return jsonify({"status": "not_implemented"}), 501  # type: ignore[return-value]

    return app


def run_server(projects_dir: Path, port: int = 5678) -> None:
    """Start Flask server and open browser."""
    app = create_app(projects_dir)
    url = f"http://localhost:{port}"

    def _open_browser() -> None:
        import time

        time.sleep(0.8)
        webbrowser.open(url)

    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    print(f"\nServing claude-code-log at {url}")
    print("Press Ctrl+C to stop\n")
    app.run(host="localhost", port=port, debug=False, use_reloader=False)
