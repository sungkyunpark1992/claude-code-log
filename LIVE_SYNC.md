# 실시간 동기화 (SSE + iframe sandbox 증분 Append)

> claude-code-log의 핵심 기능. 세션 페이지를 열어두면, Claude Code 대화 시 브라우저에 페이지 새로고침 없이 실시간 반영.
> 설계 과정에서 겪은 문제들과 해결 과정을 모두 기록.

---

## 목차

1. [전체 아키텍처](#1-전체-아키텍처)
2. [데이터 흐름](#2-데이터-흐름)
3. [기술 스택](#3-기술-스택)
4. [설계 결정 기록](#4-설계-결정-기록)
5. [디버깅 히스토리](#5-디버깅-히스토리)
6. [현재 구현 코드](#6-현재-구현-코드)
7. [현재 한계점](#7-현재-한계점)
8. [변경 이력 요약](#8-변경-이력-요약)
9. [인덱스 페이지 업데이트 방식](#9-인덱스-페이지-업데이트-방식)

---

## 1. 전체 아키텍처

```
┌─────────────┐     JSONL 파일     ┌──────────────┐     SSE/HTTP      ┌─────────────┐
│ Claude Code │ ──── 기록 ────→    │ Flask 서버    │ ──── 전송 ────→   │  브라우저     │
│ (터미널)     │                   │ (localhost    │                  │ (세션 페이지) │
│             │                   │  :5678)       │                  │             │
└─────────────┘                   └──────────────┘                   └─────────────┘
```

### 핵심 컴포넌트

| 컴포넌트 | 위치 | 역할 |
|---------|------|------|
| SSE 스트림 서버 | `server.py` → `stream_session()` | watchdog으로 JSONL/settings.json 감시, 변경 시 이벤트 전송 |
| 메시지 증분 API | `server.py` → `render_messages()` | Python 객체(`TemplateMessage`) 리스트 기반 카운트, `after=N` 이후만 `render_fragment()`로 렌더링 |
| 동적 세션 렌더링 | `server.py` → `serve_file()` | 세션 페이지 요청 시 JSONL에서 최신 HTML 동적 생성 |
| EventSource 클라이언트 | `transcript.html` → `<script>` | SSE 수신, iframe sandbox 파싱, DOM 증분 추가 |
| ~~메시지 분할 마커~~ | ~~`transcript.html` → 템플릿~~ | **폐기** — HTML 마커 방식은 Bug 8로 완전 폐기. Python 객체 카운트로 대체 |

---

## 2. 데이터 흐름

```
1. Claude Code가 JSONL 파일에 새 줄 기록
       ↓
2. watchdog Observer가 OS 네이티브 이벤트로 즉각 감지 (ms 단위)
       ↓
3. 버스트 드레인 + 0.3s settle: 연속 쓰기를 묶어 처리, JSONL 안정 확보
       ↓
4. SSE로 {"type": "updated", "model": "..."} 이벤트 전송
       ↓
5. 브라우저 EventSource가 수신
       ↓
6. /api/sessions/{id}/messages?after=N 으로 새 메시지만 요청
       ↓
7. 서버: JSONL 전체 파싱 → `get_template_messages()` → Python `TemplateMessage` 리스트로 총 수 계산 → `[N:]` 슬라이스 → `render_fragment()`로 증분 HTML 반환
       ↓
8. 브라우저: iframe sandbox에서 HTML 파싱 → document.adoptNode()로 #sse-live-messages에 추가
       ↓
9. 후처리: convertTimestamps(), initEmptyPrompt(), 자동 스크롤
```

---

## 3. 기술 스택

| 구분 | 기술 | 역할 |
|------|------|------|
| **서버 프레임워크** | Flask (Python) | HTTP/SSE 서빙, API 엔드포인트 |
| **실시간 통신** | SSE (Server-Sent Events) | 서버→브라우저 단방향 이벤트 스트림 |
| **파일 변경 감지** | `watchdog` (`Observer` + `_SSEFileWatcher`) | OS 네이티브 이벤트 (Windows: ReadDirectoryChangesW, macOS: FSEvents, Linux: inotify). JSONL + settings.json 동시 감시. |
| **데이터 소스** | JSONL 파일 + `~/.claude/settings.json` | Claude Code 대화 로그 + 전역 모델 설정 |
| **API 응답** | JSON | `{"total": N, "html": "...", "model": "..."}` 형식 |
| **HTML 렌더링** | Jinja2 + mistune + Pygments | JSONL → 메시지 파싱 → HTML 생성 |
| **DOM 조작** | iframe sandbox + `document.adoptNode()` | 격리 환경에서 HTML 파싱 후 안전한 DOM 이동 |
| **메시지 카운트/분할** | Python `TemplateMessage` 객체 리스트 | `get_template_messages()` → `len()` / `[after:]` 슬라이스 → `render_fragment()` |

추가된 외부 의존성: `watchdog>=4.0.0` (OS 네이티브 파일 감시). 나머지는 기존 의존성(Flask, Jinja2 등)만 사용.

---

## 4. 설계 결정 기록

### 4-1. 왜 SSE인가? (WebSocket 아닌 이유)

- 서버→브라우저 **단방향 통신**만 필요 (파일 변경 알림)
- HTTP 기반이라 Flask에서 별도 라이브러리 없이 구현 가능
- WebSocket은 양방향이 필요한 채팅앱(카카오톡 등)에 적합, 여기선 과잉

### 4-2. 왜 iframe sandbox + adoptNode인가?

DOM 삽입 방식의 진화 과정:

| 단계 | 방식 | 결과 |
|------|------|------|
| 1차 | `DOMParser.parseFromString()` | **실패** — 대용량 세션(800+ 메시지, 4MB+ HTML)에서 깨진 HTML 태그(닫히지 않은 `<code>`, 이스케이프 안 된 `</div>` 등)를 만나면 DOM 구조를 엉뚱하게 해석, 수백 개 메시지 누락 |
| 2차 | `innerHTML` 전체 교체 | **실패** — 같은 HTML 파싱 문제 |
| 3차 | `insertAdjacentHTML` | **실패** — 메인 DOM에 직접 파싱하면 같은 HTML 파서 한계에 노출 |
| 4차 | `location.reload()` | **작동하지만 UX 저하** — 페이지 깜빡임, 스크롤 위치 손실 |
| **최종** | **iframe sandbox + `document.adoptNode()`** | **채택** — 숨겨진 iframe에서 격리 파싱 → `adoptNode()`로 노드를 메인 문서로 이동. 기존 DOM 건드리지 않고 새 메시지만 끝에 추가. 파싱 문제 완전 회피, 깜빡임 없음 |

**iframe sandbox 동작 원리**:
```
1. 숨겨진 iframe 생성 (width:0, height:0, visibility:hidden)
2. iframe.srcdoc에 새 메시지 HTML 주입
3. iframe.onload에서 iframe.contentDocument 접근
4. wrapper 내부의 각 노드를 document.adoptNode()로 메인 문서로 이동
5. #sse-live-messages 컨테이너에 appendChild
6. iframe 제거
```

**왜 `#sse-live-messages`인가?** (`#messages-container` 아닌 이유):
- 기존 `#messages-container`의 DOM이 대용량 세션에서 이미 불안정할 수 있음
- 별도의 깨끗한 컨테이너(`#sse-live-messages`)를 `messages-container` 바로 뒤에 배치
- 시각적으로는 연속으로 보이지만, DOM 구조적으로는 독립

### 4-3. 왜 `@@CCL_` 접두사 마커인가? (`<!-- MSG -->` 아닌 이유) — *역사적 기록, 이 방식도 결국 폐기됨*

**문제 상황**: claude-code-log 자체의 대화 세션에서 마커 문자열이 대화 내용에 리터럴로 포함됨.

예를 들어 이 대화에서:
- "서버의 `<!-- MSG -->` 마커로 분할" ← 대화 내용에 마커 문자열이 그대로 출력됨
- "서버의 `<!-- end-messages-container -->` 마커" ← 동일
- "`id='sse-empty-prompt'`" ← 동일

이 때문에:
- `html.find('<!-- end-messages-container -->')` → 대화 내용의 문자열에서 먼저 매칭 → HTML 추출이 메시지 1033에서 잘림
- `container_html.find("id='sse-empty-prompt'")` → 대화 내용에서 매칭 → empty-prompt 제거 시 정상 메시지까지 삭제
- `container_html.split('<!-- MSG -->')` → 대화 내용의 마커에서도 분할 → 메시지 카운트 불일치

**해결**:

| 항목 | 이전 (충돌 가능) | 현재 (충돌 방지) |
|------|-----------------|-----------------|
| 메시지 분할 마커 | `<!-- MSG -->` | `<!-- @@CCL_MSG_SPLIT@@ -->` |
| 컨테이너 종료 마커 | `<!-- end-messages-container -->` | `<!-- @@CCL_END_CONTAINER@@ -->` |
| 빈 프롬프트 ID | `id="sse-empty-prompt"` | `id="ccl-live-prompt"` |
| 문자열 검색 | `find()` (첫 번째 매칭) | `rfind()` (마지막 매칭, 이중 안전장치) |

### 4-4. 왜 폴링에서 watchdog으로 전환했나? (역사적 기록)

**초기 선택 이유 (폴링)**: 외부 의존성 없이 순수 `os.stat()`로 단순 구현. 2초 간격으로 CPU 부하 최소.

**전환 이유 (watchdog)**:
- 2초 폴링 + 5초 디바운스 → 최소 7초 지연. 실시간 동기화와 어울리지 않음.
- `settings.json`도 함께 감시해야 모델 변경을 즉각 감지할 수 있는데, 폴링으로 두 파일을 함께 감시하면 더 복잡해짐.
- `watchdog`은 크로스 플랫폼 호환 (Windows: ReadDirectoryChangesW, macOS: FSEvents, Linux: inotify) + 이미 PyPI의 일반적인 패키지.
- 결과: 즉각 감지 (ms 단위), idle 상태에서 CPU 사용 0.

### 4-5. 버스트 드레인 + settle이 필요한 이유

- Claude Code는 한 번의 응답에서 JSONL에 여러 항목(assistant, tool_use, tool_result, file-history-snapshot 등)을 순차 기록
- 첫 이벤트 즉시 읽으면 **쓰다 만 JSONL**을 파싱하게 됨
- watchdog은 각 쓰기마다 이벤트를 발생시키므로, 버스트(연속 이벤트)를 Queue에서 드레인 후 0.3s 대기
- 0.3s 후 다시 드레인하여 짧은 burst 전체를 하나의 이벤트로 처리 (이전 방식: 최대 5초 디바운스)

### 4-6. empty-prompt 관리

- 서버 응답에서 `id="ccl-live-prompt"` 요소를 제거 (브라우저 JS가 별도 관리)
- 새 메시지 append 전에 기존 empty-prompt를 ID로 제거 → 새 메시지 추가 → 새 empty-prompt 재생성
- 클래스가 아닌 ID로 관리하는 이유: 클릭 시 `empty-prompt` 클래스가 제거되어 querySelector로 찾지 못하는 문제 방지

### 4-7. 초기 메시지 카운트 방식

| 방식 | 결과 |
|------|------|
| `TreeWalker`로 `<!-- MSG -->` 주석 노드 순회 | **폐기** — 대용량 DOM에서 HTML 파싱 오류로 주석 노드 누락 가능, 마커 이름 변경 시 동기화 필요 |
| **`{{ messages\|length }}` Jinja2 서버 주입** | **채택** — 서버에서 정확한 메시지 수를 템플릿에 직접 주입, DOM 상태에 무관하게 정확 |

---

## 5. 디버깅 히스토리

실시간 동기화 구현 과정에서 발생한 버그들과 해결 과정. 시간순 기록.

### Bug 1: `updating` 플래그 영구 차단

**증상**: SSE 이벤트가 한 번 처리된 후 더 이상 업데이트되지 않음. 브라우저 콘솔에 SSE 이벤트는 계속 수신되지만 무시됨.

**원인**: 새 메시지가 없을 때(`serverTotal <= msgCount`) early return하면서 `updating = false`를 안 함.

```javascript
// 버그 코드
if (resp.total <= msgCount || !resp.html || !resp.html.trim()) return;
// ↑ updating이 true인 채로 return → 이후 모든 SSE 이벤트가 if (updating) return;에 걸림

// 수정 코드
if (serverTotal <= msgCount || !newHtml || !newHtml.trim()) {
    updating = false;  // ← 반드시 리셋
    return;
}
```

**영향**: SSE 연결은 살아있고 이벤트도 수신하지만, 모든 업데이트가 영구 차단됨.

### Bug 2: `after >= total` 시 4MB+ 불필요 전송

**증상**: 서버 로그에 매번 전체 HTML이 렌더링/전송되는 것이 보임. 이미 최신 상태인데도 대용량 응답.

**원인**: `after` 파라미터가 `total_msgs` 이상일 때 조기 반환 로직이 없어서, 전체 HTML을 렌더링하고 `container_html` 전체를 반환.

**수정**: 서버에 조기 반환 추가:
```python
if after >= total_msgs:
    return Response(
        json.dumps({"total": total_msgs, "html": ""}),
        mimetype="application/json", ...
    )
```

### Bug 3: 마커 문자열이 대화 내용과 충돌

**증상**: `total=1033`으로 고정, 실제 메시지는 1067개 이상. 브라우저에서 "server total: 1033, local count: 1067"로 new messages가 음수.

**원인**: 이 대화 세션 자체가 SSE 마커에 대해 논의하는 내용이라, 렌더링된 HTML에 마커 문자열이 대화 내용으로 포함됨.

```
html.find('<!-- end-messages-container -->')
→ 실제 템플릿 마커가 아닌, 메시지 #1033의 대화 내용에서 먼저 매칭
→ HTML 추출이 1033번째 메시지에서 잘림
→ 그 이후 메시지 전부 누락
```

**같은 원인의 연쇄 문제**:
- `container_html.find("id='sse-empty-prompt'")` → 대화 내용에서 매칭 → 정상 메시지 삭제
- `container_html.split('<!-- MSG -->')` → 대화 내용에서도 분할 → 메시지 카운트 불일치

**수정 (3단계)**:
1. `find()` → `rfind()` 변경 (마지막 매칭 = 진짜 템플릿 마커)
2. 모든 마커를 고유 접두사로 변경 (`@@CCL_MSG_SPLIT@@`, `@@CCL_END_CONTAINER@@`, `ccl-live-prompt`)
3. 서버 + 템플릿 양쪽 모두 동시에 마커 변경 (안 하면 Bug 4 발생)

> **⚠️ 이 접근법도 결국 실패**: Bug 8 참고. `rfind()`로 안전장치를 달아도, 대화 내용이 동일한 마커 문자열을 포함하면 대화 마지막 부분에서 여전히 오작동. HTML 마커 방식 자체를 완전 폐기하고 Python 객체 기반으로 전환.

### Bug 4: 마커 불일치로 `total=0` + `SyntaxError`

**증상**: 재설치 전에 브라우저 콘솔에서 `total=0`, `SyntaxError: Unexpected token '<'` 에러.

**원인**: 서버 코드만 새 마커(`@@CCL_MSG_SPLIT@@`)로 변경했는데, 브라우저에 로드된 템플릿은 아직 구 마커(`<!-- MSG -->`). 서버가 새 마커로 분할하려 하면 매칭되지 않아 `total=0` 반환. 또한 JSON 대신 HTML 에러 페이지가 반환되어 `JSON.parse()` 실패.

**수정**: 패키지 재설치(`uv pip install -e .`)로 템플릿 동기화. 이후 서버 재시작.

**교훈**: 서버 코드와 템플릿의 마커는 반드시 동시에 변경해야 함. 재설치 없이 서버만 재시작하면 캐시된 구 템플릿이 사용될 수 있음.

### Bug 6: custom title 기능 추가 후 SSE 500 에러

**증상**: SSE 실시간 동기화가 완전히 멈춤. 브라우저 콘솔에 매 업데이트마다 `500 INTERNAL SERVER ERROR`. 서버 로그에 `AttributeError: 'list' object has no attribute 'read_text'`.

**원인**: 다른 세션에서 custom title 기능(`_get_custom_title`)을 추가하면서 `render_session`과 `render_messages` 두 곳에서 잘못된 인자를 넘김.

```python
# 버그 코드 (render_session, render_messages 둘 다)
messages = load_transcript(jsonl_file, silent=True)
custom_title = _get_custom_title(messages, session_id)
#                                ↑ list를 넘김 — _get_custom_title은 Path를 받아야 함

# 수정 코드
custom_title = _get_custom_title(jsonl_file, session_id)
#                                ↑ Path 객체를 넘김
```

**영향**: `/api/sessions/.../messages` 엔드포인트(SSE가 새 메시지를 가져오는 곳)가 매번 500으로 실패 → 실시간 동기화 완전 중단. SSE 연결 자체(`/stream`)는 살아있어 LIVE 표시는 유지되지만 실제 내용 업데이트 없음.

**참고**: `serve_file`(세션 페이지 초기 로딩)은 `_get_custom_title(jsonl_file, ...)` 올바르게 호출하고 있었음. 그래서 페이지 열기는 정상, 실시간 업데이트만 실패.

---

### Bug 7: SSE로 추가된 메시지의 타임스탬프가 UTC 그대로 표시

**증상**: 초기 페이지 로드 시 메시지 시간은 로컬 시간(KST)으로 표시되지만, SSE로 실시간 추가된 메시지는 UTC 시간 그대로 표시됨.

**원인**: `timezone_converter.js`의 변환 함수가 IIFE 안에 갇혀 전역으로 노출되지 않음. SSE 코드가 `convertTimestamps()`를 호출하지만 해당 함수가 전역에 존재하지 않아 무시됨.

```javascript
// timezone_converter.js (수정 전)
(function() {
    function convertTimestampsToLocalTimezone() { ... }
    convertTimestampsToLocalTimezone(); // 초기 실행은 되지만 전역 노출 없음
})();

// SSE 코드에서 호출 시도
if (typeof convertTimestamps === 'function') convertTimestamps(); // undefined → 무시됨
```

**수정**: `timezone_converter.js`에 전역 노출 한 줄 추가:

```javascript
    convertTimestampsToLocalTimezone();
    window.convertTimestamps = convertTimestampsToLocalTimezone; // ← 추가
})();
```

**영향**: 초기 페이지 로드 시 모든 타임스탬프는 변환됨. SSE 추가 메시지만 UTC 그대로 표시되는 문제였음.

---

### Bug 8: `total` 값 고정 — 마커 오염 재발 (최종 해결: 마커 방식 완전 폐기)

**증상**: `total=1692`(또는 특정 값)으로 고정, 이후 새 메시지 추가되어도 SSE 업데이트 미발생. 브라우저 콘솔에 "server total: 1692, local count: 1692, no new messages"가 반복 출력됨.

**원인**: Bug 3에서 `@@CCL_MSG_SPLIT@@` 마커로 교체하고 `rfind()`로 안전장치를 달았지만, 근본 원인이 해결되지 않았음.

이 프로젝트의 세션 대화 자체에서 다음과 같은 대화가 이루어짐:
```
"서버의 <!-- @@CCL_MSG_SPLIT@@ --> 마커가..."
"`<ccl-msg-split></ccl-msg-split>` 방식으로 교체 후..."
```

이 텍스트가 JSONL에 저장 → mistune이 HTML 주석/태그를 이스케이프 없이 통과 → 렌더링된 HTML에 95개 이상의 마커 문자열이 대화 내용으로 포함. `rfind()`는 HTML 마지막에 위치한 `<!-- @@CCL_MSG_SPLIT@@ -->`을 찾지만, 그게 진짜 마커가 아니라 대화 내용에서 온 것일 경우 카운트가 오염됨.

**근본 문제**: HTML 마커는 어떤 접두사/이름을 쓰든, 마커 자체가 대화 주제가 될 경우 오염 불가피. `rfind()`는 위치 기반 안전장치일 뿐 내용 오염을 막지 못함.

**최종 해결: 마커 방식 완전 폐기**

```python
# 이전 (마커 기반)
html = renderer.generate_session(messages, session_id)
container_html = html[html.find('<div id="messages-container">'):html.rfind('<!-- @@CCL_END_CONTAINER@@ -->')]
parts = container_html.split('<!-- @@CCL_MSG_SPLIT@@ -->')
total_msgs = len(parts) - 1  # ← 대화 내용에 마커가 있으면 오염

# 현재 (Python 객체 기반)
template_messages = renderer.get_template_messages(messages, session_id=session_id)
total_msgs = len(template_messages)  # ← 순수 Python 리스트 길이, 오염 불가
if after is not None:
    new_tmpl = template_messages[after:]
    new_html = renderer.render_fragment(new_tmpl)  # 증분 렌더링
```

**추가 변경 (레이아웃 버그)**:
- 새 메시지가 `#prompt-dock` 아래에 표시되는 버그 발생
- 원인: DOM에서 `#sse-live-messages`가 `#prompt-dock` 뒤에 위치
- 수정: `#sse-live-messages`를 `#prompt-dock` 바로 앞으로 이동

**관련 추가 구현**:
- `html/renderer.py`: `get_template_messages()`, `render_fragment()` 메서드 추가
- `html/templates/messages_fragment.html`: 증분 렌더링용 Jinja2 프래그먼트 템플릿 (신규)
- `transcript.html`: 마커 3개 모두 제거 (`<!-- @@CCL_MSG_SPLIT@@ -->` 2곳, `<!-- @@CCL_END_CONTAINER@@ -->` 1곳)

---

### Bug 5: SSE 재연결 시 OFFLINE 표시 복구 안 됨

**증상**: 서버를 재시작하면 기존 탭에서 SSE가 자동 재연결되어 실시간 동기화는 정상 작동하지만, 우상단 인디케이터가 "OFFLINE"으로 유지됨.

**원인**: `source.onerror`에서 "OFFLINE"으로 변경하지만, EventSource 자동 재연결 시 `onopen`이 호출될 때 indicator를 복구하는 핸들러가 없음.

**수정**:
```javascript
source.onopen = function() {
    indicator.textContent = 'LIVE';
    indicator.style.background = '#22c55e';
};
```

**참고**: EventSource는 연결 끊김 시 자동으로 재연결을 시도함 (브라우저 내장). 재연결 성공 시 `onopen` 이벤트가 발생하므로 여기서 indicator를 복구.

### Bug 9: SSE `updating` 플래그에 의한 이벤트 누락 — Thinking만 표시되고 Assistant 응답 미표시

**증상**: SSE 콘솔에 `adopted 3 nodes` 성공 로그가 나오지만, Thinking 메시지만 화면에 보이고 Assistant 텍스트 응답이 표시되지 않음. 새탭에서 열기(전체 새로고침)하면 정상 표시.

**원인 분석**:

1. **JSONL 구조**: Claude Code는 Thinking과 Text를 **별도 JSONL 엔트리**로 저장 (같은 엔트리가 아님)
   ```
   Line 3472: assistant, types=['thinking']  ts=05:20:13
   Line 3473: assistant, types=['text']      ts=05:20:17  (4초 후)
   ```

2. **SSE 서버 타이밍**: 파일 변경 감지 → 디바운스(1초 안정 확인) → `updated` 이벤트 전송. Thinking 작성 시 파일이 일시적으로 안정되면(Text가 아직 안 쓰여짐) Thinking만 포함된 이벤트 발송.

3. **클라이언트 `updating` 플래그**: 
   ```javascript
   if (updating) return;  // ← 두 번째 이벤트를 완전히 무시!
   ```
   첫 번째 이벤트(Thinking) 처리 중 두 번째 이벤트(Text)가 도착하면 스킵. 3600줄 JSONL 파싱 + iframe 생성 + 노드 adopt에 5초 이상 소요되므로, 4초 간격의 Text 이벤트는 거의 항상 스킵됨.

4. **다음 이벤트 부재**: 첫 처리 완료 후 `updating=false`가 되지만, 스킵된 이벤트는 복구 불가. JSONL에 추가 변경이 없으면 영원히 누락.

**타임라인**:
```
05:20:13  Thinking 엔트리 작성
~05:20:15 SSE 감지 → "updated" 전송 → 클라이언트 fetch 시작 (updating=true)
05:20:17  Text 엔트리 작성
~05:20:20 SSE 감지 → "updated" 전송 → 클라이언트: updating=true → 스킵!
~05:20:22 첫 처리 완료 (updating=false) → 하지만 두 번째 이벤트 이미 유실
→ 추가 JSONL 변경 없으면 Text 영영 표시 안 됨
```

**수정** (`transcript.html`):

```javascript
// 이전: 이벤트 완전 스킵
if (updating) return;

// 수정: 이벤트를 기억해뒀다가 처리 완료 후 재fetch
var pendingUpdate = false;

source.onmessage = function(e) {
    var data = JSON.parse(e.data);
    if (data.type === 'updated') {
        if (updating) {
            pendingUpdate = true;  // 스킵하지 않고 기억
            return;
        }
        updating = true;
        // ... fetch 처리 ...
    }
};

// iframe onload 콜백 끝에:
updating = false;
if (pendingUpdate) {
    pendingUpdate = false;
    console.log('[SSE] processing pending update...');
    source.onmessage({data: JSON.stringify({type: 'updated'})});
}

// .catch() 핸들러에도 동일 로직 추가
```

**핵심**: `updating` 중 도착한 이벤트를 버리지 않고 `pendingUpdate` 플래그로 기억. 현재 처리 완료(성공/실패) 후 자동으로 `source.onmessage`를 재호출하여 누락된 메시지를 fetch.

**이 버그가 이전에 발견되지 않은 이유**: Bug 8(마커 오염)로 인해 2000+ 메시지 세션에서 `#sse-live-messages` 컨테이너 자체가 DOM 오염에 갇혀 보이지 않았음. HTML 이스케이프 수정 후 DOM이 정상화되면서 SSE가 처음으로 제대로 작동하게 되었고, 그제서야 이 이벤트 누락 문제가 관찰됨.

---

### Bug 10: SSE 동적 메시지의 fold 토글 미작동

**증상**: 페이지 초기 로드 시 이미 존재하던 메시지의 fold-bar는 정상 동작하지만, SSE 실시간 동기화로 새로 추가된 메시지의 fold-bar를 클릭해도 접기/펼치기가 동작하지 않음.

**원인 분석**:

1. **초기 리스너 바인딩 방식**: 페이지 로드 시 `querySelectorAll('.fold-bar-section')`으로 **그 시점에 존재하는 요소만** 탐색하여 각각 `addEventListener('click', ...)` 부착
   ```javascript
   // 기존 코드 — 페이지 로드 시점 요소에만 바인딩
   const foldBarSections = document.querySelectorAll('.fold-bar-section');
   foldBarSections.forEach(section => {
       section.addEventListener('click', function(e) { ... });
   });
   ```

2. **SSE 동적 추가**: iframe sandbox → `adoptNode()`로 DOM에 추가된 새 메시지 노드는 초기 `querySelectorAll` 실행 이후에 추가되므로, 클릭 이벤트 리스너가 없음

3. **리스너 재바인딩 부재**: SSE `iframe.onload` 콜백에서 `convertTimestamps()`, `initEmptyPrompt()` 등 후처리는 있지만, fold 리스너 재초기화는 호출하지 않음

**수정** (`transcript.html`):

개별 요소 바인딩을 **이벤트 위임(event delegation)** 패턴으로 변경. `document.body`에 한 번만 리스너를 등록하고, 클릭 이벤트가 버블업될 때 `closest('.fold-bar-section')`으로 대상 판별:

```javascript
// 수정: 이벤트 위임 — 동적 추가 요소에도 자동 적용
document.body.addEventListener('click', function(e) {
    var section = e.target.closest('.fold-bar-section');
    if (!section) return;
    e.stopPropagation();
    var action = section.getAttribute('data-action');
    var targetId = section.getAttribute('data-target');
    var isFolded = section.classList.contains('folded');

    if (action === 'fold-one') {
        handleFoldOne(targetId, isFolded, section);
    } else if (action === 'fold-all') {
        handleFoldAll(targetId, isFolded, section);
    }
});
```

**핵심**: 이벤트 위임은 부모 요소(body)에 리스너 하나만 등록하므로, 이후 DOM에 추가되는 모든 `.fold-bar-section` 요소가 별도 바인딩 없이 자동으로 fold 기능을 갖게 됨. SSE `iframe.onload`에 별도 초기화 코드 불필요.

---

### Bug 11: SSE 후 sticky 도크 padding 폭발 — 위로 스크롤 상태에서 재계산 시 body 하단에 수천 px 빈 공간

**증상**: SSE로 새 메시지가 도착한 뒤 마지막 Assistant 메시지창과 화면 맨 아래 사이가 너무 벌어짐. `scroll-bottom` 버튼(⬇️)을 눌러도 텅 빈 공간의 맨 밑으로만 이동하고, 마지막 메시지를 보려면 마우스 휠을 한참 위로 굴려야 함. `prev-user-msg` 버튼(▲)도 화면이 "쭈~욱" 위로 튐.

**원인 — 잘못 복사한 padding 재계산 공식**:

§24 (SSE textarea 보존 fix, `7e6f0ce`) 에서 프롬프트 element 재생성을 폐기하면서, body의 `padding-bottom` 을 SSE 업데이트 마다 다시 계산하는 코드를 추가. 이 때 §10 (sticky prompt, `556e3b4`) 의 초기 계산식을 그대로 복붙:

```javascript
// 잘못된 코드 — sticky된 도크에 대해 rect를 사용
var dockAbsTop = dock.getBoundingClientRect().top + window.scrollY;
var docHeight = document.documentElement.scrollHeight;
document.body.style.paddingBottom = (docHeight - dockAbsTop) + 'px';
```

이 공식은 **§10 초기 계산 시점엔 옳음** — 그땐 도크가 아직 normal flow에 있어서 `rect.top + scrollY`가 문서 내 실제 위치.

하지만 **§24 SSE 재계산 시점엔 도크가 이미 `position: fixed`** (sticky 된 상태). `getBoundingClientRect().top`이 뷰포트 기준 좌표를 리턴함:

- 뷰포트 하단에 고정된 도크의 `rect.top` ≈ `viewport_height - dock_height - 10`
- `dockAbsTop = (viewport_height - dock_height - 10) + scrollY`
- `padding = docHeight - dockAbsTop = docHeight - scrollY - viewport_height + dock_height + 10`

즉 padding이 **사용자의 스크롤 위치에 의존**하게 됨.

**수치로 재현** (문서 콘텐츠 4850px, 뷰포트 800px, 도크 150px):

| scrollY | 계산된 padding | 결과 |
|---|---|---|
| 4050 (하단 근처) | ~160px | 정상 |
| 500 (위로 스크롤한 상태) | **3710px** | body 하단에 거대한 빈 공간 |

`scroll-bottom` → `scrollHeight` (= 콘텐츠 4850 + padding 3710 = 8560) 로 이동 → 뷰포트 (7760~8560) 는 전부 빈 공간, 마지막 메시지(4750~4850)는 3000px 위에 있음.

**수정** ([transcript.html:1444-1454](claude_code_log/html/templates/transcript.html)):

같은 파일의 최소화 버튼 핸들러가 이미 사용하던 정답 방식으로 통일:

```javascript
// 도크는 position:fixed 라서 rect는 사용 불가. offsetHeight는 positioning과
// 무관하게 요소의 실제 레이아웃 높이를 리턴하므로 이걸 사용.
var dock = document.getElementById('prompt-dock');
if (dock && dock.classList.contains('sticky')) {
    document.body.style.paddingBottom = dock.offsetHeight + 'px';
}
```

**결과 — 세 곳의 padding 계산이 일관됨**:

| 위치 | 도크 상태 | 계산 방식 |
|---|---|---|
| §10 초기 (`initEmptyPrompt`) | normal flow | `docHeight - dockAbsTop` (= 사실상 `dock.offsetHeight`) |
| §10 최소화 버튼 핸들러 | fixed | `dock.offsetHeight` |
| §24 SSE 재계산 (**수정 후**) | fixed | `dock.offsetHeight` ← 통일 |

`docHeight - dockAbsTop` 공식은 오직 §10 초기 시점(도크가 normal flow에 있을 때)에만 옳게 동작한다는 사실을 인지하지 못하고 §24 코드에 복사한 게 이 버그의 근원.

---

## 6. 현재 구현 코드

### 수정 파일 (2개)

#### 6-1. `claude_code_log/server.py` — 4개 엔드포인트

**동적 세션 렌더링** (`serve_file` 수정):
```python
@app.route("/<path:filepath>")
def serve_file(filepath: str) -> Response:
    import re
    # 세션 페이지 요청이면 정적 파일 대신 JSONL에서 동적 렌더링
    session_match = re.match(r".+/session-([a-f0-9-]+)\.html$", filepath)
    if session_match:
        session_id = session_match.group(1)
        jsonl_file = _find_session_jsonl(projects_dir, session_id)
        if jsonl_file is not None:
            from .converter import load_transcript
            from .html.renderer import HtmlRenderer
            messages = load_transcript(jsonl_file, silent=True)
            renderer = HtmlRenderer()
            html = renderer.generate_session(messages, session_id)
            return Response(html, mimetype="text/html",
                          headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    # 그 외 파일은 정적 서빙
    ...
```

> **핵심**: 세션 페이지를 정적 파일에서 서빙하면 템플릿 변경이 반영되지 않고 내용도 구식임. 동적 렌더링으로 항상 최신.

**SSE 엔드포인트** (watchdog + 버스트 드레인):
```python
@app.route("/api/sessions/<session_id>/stream")
def stream_session(session_id: str) -> Response:
    jsonl_file = _find_session_jsonl(projects_dir, session_id)

    def generate():
        event_queue: Queue[str] = Queue()
        handler = _SSEFileWatcher(
            {jsonl_file: "jsonl", _CLAUDE_SETTINGS_PATH: "settings"},
            event_queue,
        )
        observer = Observer()
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
            # 연결 즉시 현재 모델 전송 → 배지 즉시 표시
            if last_model:
                yield f"data: {json.dumps({'type': 'model', 'model': last_model})}\n\n"

            while True:
                try:
                    tag = event_queue.get(timeout=15.0)  # 15s keepalive
                except Empty:
                    yield ":\n\n"  # SSE keepalive
                    continue

                # 버스트 드레인 + settle
                tags = {tag}
                try:
                    while True: tags.add(event_queue.get_nowait())
                except Empty:
                    pass
                time_module.sleep(0.3)
                try:
                    while True: tags.add(event_queue.get_nowait())
                except Empty:
                    pass

                if "jsonl" in tags:
                    try:
                        stat = jsonl_file.stat()
                    except FileNotFoundError:
                        yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                        break
                    if stat.st_size != last_size or stat.st_mtime != last_mtime:
                        last_size = stat.st_size
                        last_mtime = stat.st_mtime
                        model = _get_latest_model(jsonl_file)
                        last_model = model
                        yield f"data: {json.dumps({'type': 'updated', 'model': model})}\n\n"
                        continue

                # settings.json watchdog 이벤트 → settings.json에서 직접 읽음.
                # _get_latest_model() 사용 금지: JSONL을 우선 읽는데, /model은
                # 메시지 전송 전까지 JSONL에 기록되지 않아 이전 모델이 반환됨.
                current_model = _get_current_model_from_settings() or _DEFAULT_MODEL
                if current_model != last_model:
                    last_model = current_model
                    yield f"data: {json.dumps({'type': 'model', 'model': current_model})}\n\n"
        finally:
            observer.stop()
            observer.join(timeout=2)

    return Response(generate(), mimetype="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

**렌더 엔드포인트** (전체 세션 HTML):
```python
@app.route("/api/sessions/<session_id>/render")
def render_session(session_id: str) -> Response:
    jsonl_file = _find_session_jsonl(projects_dir, session_id)
    messages = load_transcript(jsonl_file, silent=True)
    renderer = HtmlRenderer()
    html = renderer.generate_session(messages, session_id)
    return Response(html, mimetype="text/html",
                   headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
```

**메시지 증분 엔드포인트** (핵심):
```python
@app.route("/api/sessions/<session_id>/messages")
def render_messages(session_id: str) -> Response:
    # JSONL 파싱 → Python TemplateMessage 리스트 (HTML 렌더링 없이 객체만 생성)
    messages = load_transcript(jsonl_file, silent=True)
    renderer = HtmlRenderer()
    template_messages = renderer.get_template_messages(messages, session_id=session_id)
    total_msgs = len(template_messages)  # ← 순수 Python 리스트 길이, 대화 내용에 무관

    after = request.args.get('after', type=int)
    if after is not None:
        if after >= total_msgs:
            # 이미 최신 — 빈 응답 반환 (불필요한 전송 방지)
            return Response(
                json.dumps({"total": total_msgs, "html": ""}),
                mimetype="application/json", ...
            )
        new_tmpl = template_messages[after:]   # Python 슬라이싱
        new_html = renderer.render_fragment(new_tmpl)  # 증분 렌더링
        return Response(json.dumps({"total": total_msgs, "html": new_html}), ...)

    # after 없음: 전체 프래그먼트
    full_html = renderer.render_fragment(template_messages)
    return Response(json.dumps({"total": total_msgs, "html": full_html}), ...)
```

> **핵심 차이**: 이전에는 전체 HTML을 렌더링 후 마커로 문자열 파싱. 현재는 Python 객체 리스트를 슬라이싱 후 해당 부분만 렌더링. 대화 내용에 마커가 포함되어도 카운트 오염 자체가 불가능.

#### 6-2. `claude_code_log/html/templates/transcript.html`

**마커 완전 제거**: `<!-- @@CCL_MSG_SPLIT@@ -->` (메시지 앞 2곳), `<!-- @@CCL_END_CONTAINER@@ -->` (컨테이너 종료 1곳) 모두 삭제.

**`#sse-live-messages` 위치**: `#prompt-dock` 바로 앞에 배치 (DOM 순서가 시각적 순서를 결정):
```html
</div><!-- messages-container 닫기 -->
<!-- SSE 실시간 메시지 컨테이너: #prompt-dock 앞에 위치해야 새 메시지가 올바른 순서로 표시됨 -->
<div id="sse-live-messages"></div>
<div id="prompt-dock">
    <div id='ccl-live-prompt' class='message user empty-prompt'>...</div>
</div>
```

> 이전: `#sse-live-messages`가 `#prompt-dock` 뒤에 있어 새 메시지가 빈 말풍선 아래에 삽입되는 레이아웃 버그 존재.

**신규 파일**: `claude_code_log/html/templates/messages_fragment.html` — 증분 렌더링용 Jinja2 프래그먼트 템플릿. `transcript.html`의 메시지 루프와 동일하되 페이지 구조(`<html>`, `<head>` 등) 없음.

**EventSource JS** (iframe sandbox + adoptNode 방식):
```javascript
(function() {
    var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
    if (!match) return;
    var sessionId = match[1];
    var source = new EventSource('/api/sessions/' + sessionId + '/stream');
    var updating = false;

    // LIVE 인디케이터 (우상단 초록 뱃지)
    var indicator = document.createElement('div');
    indicator.id = 'live-indicator';
    indicator.textContent = 'LIVE';
    indicator.style.cssText = 'position:fixed;top:10px;right:10px;background:#22c55e;...';
    document.body.appendChild(indicator);

    // 초기 메시지 수: 서버에서 Jinja2로 주입 (DOM 카운트보다 정확)
    var msgCount = {{ messages|length }};

    source.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (data.type === 'updated') {
            if (updating) return;
            updating = true;
            var atBottom = (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 150;

            // 새 메시지만 요청
            fetch('/api/sessions/' + sessionId + '/messages?after=' + msgCount + '&t=' + Date.now())
                .then(function(r) { return r.json(); })
                .then(function(resp) {
                    var serverTotal = resp.total;
                    var newHtml = resp.html;

                    if (serverTotal <= msgCount || !newHtml || !newHtml.trim()) {
                        updating = false;  // 반드시 리셋 (안 하면 이후 모든 SSE 이벤트 영구 차단)
                        return;
                    }

                    // empty-prompt 제거
                    var oldPrompt = document.getElementById('ccl-live-prompt');
                    if (oldPrompt) oldPrompt.remove();

                    // #sse-live-messages: messages-container 외부의 깨끗한 컨테이너
                    var liveContainer = document.getElementById('sse-live-messages');

                    // iframe sandbox에서 격리 파싱 → adoptNode로 안전한 DOM 이동
                    var iframe = document.createElement('iframe');
                    iframe.style.cssText = 'position:absolute;width:0;height:0;border:0;visibility:hidden;';
                    document.body.appendChild(iframe);
                    iframe.srcdoc = '<!DOCTYPE html><html><body><div id="__wrapper">' + newHtml + '</div></body></html>';

                    iframe.onload = function() {
                        var wrapper = iframe.contentDocument.getElementById('__wrapper');
                        if (wrapper) {
                            var nodeCount = 0;
                            while (wrapper.firstChild) {
                                var node = document.adoptNode(wrapper.firstChild);
                                liveContainer.appendChild(node);
                                nodeCount++;
                            }
                        }

                        // empty-prompt 재생성
                        var promptDiv = document.createElement('div');
                        promptDiv.id = 'ccl-live-prompt';
                        promptDiv.className = 'message user empty-prompt';
                        promptDiv.innerHTML = '...';
                        liveContainer.appendChild(promptDiv);

                        document.body.removeChild(iframe);

                        // 후처리
                        if (typeof convertTimestamps === 'function') convertTimestamps();
                        if (typeof window.initEmptyPrompt === 'function') window.initEmptyPrompt();
                        if (atBottom) window.scrollTo(0, document.body.scrollHeight);

                        // 인디케이터 깜빡임 (파란색 → 초록색)
                        indicator.style.background = '#3b82f6';
                        setTimeout(function() { indicator.style.background = '#22c55e'; }, 300);

                        msgCount = serverTotal;
                        updating = false;
                    };
                })
                .catch(function(err) {
                    console.error('[SSE] update error:', err);
                    updating = false;
                });
        } else if (data.type === 'deleted') {
            indicator.textContent = 'DELETED';
            indicator.style.background = '#ef4444';
            source.close();
        }
    };
    source.onerror = function() {
        indicator.textContent = 'OFFLINE';
        indicator.style.background = '#6b7280';
    };
    source.onopen = function() {
        indicator.textContent = 'LIVE';
        indicator.style.background = '#22c55e';
    };
})();
```

---

## 7. 현재 한계점

1. **매 요청마다 전체 JSONL 파싱**: 새 메시지 1개를 위해 JSONL 전체를 파싱하고 `TemplateMessage` 리스트를 생성. 단, `render_fragment()`는 `after:` 슬라이스만 렌더링하므로 HTML 생성은 증분으로 이루어짐.
2. **Flask 내장 서버 제한**: SSE 연결이 스레드 하나를 점유, 동시 연결 수 제한
3. **메시지 카운트 기반 동기화**: 메시지 수정/삭제는 감지하지 못함 (추가만 감지)

---

## 8. 변경 이력 요약

### 초기 구현 → 현재 (전체 변경 내역)

| # | 항목 | 이전 (초기) | 현재 | 이유 |
|---|------|-----------|------|------|
| 1 | DOM 삽입 | `insertAdjacentHTML` | iframe sandbox + `adoptNode()` | 깨진 HTML 파싱 안전성 |
| 2 | 삽입 대상 | `#messages-container` | `#sse-live-messages` | 기존 DOM 오염 방지 |
| 3 | 초기 카운트 | `TreeWalker` 주석 순회 | `{{ messages\|length }}` 서버 주입 | DOM 상태 무관 정확성 |
| 4 | 메시지 마커 | `<!-- MSG -->` | `<!-- @@CCL_MSG_SPLIT@@ -->` | 대화 내용과 충돌 방지 |
| 5 | 종료 마커 | `<!-- end-messages-container -->` | `<!-- @@CCL_END_CONTAINER@@ -->` | 동일 |
| 6 | 프롬프트 ID | `id="sse-empty-prompt"` | `id="ccl-live-prompt"` | 동일 |
| 7 | 문자열 검색 | `find()` | `rfind()` | 이중 안전장치 |
| 8 | `after>=total` | 전체 HTML 반환 | 빈 응답 조기 반환 | 4MB+ 불필요 전송 방지 |
| 9 | early return | `updating` 미리셋 | `updating = false` 추가 | SSE 영구 차단 버그 |
| 10 | 재연결 복구 | 없음 | `source.onopen` 핸들러 | OFFLINE→LIVE 자동 복구 |
| 11 | 에러 처리 | 없음 | `.catch()` 핸들러 | fetch 실패 시 플래그 리셋 |
| 12 | `_get_custom_title` 인자 | `messages`(list) 잘못 전달 | `jsonl_file`(Path) 올바르게 전달 | custom title 추가 시 버그, SSE 500 에러 유발 |
| 13 | SSE 추가 메시지 시간 변환 | 변환 안 됨 (UTC 그대로) | `window.convertTimestamps` 전역 노출 | `timezone_converter.js` 함수가 IIFE 안에 갇혀 SSE 호출 불가 |
| 14 | 메시지 카운트 방식 | HTML 마커 + `rfind()` 문자열 파싱 | `get_template_messages()` Python 객체 `len()` | Bug 8: 마커 문자열이 대화 내용에 포함 → `rfind()`도 오염 방어 불가 |
| 15 | 증분 렌더링 | 마커 분할 + 문자열 슬라이싱 | `template_messages[after:]` + `render_fragment()` | 마커 방식 폐기의 연장선 |
| 16 | `#sse-live-messages` DOM 위치 | `#prompt-dock` 뒤 | `#prompt-dock` 앞 | 새 메시지가 빈 말풍선 아래에 표시되는 레이아웃 버그 수정 |
| 17 | 마커 파일 | `<!-- @@CCL_MSG_SPLIT@@ -->`, `<!-- @@CCL_END_CONTAINER@@ -->` in `transcript.html` | 마커 완전 제거 | 마커 방식 폐기 |
| 18 | `updating` 중 이벤트 처리 | `if (updating) return;` — 완전 스킵 | `pendingUpdate` 플래그 + 처리 완료 후 재fetch | Bug 9: Thinking/Text 별도 엔트리 → 두 번째 이벤트 유실 |
| 19 | fold-bar 이벤트 바인딩 | `querySelectorAll().forEach(addEventListener)` — 초기 요소만 | `document.body` 이벤트 위임 (`closest()`) | Bug 10: SSE 동적 메시지에 리스너 없음 |
| 20 | 파일 변경 감지 | `time.sleep(2)` + `os.stat()` 폴링 | `watchdog` Observer + `Queue` 브리지 | 즉각 감지 (ms), idle CPU 0, settings.json 동시 감시 |
| 21 | 모델 배지 | 없음 | SSE `{type:'model'}` 이벤트, JSONL-first 우선순위 | 빈 프롬프트에 현재 모델 실시간 표시, 세션-로컬 정확도 |
| 22 | settings.json 감시 | 없음 | watchdog이 settings.json도 함께 감시 | `/model` 전환 즉시 모델 배지 갱신 |
| 23 | 모델 우선순위 | settings.json 전역 우선 | JSONL 마지막 assistant → settings.json 폴백 | 다른 프로젝트 /model 전환이 현재 세션에 영향 주던 버그 수정 |
| 24 | settings 이벤트 모델 읽기 | `_get_latest_model()` (JSONL 우선) | `_get_current_model_from_settings() or _DEFAULT_MODEL` | `/model` 실행 후 JSONL에 아직 기록 전이라 JSONL 우선 읽기 시 이전 모델 반환 → 배지 갱신 안 됨. settings.json 직접 읽기로 수정 |
| 25 | `/model default` 처리 | 없음 (None 반환 → 배지 갱신 안 됨) | `_DEFAULT_MODEL = "claude-sonnet-4-6"` 상수 + `or _DEFAULT_MODEL` 매핑 | `/model default` 시 settings.json에서 `"model"` 키 삭제됨 → None → 기본 모델로 배지 갱신 |
| 26 | JSONL user 엔트리 스캔 | assistant 엔트리만 스캔 | `_MODEL_CMD_RE.search()` + user 엔트리 `"Set model to X"` 패턴 스캔 | 응답 전에도 `/model` 명령이 JSONL에 기록된 경우 모델 반영 가능 |

### 관련 커밋

> 커밋 히스토리는 [CUSTOM_FEATURES.md](CUSTOM_FEATURES.md#커밋-히스토리-시간순)에서 통합 관리.

---

## 9. 인덱스 페이지 업데이트 방식

세션 페이지는 SSE로 실시간 동기화되지만, 인덱스 페이지(`/`)는 별도의 메커니즘이 필요하다.

### 배경

기존에는 서버 시작 시 `index.html`을 한 번만 생성했고, 이후 Claude가 새 세션을 만들어도 브라우저를 새로고침해도 반영되지 않았음.

### 비교: 세션 페이지 vs 인덱스 페이지

| 구분 | 세션 페이지 | 인덱스 페이지 |
|------|------------|-------------|
| **업데이트 방식** | SSE + EventSource (자동) | 수동 새로고침 시 재생성 |
| **필요성** | Claude 대화 중 실시간 확인 필요 | 새 세션 확인은 세션 시작 전후 → 수동 새로고침으로 충분 |
| **부하** | JSONL 폴링 2초 간격 | 새로고침할 때만 1회 |

### 설계 결정: 왜 폴링/SSE 없이 새로고침 기반인가?

인덱스 페이지에서 실시간 감지까지 구현하는 건 과잉이다:
- 새 세션이 생겼는지 확인하는 행위 자체가 이미 사용자의 의식적인 액션 (탭 전환, 새로고침)
- 10초 폴링도 불필요한 서버 부하 발생
- 수동 새로고침 시 재생성으로 요구사항 100% 충족

### 구현

**`claude_code_log/server.py`** — `index()` 라우트

```python
@app.route("/")
def index() -> Response:
    from .converter import process_projects_hierarchy

    process_projects_hierarchy(projects_dir, use_cache=True, silent=True, cache_only=True)
    index_file = projects_dir / "index.html"
    if index_file.exists():
        response = send_file(index_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    return Response(LOADING_HTML, mimetype="text/html")
```

> **핵심**: `cache_only=True`로 호출하여 캐시 메타데이터만 갱신하고 HTML 생성을 스킵. 인덱스 페이지에 필요한 세션 목록/요약 정보는 캐시에서 조회. 이 최적화로 20.8s → 5~7s로 단축. index.html이 없으면(삭제된 경우) 로딩 화면 표시 후 재생성 완료 시 자동 전환 (섹션 6 참조).
