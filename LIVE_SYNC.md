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
| SSE 스트림 서버 | `server.py` → `stream_session()` | JSONL 파일 폴링, 변경 시 이벤트 전송 |
| 메시지 증분 API | `server.py` → `render_messages()` | 전체 HTML 렌더링 후 마커로 분할, `after=N` 이후만 반환 |
| 동적 세션 렌더링 | `server.py` → `serve_file()` | 세션 페이지 요청 시 JSONL에서 최신 HTML 동적 생성 |
| EventSource 클라이언트 | `transcript.html` → `<script>` | SSE 수신, iframe sandbox 파싱, DOM 증분 추가 |
| 메시지 분할 마커 | `transcript.html` → 템플릿 | `<!-- @@CCL_MSG_SPLIT@@ -->` 주석으로 메시지 경계 표시 |

---

## 2. 데이터 흐름

```
1. Claude Code가 JSONL 파일에 새 줄 기록
       ↓
2. SSE 서버가 2초 폴링으로 파일 크기/수정시간 변경 감지
       ↓
3. 디바운스: 1초간 추가 변경 없을 때까지 대기 (최대 5회)
       ↓
4. SSE로 {"type": "updated"} 이벤트 전송
       ↓
5. 브라우저 EventSource가 수신
       ↓
6. /api/sessions/{id}/messages?after=N 으로 새 메시지만 요청
       ↓
7. 서버: JSONL 전체 파싱 → HTML 렌더링 → <!-- @@CCL_MSG_SPLIT@@ --> 마커로 분할 → N 이후 메시지만 반환
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
| **파일 변경 감지** | `os.stat()` 폴링 | JSONL 파일 크기/수정시간 비교 (2초 간격) |
| **데이터 소스** | JSONL 파일 | Claude Code가 기록하는 대화 로그 |
| **API 응답** | JSON | `{"total": N, "html": "..."}` 형식 |
| **HTML 렌더링** | Jinja2 + mistune + Pygments | JSONL → 메시지 파싱 → HTML 생성 |
| **DOM 조작** | iframe sandbox + `document.adoptNode()` | 격리 환경에서 HTML 파싱 후 안전한 DOM 이동 |
| **메시지 분할** | `<!-- @@CCL_MSG_SPLIT@@ -->` HTML 주석 마커 | 서버/브라우저 간 메시지 단위 동기화 |

추가된 외부 의존성 **없음**. 모두 기존 의존성(Flask, Jinja2 등)만 사용.

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

### 4-3. 왜 `@@CCL_` 접두사 마커인가? (`<!-- MSG -->` 아닌 이유)

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

### 4-4. 왜 폴링인가? (파일시스템 이벤트 아닌 이유)

- `watchdog` 같은 라이브러리 없이 순수 `os.stat()`로 단순 구현
- 크로스 플랫폼 호환 (Windows/macOS/Linux)
- 2초 간격으로 CPU 부하 최소

### 4-5. 디바운스가 필요한 이유

- Claude Code는 한 번의 응답에서 JSONL에 여러 항목(assistant, tool_use, tool_result, file-history-snapshot 등)을 순차 기록
- 파일 변경 즉시 읽으면 **쓰다 만 JSONL**을 파싱하게 됨
- 1초간 추가 변경 없을 때까지 대기 (최대 5회 = 5초)하여 완전한 데이터만 처리

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

**SSE 엔드포인트** (폴링 + 디바운스):
```python
@app.route("/api/sessions/<session_id>/stream")
def stream_session(session_id: str) -> Response:
    jsonl_file = _find_session_jsonl(projects_dir, session_id)

    def generate():
        last_size = jsonl_file.stat().st_size
        last_mtime = jsonl_file.stat().st_mtime
        while True:
            time_module.sleep(2)  # 2초 간격 폴링
            try:
                stat = jsonl_file.stat()
            except FileNotFoundError:
                yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                break
            if stat.st_size != last_size or stat.st_mtime != last_mtime:
                # Debounce: 파일이 안정될 때까지 대기 (최대 5초)
                for _ in range(5):
                    time_module.sleep(1)
                    try:
                        new_stat = jsonl_file.stat()
                    except FileNotFoundError:
                        break
                    if new_stat.st_size == stat.st_size and new_stat.st_mtime == stat.st_mtime:
                        break  # 파일 안정됨
                    stat = new_stat
                last_size = stat.st_size
                last_mtime = stat.st_mtime
                yield f"data: {json.dumps({'type': 'updated'})}\n\n"
            else:
                yield ":\n\n"  # SSE keepalive

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
    # JSONL → 전체 HTML 렌더링
    messages = load_transcript(jsonl_file, silent=True)
    html = renderer.generate_session(messages, session_id)

    # messages-container 내용 추출 (rfind로 마지막 마커 매칭 — 대화 내용과의 충돌 방지)
    start_marker = '<div id="messages-container">'
    end_marker = '<!-- @@CCL_END_CONTAINER@@ -->'
    start_idx = html.find(start_marker)
    end_idx = html.rfind(end_marker)  # rfind: 대화 내용에 마커 문자열이 있어도 마지막(진짜) 마커를 찾음
    container_html = html[start_idx + len(start_marker):end_idx]

    # empty-prompt 제거 (브라우저 JS가 관리) — rfind로 마지막 매칭
    prompt_marker = "id='ccl-live-prompt'"
    prompt_idx = container_html.rfind(prompt_marker)
    if prompt_idx != -1:
        div_start = container_html.rfind('<div', 0, prompt_idx)
        container_html = container_html[:div_start].rstrip()

    # <!-- @@CCL_MSG_SPLIT@@ --> 마커로 분할
    msg_marker = '<!-- @@CCL_MSG_SPLIT@@ -->'
    parts = container_html.split(msg_marker)
    total_msgs = len(parts) - 1

    after = request.args.get('after', type=int)
    if after is not None:
        if after >= total_msgs:
            # 이미 최신 — 빈 응답 반환 (불필요한 4MB+ HTML 전송 방지)
            return json({"total": total_msgs, "html": ""})
        new_parts = parts[after + 1:]
        new_html = ''.join(msg_marker + p for p in new_parts)
        return json({"total": total_msgs, "html": new_html})

    return json({"total": total_msgs, "html": container_html})
