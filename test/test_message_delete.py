"""고른 문답만 지우고, 대화 사슬은 성하게 남기는가.

이 기능의 위험은 하나로 요약된다 — **JSONL 이 트리처럼 보이지만 실은 연결
리스트**라는 것. 각 메시지의 부모가 바로 앞 메시지라, 자손을 따라가며 지우면
그 뒤 대화가 통째로 사라진다. 여기 시험들은 그 경계와 사슬 복구를 못 박는다.

지우는 단위는 **고른 메시지 하나**다. 질문만, 답변만, 또는 둘 다 고를 수 있다 —
답변만 골라 내보내거나 지우고 싶을 때가 있기 때문이다. 딸린 attachment 는 그
메시지와 운명을 같이한다.
"""

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from claude_code_log import message_delete as md

CWD = "C:/work"


def _entry(
    kind: str,
    uid: str,
    parent: Optional[str],
    text: str = "",
    ts: str = "2026-08-26T00:00:00.000Z",
) -> "dict[str, Any]":
    row: "dict[str, Any]" = {
        "type": kind,
        "uuid": uid,
        "parentUuid": parent,
        "cwd": CWD,
        "sessionId": "s1",
        "timestamp": ts,
    }
    if kind in ("user", "assistant"):
        row["message"] = {
            "role": kind,
            "content": [{"type": "text", "text": text}],
        }
        if kind == "assistant":
            row["message"]["model"] = "claude-sonnet-5"
    return row


def _write(path: Path, rows: "list[dict[str, Any]]") -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    """사람 문답 → 자동 메시지 → 자동 메시지 → 사람 문답, 한 줄로 이어진 기록.

    실제 파일과 같은 모양으로 만든다. 질문 뒤에 attachment 가 끼고, 그 다음이
    응답이며, 다음 질문은 **앞 응답을 부모로** 삼는다.
    """
    rows = [
        _entry("user", "u1", None, "안녕하세요"),
        _entry("attachment", "at1", "u1"),
        _entry("assistant", "a1", "at1", "네 안녕하세요"),
        # 자동 메시지 ①
        _entry("user", "k1", "a1", "세션 유지용 메세지"),
        _entry("attachment", "at2", "k1"),
        _entry("assistant", "a2", "at2", "ok"),
        # 자동 메시지 ②
        _entry("user", "k2", "a2", "세션 유지용 메세지"),
        _entry("attachment", "at3", "k2"),
        _entry("attachment", "at4", "at3"),
        _entry("assistant", "a3", "at4", "ok"),
        # 사람 문답
        _entry("user", "u2", "a3", "다음 질문입니다"),
        _entry("attachment", "at5", "u2"),
        _entry("assistant", "a4", "at5", "답변입니다"),
    ]
    path = tmp_path / "s1.jsonl"
    _write(path, rows)
    return path


def _rows(path: Path) -> "list[dict[str, Any]]":
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def test_unit_is_the_message_and_only_its_own_attachments(transcript: Path) -> None:
    """지우는 단위는 고른 메시지 하나와 거기 딸린 것뿐이다.

    이 경계가 없으면 자손을 따라가다 뒤 대화 전체를 삼킨다. 실제 세션에서
    3줄짜리를 지우려다 22줄이 지워진 적이 있다.
    """
    rows = _rows(transcript)

    # 질문을 고르면 질문 + 그 attachment 까지. 답변은 딸려오지 않는다.
    assert md.unit_of(rows, "k1") == {"k1", "at2"}
    # 답변만 고를 수도 있다
    assert md.unit_of(rows, "a2") == {"a2"}
    # 뒤따르는 것들은 절대 들어오면 안 된다
    assert not md.unit_of(rows, "k1") & {"k2", "at3", "at4", "a3", "u2", "at5", "a4"}


def test_exchange_of_still_groups_a_whole_pair(transcript: Path) -> None:
    """문답 한 쌍을 묶는 계산은 남겨둔다 — 화면이 답변까지 함께 고를 때 쓴다."""
    group = md.exchange_of(_rows(transcript), "k1")
    assert group == {"k1", "at2", "a2"}


def test_deleting_one_exchange_keeps_the_chain_whole(transcript: Path) -> None:
    """지운 자리를 건너뛰도록 사슬이 다시 이어지는가."""
    before = md.verify_chain(_rows(transcript))
    assert before[0] is True

    # 질문과 답변을 함께 골랐을 때만 둘 다 지워진다
    result = md.delete_exchanges(transcript, ["k1", "a2"])
    assert result["ok"] is True, result.get("error")
    assert result["removed_lines"] == 3
    assert result["removed_messages"] == 2
    assert result["removed_questions"] == 1
    assert result["removed_answers"] == 1
    assert result["relinked"] == 1

    rows = _rows(transcript)
    ok, reason, hops = md.verify_chain(rows)
    assert ok is True, reason
    # 지운 3단계만큼만 짧아져야 한다
    assert hops == before[2] - 3

    # 다음 자동 메시지가 지워진 것의 부모로 옮겨붙었는가
    k2 = next(r for r in rows if r["uuid"] == "k2")
    assert k2["parentUuid"] == "a1"

    # 고아가 없어야 한다
    alive = {r["uuid"] for r in rows}
    assert not [
        r for r in rows if r["parentUuid"] is not None and r["parentUuid"] not in alive
    ]


