"""Local web server for serving generated HTML files with API support."""
from __future__ import annotations

import json
import re
import threading
import time as time_module
import webbrowser
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Optional, cast

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


def _has_conversation(jsonl_file: Path, probe_lines: int = 400) -> bool:
    """True if the file holds actual conversation, not just metadata.

    Claude Code writes a ~200 byte stub (ai-title + mode, no messages) into a
    project's slug folder merely from opening that folder. If a session's JSONL
    was moved elsewhere, that stub shares its filename and can win the lookup,
    producing a page with a title and no content.

    Only the head of the file is read — a real transcript has user/assistant
    entries near the start, and these files reach tens of megabytes.
    """
    try:
        with jsonl_file.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(probe_lines), handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                entry = cast("dict[str, Any]", raw)
                if entry.get("type") in ("user", "assistant"):
                    return True
    except OSError:
        return False
    return False


def _find_session_jsonl(
    projects_dir: Path, session_id: str, prefer_dir: Optional[Path] = None
) -> Optional[Path]:
    """Find the JSONL file containing the given session ID.

    Tries filename match first (e.g. {session_id}.jsonl), then falls back
    to searching for entries whose `sessionId` field actually equals the id —
    a session can live inside another file (agent/sidechain transcripts).

    The fallback matches on the parsed field, never on a raw substring. A
    transcript that merely *mentions* a session id in its message text would
    otherwise match, and callers act on the result: the delete endpoint once
    removed a live transcript because that transcript discussed the id of the
    session being deleted.

    `prefer_dir` resolves the case where the same filename exists under two
    project folders — copying a JSONL to continue a conversation from another
    directory does exactly that. Callers that know the project from the request
    URL should pass it; the others fall back to picking whichever candidate
    actually contains a conversation.
    """
    # 0차: 요청 URL 이 프로젝트를 알려준 경우 그 폴더를 먼저 본다
    if prefer_dir is not None:
        candidate = prefer_dir / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate

    # 1차: 파일명으로 검색 (가장 빠르고 정확)
    named = sorted(projects_dir.rglob(f"{session_id}.jsonl"))
    if len(named) == 1:
        return named[0]
    if named:
        # 같은 이름이 여러 폴더에 있다 — 빈 껍데기를 집지 않도록 내용을 확인한다.
        for jsonl_file in named:
            if _has_conversation(jsonl_file):
                return jsonl_file
        return max(named, key=lambda p: p.stat().st_size)

    # 2차: sessionId 필드가 실제로 일치하는 파일 검색
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        try:
            text = jsonl_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            # 값이 어디에도 없는 줄은 파싱하지 않고 건너뛴다 (대부분 여기서 걸러짐)
            if session_id not in line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            entry = cast("dict[str, Any]", raw)
            if entry.get("sessionId") == session_id:
                return jsonl_file

    return None


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _project_path_to_slug(project_path: str) -> str:
    """Claude Code's slug for a working directory.

    It replaces ':' and both slashes with '-', so c:\\kyo-prj\\app becomes
    c--kyo-prj-app. Verified against every existing project folder.
    """
    return re.sub(r"[:\\/]", "-", project_path.strip().rstrip("\\/"))


def _session_id_in_file(jsonl_file: Path) -> Optional[str]:
    """The sessionId this file's entries claim, or None if they disagree/absent."""
    found: Optional[str] = None
    try:
        with jsonl_file.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(400), handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                entry = cast("dict[str, Any]", raw)
                sid = entry.get("sessionId")
                if isinstance(sid, str) and sid:
                    if found is None:
                        found = sid
                    elif found != sid:
                        return None
    except OSError:
        return None
    return found


def _fork_session_file(
    src: Path, dst: Path, old_id: str, new_id: str, new_title: Optional[str]
) -> int:
    """Copy the JSONL, rewriting only the sessionId values. Returns the count.

    Deliberately a string replacement rather than parse -> re-serialise: these
    files reach tens of megabytes and re-serialising would rewrite every byte
    (key order, separators, escaping), making the copy needlessly different
    from the original. Both spacings are handled — the compact form dominates
    but Claude Code emits the spaced one occasionally.
    """
    text = src.read_text(encoding="utf-8", errors="replace")
    replaced = 0
    for pattern, replacement in (
        (f'"sessionId":"{old_id}"', f'"sessionId":"{new_id}"'),
        (f'"sessionId": "{old_id}"', f'"sessionId": "{new_id}"'),
    ):
        replaced += text.count(pattern)
        text = text.replace(pattern, replacement)

    if new_title:
        if not text.endswith("\n"):
            text += "\n"
        text += json.dumps(
            {"type": "custom-title", "customTitle": new_title, "sessionId": new_id},
            ensure_ascii=False,
        ) + "\n"

    dst.write_text(text, encoding="utf-8", newline="")
    return replaced


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


