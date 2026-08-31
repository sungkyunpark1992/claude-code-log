"""나중에 물어볼 질문 적어두기.

프롬프트를 쓰다 "지금 말고 나중에" 물어야 할 것이 생길 때 쓴다. 그 세션의 JSONL
옆에 Markdown 한 파일로 둔다 — 다른 데 옮겨 적으면 어느 세션에서 하려던 이야기인지
잃어버리기 때문이다.

여기서 못 박는 것은 **되읽기가 깨지지 않는가** 다. 질문 본문에 `---` 나 `## ` 같은
Markdown 문법이 들어가는 일은 흔한데, 그런 줄을 경계로 삼으면 그 순간 무너진다.
"""

from pathlib import Path

import pytest

from claude_code_log import drafts as dr

SID = "cafe1111-2222-3333-4444-555566667777"


@pytest.fixture
def jsonl(tmp_path: Path) -> Path:
    path = tmp_path / f"{SID}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_saved_next_to_the_transcript(jsonl: Path) -> None:
    """대화 기록 옆에 둔다 — 열면 적어둔 질문도 곁에 있어야 한다."""
    result = dr.add_draft(jsonl, SID, "나중에 물어볼 것")
    assert result["ok"] is True

    path = dr.drafts_path(jsonl, SID)
    assert path.parent == jsonl.parent
    assert path.name == f"{SID}-질문메모.md"
    assert SID in path.read_text(encoding="utf-8")


def test_markdown_syntax_in_the_body_survives(jsonl: Path) -> None:
    """본문에 `---` 나 `## ` 가 들어가도 경계가 무너지지 않는가.

    사람이 흔히 쓰는 글자를 경계로 삼으면 여기서 깨진다. 그래서 눈에 안 보이는
    표식(`<!-- ccl-draft ... -->`)을 쓴다.
    """
    tricky = "구분선 ---\n## 제목처럼 보이는 줄\n\n본문 계속"
    dr.add_draft(jsonl, SID, tricky)

    got = dr.load_drafts(dr.drafts_path(jsonl, SID))
    assert len(got) == 1
    assert got[0]["text"] == tricky


def test_newest_first(jsonl: Path) -> None:
    """화면에서는 최근에 적은 것부터 보여야 한다."""
    dr.add_draft(jsonl, SID, "먼저 적은 것")
    dr.add_draft(jsonl, SID, "나중에 적은 것")

    got = dr.load_drafts(dr.drafts_path(jsonl, SID))
    assert [d["text"] for d in got] == ["나중에 적은 것", "먼저 적은 것"]


def test_rapid_saves_do_not_collide(jsonl: Path) -> None:
    """식별자가 초 단위라 잇달아 저장하면 겹친다 — 일련번호로 피한다."""
    for i in range(5):
        assert dr.add_draft(jsonl, SID, f"질문 {i}")["ok"] is True

    got = dr.load_drafts(dr.drafts_path(jsonl, SID))
    assert len(got) == 5
    assert len({d["id"] for d in got}) == 5


def test_empty_text_is_refused(jsonl: Path) -> None:
    assert dr.add_draft(jsonl, SID, "   \n  ")["ok"] is False
    assert not dr.drafts_path(jsonl, SID).exists()


def test_delete_leaves_the_others(jsonl: Path) -> None:
    dr.add_draft(jsonl, SID, "남길 것")
    dr.add_draft(jsonl, SID, "지울 것")
    path = dr.drafts_path(jsonl, SID)
    target = next(d for d in dr.load_drafts(path) if d["text"] == "지울 것")

    result = dr.delete_draft(jsonl, SID, str(target["id"]))
    assert result["ok"] is True

    left = dr.load_drafts(path)
    assert [d["text"] for d in left] == ["남길 것"]


def test_deleting_the_last_one_removes_the_file(jsonl: Path) -> None:
    """빈 껍데기 파일을 남기지 않는다 — 폴더가 지저분해진다."""
    dr.add_draft(jsonl, SID, "하나뿐인 질문")
    path = dr.drafts_path(jsonl, SID)
    only = dr.load_drafts(path)[0]

    dr.delete_draft(jsonl, SID, str(only["id"]))
    assert not path.exists()


def test_deleting_something_that_is_not_there(jsonl: Path) -> None:
    dr.add_draft(jsonl, SID, "질문")
    before = dr.drafts_path(jsonl, SID).read_text(encoding="utf-8")

    assert dr.delete_draft(jsonl, SID, "없는아이디")["ok"] is False
    assert dr.drafts_path(jsonl, SID).read_text(encoding="utf-8") == before


def test_missing_file_reads_as_empty(jsonl: Path) -> None:
    assert dr.load_drafts(dr.drafts_path(jsonl, SID)) == []


def test_hand_edited_file_still_reads(jsonl: Path) -> None:
    """손으로 고칠 수 있어야 한다 — 그게 Markdown 으로 둔 이유다."""
    dr.add_draft(jsonl, SID, "원래 질문")
    path = dr.drafts_path(jsonl, SID)
    text = path.read_text(encoding="utf-8").replace("원래 질문", "손으로 고친 질문")
    path.write_text(text, encoding="utf-8")

    got = dr.load_drafts(path)
    assert len(got) == 1
    assert got[0]["text"] == "손으로 고친 질문"
