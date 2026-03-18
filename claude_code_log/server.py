"""Local web server for serving generated HTML files with API support."""
from __future__ import annotations

import json
import threading
import time as time_module
import webbrowser
from pathlib import Path
from typing import Optional

from flask import Flask, Response, abort, jsonify, request, send_file


def _find_session_jsonl(projects_dir: Path, session_id: str) -> Optional[Path]:
    """Find the JSONL file containing the given session ID.

    Tries filename match first (e.g. {session_id}.jsonl), then falls back
    to content search for sessions embedded in other JSONL files.
    """
    # 1차: 파일명으로 검색 (가장 빠르고 정확)
    for jsonl_file in projects_dir.rglob(f"{session_id}.jsonl"):
        return jsonl_file

    # 2차: 파일 내용으로 검색 (sessionId 필드가 있는 경우)
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        if session_id in jsonl_file.read_text(encoding="utf-8"):
            return jsonl_file

    return None


def _update_custom_title(jsonl_file: Path, session_id: str, new_title: str) -> None:
    """Add or update a custom-title entry in the JSONL file."""
    lines = jsonl_file.read_text(encoding="utf-8").splitlines()
    new_entry = json.dumps(
        {"type": "custom-title", "customTitle": new_title, "sessionId": session_id},
        ensure_ascii=False,
    )

    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            data = json.loads(stripped)
            if data.get("type") == "custom-title" and data.get("sessionId") == session_id:
                new_lines.append(new_entry)
                updated = True
                continue
        except json.JSONDecodeError:
            pass
        new_lines.append(line)

    if not updated:
        new_lines.append(new_entry)

    jsonl_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def create_app(projects_dir: Path) -> Flask:
    """Create Flask app that serves HTML files from projects_dir."""
    app = Flask(__name__)

    LOADING_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Loading...</title>