def _get_title_entry(
    jsonl_file: Path, session_id: str, entry_type: str, field: str
) -> Optional[str]:
    """Return the LAST title entry of the given type for this session.

    load_transcript() skips title entries during date filtering, so we read the
    JSONL directly. Both title kinds are written repeatedly as a session grows,
    so the last one wins.
    """
    result: Optional[str] = None
    for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
            if data.get("type") == entry_type and data.get("sessionId") == session_id:
                result = str(data[field])
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def _get_custom_title(jsonl_file: Path, session_id: str) -> Optional[str]:
    """Title the user set explicitly (dashboard ✏️ or the VS Code extension)."""
    return _get_title_entry(jsonl_file, session_id, "custom-title", "customTitle")


def _get_ai_title(jsonl_file: Path, session_id: str) -> Optional[str]:
    """Title Claude Code generated by summarising the conversation."""
    return _get_title_entry(jsonl_file, session_id, "ai-title", "aiTitle")


def _get_session_title(jsonl_file: Path, session_id: str) -> Optional[str]:
    """Title for a session page, matching the dashboard's priority.

    직접 수정 > Claude Code 자동 생성. 둘 다 없으면 None 이고, 호출부가
    `Session <id 앞 8자>` 로 떨어진다.
    """
    return _get_custom_title(jsonl_file, session_id) or _get_ai_title(
        jsonl_file, session_id
    )


