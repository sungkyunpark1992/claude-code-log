"""대화 본문만 추려내기.

JSONL 을 통째로 복제해 대화를 이어가면 문맥에 대화가 아닌 것이 잔뜩 실린다.
실측한 살아있는 사슬의 구성이 이랬다.

    ba1ea00b   image 44.9% · tool_use 31.6% · tool_result 18.1% · text  5.3%
    23a08897   tool_result 59.8% · tool_use 17.0% ·               text 23.2%

문답만 남기면 문맥이 62~95% 줄어든다. 대신 도구 결과가 사라져 모델은 코드베이스를
모르게 되므로, 되짚을 수 있도록 **원본 uuid** 를 함께 남기는 것이 이 기능의 핵심이다.
"""

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from claude_code_log import digest

SID = "beef1111-2222-3333-4444-555566667777"


def _iso(n: int) -> str:
    return f"2026-08-30T0{n}:00:00.000Z"


def _row(
    kind: str,
    uid: str,
    parent: Optional[str],
    content: Any,
    n: int = 1,
) -> "dict[str, Any]":
    return {
        "type": kind,
        "uuid": uid,
        "parentUuid": parent,
        "sessionId": SID,
        "cwd": "C:/work",
        "timestamp": _iso(n),
        "message": {"role": kind, "content": content},
    }


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    """문답 사이에 도구 호출·결과·그림이 섞인 기록."""
    rows = [
        _row("user", "u1", None, "첫 질문입니다", 1),
        _row(
            "assistant",
            "a1",
            "u1",
            [
                {"type": "text", "text": "먼저 파일을 보겠습니다"},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Read",
                    "input": {"file_path": "비" * 500},
                },
            ],
            2,
        ),
        _row(
            "user",
            "r1",
            "a1",
            [
                {"type": "tool_result", "tool_use_id": "t1", "content": "가" * 800},
            ],
            3,
        ),
        _row(
            "assistant",
            "a2",
            "r1",
            [
                {"type": "text", "text": "확인했습니다. 결론은 이렇습니다"},
            ],
            4,
        ),
        _row("user", "u2", "a2", "두 번째 질문", 5),
        _row(
            "assistant",
            "a3",
            "u2",
            [
                {"type": "image", "source": {"data": "나" * 900}},
                {"type": "text", "text": "그림과 함께 설명합니다"},
            ],
            6,
        ),
    ]
    path = tmp_path / f"{SID}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_only_conversation_text_survives(transcript: Path) -> None:
    """도구 호출·결과·그림은 빠지고 문답 본문만 남는가."""
    text = digest.build_digest(transcript, SID)["text"]

    assert "첫 질문입니다" in text
    assert "먼저 파일을 보겠습니다" in text
    assert "확인했습니다. 결론은 이렇습니다" in text
    assert "그림과 함께 설명합니다" in text

    # 덩치를 차지하던 것들은 사라져야 한다
    assert "비" * 100 not in text
    assert "가" * 100 not in text
    assert "나" * 100 not in text


def test_each_message_carries_its_uuid(transcript: Path) -> None:
    """되짚을 수 있어야 한다 — 이게 없으면 근거를 확인할 길이 없다."""
    text = digest.build_digest(transcript, SID)["text"]
    for uid in ("u1", "a1", "a2", "u2", "a3"):
        assert f"uuid: {uid}" in text, f"{uid} 가 빠졌다"


def test_header_says_where_it_came_from(transcript: Path) -> None:
    """세션 ID·원본 경로·화면 주소가 내용 안에 있어야 찾아갈 수 있다."""
    text = digest.build_digest(transcript, SID)["text"]
    assert SID in text
    assert str(transcript) in text
    assert f"session-{SID}.html" in text


def test_numbering_is_turn_and_step(transcript: Path) -> None:
    """한 질문에 답변이 여러 번 오므로 질문 번호만으로는 가리킬 수 없다."""
    text = digest.build_digest(transcript, SID)["text"]
    assert "## 1-1." in text  # 첫 질문
    assert "## 1-2." in text  # 그 답변
    assert "## 2-1." in text  # 두 번째 질문


def test_stats_report_how_much_was_dropped(transcript: Path) -> None:
    """얼마나 덜어냈는지 알려야 이 기능을 쓸지 판단할 수 있다."""
    result = digest.build_digest(transcript, SID)
    assert result["chars"] < result["total_chars"]
    assert 0 < result["ratio"] < 0.5, f"덜어낸 정도가 이상하다: {result['ratio']}"
    assert result["messages"] == 5  # tool_result 만 있는 차례는 남길 글이 없다


def test_live_chain_is_the_default(tmp_path: Path) -> None:
    """압축·분기로 사슬 밖에 남은 것은 기본으로 빼고, 몇 건인지 알린다.

    모델이 실제로 기억하는 범위가 사슬이다. 파일 전체를 담으면 새 세션에
    옮겨 붙일 수 없을 만큼 커진다 (실측: 62MB 파일의 대화 4,657건 중 사슬 473건).
    """
    rows = [
        _row("user", "old1", None, "압축으로 잘려나간 옛 질문", 1),
        _row("assistant", "old2", "old1", [{"type": "text", "text": "옛 답변"}], 2),
        # 사슬이 여기서 새로 시작한다 (parentUuid 가 앞을 가리키지 않는다)
        _row("user", "new1", None, "살아있는 질문", 3),
        _row(
            "assistant", "new2", "new1", [{"type": "text", "text": "살아있는 답변"}], 4
        ),
    ]
    path = tmp_path / f"{SID}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )

    only = digest.build_digest(path, SID)
    assert "살아있는 질문" in only["text"]
    assert "압축으로 잘려나간 옛 질문" not in only["text"]
    assert only["chain"] == 2
    assert only["all_messages"] == 4
    assert "2건이 더 있음" in only["text"]

    every = digest.build_digest(path, SID, chain_only=False)
    assert "압축으로 잘려나간 옛 질문" in every["text"]
    assert every["messages"] == 4


def test_turn_with_no_text_is_skipped(transcript: Path) -> None:
    """도구 결과만 있는 차례는 남길 글이 없으므로 빈 항목을 만들지 않는다."""
    text = digest.build_digest(transcript, SID)["text"]
    # tool_result 만 있던 r1 은 제목조차 나오지 않아야 한다
    assert "uuid: r1" not in text