```

#### 6-2. `claude_code_log/html/templates/transcript.html` — 3가지 변경

**`<!-- @@CCL_MSG_SPLIT@@ -->` 마커 추가** (각 메시지 div 앞):
```html
<div id="messages-container">
{% for message, ... in messages %}
    <!-- @@CCL_MSG_SPLIT@@ -->
    <div class='message {{ css_class }}' ...>
        ...
    </div>
{% endfor %}
    <div id='ccl-live-prompt' class='message user empty-prompt'>...</div>
</div><!-- @@CCL_END_CONTAINER@@ -->
```

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

1. **매 요청마다 전체 JSONL 파싱 + 전체 HTML 렌더링**: 새 메시지 1개를 위해 전체를 렌더링하고 잘라서 반환 (증분 렌더링 미구현)
2. **폴링 기반 감지**: 최소 2초 + 디바운스 1초 = 최소 3초 지연 (파일시스템 이벤트 방식으로 개선 가능)
3. **Flask 내장 서버 제한**: SSE 연결이 스레드 하나를 점유, 동시 연결 수 제한
4. **메시지 카운트 기반 동기화**: 메시지 수정/삭제는 감지하지 못함 (추가만 감지)

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

    process_projects_hierarchy(projects_dir, use_cache=True, silent=True)
    index_file = projects_dir / "index.html"
    if index_file.exists():
        response = send_file(index_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    return Response(LOADING_HTML, mimetype="text/html")
```

> **핵심**: `use_cache=True`로 호출하므로 변경된 파일만 처리. 캐시 덕분에 대부분의 경우 빠르게 완료. index.html이 없으면(삭제된 경우) 로딩 화면 표시 후 재생성 완료 시 자동 전환 (섹션 6 참조).