<meta http-equiv="refresh" content="2">
<style>
body{display:flex;justify-content:center;align-items:center;height:100vh;margin:0;
font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0}
.loader{text-align:center}
.spinner{width:40px;height:40px;border:4px solid #333;border-top:4px solid #3b82f6;
border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body><div class="loader"><div class="spinner"></div><p>Regenerating index...</p></div></body>
</html>"""

    @app.route("/")
    def index() -> Response:
        index_file = projects_dir / "index.html"
        if index_file.exists():
            response = send_file(index_file)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"  # type: ignore[union-attr]
            return response  # type: ignore[return-value]
        return Response(LOADING_HTML, mimetype="text/html")

    @app.route("/<path:filepath>")
    def serve_file(filepath: str) -> Response:
        import re

        # 세션 페이지는 동적 렌더링 (항상 JSONL에서 최신 내용 생성)
        session_match = re.match(r".+/session-([a-f0-9-]+)\.html$", filepath)
        if session_match:
            session_id = session_match.group(1)
            jsonl_file = _find_session_jsonl(projects_dir, session_id)
            if jsonl_file is not None:
                from .converter import load_transcript
                from .html.renderer import HtmlRenderer

                messages = load_transcript(jsonl_file, silent=True)
                renderer = HtmlRenderer()
                html = renderer.generate_session(messages, session_id)
                print(f"[serve_file] session={session_id[:8]}, messages={len(messages)}, html_len={len(html)}, jsonl_size={jsonl_file.stat().st_size}")
                return Response(
                    html,
                    mimetype="text/html",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )

        target = (projects_dir / filepath).resolve()
        # Security: prevent path traversal outside projects_dir
        if not str(target).startswith(str(projects_dir.resolve())):
            abort(403)
        if target.exists() and target.is_file():
            response = send_file(target)
            if filepath.endswith(".html"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"  # type: ignore[union-attr]
            return response  # type: ignore[return-value]
        abort(404)

    # --- API endpoints (Phase 2~4) ---

    @app.route("/api/sessions/<session_id>/title", methods=["PUT"])
    def update_title(session_id: str) -> Response:
        data = request.get_json()
        if not data or "title" not in data:
            return jsonify({"error": "title required"}), 400  # type: ignore[return-value]
        new_title = str(data["title"]).strip()
        if not new_title:
            return jsonify({"error": "title cannot be empty"}), 400  # type: ignore[return-value]

        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is None:
            return jsonify({"error": "session not found"}), 404  # type: ignore[return-value]

        _update_custom_title(jsonl_file, session_id, new_title)

        from .converter import process_projects_hierarchy
        process_projects_hierarchy(projects_dir, use_cache=True, silent=True)

        return jsonify({"status": "ok", "title": new_title})  # type: ignore[return-value]

    @app.route("/api/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id: str) -> Response:
        from .cache import CacheManager
        from .converter import get_library_version, process_projects_hierarchy

        # 1) 프로젝트 디렉토리 찾기 (JSONL 또는 세션 HTML로)
        project_dir = None
        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is not None:
            project_dir = jsonl_file.parent
        else:
            matches = list(projects_dir.rglob(f"session-{session_id}.html"))
            if matches:
                project_dir = matches[0].parent

        if project_dir is None:
            return jsonify({"error": "session not found"}), 404  # type: ignore[return-value]

        # 2) 소스 파일 삭제: JSONL + 세션 HTML
        if jsonl_file is not None:
            jsonl_file.unlink()
        session_html = project_dir / f"session-{session_id}.html"
        if session_html.exists():
            session_html.unlink()

        # 3) 프로젝트 캐시 전체 초기화 (SQLite) → 남은 JSONL로 처음부터 다시 빌드
        try:
            cm = CacheManager(project_dir, get_library_version())
            cm.clear_cache()
        except Exception:
            pass

        # 4) 생성된 HTML 파일 삭제 (combined + index)
        for f in project_dir.glob("combined_transcripts*.html"):
            f.unlink()
        index_html = projects_dir / "index.html"
        if index_html.exists():
            index_html.unlink()

        # 5) 모든 프로젝트 재생성 (캐시 사용 → 빠르게, 해당 프로젝트만 처음부터)
        process_projects_hierarchy(projects_dir, use_cache=True, silent=True)

        return jsonify({"status": "ok"})  # type: ignore[return-value]

    # --- Live streaming endpoints ---

    @app.route("/api/sessions/<session_id>/stream")
    def stream_session(session_id: str) -> Response:
        """SSE endpoint: polls JSONL file for changes, notifies browser."""
        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is None:
            return jsonify({"error": "session not found"}), 404  # type: ignore[return-value]

        def generate():  # type: ignore[no-untyped-def]
            last_size = jsonl_file.stat().st_size if jsonl_file.exists() else 0
            last_mtime = jsonl_file.stat().st_mtime if jsonl_file.exists() else 0.0
            print(f"[SSE] watching {jsonl_file.name}, size={last_size}, mtime={last_mtime}")
            while True:
                time_module.sleep(2)
                try:
                    stat = jsonl_file.stat()
                except FileNotFoundError:
                    yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                    break
                if stat.st_size != last_size or stat.st_mtime != last_mtime:
                    # Debounce: wait until file is stable (no changes for 1 second)
                    # to avoid reading a partially-written JSONL
                    for _ in range(5):  # max 5 retries (5 seconds total)
                        time_module.sleep(1)
                        try:
                            new_stat = jsonl_file.stat()
                        except FileNotFoundError:
                            break
                        if new_stat.st_size == stat.st_size and new_stat.st_mtime == stat.st_mtime:
                            break  # file is stable
                        stat = new_stat
                    print(f"[SSE] change detected: size {last_size}->{stat.st_size}, sending updated")
                    last_size = stat.st_size
                    last_mtime = stat.st_mtime
                    yield f"data: {json.dumps({'type': 'updated'})}\n\n"
                else:
                    yield ":\n\n"  # SSE keepalive

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/sessions/<session_id>/render")
    def render_session(session_id: str) -> Response:
        """Dynamically render session HTML from JSONL (for live updates)."""
        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is None:
            return jsonify({"error": "session not found"}), 404  # type: ignore[return-value]

        from .converter import load_transcript
        from .html.renderer import HtmlRenderer

        messages = load_transcript(jsonl_file, silent=True)
        renderer = HtmlRenderer()
        html = renderer.generate_session(messages, session_id)
        print(f"[render_session] session={session_id[:8]}, messages={len(messages)}, html_len={len(html)}, jsonl_size={jsonl_file.stat().st_size}")
        return Response(html, mimetype="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

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
