"""대화 본문만 추려 Markdown 으로 뽑는다.

## 왜 필요한가

JSONL 을 통째로 복제해 대화를 이어가면 문맥에 **대화가 아닌 것**이 잔뜩 실린다.
실측한 네 세션의 살아있는 사슬 구성이다.

    ba1ea00b   image 44.9% · tool_use 31.6% · tool_result 18.1% · text  5.3%
    7caad578   tool_use 46.0% · tool_result 40.1% ·               text 13.9%
    23a08897   tool_result 59.8% · tool_use 17.0% ·               text 23.2%
    dabc0001   tool_use 32.0% · tool_result 30.1% ·               text 38.0%

문답만 남기면 문맥이 **62~95% 줄어든다.** 대신 도구 결과가 사라지므로 모델은
코드베이스에 대해 아는 바가 없어진다 — 설계·의사결정을 이어가는 데는 충분하고,
코드 작업을 그대로 잇는 데는 부족하다.

## 되짚을 수 있게 uuid 를 남긴다

추려낸 글만 있으면 "그때 왜 그렇게 결론냈지" 를 확인할 길이 없다. 그래서 각
문답에 **원본 uuid 와 번호**를 적어 둔다. 원본 세션에서 그 uuid 로 찾으면 추론
과정과 도구 실행 결과가 그대로 있다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

# 대화 본문으로 볼 것. 나머지(tool_use, tool_result, image, thinking)는 뺀다.
TEXT_BLOCK = "text"


def _text_of(content: Any) -> str:
    """대화 본문만. 도구 호출·결과·그림·추론은 버린다."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: "list[str]" = []
    for block in cast("list[Any]", content):
        if not isinstance(block, dict):
            continue
        b = cast("dict[str, Any]", block)
        if b.get("type") == TEXT_BLOCK and isinstance(b.get("text"), str):
            parts.append(cast(str, b["text"]))
    return "\n\n".join(parts)


def _weights(content: Any) -> "dict[str, int]":
    """무엇이 얼마나 차지하는지 — 얼마나 덜어냈는지 알리기 위해서다."""
    out: "dict[str, int]" = {}
    if isinstance(content, str):
        out["text"] = len(content)
        return out
    if not isinstance(content, list):
        return out
    for block in cast("list[Any]", content):
        if not isinstance(block, dict):
            continue
        b = cast("dict[str, Any]", block)
        kind = str(b.get("type", "?"))
        if kind == TEXT_BLOCK:
            size = len(str(b.get("text", "")))
        elif kind == "thinking":
            size = len(str(b.get("thinking", "")))
        else:
            size = len(json.dumps(b, ensure_ascii=False))
        out[kind] = out.get(kind, 0) + size
    return out


