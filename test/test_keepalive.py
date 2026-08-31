"""세션 유지용 자동 메시지 워커의 켜짐/꺼짐 판단.

여기서 지키려는 규칙은 하나다 — **워커가 스스로 끈 것은 스스로 되살리고,
사람이 끈 것은 건드리지 않는다.**

캐시가 만료된 세션에 자동 메시지를 보내면 아끼려던 것과 정반대로 캐시를 비싸게
새로 쓰게 된다. 그래서 워커는 그런 세션을 꺼둔다. 문제는 나중에 캐시가 되살아나도
그 상태가 풀리지 않으면 세션이 영영 조용히 죽는다는 것이다. 게다가 꺼졌다는 유일한
표시인 오류 문구는 새 응답이 오는 순간 지워지므로, 화면만 봐서는 알 수도 없다.

실제 전송은 하지 않는다. 주기를 크게 잡거나 활동 창을 피해 워커가 `send_keepalive`
까지 내려가지 않게 한다.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from claude_code_log import keepalive as ka

SESSION_ID = "aaaaaaaa-1111-2222-3333-444444444444"
STALE_SEEN = "2020-01-01T00:00:00.000Z"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _write_jsonl(path: Path, cwd: str, response_at: datetime) -> None:
    """마지막 응답 시각만 정확하면 되는 최소 기록."""
    stamp = _iso(response_at)
    rows: "list[dict[str, Any]]" = [
        {"type": "user", "cwd": cwd, "sessionId": SESSION_ID, "timestamp": stamp},
        {
            "type": "assistant",
            "cwd": cwd,
            "sessionId": SESSION_ID,
            "timestamp": stamp,
            "message": {
                "model": "claude-sonnet-5",
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 43232,
                    "cache_creation_input_tokens": 82,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    # 워커는 파일이 방금 바뀌었으면 "사람이 입력 중"으로 보고 비켜선다.
    # 그 창(ACTIVE_WINDOW_SEC)에 걸리지 않게 수정 시각을 과거로 민다.
    past = time.time() - ka.ACTIVE_WINDOW_SEC * 5
    os.utime(path, (past, past))


def _make(tmp_path: Path, response_at: datetime) -> "tuple[Path, Path, str]":
    projects = tmp_path / "projects"
    (projects / "C--fake").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    jsonl = projects / "C--fake" / f"{SESSION_ID}.jsonl"
    _write_jsonl(jsonl, str(work), response_at)
    return projects, jsonl, str(work)


def _worker(projects: Path, jsonl: Path, debug: bool = False) -> ka.KeepaliveWorker:
    def find(_dir: Path, session_id: str) -> Optional[Path]:
        return jsonl if session_id == SESSION_ID else None

    return ka.KeepaliveWorker(projects, find, debug=debug)


def _item(**over: Any) -> "dict[str, Any]":
    base: "dict[str, Any]" = {
        "session_id": SESSION_ID,
        "message": "ok",
        "interval": 900,
        "max": 12,
        "count": 0,
        "enabled": True,
        "stopped": False,
    }
    base.update(over)
    return base


def test_last_usage_is_read_from_the_transcript(tmp_path: Path) -> None:
    """직전 문답의 실제 토큰이 화면까지 실려 나가는가.

    이 숫자가 없으면 자동 메시지가 캐시를 맞히고 있는지(82 토큰) 빗나가고
    있는지(수십만 토큰) 화면에서 알 수 없다.
    """
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, cwd = _make(tmp_path, fresh)
    ka.save_config(projects, [_item()])

    facts = ka.read_session_facts(jsonl)
    assert facts["last_usage"] == {
        "input": 7,
        "output": 4,
        "cache_read": 43232,
        "cache_creation": 82,
    }

    shot = _worker(projects, jsonl).snapshot()[0]
    assert shot["last_usage"]["cache_read"] == 43232


def test_last_usage_is_none_without_a_transcript(tmp_path: Path) -> None:
    """읽을 파일이 없으면 토큰 칸은 비워둔다 — 0 으로 꾸며내지 않는다."""
    facts = ka.read_session_facts(tmp_path / "없는파일.jsonl")
    assert facts["last_usage"] is None


def _append_synthetic(path: Path, cwd: str, at: datetime, text: str) -> None:
    """한도 초과 등으로 실제 모델이 답하지 못했을 때 남는 가짜 응답."""
    row = {
        "type": "assistant",
        "cwd": cwd,
        "sessionId": SESSION_ID,
        "timestamp": _iso(at),
        "message": {
            "model": "<synthetic>",
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    past = time.time() - ka.ACTIVE_WINDOW_SEC * 5
    os.utime(path, (past, past))


def test_synthetic_reply_is_not_treated_as_a_response(tmp_path: Path) -> None:
    """한도 초과 안내문은 응답이 아니다.

    이것을 응답으로 세면 캐시가 만들어지지도 않았는데 '방금 갱신됨'으로 보여
    만료 버튼이 사라지고, 다음 전송은 비싼 재작성이 된다. 모델 이름도
    '<synthetic>' 으로 잘못 표시된다.
    """
    real = datetime.now(timezone.utc) - timedelta(hours=3)
    projects, jsonl, cwd = _make(tmp_path, real)
    _append_synthetic(
        jsonl, cwd, datetime.now(timezone.utc), "You've hit your session limit"
    )

    facts = ka.read_session_facts(jsonl)
    # 마지막 응답 시각은 진짜 응답의 것이어야 한다
    assert facts["last_response_at"] == _iso(real)
    assert facts["model"] == "claude-sonnet-5"
    assert facts["last_error"] is not None
    assert "session limit" in facts["last_error"]

    ka.save_config(projects, [_item()])
    shot = _worker(projects, jsonl).snapshot()[0]
    # 캐시는 3시간 전 그대로 — 만료로 보여야 만료 버튼이 나온다
    assert shot["cache_expired"] is True


def test_resume_does_not_revive_a_dead_cache(tmp_path: Path) -> None:
    """정지에서 재개해도 캐시 수명은 마지막 응답 시각에서만 흐른다.

    재개 시각을 캐시 판정에 쓰면 어제 죽은 캐시도 '방금 살아났다'고 보고
    그대로 전송해, 아끼려던 비싼 재작성을 일으킨다.
    """
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    projects, jsonl, _ = _make(tmp_path, stale)
    ka.save_config(projects, [_item(enabled=False, stopped=True, seen_at=_iso(stale))])
    worker = _worker(projects, jsonl)

    # ▶ 로 재개 — resume_at 이 지금으로 찍힌다
    assert worker.mutate(SESSION_ID, "toggle") is True
    saved = ka.load_config(projects)[0]
    assert saved["resume_at"] is not None
    assert saved["enabled"] is True

    # 화면은 여전히 '만료' 로 봐야 한다
    assert worker.snapshot()[0]["cache_expired"] is True

    # 주기가 다 차도 워커는 보내지 않고 꺼야 한다
    saved["interval"] = 0
    ka.save_config(projects, [saved])
    worker._tick()

    after = ka.load_config(projects)[0]
    assert after["enabled"] is False
    assert after["auto_off"] is True
    assert after["error"] == "캐시 만료로 중지됨"


def test_limit_message_counts_as_a_failed_send() -> None:
    """CLI 가 정상 종료해도 한도 안내문이면 실패다.

    성공으로 세면 예산만 깎이고, 캐시가 생기지 않았는데 생긴 것처럼
    다음 주기를 세게 된다.
    """
    assert ka._looks_like_limit("You've hit your session limit · resets 9pm") is True
    assert ka._looks_like_limit("Usage limit reached") is True
    assert ka._looks_like_limit("ok") is False


def test_default_interval_leaves_room_before_the_ttl(tmp_path: Path) -> None:
    """기본 주기는 TTL 보다 넉넉히 짧아야 한다.

    58분이던 시절 여유가 2분뿐이라, 잠깐만 밀려도 보낼 창을 놓치고
    그대로 캐시가 죽었다. 실제로 그렇게 놓쳤다.
    """
    window = ka.CACHE_TTL_SEC - ka.DEFAULT_INTERVAL_SEC
    assert ka.DEFAULT_INTERVAL_SEC == 3300  # 55분
    assert window >= 300, f"보낼 창이 {window}초뿐이다"

    # 주기를 적지 않은 옛 설정도 이 기본값을 따라야 한다
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    item = _item()
    del item["interval"]
    ka.save_config(projects, [item])
    _worker(projects, jsonl)._tick()
    # 55분이 안 지났으니 아무 일도 없어야 한다
    assert ka.load_config(projects)[0]["enabled"] is True


def test_cwd_follows_the_folder_the_session_lives_in(tmp_path: Path) -> None:
    """복제한 세션은 원본의 cwd 를 물려받는다 — 파일이 놓인 폴더를 따라야 한다.

    실제로 겪은 일이다. 62MB 짜리 복제 세션에서 가장 흔한 cwd 가 이미 사라진
    원본 폴더(`chicken-proj2`)였고, `claude --resume` 을 거기서 돌리려다
    자동 메시지가 한 번도 나가지 못했다. 기록을 고치지 않고 읽는 쪽에서 바로잡는다.
    """
    projects = tmp_path / "projects"
    real = tmp_path / "kyochon-prac"
    real.mkdir(parents=True)
    folder = projects / _slug_of(str(real))
    folder.mkdir(parents=True)
    jsonl = folder / f"{SESSION_ID}.jsonl"

    stamp = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    rows: "list[dict[str, Any]]" = []
    # 원본 프로젝트의 cwd 가 압도적으로 많다 — 그래도 이걸 고르면 안 된다
    for _ in range(50):
        rows.append(
            {
                "type": "user",
                "cwd": str(tmp_path / "사라진원본"),
                "sessionId": SESSION_ID,
                "timestamp": stamp,
            }
        )
    rows.append(
        {
            "type": "assistant",
            "cwd": str(real),
            "sessionId": SESSION_ID,
            "timestamp": stamp,
            "message": {"model": "claude-opus-5"},
        }
    )
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    facts = ka.read_session_facts(jsonl)
    assert facts["cwd"] == str(real), "파일이 놓인 폴더와 짝이 맞는 cwd 여야 한다"
    assert Path(facts["cwd"]).is_dir()


def _slug_of(path: str) -> str:
    return ka._slug_of(path)


def test_cwd_falls_back_to_an_existing_path(tmp_path: Path) -> None:
    """폴더 이름과 짝이 맞는 게 없으면, 적어도 실재하는 경로를 고른다."""
    projects = tmp_path / "projects"
    (projects / "C--전혀다른이름").mkdir(parents=True)
    real = tmp_path / "있는폴더"
    real.mkdir()
    jsonl = projects / "C--전혀다른이름" / f"{SESSION_ID}.jsonl"

    stamp = _iso(datetime.now(timezone.utc))
    rows = [
        {
            "type": "user",
            "cwd": str(tmp_path / "없는폴더"),
            "sessionId": SESSION_ID,
            "timestamp": stamp,
        },
        {
            "type": "user",
            "cwd": str(tmp_path / "없는폴더"),
            "sessionId": SESSION_ID,
            "timestamp": stamp,
        },
        {"type": "user", "cwd": str(real), "sessionId": SESSION_ID, "timestamp": stamp},
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert ka.read_session_facts(jsonl)["cwd"] == str(real)


def test_debug_log_records_a_missing_working_directory(tmp_path: Path) -> None:
    """복제한 세션의 cwd 가 사라진 경우를 기록에 남기는가.

    실제로 겪은 일이다 — 복제 기능이 sessionId 만 바꾸고 cwd 는 원본 프로젝트를
    가리킨 채로 두어, 그 폴더가 없어지자 자동 메시지가 한 번도 나가지 못했다.
    화면에는 오류 한 줄뿐이라 원인을 좁힐 수 없었다.
    """
    stale = datetime.now(timezone.utc) - timedelta(minutes=40)
    projects, jsonl, _ = _make(tmp_path, stale)
    # cwd 를 없는 폴더로 바꿔 쓴다
    rows = [
        json.loads(ln)
        for ln in jsonl.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for row in rows:
        row["cwd"] = str(tmp_path / "사라진폴더")
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    past = time.time() - ka.ACTIVE_WINDOW_SEC * 5
    os.utime(jsonl, (past, past))

    ka.save_config(projects, [_item(interval=60, seen_at=_iso(stale))])
    _worker(projects, jsonl, debug=True)._tick()

    saved = ka.load_config(projects)[0]
    assert saved["error"] == "작업 폴더를 찾을 수 없습니다"

    text = ka.debug_log_path(projects).read_text(encoding="utf-8")
    assert "작업 폴더 없음" in text
    assert "사라진폴더" in text
    # 원인을 짚어주는 힌트까지 남아야 쓸모가 있다
    assert "복제한 세션" in text


def test_debug_log_notices_a_frozen_worker(tmp_path: Path) -> None:
    """검사가 오래 멈췄던 흔적을 남기는가 — 절전 여부를 사후에 가릴 근거다."""
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(projects, [_item()])
    worker = _worker(projects, jsonl, debug=True)

    worker._tick()
    # 직전 검사가 한참 전이었던 것처럼 꾸민다
    worker._last_tick_at = time.time() - 3000
    worker._tick()

    text = ka.debug_log_path(projects).read_text(encoding="utf-8")
    assert "검사가" in text and "멈춰" in text
    assert "절전" in text


def test_debug_log_can_be_turned_off(tmp_path: Path) -> None:
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(projects, [_item()])
    _worker(projects, jsonl, debug=False)._tick()
    assert not ka.debug_log_path(projects).exists()


def test_expired_cache_disables_with_a_marker(tmp_path: Path) -> None:
    """캐시가 죽은 세션은 꺼지되, 사람이 끈 것과 구분되는 표식을 남긴다."""
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    projects, jsonl, _ = _make(tmp_path, stale)
    ka.save_config(projects, [_item(seen_at=_iso(stale))])

    _worker(projects, jsonl)._tick()

    saved = ka.load_config(projects)[0]
    assert saved["enabled"] is False
    assert saved["auto_off"] is True
    assert saved["error"] == "캐시 만료로 중지됨"


def test_recovered_cache_re_enables(tmp_path: Path) -> None:
    """워커가 껐던 세션은 캐시가 되살아나면 자동으로 다시 켜진다.

    이것이 없으면 '만료 후 메시지 보내기'로 캐시를 되살려도 세션은 꺼진 채
    남고, 오류 문구까지 지워져 아무 단서 없이 조용히 죽는다.
    """
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(
        projects,
        [
            _item(
                enabled=False,
                auto_off=True,
                error="캐시 만료로 중지됨",
                count=5,
                seen_at=STALE_SEEN,  # 낡은 값 → 새 응답으로 감지된다
                interval=999_999,  # 전송 단계까지 내려가지 않게
            )
        ],
    )

    _worker(projects, jsonl)._tick()

    saved = ka.load_config(projects)[0]
    assert saved["enabled"] is True
    assert saved.get("auto_off") is None
    assert saved["error"] is None


def test_human_pause_survives_new_activity(tmp_path: Path) -> None:
    """사람이 일시정지한 세션은 새 응답이 와도 멋대로 켜지지 않는다."""
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(
        projects,
        [_item(enabled=False, seen_at=STALE_SEEN, interval=999_999)],
    )

    _worker(projects, jsonl)._tick()

    saved = ka.load_config(projects)[0]
    assert saved["enabled"] is False
    assert saved.get("auto_off") is None


def test_full_cycle_expire_then_recover(tmp_path: Path) -> None:
    """만료 → 자동 중지 → 캐시 복구 → 자동 재개까지 한 흐름으로."""
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    projects, jsonl, cwd = _make(tmp_path, stale)
    ka.save_config(projects, [_item(seen_at=_iso(stale))])
    worker = _worker(projects, jsonl)

    worker._tick()
    assert ka.load_config(projects)[0]["auto_off"] is True

    # '만료 후 메시지 보내기'(또는 사람)가 새 응답을 만들어 캐시가 되살아난 상태
    _write_jsonl(jsonl, cwd, datetime.now(timezone.utc) - timedelta(minutes=3))
    worker._tick()

    saved = ka.load_config(projects)[0]
    assert saved["enabled"] is True
    assert saved.get("auto_off") is None


def test_manual_toggle_claims_ownership(tmp_path: Path) -> None:
    """사람이 버튼을 만지면 자동 표식은 사라진다.

    그 뒤의 켜고 끔은 사람의 의사이지 캐시 사정이 아니므로, 워커가 나중에
    임의로 되살리면 안 된다.
    """
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(
        projects, [_item(enabled=False, auto_off=True, error="캐시 만료로 중지됨")]
    )
    worker = _worker(projects, jsonl)

    # ▶ 를 눌러 사람이 직접 켰다
    assert worker.mutate(SESSION_ID, "toggle") is True
    saved = ka.load_config(projects)[0]
    assert saved["enabled"] is True
    assert saved.get("auto_off") is None

    # 다시 ⏸ 로 껐다면 그건 사람의 결정이다
    assert worker.mutate(SESSION_ID, "toggle") is True
    assert ka.load_config(projects)[0]["enabled"] is False

    _worker(projects, jsonl)._tick()
    assert ka.load_config(projects)[0]["enabled"] is False


def test_stop_clears_the_marker(tmp_path: Path) -> None:
    """⏹ 정지도 사람의 결정이므로 자동 표식을 넘겨받는다."""
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(projects, [_item(enabled=False, auto_off=True)])
    worker = _worker(projects, jsonl)

    assert worker.mutate(SESSION_ID, "stop") is True
    saved = ka.load_config(projects)[0]
    assert saved["stopped"] is True
    assert saved.get("auto_off") is None

    _worker(projects, jsonl)._tick()
    assert ka.load_config(projects)[0]["enabled"] is False


def test_clear_reload_only_touches_that_flag(tmp_path: Path) -> None:
    """뱃지를 지워도 다른 상태는 건드리지 않는다.

    이 표시는 서버에 있으므로 대시보드와 세션 화면 어느 쪽에서 눌러도
    양쪽에서 함께 사라진다 — 그게 이 동작을 서버에 둔 이유다.
    """
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(projects, [_item(needs_reload=True, count=3, enabled=True)])
    worker = _worker(projects, jsonl)

    assert worker.snapshot()[0]["needs_reload"] is True
    assert worker.mutate(SESSION_ID, "clear_reload") is True

    saved = ka.load_config(projects)[0]
    assert saved["needs_reload"] is False
    # 나머지는 그대로여야 한다
    assert saved["count"] == 3
    assert saved["enabled"] is True
    assert saved["stopped"] is False


def test_clear_reload_on_unknown_session_is_refused(tmp_path: Path) -> None:
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, _ = _make(tmp_path, fresh)
    ka.save_config(projects, [_item()])
    assert _worker(projects, jsonl).mutate("없는세션", "clear_reload") is False


def test_facts_are_reused_until_the_file_changes(tmp_path: Path) -> None:
    """같은 파일을 거듭 읽지 않는다.

    /api/keepalive 는 대시보드와 세션 화면이 각각 5초마다 부른다. 매번 JSONL 을
    통째로 파싱하면 큰 세션에서 화면을 열어두는 것만으로 수십 MB 를 계속 읽는다
    (실측 62MB → 0.48초). JSONL 은 덧붙이기만 하므로 (수정시각, 크기) 로 판별한다.
    """
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    projects, jsonl, cwd = _make(tmp_path, fresh)

    first = ka.read_session_facts(jsonl)
    second = ka.read_session_facts(jsonl)
    assert first == second

    # 돌려준 값을 고쳐도 보관본이 오염되면 안 된다
    second["cwd"] = "망가뜨림"
    assert ka.read_session_facts(jsonl)["cwd"] == first["cwd"]

    # 파일이 바뀌면 다시 읽는다
    later = datetime.now(timezone.utc) - timedelta(minutes=1)
    _write_jsonl(jsonl, cwd, later)
    assert ka.read_session_facts(jsonl)["last_response_at"] == _iso(later)


def test_missing_file_does_not_poison_the_cache(tmp_path: Path) -> None:
    """읽을 수 없는 파일은 보관하지 않는다 — 나중에 생기면 읽혀야 한다."""
    missing = tmp_path / "아직없음.jsonl"
    assert ka.read_session_facts(missing)["cwd"] is None

    (tmp_path / "work").mkdir()
    _write_jsonl(missing, str(tmp_path / "work"), datetime.now(timezone.utc))
    assert ka.read_session_facts(missing)["cwd"] == str(tmp_path / "work")
