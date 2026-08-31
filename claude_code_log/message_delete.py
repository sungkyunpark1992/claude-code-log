"""대화 기록에서 문답을 골라 지운다.

자동 메시지나 실수로 보낸 질문이 기록을 어지럽힐 때 쓴다. 토큰을 아끼려는 것이
아니다 — 자동 메시지는 파일의 2~3% 밖에 안 되고, 대화 중간을 지우면 그 지점부터
캐시가 무효가 되어 오히려 손해다. **읽기 좋게 만드는 것**이 목적이다.

## 반드시 지켜야 하는 두 가지

**① 덩어리의 끝은 '다음 질문 직전'이다**

Claude Code 의 JSONL 은 트리처럼 보이지만 사실상 **연결 리스트**다. 각 메시지의
부모가 바로 앞 메시지라, "이 노드의 자손을 전부 지운다"고 하면 **그 뒤 대화가
통째로 딸려 나온다.** 실측에서 문답 하나(3줄)를 지우려다 22줄이 지워졌다.

    [193] user       uuid=4276d774  parent=abef23fe   ← 지우려는 것
    [194] attachment uuid=a87eca71  parent=4276d774
    [196] assistant  uuid=be51107e  parent=a87eca71
    [200] user       uuid=236f8a66  parent=be51107e   ← 다음 문답이 여기 매달린다
                                                         (여기서 멈춰야 한다)

**② 자식을 죽은 노드의 부모로 다시 이어야 한다**

VS Code 는 마지막 메시지에서 `parentUuid` 를 거슬러 올라가며 대화를 복원한다.
고리 하나만 끊겨도 그 앞이 전부 보이지 않는다. 지운 자리를 건너뛰도록
살아남은 조상으로 이어붙인다.

    지우기 전 :  A ← B ← C
    그냥 지우면:  A     ← C      C 의 부모가 없다 → 끊김
    다시 이으면:  A ← C          C.parentUuid 를 B 에서 A 로
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

# 대화를 이루는 항목. 나머지(attachment, queue-operation 등)는 딸린 것으로 본다.
CONVERSATION_TYPES = ("user", "assistant")


def load_rows(jsonl_file: Path) -> "list[dict[str, Any]]":
    """파싱된 항목만. 호출자가 uuid 를 되짚을 때 쓴다."""
    return _load(jsonl_file)[0]


def _load(jsonl_file: Path) -> "tuple[list[dict[str, Any]], list[str]]":
    """(파싱된 항목, 원본 줄) — 원본 줄은 건드리지 않은 항목을 그대로 쓰기 위해서다."""
    rows: "list[dict[str, Any]]" = []
    raw: "list[str]" = []
    for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        rows.append(cast("dict[str, Any]", parsed))
        raw.append(line)
    return rows, raw


def exchange_of(rows: "list[dict[str, Any]]", user_uuid: str) -> "set[str]":
    """질문 하나와 거기 딸린 항목들의 uuid.

    **다음 질문(user) 을 만나면 멈춘다.** 이 경계가 없으면 뒤 대화 전체가 딸려온다.
    """
    children: "dict[Optional[str], list[dict[str, Any]]]" = {}
    for entry in rows:
        children.setdefault(entry.get("parentUuid"), []).append(entry)

    group = {user_uuid}
    frontier = [user_uuid]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            uid = child.get("uuid")
            if not isinstance(uid, str) or uid in group:
                continue
            if child.get("type") == "user":
                continue  # 다음 문답의 시작 — 여기가 경계다
            group.add(uid)
            frontier.append(uid)
    return group


def unit_of(rows: "list[dict[str, Any]]", uuid: str) -> "set[str]":
    """메시지 하나와 **거기에만 딸린 것들**.

    `exchange_of` 와 달리 문답 한 쌍이 아니라 고른 그 메시지만 본다. 답변 하나만
    지우고 질문은 남기는 것도 할 수 있어야 하기 때문이다.

    딸린 것이란 `attachment` 같은 대화 아닌 항목이다. 그것들은 홀로 의미가 없어
    붙어 있던 메시지와 운명을 같이한다. 다음 대화 항목(user/assistant)을 만나면
    거기서 멈춘다 — 그건 다른 메시지의 몫이다.
    """
    children: "dict[Optional[str], list[dict[str, Any]]]" = {}
    for entry in rows:
        children.setdefault(entry.get("parentUuid"), []).append(entry)

    group = {uuid}
    frontier = [uuid]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            cid = child.get("uuid")
            if not isinstance(cid, str) or cid in group:
                continue
            if child.get("type") in CONVERSATION_TYPES:
                continue  # 다른 메시지의 시작 — 여기가 경계다
            group.add(cid)
            frontier.append(cid)
    return group


def questions_left_unanswered(
    rows: "list[dict[str, Any]]", doomed: "set[str]"
) -> "list[dict[str, Any]]":
    """지우고 나면 답변이 하나도 남지 않는 질문들.

    막지는 않는다 — 답변만 지우고 싶을 때가 있다. 다만 확인창에서 알려주어
    모르고 그렇게 되는 일은 없게 한다.
    """
    by_uuid = {e["uuid"]: e for e in rows if isinstance(e.get("uuid"), str)}
    answered: "dict[str, int]" = {}

    def owner(entry: "dict[str, Any]") -> Optional[str]:
        """이 답변이 어느 질문에 달린 것인가."""
        seen: "set[str]" = set()
        cur = entry.get("parentUuid")
        while isinstance(cur, str) and cur not in seen:
            seen.add(cur)
            node = by_uuid.get(cur)
            if node is None:
                return None
            if node.get("type") == "user":
                uid = node.get("uuid")
                return uid if isinstance(uid, str) else None
            cur = node.get("parentUuid")
        return None

    for entry in rows:
        if entry.get("type") != "assistant":
            continue
        root = owner(entry)
        if root is None:
            continue
        answered.setdefault(root, 0)
        if entry.get("uuid") not in doomed:
            answered[root] += 1

    return [
        by_uuid[root]
        for root, left in answered.items()
        if left == 0 and root not in doomed and root in by_uuid
    ]


def resolve_roots(
    rows: "list[dict[str, Any]]", uuids: "list[str]"
) -> "tuple[list[str], list[str]]":
    """고른 항목이 속한 문답의 '질문'을 찾아 준다. (찾은 것, 못 찾은 것)

    사람은 답변에 체크하고 지우려 할 수도 있다. 답변만 지우면 질문이 홀로 남아
    대화가 이상해지므로, 어느 것을 골랐든 그 문답 전체를 대상으로 삼는다.
    """
    by_uuid = {e["uuid"]: e for e in rows if isinstance(e.get("uuid"), str)}
    roots: "list[str]" = []
    missing: "list[str]" = []
    for uid in uuids:
        current = by_uuid.get(uid)
        seen: "set[str]" = set()
        while current is not None:
            cur_id = current.get("uuid")
            if not isinstance(cur_id, str) or cur_id in seen:
                current = None
                break
            seen.add(cur_id)
            if current.get("type") == "user":
                break
            parent = current.get("parentUuid")
            current = by_uuid.get(parent) if isinstance(parent, str) else None
        if current is None:
            missing.append(uid)
            continue
        root = current.get("uuid")
        if isinstance(root, str) and root not in roots:
            roots.append(root)
    return roots, missing


def plan_deletion(jsonl_file: Path, uuids: "list[str]") -> "dict[str, Any]":
    """무엇이 지워질지 미리 계산한다. 파일은 건드리지 않는다.

    **고른 것만** 지운다. 질문을 골랐다고 답변까지 딸려가지 않는다 —
    답변만 지우고 싶을 때가 있기 때문이다. 대신 그 결과로 답변을 잃는 질문이
    생기면 `unanswered` 로 알려 확인창에서 보여준다.
    """
    rows, _ = _load(jsonl_file)
    known = {
        e["uuid"]
        for e in rows
        if isinstance(e.get("uuid"), str) and e.get("type") in CONVERSATION_TYPES
    }
    unknown = [u for u in uuids if u not in known]

    doomed: "set[str]" = set()
    for uid in uuids:
        if uid in known:
            doomed |= unit_of(rows, uid)

    removed_convo = [
        e
        for e in rows
        if e.get("uuid") in doomed and e.get("type") in CONVERSATION_TYPES
    ]
    stranded = questions_left_unanswered(rows, doomed)
    return {
        "doomed": doomed,
        "lines": len(doomed),
        "messages": len(removed_convo),
        "questions": len([e for e in removed_convo if e.get("type") == "user"]),
        "answers": len([e for e in removed_convo if e.get("type") == "assistant"]),
        "unanswered": len(stranded),
        "unknown": unknown,
        "total_lines": len(rows),
    }


def _surviving_ancestor(
    uid: Optional[str],
    by_uuid: "dict[str, dict[str, Any]]",
    doomed: "set[str]",
) -> Optional[str]:
    """지워지지 않는 가장 가까운 조상. 사슬을 이어붙일 자리다."""
    seen: "set[str]" = set()
    while isinstance(uid, str) and uid in doomed and uid not in seen:
        seen.add(uid)
        uid = by_uuid.get(uid, {}).get("parentUuid")
    return uid if isinstance(uid, str) else None


def verify_chain(rows: "list[dict[str, Any]]") -> "tuple[bool, str, int]":
    """VS Code 가 하는 일을 그대로 해본다 — 마지막 메시지에서 뿌리까지 거슬러 오르기."""
    by_uuid = {e["uuid"]: e for e in rows if isinstance(e.get("uuid"), str)}
    convo = [e for e in rows if e.get("type") in CONVERSATION_TYPES]
    if not convo:
        return True, "대화 없음", 0

    current = convo[-1]
    seen: "set[str]" = set()
    hops = 0
    while True:
        uid = current.get("uuid")
        if not isinstance(uid, str) or uid in seen:
            return False, "사슬이 순환한다", hops
        seen.add(uid)
        hops += 1
        parent = current.get("parentUuid")
        if parent is None:
            return True, "뿌리까지 이어짐", hops
        nxt = by_uuid.get(parent) if isinstance(parent, str) else None
        if nxt is None:
            return False, f"사슬이 끊겼다 (parent={str(parent)[:8]})", hops
        current = nxt


# 끝의 `-N` 은 같은 초에 두 번 이상 백업할 때 붙는 일련번호다.
BACKUP_SUFFIX_RE = re.compile(r"\.jsonl\.bak-\d{8}-\d{6}(-\d+)?$")


def backup_path(jsonl_file: Path, now: Optional[datetime] = None) -> Path:
    """아직 없는 백업 경로.

    파일명이 초 단위라, 지우고 곧바로 되돌리면 같은 이름이 나온다. 그대로 쓰면
    앞선 백업을 덮어써 되돌릴 곳이 사라지므로 일련번호를 붙여 피한다.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = jsonl_file.suffix + f".bak-{stamp}"
    candidate = jsonl_file.with_suffix(base)
    counter = 1
    while candidate.exists():
        candidate = jsonl_file.with_suffix(f"{base}-{counter}")
        counter += 1
    return candidate