def _local(ts: Any) -> str:
    try:
        return (
            datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except (ValueError, TypeError):
        return str(ts or "")


def _load(jsonl_file: Path) -> "list[dict[str, Any]]":
    rows: "list[dict[str, Any]]" = []
    for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(cast("dict[str, Any]", parsed))
    return rows


def live_chain(rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """마지막 메시지에서 parentUuid 를 거슬러 오른 한 줄기.

    모델에 실제로 실려 가는 것이 이것이다. 파일에는 갈라진 가지와 압축으로
    잘려나간 앞부분까지 남아 있어, 파일 전체를 세면 문맥을 크게 부풀려 본다
    (실측: 62MB 파일의 대화 4,657건 중 살아있는 사슬은 473건).
    """
    by_uuid = {e["uuid"]: e for e in rows if isinstance(e.get("uuid"), str)}
    convo = [e for e in rows if e.get("type") in ("user", "assistant")]
    if not convo:
        return []
    chain: "list[dict[str, Any]]" = []
    current: "Optional[dict[str, Any]]" = convo[-1]
    seen: "set[str]" = set()
    while current is not None:
        uid = current.get("uuid")
        if not isinstance(uid, str) or uid in seen:
            break
        seen.add(uid)
        chain.append(current)
        parent = current.get("parentUuid")
        current = by_uuid.get(parent) if isinstance(parent, str) else None
    chain.reverse()
    return chain


def build_digest(
    jsonl_file: Path,
    session_id: str,
    *,
    chain_only: bool = True,
    title: Optional[str] = None,
) -> "dict[str, Any]":
    """추려낸 Markdown 과 통계.

    chain_only 면 살아있는 사슬만 — 새 세션에 옮겨 붙일 목적이라면 이쪽이다.
    끄면 파일에 남은 모든 문답을 시간순으로 담는다(읽기·보관용).
    """
    rows = _load(jsonl_file)
    convo_all = [e for e in rows if e.get("type") in ("user", "assistant")]
    chain = live_chain(rows)
    picked = chain if chain_only else convo_all

    kept: "list[dict[str, Any]]" = []
    weights: "dict[str, int]" = {}
    for entry in picked:
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = cast("dict[str, Any]", message).get("content")
        for kind, size in _weights(content).items():
            weights[kind] = weights.get(kind, 0) + size
        body = _text_of(content).strip()
        if not body:
            continue  # 도구 호출만 있는 차례 — 남길 글이 없다
        kept.append({"entry": entry, "body": body})

    total_chars = sum(weights.values())
    text_chars = sum(len(k["body"]) for k in kept)

    project = jsonl_file.parent.name
    lines: "list[str]" = []
    lines.append(f"# 대화 기록 — {title or session_id[:8]}")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| 원본 세션 ID | `{session_id}` |")
    lines.append(f"| 프로젝트 폴더 | `{project}` |")
    lines.append(f"| 원본 파일 | `{jsonl_file}` |")
    lines.append(
        f"| 원본 화면 | http://localhost:5678/{project}/session-{session_id}.html |"
    )
    lines.append(f"| 추려낸 시각 | {datetime.now():%Y-%m-%d %H:%M:%S} |")
    lines.append(
        f"| 담은 범위 | {'살아있는 사슬만' if chain_only else '파일의 모든 문답'}"
        f" · 문답 {len(kept)}건 |"
    )
    if total_chars:
        lines.append(
            f"| 덜어낸 정도 | {total_chars:,}자 → {text_chars:,}자 "
            f"({text_chars / total_chars * 100:.1f}%) |"
        )
    if chain_only and len(convo_all) > len(chain):
        lines.append(
            f"| 이 밖에 | 파일에 문답 {len(convo_all) - len(chain)}건이 더 있음"
            " (갈라진 가지 · 압축으로 잘린 앞부분) |"
        )
    lines.append("")

    if weights:
        lines.append("덜어낸 내역 (원본 기준)")
        lines.append("")
        lines.append("| 종류 | 글자 | 비중 |")
        lines.append("|---|---:|---:|")
        for kind, size in sorted(weights.items(), key=lambda x: -x[1]):
            mark = " ← 남김" if kind == TEXT_BLOCK else ""
            lines.append(
                f"| {kind} | {size:,} | {size / max(total_chars, 1) * 100:.1f}%{mark} |"
            )
        lines.append("")

    lines.append(
        "> 추론 과정·도구 실행 결과·그림은 뺐습니다. 그때의 근거를 확인하려면"
        " 각 문답에 적힌 **uuid** 로 위 원본에서 찾으세요."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 번호는 "몇 번째 문답의 몇 번째 글" 로 매긴다. 한 질문에 답변이 여러 번
    # 나뉘어 오는 일이 흔해서(도구를 쓰는 사이사이), 질문 번호만으로는 어느
    # 글을 말하는지 가리킬 수 없다.
    turn = 0
    step = 0
    for item in kept:
        entry = cast("dict[str, Any]", item["entry"])
        kind = entry.get("type")
        if kind == "user":
            turn += 1
            step = 0
        step += 1
        role = "🤷 질문" if kind == "user" else "🤖 답변"
        uid = str(entry.get("uuid") or "")
        lines.append(f"## {turn}-{step}. {role} · {_local(entry.get('timestamp'))}")
        lines.append("")
        lines.append(f"`uuid: {uid}`")
        lines.append("")
        lines.append(str(item["body"]))
        lines.append("")

    return {
        "text": "\n".join(lines),
        "session_id": session_id,
        "project": project,
        "suggested_name": f"{session_id}-대화만.md",
        "messages": len(kept),
        "chars": text_chars,
        "total_chars": total_chars,
        "ratio": (text_chars / total_chars) if total_chars else 0.0,
        "chain": len(chain),
        "all_messages": len(convo_all),
        "weights": weights,
    }