def test_deleting_several_at_once(transcript: Path) -> None:
    """자동 메시지 두 건을 한 번에 지워도 사람 대화는 이어진다."""
    result = md.delete_exchanges(transcript, ["k1", "a2", "k2", "a3"])
    assert result["ok"] is True, result.get("error")
    assert result["removed_lines"] == 7
    assert result["removed_messages"] == 4

    rows = _rows(transcript)
    ok, reason, _ = md.verify_chain(rows)
    assert ok is True, reason

    # 사람 대화만 남았는가
    texts = [
        r["message"]["content"][0]["text"]
        for r in rows
        if r["type"] in ("user", "assistant")
    ]
    assert texts == ["안녕하세요", "네 안녕하세요", "다음 질문입니다", "답변입니다"]

    u2 = next(r for r in rows if r["uuid"] == "u2")
    assert u2["parentUuid"] == "a1"


def test_deleting_the_last_exchange(transcript: Path) -> None:
    """맨 끝 문답을 지우면 재연결할 자식이 없다 — 그래도 성해야 한다."""
    result = md.delete_exchanges(transcript, ["u2", "a4"])
    assert result["ok"] is True, result.get("error")
    assert result["relinked"] == 0

    rows = _rows(transcript)
    ok, reason, _ = md.verify_chain(rows)
    assert ok is True, reason
    assert not [r for r in rows if r["uuid"] == "u2"]


def test_backup_is_written_before_touching_the_file(transcript: Path) -> None:
    """되돌릴 수 없는 작업이므로 원본이 남아야 한다."""
    original = transcript.read_text(encoding="utf-8")

    result = md.delete_exchanges(transcript, ["k1"])
    assert result["ok"] is True

    backup = transcript.parent / result["backup"]
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original
    assert transcript.read_text(encoding="utf-8") != original


def test_untouched_lines_are_written_byte_for_byte(transcript: Path) -> None:
    """건드리지 않은 줄은 원본 그대로 남는가.

    다시 직렬화하면 키 순서나 표기가 미묘하게 달라져, 나중에 원본과 비교하기
    어려워진다. 부모를 고쳐 쓴 줄만 새로 만든다.
    """
    before = {
        json.loads(ln)["uuid"]: ln
        for ln in transcript.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }
    md.delete_exchanges(transcript, ["k1"])
    after = {
        json.loads(ln)["uuid"]: ln
        for ln in transcript.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }
    # 질문 k1 만 지웠으니 그 답변 a2 의 부모가 바뀐다. 나머지는 글자 그대로여야 한다
    for uid, line in after.items():
        if uid == "a2":
            continue
        assert line == before[uid], f"{uid} 가 다시 직렬화됐다"


def test_unknown_uuid_is_refused(transcript: Path) -> None:
    """모르는 항목이 섞이면 아무것도 하지 않는다."""
    original = transcript.read_text(encoding="utf-8")
    result = md.delete_exchanges(transcript, ["k1", "없는uuid"])
    assert result["ok"] is False
    assert "없" in result["error"]
    assert transcript.read_text(encoding="utf-8") == original


def test_empty_selection_is_refused(transcript: Path) -> None:
    original = transcript.read_text(encoding="utf-8")
    assert md.delete_exchanges(transcript, [])["ok"] is False
    assert transcript.read_text(encoding="utf-8") == original


def test_plan_reports_what_would_go(transcript: Path) -> None:
    """미리보기는 파일을 건드리지 않는다."""
    original = transcript.read_text(encoding="utf-8")
    plan = md.plan_deletion(transcript, ["k1", "a2", "k2", "a3"])

    assert plan["lines"] == 7
    assert plan["messages"] == 4
    assert plan["questions"] == 2
    assert plan["answers"] == 2
    assert plan["unknown"] == []
    assert transcript.read_text(encoding="utf-8") == original


def test_restore_brings_the_deleted_messages_back(transcript: Path) -> None:
    """되돌리기가 삭제 이전 상태를 글자 그대로 복원하는가."""
    original = transcript.read_text(encoding="utf-8")
    deleted = md.delete_exchanges(transcript, ["k1", "k2"])
    assert deleted["ok"] is True
    assert transcript.read_text(encoding="utf-8") != original

    result = md.restore_backup(transcript, deleted["backup"])
    assert result["ok"] is True, result.get("error")
    assert transcript.read_text(encoding="utf-8") == original

    ok, reason, _ = md.verify_chain(_rows(transcript))
    assert ok is True, reason