def _update_custom_title(jsonl_file: Path, session_id: str, new_title: str) -> None:
    """Add or update a custom-title entry in the JSONL file.

    Removes ALL existing custom-title entries (regardless of sessionId) and
    appends a single authoritative entry, so the file cannot accumulate
    stale/garbage titles.

    Readers take the LAST custom-title entry, not the first — the VS Code
    extension parses the file in order and each custom-title overwrites the
    previous one. That has a consequence: while a session is open in VS Code
    the extension keeps appending its own in-memory title on every turn, so an
    edit made here is quickly buried and will not show up. Editing the title
    of a session that is not currently open works as expected.
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
        session_match = re.match(r"(.+)/session-([a-f0-9-]+)\.html$", filepath)
        if session_match:
            project_slug = session_match.group(1)
            session_id = session_match.group(2)
            # URL 이 프로젝트를 알려주므로 그 폴더를 먼저 본다. 같은 세션 JSONL 이
            # 두 폴더에 있을 때(대화를 다른 디렉토리로 이어가려고 복사한 경우)
            # 엉뚱한 쪽 — 특히 Claude Code 가 만든 빈 껍데기 — 을 집지 않는다.
            prefer_dir = (projects_dir / project_slug).resolve()
            if not str(prefer_dir).startswith(str(projects_dir.resolve())):
                prefer_dir = None  # 경로 탈출 시도는 무시하고 일반 검색으로
            jsonl_file = _find_session_jsonl(projects_dir, session_id, prefer_dir)
            # Only render dynamically when the JSONL filename matches the session_id.
            # Content-only matches (another JSONL that mentions this ID) must not be used
            # because they produce empty pages — fall through to serve the static HTML instead.
            if jsonl_file is not None and jsonl_file.stem == session_id:
                from .converter import load_transcript
                from .html.renderer import HtmlRenderer

                messages = load_transcript(jsonl_file, silent=True)
                renderer = HtmlRenderer()
                title = _get_session_title(jsonl_file, session_id)
                html = renderer.generate_session(messages, session_id, title=title)
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
        # 이 엔드포인트는 JSONL 을 다시 쓴다. 삭제와 같은 이유로 파일명을 확인한다.
        if jsonl_file.stem != session_id:
            return jsonify({"error": "filename does not match session id"}), 409  # type: ignore[return-value]

        _update_custom_title(jsonl_file, session_id, new_title)

        from .converter import process_projects_hierarchy
        process_projects_hierarchy(projects_dir, use_cache=True, silent=True)

        return jsonify({"status": "ok", "title": new_title})  # type: ignore[return-value]

    @app.route("/api/sessions/fork", methods=["POST"])
    def fork_session_api() -> Response:
        """Copy a session's JSONL under a fresh session id, for another project.

        Copy-only: the source is read and never modified, so a mistake is
        undone by deleting the result. See CUSTOM_FEATURES.md for why the id
        must change — two folders holding the same session id makes lookups
        ambiguous and lets Claude Code's empty stub win.
        """
        import shutil
        import uuid

        payload = request.get_json(silent=True)
        data = cast("dict[str, Any]", payload if isinstance(payload, dict) else {})
        raw_source = str(data.get("source") or "").strip().strip('"')
        raw_target = str(data.get("target_project") or "").strip().strip('"')
        new_title = str(data.get("title") or "").strip() or None
        copy_side = bool(data.get("copy_side", True))
        copy_memory = bool(data.get("copy_memory", True))

        def fail(message: str, status: int = 400) -> Response:
            return jsonify({"error": message}), status  # type: ignore[return-value]

        if not raw_source:
            return fail("원본 JSONL 경로가 필요합니다.")
        if not raw_target:
            return fail("대상 프로젝트 경로가 필요합니다.")

        # --- 원본 검증 -------------------------------------------------
        try:
            src = Path(raw_source).resolve()
        except OSError:
            return fail("원본 경로를 해석할 수 없습니다.")

        root = projects_dir.resolve()
        if not str(src).startswith(str(root)):
            return fail("원본은 projects 디렉토리 안에 있어야 합니다.")
        if src.suffix.lower() != ".jsonl" or not src.is_file():
            return fail("원본 .jsonl 파일을 찾을 수 없습니다.")

        old_id = src.stem
        if not _UUID_RE.match(old_id):
            return fail("원본 파일명이 세션 ID(UUID) 형식이 아닙니다.")

        # 파일명과 내용이 어긋난 파일(200바이트 껍데기 등)을 복제하면 그대로 깨진다
        inner_id = _session_id_in_file(src)
        if inner_id is None:
            return fail("원본에서 sessionId 를 확인할 수 없습니다.")
        if inner_id != old_id:
            return fail(f"파일명과 내용의 sessionId 가 다릅니다 (내용: {inner_id[:8]}).")

        # --- 대상 결정 -------------------------------------------------
        slug = _project_path_to_slug(raw_target)
        if not slug or slug in (".", ".."):
            return fail("대상 프로젝트 경로가 올바르지 않습니다.")
        dst_dir = (root / slug).resolve()
        if not str(dst_dir).startswith(str(root)) or dst_dir == root:
            return fail("대상 경로가 projects 디렉토리를 벗어납니다.")
        if dst_dir == src.parent:
            return fail("원본과 같은 프로젝트로는 복제할 수 없습니다.")

        # --- 새 세션 ID ------------------------------------------------
        new_id = ""
        for _ in range(10):
            candidate = str(uuid.uuid4())
            if not list(root.rglob(f"{candidate}.jsonl")):
                new_id = candidate
                break
        if not new_id:
            return fail("새 세션 ID 를 만들지 못했습니다.", 500)

        dst = dst_dir / f"{new_id}.jsonl"
        if dst.exists():
            return fail("대상 파일이 이미 존재합니다.", 409)

        # --- 복제 ------------------------------------------------------
        copied: "list[str]" = []
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            replaced = _fork_session_file(src, dst, old_id, new_id, new_title)
            copied.append("jsonl")

            if copy_side:
                side = src.parent / old_id
                if side.is_dir():
                    shutil.copytree(side, dst_dir / new_id)
                    copied.append("tool-results")

            if copy_memory:
                memory = src.parent / "memory"
                if memory.is_dir() and not (dst_dir / "memory").exists():
                    shutil.copytree(memory, dst_dir / "memory")
                    copied.append("memory")
        except OSError as exc:
            # 만들다 만 결과를 남기지 않는다
            for leftover in (dst, dst_dir / new_id):
                try:
                    if leftover.is_dir():
                        shutil.rmtree(leftover)
                    elif leftover.exists():
                        leftover.unlink()
                except OSError:
                    pass
            return fail(f"복제 중 오류: {exc}", 500)

        from .converter import process_projects_hierarchy

        process_projects_hierarchy(projects_dir, use_cache=True, silent=True)

        return jsonify(  # type: ignore[return-value]
            {
                "status": "ok",
                "new_session_id": new_id,
                "slug": slug,
                "target_dir": str(dst_dir),
                "replaced": replaced,
                "copied": copied,
                "size": dst.stat().st_size,
            }
        )

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
        # 파일명이 정확히 일치할 때만 지운다. _find_session_jsonl 이 필드로
        # 매칭하도록 고쳤지만, 삭제는 되돌릴 수 없으므로 한 겹 더 확인한다.
        if jsonl_file is not None:
            if jsonl_file.stem != session_id:
                return jsonify({"error": "filename does not match session id"}), 409  # type: ignore[return-value]
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
        title = _get_session_title(jsonl_file, session_id)
        html = renderer.generate_session(messages, session_id, title=title)
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
