"""나중에 물어볼 질문을 적어 두는 곳.

프롬프트를 쓰다 보면 "지금 말고 나중에" 물어야 할 것이 생긴다. 그때마다 다른
곳에 옮겨 적으면 어느 세션에서 하려던 이야기였는지 잃어버린다. 그래서 **그 세션의
JSONL 옆**에 함께 둔다 — 대화 기록을 열면 적어둔 질문도 바로 곁에 있다.

## 왜 Markdown 한 파일인가

편집기로 열어 손으로 고칠 수 있어야 한다. JSON 으로 두면 사람이 읽기 나쁘고,
질문마다 파일을 따로 만들면 폴더가 금세 지저분해진다.

되읽을 때 경계를 알아야 하므로 눈에 안 보이는 표식을 쓴다. 사람이 우연히 칠 만한
글(`---`, `## `)을 경계로 삼으면 질문 본문에 그런 줄이 들어가는 순간 깨진다.

    <!-- ccl-draft 20260831-183000 -->
    ## 2026-08-31 18:30:00

    (질문 본문)
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

MARKER = "<!-- ccl-draft "
MARKER_RE = re.compile(r"^<!-- ccl-draft ([0-9]{8}-[0-9]{6}(?:-[0-9]+)?) -->$")


def drafts_path(jsonl_file: Path, session_id: str) -> Path:
    return jsonl_file.with_name(f"{session_id}-질문메모.md")


def _pretty(draft_id: str) -> str:
    """20260831-183000 → 2026-08-31 18:30:00"""
    stamp = draft_id.split("-")[0:2]
    try:
        return datetime.strptime("-".join(stamp), "%Y%m%d-%H%M%S").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        return draft_id


def load_drafts(path: Path) -> "list[dict[str, Any]]":
    """적어둔 질문들. 최근 것이 먼저."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    found: "list[dict[str, Any]]" = []
    current: "Optional[dict[str, Any]]" = None
    body: "list[str]" = []
    for line in text.splitlines():
        match = MARKER_RE.match(line.strip())
        if match:
            if current is not None:
                current["text"] = "\n".join(body).strip()
                found.append(current)
            current = {"id": match.group(1), "saved_at": _pretty(match.group(1))}
            body = []
            continue
        if current is None:
            continue  # 머리말 — 표식이 나오기 전은 버린다
        # 표식 바로 뒤의 제목 줄은 사람이 읽으라고 넣은 것이라 본문이 아니다
        if not body and line.startswith("## "):
            continue
        body.append(line)
    if current is not None:
        current["text"] = "\n".join(body).strip()
        found.append(current)

    found.sort(key=lambda d: str(d["id"]), reverse=True)
    return [d for d in found if d.get("text")]


def _render(drafts: "list[dict[str, Any]]", session_id: str, jsonl_file: Path) -> str:
    project = jsonl_file.parent.name
    lines = [
        f"# 나중에 물어볼 질문 — {session_id[:8]}",
        "",
        f"- 세션 : `{session_id}`",
        f"- 원본 : `{jsonl_file}`",
        f"- 화면 : http://localhost:5678/{project}/session-{session_id}.html",
        "",
        "> 이 파일은 손으로 고쳐도 됩니다. 다만 `<!-- ccl-draft ... -->` 줄은"
        " 경계 표식이라 지우면 그 질문이 하나로 합쳐집니다.",
        "",
    ]
    # 파일에는 시간순으로 적는다 — 읽을 때 자연스럽다. 화면에서는 최신을 위로 올린다.
    for draft in sorted(drafts, key=lambda d: str(d["id"])):
        lines.append(f"{MARKER}{draft['id']} -->")
        lines.append(f"## {draft['saved_at']}")
        lines.append("")
        lines.append(str(draft["text"]).strip())
        lines.append("")
    return "\n".join(lines)


def _new_id(existing: "set[str]", now: Optional[datetime] = None) -> str:
    """초 단위라 잇달아 저장하면 겹친다 — 일련번호로 피한다."""
    base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    if base not in existing:
        return base
    counter = 1
    while f"{base}-{counter}" in existing:
        counter += 1
    return f"{base}-{counter}"


def add_draft(jsonl_file: Path, session_id: str, text: str) -> "dict[str, Any]":
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "저장할 내용이 없습니다"}

    path = drafts_path(jsonl_file, session_id)
    drafts = load_drafts(path)
    draft_id = _new_id({str(d["id"]) for d in drafts})
    drafts.append({"id": draft_id, "saved_at": _pretty(draft_id), "text": body})
    try:
        path.write_text(_render(drafts, session_id, jsonl_file), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"파일을 쓰지 못했습니다: {exc}"}
    return {
        "ok": True,
        "id": draft_id,
        "saved_to": str(path),
        "count": len(drafts),
        "drafts": load_drafts(path),
    }


def delete_draft(jsonl_file: Path, session_id: str, draft_id: str) -> "dict[str, Any]":
    path = drafts_path(jsonl_file, session_id)
    drafts = load_drafts(path)
    left = [d for d in drafts if str(d["id"]) != draft_id]
    if len(left) == len(drafts):
        return {"ok": False, "error": "그런 메모가 없습니다"}
    try:
        if left:
            path.write_text(_render(left, session_id, jsonl_file), encoding="utf-8")
        else:
            # 마지막 하나를 지웠으면 빈 파일을 남기지 않는다
            path.unlink(missing_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"파일을 고치지 못했습니다: {exc}"}
    return {"ok": True, "count": len(left), "drafts": left}