def _label(name: str) -> str:
    """파일명 끝의 시각을 사람이 읽는 꼴로. 실패하면 파일명 그대로."""
    try:
        stamp = name.rsplit(".bak-", 1)[1]
    except IndexError:
        return name
    # 일련번호가 붙어 있으면 떼고 읽는다
    parts = stamp.split("-")
    try:
        moment = datetime.strptime("-".join(parts[:2]), "%Y%m%d-%H%M%S")
    except ValueError:
        return name
    return moment.strftime("%m/%d %H:%M:%S")


def list_backups(jsonl_file: Path) -> "list[dict[str, Any]]":
    """이 세션의 백업들. 최신이 먼저."""
    found: "list[dict[str, Any]]" = []
    for path in jsonl_file.parent.glob(f"{jsonl_file.name}.bak-*"):
        if not BACKUP_SUFFIX_RE.search(path.name):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        found.append(
            {
                "name": path.name,
                "label": _label(path.name),
                "size": size,
                "mtime": path.stat().st_mtime,
            }
        )
    # 만든 시각 순. 이름순으로 하면 일련번호 -10 이 -2 보다 앞서 버린다.
    found.sort(key=lambda item: (item["mtime"], item["name"]), reverse=True)
    return found


def restore_backup(jsonl_file: Path, backup_name: str) -> "dict[str, Any]":
    """백업으로 되돌린다.

    되돌리기 자체도 기록을 덮어쓰는 일이므로, 되돌리기 **전에** 지금 상태를
    새 백업으로 남긴다. 잘못 되돌렸을 때 다시 앞으로 갈 수 있어야 한다.
    """
    # 경로를 받지 않는다 — 이름만 받고, 이 세션의 백업 형식일 때만 연다.
    if "/" in backup_name or "\\" in backup_name:
        return {"ok": False, "error": "백업 이름이 올바르지 않습니다"}
    if not backup_name.startswith(jsonl_file.name + ".bak-"):
        return {"ok": False, "error": "이 세션의 백업이 아닙니다"}
    if not BACKUP_SUFFIX_RE.search(backup_name):
        return {"ok": False, "error": "백업 이름이 올바르지 않습니다"}

    source = jsonl_file.parent / backup_name
    if not source.is_file():
        return {"ok": False, "error": "백업 파일을 찾을 수 없습니다"}

    rows = _load(source)[0]
    ok, reason, hops = verify_chain(rows)
    if not ok:
        return {"ok": False, "error": f"백업이 온전하지 않습니다 — {reason}"}

    safety = backup_path(jsonl_file)
    if jsonl_file.exists() and safety.resolve() != source.resolve():
        shutil.copy2(jsonl_file, safety)
    shutil.copy2(source, jsonl_file)

    return {
        "ok": True,
        "restored_from": backup_name,
        "restored_label": _label(backup_name),
        "lines": len(rows),
        "chain_hops": hops,
        "safety_backup": safety.name if safety.exists() else None,
    }


