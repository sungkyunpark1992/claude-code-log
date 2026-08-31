"""세션 유지용 자동 메시지.

마지막 응답으로부터 설정한 시간이 지나면 짧은 메시지를 보내 프롬프트 캐시를 유지한다.
캐시가 만료되면 이전 대화를 통째로 다시 캐시에 써야 해서 토큰이 크게 드는데, 그 비용을
줄이려는 것이다.

전송은 `claude --resume <id> -p "<메시지>"` 를 그 세션의 작업 폴더에서 실행하는 방식이다.
API 를 직접 부르지 않는 이유는 CLI 가 이미 세션 컨텍스트와 인증을 알고 있고, 실측에서
VS Code 확장이 만든 캐시를 그대로 이어받는 것을 확인했기 때문이다.
상세: CUSTOM_FEATURES.md 35번
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

# 확인 주기. 예약 작업(최소 1분)과 달리 서버 안에서 도니 짧게 잡을 수 있다.
CHECK_INTERVAL_SEC = 10.0

# 이 시간 안에 JSONL 이 바뀌었으면 사람이 쓰는 중으로 본다.
# 질문을 보냈지만 응답이 아직 안 끝난 경우, 마지막 "응답" 시각은 낡았는데 파일은
# 갱신되고 있다. 그때 자동 메시지를 끼워 넣으면 대화가 갈라진다.
ACTIVE_WINDOW_SEC = 120.0

# 전송이 이 시간을 넘기면 포기한다. 실측 응답은 1~2초였다.
SEND_TIMEOUT_SEC = 120

# 캐시 TTL. 이 시간이 지나면 전송해봐야 의미가 없어 재시도를 멈춘다.
CACHE_TTL_SEC = 3600

# 기본 주기 55분. TTL 까지 5분 여유를 둔다.
# 58분으로 두면 여유가 2분뿐이라 잠깐만 밀려도 창을 놓친다 — 실제로 놓쳤다.
DEFAULT_INTERVAL_SEC = 3300

# 진단 기록. 자리를 비운 사이 무슨 판단을 했는지 남긴다.
# 켜려면 CLAUDE_CODE_LOG_KEEPALIVE_DEBUG=1
DEBUG_ENV = "CLAUDE_CODE_LOG_KEEPALIVE_DEBUG"
DEBUG_HEARTBEAT_SEC = 300.0
DEBUG_MAX_BYTES = 2 * 1024 * 1024


def keepalive_path(projects_dir: Path) -> Path:
    return projects_dir / "keepalive.json"


def debug_log_path(projects_dir: Path) -> Path:
    return projects_dir / "keepalive-debug.log"


class _DebugLog:
    """워커가 매 순간 무엇을 보고 무엇을 결정했는지 남긴다.

    자리를 비운 사이 안 나갔을 때, 남는 것이 "오류 문구 한 줄"뿐이면 원인을
    좁힐 수 없다. 그래서 판단의 근거(경과 시간·만기까지·캐시 남은 시간·건너뛴
    이유)를 함께 적는다.

    같은 상태가 이어질 때는 5분에 한 번만 적는다. 10초마다 전부 적으면 하룻밤에
    수만 줄이 쌓여 정작 중요한 변화가 묻힌다.
    """

    def __init__(self, path: Path, enabled: bool) -> None:
        self._path = path
        self._enabled = enabled
        self._last_line: "dict[str, str]" = {}
        self._last_at: "dict[str, float]" = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def write(self, key: str, message: str, *, always: bool = False) -> None:
        if not self._enabled:
            return
        now = time.time()
        with self._lock:
            same = self._last_line.get(key) == message
            recent = now - self._last_at.get(key, 0.0) < DEBUG_HEARTBEAT_SEC
            if same and recent and not always:
                return
            self._last_line[key] = message
            self._last_at[key] = now
            stamp = datetime.now().strftime("%m-%d %H:%M:%S")
            try:
                self._rotate_if_large()
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{stamp}  {message}\n")
                    handle.flush()
                    # 절전이나 강제 종료로 프로세스가 끊겨도 여기까지는 남아야 한다
                    os.fsync(handle.fileno())
            except OSError:
                # 기록을 못 남기는 것 때문에 본 기능이 멈추면 안 된다
                pass

    def _rotate_if_large(self) -> None:
        """한 세대만 남기고 갈아끼운다. 몇 달을 켜두어도 무한정 자라지 않게."""
        try:
            if self._path.stat().st_size < DEBUG_MAX_BYTES:
                return
        except OSError:
            return
        previous = self._path.with_suffix(self._path.suffix + ".1")
        try:
            if previous.exists():
                previous.unlink()
            self._path.rename(previous)
        except OSError:
            pass


def load_config(projects_dir: Path) -> "list[dict[str, Any]]":
    """등록된 세션 목록. 파일이 없거나 깨졌으면 빈 목록."""
    path = keepalive_path(projects_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    data = cast("dict[str, Any]", raw)
    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        return []
    items = cast("list[Any]", sessions)
    return [cast("dict[str, Any]", s) for s in items if isinstance(s, dict)]


def save_config(projects_dir: Path, sessions: "list[dict[str, Any]]") -> None:
    path = keepalive_path(projects_dir)
    path.write_text(
        json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="",
    )


def _parse_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_int(value: Any) -> int:
    """usage 값은 없거나 null 인 경우가 있다. 화면에서 계산에 쓰이므로 0 으로 맞춘다."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# 한도 초과 등으로 실제 모델이 답하지 못했을 때 Claude Code 가 남기는 표식
