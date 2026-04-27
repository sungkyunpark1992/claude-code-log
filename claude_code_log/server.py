"""Local web server for serving generated HTML files with API support."""
from __future__ import annotations

import json
import re
import threading
import time as time_module
import webbrowser
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

from flask import Flask, Response, abort, jsonify, request, send_file
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class _SSEFileWatcher(FileSystemEventHandler):
    """Pushes a tag into a queue when a watched file is modified.

    watchdog watches directories, not files — so we filter events by
    resolved path and only forward those for paths we care about.
    """

    def __init__(
        self,
        watched: "dict[Path, str]",
        queue: "Queue[str]",
    ) -> None:
        super().__init__()
        self._watched = {p.resolve(): tag for p, tag in watched.items()}
        self._queue = queue

    def on_modified(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def _notify(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        try:
            src = Path(str(event.src_path)).resolve()
        except OSError:
            return
        tag = self._watched.get(src)
        if tag is not None:
            self._queue.put(tag)


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


_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
# Anthropic's current default model (used when settings.json has no "model" key,
# which is what Claude Code writes when the user picks /model default).
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _get_current_model_from_settings() -> Optional[str]:
    """Return the currently selected model from ~/.claude/settings.json.

    Claude Code writes the active model here when the user runs /model.
    This reflects the PENDING prompt's model, not the last response's.
    """
    try:
        data = json.loads(_CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model = data.get("model")
    return str(model) if model else None


_MODEL_CMD_RE = re.compile(r"Set model to (\S+)")


def _get_latest_model_from_jsonl(jsonl_file: Path) -> Optional[str]:
    """Return the most recent model indicator from the JSONL file.

    Scans from the end of the file and returns whichever of these appears first:
      1. A user entry with '<local-command-stdout>Set model to X</local-command-stdout>'
         (written by Claude Code when /model is run — captures PENDING model)
      2. An assistant entry's message.model (captures LAST USED model)

    This way, /model switches are reflected in the badge immediately,
    even before the first response with the new model arrives. Fully
    session-isolated — /model in other sessions writes to their JSONLs, not this one.
    """
    try:
        lines = jsonl_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        entry_type = data.get("type")

        if entry_type == "assistant":
            model = data.get("message", {}).get("model")
            if model:
                return str(model)

        if entry_type == "user":
            content = data.get("message", {}).get("content", "")
            if isinstance(content, str):
                m = _MODEL_CMD_RE.search(content)
                if m:
                    return m.group(1)
    return None


def _get_latest_model(jsonl_file: Path) -> Optional[str]:
    """Return the model to display in this session's empty-prompt badge.

    Priority:
      1. Last assistant entry in THIS session's JSONL (what this session
         has actually been using — session-local, not affected by /model
         switches in other VSCode instances)
      2. ~/.claude/settings.json `model` (fallback for brand-new sessions
         with no assistant messages yet)

    Rationale: settings.json is GLOBAL across all VSCode instances. Using
    it as the primary source makes unrelated session pages display the
    wrong model after a /model switch in another project's instance.
    """
    return _get_latest_model_from_jsonl(jsonl_file) or _get_current_model_from_settings()


def _get_custom_title(jsonl_file: Path, session_id: str) -> Optional[str]:
    """Extract the custom title for a session directly from the JSONL file.

    load_transcript() skips CustomTitleTranscriptEntry during date filtering,
    so we read the JSONL directly to reliably find the custom title.
    Returns the LAST matching entry (most recent override wins).
    """
    result: Optional[str] = None
    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
            if (
                data.get("type") == "custom-title"
                and data.get("sessionId") == session_id
            ):
                result = str(data["customTitle"])
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def _update_custom_title(jsonl_file: Path, session_id: str, new_title: str) -> None:
    """Add or update a custom-title entry in the JSONL file.

    Removes ALL existing custom-title entries (regardless of sessionId) and
    appends a single authoritative entry. This prevents stale/garbage entries
    written by Claude Code from confusing VS Code extension (which reads the
    first matching entry).
    """
    lines = jsonl_file.read_text(encoding="utf-8").splitlines()
    new_entry = json.dumps(
        {"type": "custom-title", "customTitle": new_title, "sessionId": session_id},
        ensure_ascii=False,
    )

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            data = json.loads(stripped)
            if data.get("type") == "custom-title":
                continue  # Remove all custom-title entries
        except json.JSONDecodeError:
            pass
        new_lines.append(line)

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
        from .converter import process_projects_hierarchy

        process_projects_hierarchy(projects_dir, use_cache=True, silent=True, cache_only=True)
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
                custom_title = _get_custom_title(jsonl_file, session_id)
                html = renderer.generate_session(messages, session_id, title=custom_title)
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
            event_queue: "Queue[str]" = Queue()
            handler = _SSEFileWatcher(
                {jsonl_file: "jsonl", _CLAUDE_SETTINGS_PATH: "settings"},
                event_queue,
            )
            observer = Observer()
            # watchdog watches directories; one schedule per unique parent.
            scheduled_dirs: set[Path] = set()
            for target in (jsonl_file, _CLAUDE_SETTINGS_PATH):
                parent = target.parent
                if parent.exists() and parent not in scheduled_dirs:
                    observer.schedule(handler, str(parent), recursive=False)
                    scheduled_dirs.add(parent)
            observer.start()

            last_size = jsonl_file.stat().st_size if jsonl_file.exists() else 0
            last_mtime = jsonl_file.stat().st_mtime if jsonl_file.exists() else 0.0
            last_model = _get_latest_model(jsonl_file)

            try:
                # Initial model so the badge is correct immediately on connect
                if last_model:
                    yield f"data: {json.dumps({'type': 'model', 'model': last_model})}\n\n"
                print(f"[SSE] watchdog watching {jsonl_file.name} + settings.json")

                while True:
                    try:
                        tag = event_queue.get(timeout=15.0)
                    except Empty:
                        yield ":\n\n"  # SSE keepalive
                        continue

                    # Burst drain + settle
                    tags = {tag}
                    try:
                        while True:
                            tags.add(event_queue.get_nowait())
                    except Empty:
                        pass
                    time_module.sleep(0.3)
                    try:
                        while True:
                            tags.add(event_queue.get_nowait())
                    except Empty:
                        pass

                    if "jsonl" in tags:
                        try:
                            stat = jsonl_file.stat()
                        except FileNotFoundError:
                            yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                            break
                        if stat.st_size != last_size or stat.st_mtime != last_mtime:
                            print(f"[SSE] jsonl changed: size {last_size}->{stat.st_size}")
                            last_size = stat.st_size
                            last_mtime = stat.st_mtime
                            model = _get_latest_model(jsonl_file)
                            last_model = model
                            yield f"data: {json.dumps({'type': 'updated', 'model': model})}\n\n"
                            continue

                    # settings.json watchdog event → read directly from settings.json.
                    # Must NOT use _get_latest_model() here: it prioritises JSONL which
                    # hasn't been flushed yet (/model only writes to JSONL at message-send).
                    current_model = _get_current_model_from_settings() or _DEFAULT_MODEL
                    if current_model != last_model:
                        last_model = current_model
                        print(f"[SSE] settings.json model -> {current_model}")
                        yield f"data: {json.dumps({'type': 'model', 'model': current_model})}\n\n"

            finally:
                observer.stop()
                observer.join(timeout=2)

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
        custom_title = _get_custom_title(jsonl_file, session_id)
        html = renderer.generate_session(messages, session_id, title=custom_title)
        print(f"[render_session] session={session_id[:8]}, messages={len(messages)}, html_len={len(html)}, jsonl_size={jsonl_file.stat().st_size}")
        return Response(html, mimetype="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    @app.route("/api/sessions/<session_id>/messages")
    def render_messages(session_id: str) -> Response:
        """Return messages for live updates. Use ?after=N to get only new messages.

        total = len(flattened template messages) — no string markers used,
        so conversation content can never corrupt the count.
        """
        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is None:
            return jsonify({"error": "session not found"}), 404  # type: ignore[return-value]

        from .converter import load_transcript
        from .html.renderer import HtmlRenderer

        messages = load_transcript(jsonl_file, silent=True)
        renderer = HtmlRenderer()
        template_messages = renderer.get_template_messages(messages, session_id=session_id)
        total_msgs = len(template_messages)

        model = _get_latest_model(jsonl_file)

        after = request.args.get('after', type=int)
        if after is not None:
            if after >= total_msgs:
                print(f"[render_messages] session={session_id[:8]}, total={total_msgs}, after={after}, up-to-date")
                return Response(
                    json.dumps({"total": total_msgs, "html": "", "model": model}),
                    mimetype="application/json",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
            new_tmpl = template_messages[after:]
            new_html = renderer.render_fragment(new_tmpl)
            print(f"[render_messages] session={session_id[:8]}, total={total_msgs}, after={after}, new={len(new_tmpl)}")
            return Response(  # type: ignore[return-value]
                json.dumps({"total": total_msgs, "html": new_html, "model": model}),
                mimetype="application/json",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

        # Full fragment (no after param)
        full_html = renderer.render_fragment(template_messages)
        print(f"[render_messages] session={session_id[:8]}, total={total_msgs}, fragment_len={len(full_html)}")
        return Response(  # type: ignore[return-value]
            json.dumps({"total": total_msgs, "html": full_html, "model": model}),
            mimetype="application/json",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

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