def test_restore_keeps_the_state_it_replaced(transcript: Path) -> None:
    """되돌리기도 덮어쓰기다. 잘못 눌러도 다시 앞으로 갈 수 있어야 한다."""
    deleted = md.delete_exchanges(transcript, ["k1"])
    after_delete = transcript.read_text(encoding="utf-8")

    restored = md.restore_backup(transcript, deleted["backup"])
    assert restored["ok"] is True
    assert restored["safety_backup"]

    # 되돌리기 직전 상태(삭제된 판)가 백업으로 남아, 그것으로 다시 갈 수 있다
    forward = md.restore_backup(transcript, restored["safety_backup"])
    assert forward["ok"] is True
    assert transcript.read_text(encoding="utf-8") == after_delete


def test_backups_are_listed_newest_first(transcript: Path) -> None:
    md.delete_exchanges(transcript, ["k1"])
    md.delete_exchanges(transcript, ["k2"])

    listed = md.list_backups(transcript)
    # 두 번 지웠으면 백업도 둘이어야 한다. 파일명이 초 단위라 같은 초에
    # 두 번 하면 이름이 겹치는데, 그때 덮어쓰면 되돌릴 곳이 사라진다.
    assert len(listed) == 2
    assert listed[0]["name"] != listed[1]["name"]
    # 파일명이 아니라 읽을 수 있는 시각으로 보여준다
    assert ":" in listed[0]["label"]


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "..\\other.jsonl",
        "s1.jsonl.bak-hello",
        "다른세션.jsonl.bak-20260826-120000",
        "",
    ],
)
def test_restore_refuses_names_outside_this_session(
    transcript: Path, name: str
) -> None:
    """백업 이름만 받고, 이 세션의 형식일 때만 연다.

    경로를 그대로 받으면 세션 밖 파일을 기록 위에 덮어쓸 수 있다.
    """
    before = transcript.read_text(encoding="utf-8")
    result = md.restore_backup(transcript, name)
    assert result["ok"] is False
    assert transcript.read_text(encoding="utf-8") == before


def test_restore_refuses_a_corrupt_backup(transcript: Path) -> None:
    """사슬이 끊긴 백업으로는 되돌리지 않는다."""
    deleted = md.delete_exchanges(transcript, ["k1"])
    backup = transcript.parent / deleted["backup"]
    # 백업을 일부러 망가뜨린다 — 중간 항목을 이어붙이지 않고 빼버린다
    rows = [
        json.loads(ln)
        for ln in backup.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    broken = [r for r in rows if r["uuid"] != "a1"]
    _write(backup, broken)

    before = transcript.read_text(encoding="utf-8")
    result = md.restore_backup(transcript, deleted["backup"])
    assert result["ok"] is False
    assert "온전" in result["error"]
    assert transcript.read_text(encoding="utf-8") == before


def test_broken_chain_is_detected(tmp_path: Path) -> None:
    """사슬이 끊긴 상태를 실제로 알아채는가 — 검사기 자체의 시험."""
    path = tmp_path / "broken.jsonl"
    _write(
        path,
        [
            _entry("user", "u1", None, "안녕"),
            _entry("assistant", "a1", "사라진부모", "응답"),
        ],
    )
    ok, reason, _ = md.verify_chain(_rows(path))
    assert ok is False
    assert "끊" in reason


def test_deleting_only_the_answer(transcript: Path) -> None:
    """답변만 지우고 질문은 남길 수 있다.

    자동 메시지의 'ok' 만 걷어내고 싶을 때가 있다. 막지 않는다 —
    다만 답변을 잃는 질문이 생겼음을 미리 알린다.
    """
    plan = md.plan_deletion(transcript, ["a2"])
    assert plan["messages"] == 1
    assert plan["questions"] == 0
    assert plan["answers"] == 1
    assert plan["unanswered"] == 1  # k1 이 답변을 잃는다

    result = md.delete_exchanges(transcript, ["a2"])
    assert result["ok"] is True, result.get("error")

    rows = _rows(transcript)
    ok, reason, _ = md.verify_chain(rows)
    assert ok is True, reason
    # 질문은 남고 답변만 사라졌다
    assert [r for r in rows if r["uuid"] == "k1"]
    assert not [r for r in rows if r["uuid"] == "a2"]
    # 다음 문답이 지운 자리를 건너뛰어 이어졌는가
    assert next(r for r in rows if r["uuid"] == "k2")["parentUuid"] == "at2"


def test_deleting_only_the_question(transcript: Path) -> None:
    """질문만 지우고 답변을 남길 수도 있다."""
    result = md.delete_exchanges(transcript, ["k1"])
    assert result["ok"] is True, result.get("error")
    assert result["removed_questions"] == 1
    assert result["removed_answers"] == 0

    rows = _rows(transcript)
    ok, reason, _ = md.verify_chain(rows)
    assert ok is True, reason
    assert not [r for r in rows if r["uuid"] == "k1"]
    # 답변은 남고, 지운 질문의 부모로 옮겨붙었다
    assert next(r for r in rows if r["uuid"] == "a2")["parentUuid"] == "a1"


def test_unanswered_warning_counts_only_new_cases(transcript: Path) -> None:
    """질문과 답변을 함께 지우면 '답변 잃은 질문' 은 생기지 않는다."""
    plan = md.plan_deletion(transcript, ["k1", "a2"])
    assert plan["unanswered"] == 0