SYNTHETIC_MODEL = "<synthetic>"


def txt_of(content: Any) -> str:
    """assistant 응답의 본문. 문자열이거나 블록 목록이다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: "list[str]" = []
        for block in cast("list[Any]", content):
            if isinstance(block, dict):
                b = cast("dict[str, Any]", block)
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    parts.append(cast(str, b["text"]))
        return " ".join(parts)
    return ""


def _first_line(text: str) -> Optional[str]:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[0][:120] if lines else None


def _slug_of(project_path: str) -> str:
    """Claude Code 가 폴더 경로를 세션 폴더 이름으로 바꾸는 규칙."""
    out: "list[str]" = []
    for ch in project_path.strip().rstrip("\\/"):
        out.append("-" if ch in ":\\/" else ch)
    return "".join(out)


def _pick_cwd(cwds: "Counter[str]", jsonl_file: Path) -> Optional[str]:
    """이 세션을 이어가려면 어느 폴더에서 실행해야 하는가.

    단순히 "가장 많이 나온 cwd" 를 쓰면 안 된다. 대화가 길면 여러 폴더를
    오갔고, **복제한 세션은 원본 프로젝트의 cwd 를 그대로 물려받는다.**
    실제로 62MB 짜리 복제 세션에서 가장 흔한 cwd 가 이미 사라진 원본
    폴더였고, 그래서 자동 메시지가 한 번도 나가지 못했다.

    판단의 근거는 **파일이 놓인 폴더**다. Claude Code 는 현재 폴더를 슬러그로
    바꿔 세션을 찾으므로, 그 폴더 이름과 슬러그가 같은 cwd 라야 `--resume`
    이 같은 대화를 집는다. 기록을 고치지 않고 읽는 쪽에서 바로잡는다.
    """
    if not cwds:
        return None
    folder = jsonl_file.parent.name.lower()

    # 1순위: 파일이 놓인 폴더와 슬러그가 같고, 실제로 존재하는 경로
    for cwd, _ in cwds.most_common():
        if _slug_of(cwd).lower() == folder and Path(cwd).is_dir():
            return cwd
    # 2순위: 존재하는 경로 중 가장 흔한 것 (대소문자만 다른 경우 등)
    for cwd, _ in cwds.most_common():
        if Path(cwd).is_dir():
            return cwd
    # 3순위: 그래도 없으면 가장 흔한 값. 호출자가 '폴더 없음'으로 걸러낸다.
    return cwds.most_common(1)[0][0]


# 읽어둔 결과. 열쇠는 (수정시각, 크기) 라 파일이 바뀌면 저절로 빗나간다.
_FACTS_CACHE: "dict[str, tuple[tuple[float, int], dict[str, Any]]]" = {}
_FACTS_LOCK = threading.Lock()
_FACTS_MAX = 64


def read_session_facts(jsonl_file: Path) -> "dict[str, Any]":
    """JSONL 에서 뽑은 값. 파일이 그대로면 앞서 읽은 것을 준다.

    파일을 통째로 읽어 줄마다 JSON 파싱을 하는 일이라 큰 세션에서는 비싸다 —
    실측으로 62MB 에 0.48초, 등록 세션을 모두 훑는 snapshot() 이 0.59초였다.
    그런데 `/api/keepalive` 는 대시보드와 세션 화면이 **각각 5초마다** 부른다.
    그대로 두면 화면을 열어두는 것만으로 계속 수십 MB 를 읽는다.

    JSONL 은 덧붙이기만 하므로 (수정시각, 크기) 가 같으면 내용도 같다.
    """
    try:
        stat = jsonl_file.stat()
        key = str(jsonl_file)
        stamp = (stat.st_mtime, stat.st_size)
    except OSError:
        return _read_session_facts_uncached(jsonl_file)

    with _FACTS_LOCK:
        cached = _FACTS_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            # 호출자가 고쳐도 보관본이 오염되지 않도록 사본을 준다
            return dict(cached[1])

    facts = _read_session_facts_uncached(jsonl_file)
    with _FACTS_LOCK:
        if len(_FACTS_CACHE) >= _FACTS_MAX:
            _FACTS_CACHE.clear()
        _FACTS_CACHE[key] = (stamp, dict(facts))
    return facts


def _read_session_facts_uncached(jsonl_file: Path) -> "dict[str, Any]":
    """JSONL 에서 전송에 필요한 값을 뽑는다.

    cwd 가 특히 중요하다 — Claude Code 는 현재 폴더를 슬러그로 바꿔 세션을 찾으므로,
    그 세션의 작업 폴더에서 실행해야 같은 대화로 이어진다.
    """
    cwds: "Counter[str]" = Counter()
    model: Optional[str] = None
    last_response: Optional[str] = None
    last_usage: "Optional[dict[str, int]]" = None
    last_error: Optional[str] = None
    try:
        text = jsonl_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "cwd": None,
            "model": None,
            "last_response_at": None,
            "last_usage": None,
            "last_error": None,
        }

    for line in text.splitlines():
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
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd:
            cwds[cwd] += 1
        if entry.get("type") == "assistant":
            message = entry.get("message")
            if isinstance(message, dict):
                msg = cast("dict[str, Any]", message)
                m = msg.get("model")
                # 한도 초과·오류일 때 Claude Code 는 model 이 "<synthetic>" 인 가짜
                # 응답을 써 넣는다. 모델도 아니고 캐시도 만들지 않았으므로,
                # 모델 표시와 캐시 판단의 근거에서 모두 빼야 한다. 근거로 삼으면
                # 캐시가 없는데도 살아있다고 보고 만료 버튼을 감춰 버린다.
                if m == SYNTHETIC_MODEL:
                    last_error = _first_line(txt_of(msg.get("content")))
                    continue
                last_error = None
                if isinstance(m, str) and m:
                    model = m
                # 직전 문답이 캐시를 맞혔는지 틀렸는지가 이 기능의 성패다.
                # 맞히면 82 토큰, 틀리면 수십만 토큰 — 화면에서 바로 보여야 한다.
                raw_usage = msg.get("usage")
                if isinstance(raw_usage, dict):
                    u = cast("dict[str, Any]", raw_usage)
                    last_usage = {
                        "input": _as_int(u.get("input_tokens")),
                        "output": _as_int(u.get("output_tokens")),
                        "cache_read": _as_int(u.get("cache_read_input_tokens")),
                        "cache_creation": _as_int(u.get("cache_creation_input_tokens")),
                    }
            ts = entry.get("timestamp")
            if isinstance(ts, str) and ts:
                last_response = ts

    return {
        "cwd": _pick_cwd(cwds, jsonl_file),
        "model": model,
        # 카운트다운의 기준은 질문 시각이 아니라 마지막 응답 시각이다.
        # 도구를 많이 쓴 긴 작업은 둘의 차이가 15분까지 벌어진다.
        "last_response_at": last_response,
        "last_usage": last_usage,
        # 마지막 시도가 한도 초과 등으로 막혔다면 그 안내문. 성공하면 지워진다.
        "last_error": last_error,
    }


def resolve_claude() -> Optional[str]:
    """claude 실행 파일의 전체 경로.

    Windows 에서 claude 는 npm 이 만든 `claude.cmd` 배치 파일이다. 배치는 실행 파일이
    아니라 셸이 해석하는 것이라, shell=False 인 subprocess 는 PATH 를 뒤져도 찾지 못한다.
    shutil.which 는 PATHEXT 를 함께 보므로 `.cmd` 까지 찾아준다.
    """
    return shutil.which("claude")


def send_keepalive(
    session_id: str, cwd: str, message: str
) -> "tuple[bool, Optional[str]]":
    """claude CLI 로 한 번 보낸다. (성공여부, 오류메시지)."""
    exe = resolve_claude()
    if exe is None:
        return False, "claude 명령을 찾을 수 없습니다 (PATH 확인 필요)"
    try:
        proc = subprocess.run(
            [exe, "--resume", session_id, "-p", message],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SEND_TIMEOUT_SEC,
            shell=False,
        )
    except FileNotFoundError:
        return False, "claude 명령을 찾을 수 없습니다"
    except subprocess.TimeoutExpired:
        return False, f"{SEND_TIMEOUT_SEC}초 안에 끝나지 않았습니다"
    except OSError as exc:
        return False, f"실행 실패: {exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1][:120] if detail else f"종료코드 {proc.returncode}"
        return False, tail

    # 사용 한도에 걸리면 CLI 는 정상 종료하면서 안내문만 답으로 돌려준다.
    # 종료코드만 믿으면 실패를 성공으로 세어 예산을 헛되이 깎고, 캐시가
    # 생기지 않았는데도 생긴 것처럼 다음 주기를 세게 된다.
    body = (proc.stdout or "").strip()
    if _looks_like_limit(body):
        return False, body.splitlines()[0][:120]
    return True, None


def _looks_like_limit(text: str) -> bool:
    """한도 초과 안내문인가. 문구가 바뀔 수 있어 넓게 잡는다."""
    low = text.lower()
    return "hit your session limit" in low or "usage limit" in low


class KeepaliveWorker:
    """등록된 세션을 주기적으로 살펴 만기된 것에 자동 메시지를 보낸다.

    한 스레드가 모든 세션을 순차 처리한다. 여러 세션이 동시에 만기되어도
    claude 프로세스가 한 번에 하나만 뜨도록 하기 위해서다.
    """

    def __init__(
        self, projects_dir: Path, find_jsonl: Any, debug: Optional[bool] = None
    ) -> None:
        self._projects_dir = projects_dir
        self._find_jsonl = find_jsonl
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        if debug is None:
            # 기본으로 켠다. 같은 상태는 5분에 한 줄만 남기므로 하루 몇백 줄이고,
            # 자리를 비운 사이 왜 안 나갔는지는 이 기록이 없으면 알 수 없다.
            debug = os.environ.get(DEBUG_ENV, "").strip().lower() not in (
                "0",
                "false",
                "off",
            )
        self._debug = _DebugLog(debug_log_path(projects_dir), debug)
        self._last_tick_at = 0.0

    # ── 공개 API ────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None:
            return
        if self._debug.enabled:
            self._debug.write(
                "worker",
                f"=== 워커 시작 · 검사 {CHECK_INTERVAL_SEC:.0f}초마다 "
                f"· 기본 주기 {DEFAULT_INTERVAL_SEC}초 · TTL {CACHE_TTL_SEC}초 ===",
                always=True,
            )
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> "list[dict[str, Any]]":
        """화면에 보낼 목록. 저장된 설정에 JSONL 에서 읽은 값을 얹는다."""
        with self._lock:
            sessions = load_config(self._projects_dir)
        out: "list[dict[str, Any]]" = []
        for item in sessions:
            enriched = dict(item)
            jsonl = self._resolve(item.get("session_id"))
            if jsonl is None:
                enriched["missing"] = True
            else:
                facts = read_session_facts(jsonl)
                enriched["missing"] = False
                enriched["cwd"] = facts["cwd"]
                enriched["model"] = facts["model"]
                enriched["last_response_at"] = facts["last_response_at"]
                enriched["last_usage"] = facts["last_usage"]
                enriched["last_error"] = facts["last_error"]
                # 캐시가 이미 사라졌는지. 화면은 이 값으로 "캐시 만료 후 메시지 보내기"
                # 버튼을 띄운다 — 만료 상태에서만 의미가 있는 동작이다.
                # 기준은 오직 마지막 응답 시각이다. 재개 버튼을 누른 시각(resume_at)을
                # 쓰면 죽은 캐시를 살아있다고 보고 버튼을 감춰, 정작 복구할 방법이 없어진다.
                base = _parse_iso(facts["last_response_at"])
                enriched["cache_expired"] = (
                    base is None or time.time() > base + CACHE_TTL_SEC
                )
            out.append(enriched)
        return out

    def mutate(self, session_id: str, action: str) -> bool:
        """toggle / stop / reset / delete. 성공하면 True."""
        with self._lock:
            sessions = load_config(self._projects_dir)
            idx = next(
                (
                    i
                    for i, s in enumerate(sessions)
                    if s.get("session_id") == session_id
                ),
                -1,
            )
            if idx < 0:
                return False
            item = sessions[idx]

            if action == "delete":
                sessions.pop(idx)
            elif action == "toggle":
                # 사람이 직접 만졌으면 자동 표식은 사라진다. 이후의 켜고 끔은
                # 사람의 의사이지 캐시 사정이 아니다.
                item.pop("auto_off", None)
                if item.get("stopped"):
                    # 정지에서 재개하면 주기를 처음부터 다시 센다
                    item["stopped"] = False
                    item["enabled"] = True
                    item["resume_at"] = _now_iso()
                    item["error"] = None
                else:
                    item["enabled"] = not item.get("enabled", True)
            elif action == "stop":
                item.pop("auto_off", None)
                item["stopped"] = True
                item["enabled"] = False
            elif action == "reset":
                item["count"] = 0
                item["error"] = None
            elif action == "clear_reload":
                # 사람이 VS Code 를 새로고침했다는 뜻. 서버에 두므로 대시보드와
                # 세션 화면 어느 쪽에서 눌러도 양쪽에서 함께 사라진다.
                item["needs_reload"] = False
            else:
                return False

            save_config(self._projects_dir, sessions)
        return True

    def prime(self, session_id: str) -> "tuple[bool, Optional[str]]":
        """캐시가 없는 세션에 지금 한 번 보내 캐시를 만든다.

        워커는 캐시가 만료된 세션을 건너뛴다 — 보내봐야 새로 쓰게 되어 목적과
        반대이기 때문이다. 하지만 "지금부터 이 세션을 지키겠다"는 결정은 사람이
        내릴 수 있어야 하므로, 그 한 번을 명시적인 버튼으로 열어 둔다.

        비싼 동작이라(캐시 재작성 ≈ 평소의 12배) 자동으로는 하지 않는다.
        예산(max)도 깎지 않는다 — 준비 동작이지 자동 전송이 아니다.
        """
        with self._lock:
            sessions = load_config(self._projects_dir)
            item = next(
                (s for s in sessions if s.get("session_id") == session_id), None
            )
            if item is None:
                return False, "등록되지 않은 세션입니다"
            message = str(item.get("message") or "").strip()

        jsonl = self._resolve(session_id)
        if jsonl is None:
            return False, "세션을 찾을 수 없습니다"
        facts = read_session_facts(jsonl)
        cwd = facts["cwd"]
        if not cwd or not Path(cwd).is_dir():
            return False, "작업 폴더를 찾을 수 없습니다"
        if not message:
            return False, "보낼 메시지가 없습니다"

        ok, err = send_keepalive(session_id, cwd, message)

        with self._lock:
            current = load_config(self._projects_dir)
            target = next(
                (s for s in current if s.get("session_id") == session_id), None
            )
            if target is not None:
                if ok:
                    target["last_sent_at"] = _now_iso()
                    target["error"] = None
                    target["needs_reload"] = True
                    # 캐시가 생겼으니 워커가 이어받아 유지할 수 있다
                    target["enabled"] = True
                    target["stopped"] = False
                    target.pop("auto_off", None)
                    target.pop("resume_at", None)
                    after = read_session_facts(jsonl)
                    if after["last_response_at"]:
                        target["seen_at"] = after["last_response_at"]
                else:
                    target["error"] = err
                save_config(self._projects_dir, current)
        return ok, err

    def add(self, item: "dict[str, Any]") -> None:
        with self._lock:
            sessions = load_config(self._projects_dir)
            sessions.append(item)
            save_config(self._projects_dir, sessions)

    # ── 내부 ────────────────────────────────────────────────
    def _resolve(self, session_id: Any) -> Optional[Path]:
        if not isinstance(session_id, str) or not session_id:
            return None
        return cast(Optional[Path], self._find_jsonl(self._projects_dir, session_id))

    def _loop(self) -> None:
        while not self._stop.wait(CHECK_INTERVAL_SEC):
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 — 스레드가 죽으면 안 된다
                print(f"[keepalive] tick 실패: {type(exc).__name__}: {exc}")

    def _tick(self) -> None:
        # 검사 간격이 비정상적으로 벌어졌다면 그 사이 워커가 얼어 있었다는 뜻이다
        # (절전·대기모드가 대표적). 원인을 나중에 짚으려면 이 흔적이 꼭 필요하다.
        now = time.time()
        if self._last_tick_at:
            gap = now - self._last_tick_at
            if gap > CHECK_INTERVAL_SEC * 3:
                self._debug.write(
                    "worker",
                    f"★ 검사가 {gap:.0f}초 동안 멈춰 있었다"
                    f" (정상 {CHECK_INTERVAL_SEC:.0f}초)."
                    " 절전·대기모드로 프로세스가 얼었을 가능성",
                    always=True,
                )
        self._last_tick_at = now

        with self._lock:
            sessions = load_config(self._projects_dir)
        if not sessions:
            self._debug.write("worker", "등록된 세션 없음")
            return

        due: "list[tuple[float, dict[str, Any], Path, str]]" = []
        changed = False

        for item in sessions:
            jsonl = self._resolve(item.get("session_id"))
            if jsonl is None:
                if item.get("error") != "세션을 찾을 수 없습니다":
                    item["error"] = "세션을 찾을 수 없습니다"
                    changed = True
                continue

            facts = read_session_facts(jsonl)
            last_at = facts["last_response_at"]

            # 사람이 대화를 이어갔으면 자동 메시지 예산을 되돌린다.
            # 상한은 "사람이 없는 동안 몇 번까지"를 정한 것이라 전제가 사라진다.
            if last_at and item.get("seen_at") != last_at:
                item["seen_at"] = last_at
                item["count"] = 0
                item["needs_reload"] = False
                item["error"] = None
                # 캐시가 없어서 우리가 껐던 것이라면, 새 응답으로 캐시가 되살아난
                # 지금이 그 조건이 사라진 시점이다. 사람이 직접 끈 것(auto_off 없음)은
                # 건드리지 않는다 — 그건 여전히 사람의 의사다.
                if item.get("auto_off"):
                    item["enabled"] = True
                    item.pop("auto_off", None)
                changed = True

            tag = str(item.get("session_id", "?"))[:8]
            if not item.get("enabled", True) or item.get("stopped"):
                self._debug.write(
                    tag,
                    f"[{tag}] 건너뜀 — "
                    + ("정지됨" if item.get("stopped") else "꺼짐")
                    + f" (auto_off={bool(item.get('auto_off'))}, "
                    f"error={item.get('error')})",
                )
                continue
            if item.get("count", 0) >= item.get("max", 12):
                self._debug.write(
                    tag,
                    f"[{tag}] 건너뜀 — 예산 소진 {item.get('count')}/{item.get('max')}",
                )
                continue

            # 두 기준을 반드시 나눠 쓴다.
            #  · 주기: 재개 버튼을 누르면 그때부터 다시 센다 (resume_at)
            #  · 캐시 수명: 오직 마지막 응답 시각에서만 흐른다
            # 캐시 판정에까지 resume_at 을 쓰면, 어제 죽은 캐시도 재개하는 순간
            # "방금 살아났다"고 오판해 비싼 재작성을 그대로 일으킨다.
            base = _parse_iso(item.get("resume_at")) or _parse_iso(last_at)
            if base is None:
                try:
                    base = jsonl.stat().st_mtime
                except OSError:
                    continue
            cache_base = _parse_iso(last_at)

            interval = float(item.get("interval", DEFAULT_INTERVAL_SEC))
            ttl_left = (cache_base + CACHE_TTL_SEC - now) if cache_base else None
            if now < base + interval:
                self._debug.write(
                    tag,
                    f"[{tag}] 대기 — 만기까지 {(base + interval - now) / 60:.1f}분"
                    f" · 캐시 남음 "
                    + (f"{ttl_left / 60:.1f}분" if ttl_left is not None else "?")
                    + f" · 창 {(CACHE_TTL_SEC - interval) / 60:.1f}분",
                )
                continue

            # 캐시가 이미 만료됐으면 보내봐야 새로 쓰게 된다 — 목적과 정반대다.
            # 사람이 끈 것과 구분되도록 표식을 남긴다. 캐시가 되살아나면
            # 이 표식을 보고 위쪽에서 자동으로 다시 켠다.
            if cache_base is None or now > cache_base + CACHE_TTL_SEC:
                over = (now - cache_base - CACHE_TTL_SEC) / 60 if cache_base else None
                self._debug.write(
                    tag,
                    f"[{tag}] ★ 캐시 만료로 중지 — "
                    + (f"{over:.1f}분 늦음" if over is not None else "기준 시각 없음")
                    + f" (만기 {interval / 60:.0f}분, TTL {CACHE_TTL_SEC / 60:.0f}분)",
                    always=True,
                )
                item["enabled"] = False
                item["auto_off"] = True
                item["error"] = "캐시 만료로 중지됨"
                changed = True
                continue

            # 응답이 진행 중일 수 있다. 파일이 방금 바뀌었으면 끼어들지 않는다.
            try:
                idle = now - jsonl.stat().st_mtime
                if idle < ACTIVE_WINDOW_SEC:
                    self._debug.write(
                        tag,
                        f"[{tag}] 보류 — 파일이 {idle:.0f}초 전에 바뀜"
                        f" (사람이 쓰는 중으로 봄, 기준 {ACTIVE_WINDOW_SEC:.0f}초)"
                        f" · 캐시 남음 "
                        + (f"{ttl_left / 60:.1f}분" if ttl_left is not None else "?"),
                        always=True,
                    )
                    continue
            except OSError as exc:
                self._debug.write(tag, f"[{tag}] 보류 — 파일 정보 읽기 실패: {exc}")
                continue

            cwd = facts["cwd"]
            if not cwd or not Path(cwd).is_dir():
                self._debug.write(
                    tag,
                    f"[{tag}] ★ 작업 폴더 없음 — cwd={cwd!r}"
                    f" (JSONL 은 {jsonl.parent.name} 에 있음)."
                    " 복제한 세션이면 cwd 가 원본 프로젝트를 가리킨다",
                    always=True,
                )
                if item.get("error") != "작업 폴더를 찾을 수 없습니다":
                    item["error"] = "작업 폴더를 찾을 수 없습니다"
                    changed = True
                continue

            self._debug.write(
                tag,
                f"[{tag}] 전송 대상 — 만기 지남"
                f" · 캐시 남음 "
                + (f"{ttl_left / 60:.1f}분" if ttl_left is not None else "?")
                + f" · cwd={cwd}",
                always=True,
            )
            due.append((base, item, jsonl, cwd))

        if changed:
            self._persist(sessions)

        if not due:
            return

        # 만기가 오래된 것부터. 한 번에 하나씩 보낸다.
        due.sort(key=lambda x: x[0])
        for _, item, _jsonl, cwd in due:
            if self._stop.is_set():
                return
            sid = str(item.get("session_id"))
            message = str(item.get("message") or "").strip()
            if not message:
                continue

            started_at = time.time()
            ok, err = send_keepalive(sid, cwd, message)
            self._debug.write(
                sid[:8],
                f"[{sid[:8]}] 전송 {'성공' if ok else '실패'}"
                f" — {time.time() - started_at:.1f}초 걸림"
                + ("" if ok else f" · {err}"),
                always=True,
            )
            with self._lock:
                current = load_config(self._projects_dir)
                target = next((s for s in current if s.get("session_id") == sid), None)
                if target is None:
                    continue
                if ok:
                    target["count"] = int(target.get("count", 0)) + 1
                    target["last_sent_at"] = _now_iso()
                    target["error"] = None
                    target.pop("resume_at", None)
                    # 파일이 앞서 나갔으니 VS Code 의 메모리와 어긋난다.
                    target["needs_reload"] = True
                    # 방금 우리가 쓴 응답을 "사람의 활동"으로 오해하지 않도록 맞춰 둔다.
                    facts = read_session_facts(_jsonl)
                    if facts["last_response_at"]:
                        target["seen_at"] = facts["last_response_at"]
                else:
                    target["error"] = err
                save_config(self._projects_dir, current)

            time.sleep(2)  # 다음 프로세스와 간격을 둔다

    def _persist(self, sessions: "list[dict[str, Any]]") -> None:
        with self._lock:
            save_config(self._projects_dir, sessions)