def delete_exchanges(jsonl_file: Path, uuids: "list[str]") -> "dict[str, Any]":
    """고른 메시지를 지운다. 성공하면 {"ok": True, ...}.

    고른 것만 지운다 — 질문만, 답변만, 또는 둘 다 고를 수 있다.

    되돌릴 수 없는 작업이므로 순서를 지킨다.
      1) 무엇이 지워질지 계산
      2) 지운 결과의 사슬이 성한지 **미리** 확인 — 성하지 않으면 아무것도 안 한다
      3) 백업
      4) 쓰기
    """
    if not uuids:
        return {"ok": False, "error": "지울 항목이 없습니다"}

    rows, raw = _load(jsonl_file)
    if not rows:
        return {"ok": False, "error": "읽을 수 있는 기록이 없습니다"}

    plan = plan_deletion(jsonl_file, uuids)
    if plan["unknown"]:
        return {
            "ok": False,
            "error": f"기록에 없는 항목이 {len(plan['unknown'])}건 있습니다",
        }
    doomed = cast("set[str]", plan["doomed"])
    if not doomed:
        return {"ok": False, "error": "지울 항목이 없습니다"}

    by_uuid = {e["uuid"]: e for e in rows if isinstance(e.get("uuid"), str)}

    kept_rows: "list[dict[str, Any]]" = []
    kept_lines: "list[str]" = []
    relinked = 0
    for entry, line in zip(rows, raw):
        if entry.get("uuid") in doomed:
            continue
        parent = entry.get("parentUuid")
        if isinstance(parent, str) and parent in doomed:
            patched = dict(entry)
            patched["parentUuid"] = _surviving_ancestor(parent, by_uuid, doomed)
            kept_rows.append(patched)
            kept_lines.append(json.dumps(patched, ensure_ascii=False))
            relinked += 1
        else:
            # 손대지 않은 항목은 원본 줄을 그대로 쓴다.
            # 다시 직렬화하면 키 순서나 실수 표기가 미묘하게 달라질 수 있다.
            kept_rows.append(entry)
            kept_lines.append(line)

    ok, reason, hops = verify_chain(kept_rows)
    if not ok:
        return {"ok": False, "error": f"삭제하면 대화가 깨집니다 — {reason}"}

    backup = backup_path(jsonl_file)
    shutil.copy2(jsonl_file, backup)
    jsonl_file.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "removed_lines": len(doomed),
        "removed_messages": plan["messages"],
        "removed_questions": plan["questions"],
        "removed_answers": plan["answers"],
        "relinked": relinked,
        "remaining_lines": len(kept_rows),
        "chain_hops": hops,
        "backup": backup.name,
    }
