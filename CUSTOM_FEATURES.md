# claude-code-log 커스텀 기능 구현 가이드

> 원본 프로젝트([daaain/claude-code-log](https://github.com/daaain/claude-code-log))에 추가한 커스텀 기능들의 구현 방법.
> 새 환경에서 동일 기능을 재현할 때 참고용.

---

## 목차

1. [빈 User 메시지 풍선](#1-빈-user-메시지-풍선)
2. [세션 제목 수정](#2-세션-제목-수정)
3. [세션 삭제 (X 버튼)](#3-세션-삭제-x-버튼)
4. [Archived 세션 필터링](#4-archived-세션-필터링)
5. [실시간 동기화 (SSE)](#5-실시간-동기화-sse)
6. [인덱스 재생성 로딩 화면](#6-인덱스-재생성-로딩-화면)
7. [색상 커스터마이징](#7-색상-커스터마이징)

---

## 1. 빈 User 메시지 풍선

**목적**: 세션 하단에 빈 User 입력 풍선을 항상 표시.

### 수정 파일

**`claude_code_log/html/templates/transcript.html`**

메시지 루프 끝에 추가 (messages-container 닫기 직전):
```html
<div class='message user empty-prompt'>
    <div class='header'><span>🤷 User</span></div>
    <div class='content'>
        <textarea class='user-input' placeholder='메시지를 입력하세요...'></textarea>
    </div>
</div>
```

> **변경 이력**: 초기에는 `{% if ns.last_css == 'assistant' %}` 조건부였으나, tool_result/tool_use로 끝나는 세션(중단된 세션)에서도 표시되어야 하므로 조건 제거하여 항상 표시.

같은 파일의 `<script>` 안에 클릭 활성화 JS:
```javascript
window.initEmptyPrompt = function() {
    var ep = document.querySelector('.message.user.empty-prompt');
    if (ep) {
        ep.addEventListener('click', function () {
            this.classList.remove('empty-prompt');
            var textarea = this.querySelector('.user-input');
            textarea.addEventListener('input', function () {
                this.style.height = 'auto';
                this.style.height = this.scrollHeight + 'px';
                window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            });
            textarea.focus();
        }, { once: true });
    }
};
window.initEmptyPrompt();
```

> **주의**: `window.initEmptyPrompt`로 전역 함수 선언 필수. SSE DOM 교체 후 재바인딩에 사용됨.

---

## 2. 세션 제목 수정

**목적**: 인덱스/세션 네비게이션에서 ✏️ 버튼으로 세션 제목을 인라인 편집.

### 수정 파일 (3개)

#### 2-1. `claude_code_log/server.py` — API 엔드포인트

헬퍼 함수:
```python
def _update_custom_title(jsonl_file: Path, session_id: str, new_title: str) -> None:
    """JSONL 파일에 custom-title 항목 추가/수정."""
    lines = jsonl_file.read_text(encoding="utf-8").splitlines()
    new_entry = json.dumps(
        {"type": "custom-title", "customTitle": new_title, "sessionId": session_id},
        ensure_ascii=False,
    )
    # 기존 custom-title 항목이 있으면 덮어쓰고, 없으면 맨 뒤에 추가
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            data = json.loads(stripped)
            if data.get("type") == "custom-title" and data.get("sessionId") == session_id:
                new_lines.append(new_entry)
                updated = True
                continue
        except json.JSONDecodeError:
            pass
        new_lines.append(line)
    if not updated:
        new_lines.append(new_entry)
    jsonl_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
```

`create_app()` 안에 PUT 엔드포인트:
```python
@app.route("/api/sessions/<session_id>/title", methods=["PUT"])
def update_title(session_id: str) -> Response:
    data = request.get_json()
    new_title = str(data["title"]).strip()
    jsonl_file = _find_session_jsonl(projects_dir, session_id)
    _update_custom_title(jsonl_file, session_id, new_title)
    process_projects_hierarchy(projects_dir, use_cache=True, silent=True)
    return jsonify({"status": "ok", "title": new_title})
```

#### 2-2. `claude_code_log/html/templates/components/session_nav.html` — 편집 버튼

```html
<button class='session-edit-btn' title='제목 수정'>✏️</button>
```

#### 2-3. `claude_code_log/html/templates/components/session_edit_script.js` — 인라인 편집 JS

```javascript
document.querySelectorAll('.session-edit-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sessionLink = this.closest('.session-link');
        var sessionId = sessionLink.dataset.sessionId;
        var titleSpan = sessionLink.querySelector('.session-title');
        var currentTitle = titleSpan.dataset.title || '';

        // input + 확인 버튼 생성
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'session-title-input';
        input.value = currentTitle;
        var confirmBtn = document.createElement('button');
        confirmBtn.className = 'session-title-confirm-btn';
        confirmBtn.textContent = '✓';
        var wrapper = document.createElement('span');
        wrapper.className = 'session-title-edit-wrapper';
        wrapper.appendChild(input);
        wrapper.appendChild(confirmBtn);
        titleSpan.replaceWith(wrapper);
        input.focus();
        input.select();

        function cancel() { wrapper.replaceWith(titleSpan); }
        function save() {
            var newTitle = input.value.trim();
            if (!newTitle || newTitle === currentTitle) { cancel(); return; }
            fetch('/api/sessions/' + sessionId + '/title', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            }).then(function (r) { if (r.ok) location.reload(); else cancel(); });
        }
        confirmBtn.addEventListener('click', save);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') cancel();
        });
        input.addEventListener('blur', cancel);
    });
});
```

---

## 3. 세션 삭제 (X 버튼)

**목적**: X 버튼 클릭 시 JSONL + 세션 HTML 삭제, SQLite 캐시 초기화, index.html 재생성.

### 수정 파일 (3개)

#### 3-1. `claude_code_log/server.py` — DELETE 엔드포인트

```python
@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id: str) -> Response:
    from .cache import CacheManager
    from .converter import get_library_version, process_projects_hierarchy

    # 1) 프로젝트 디렉토리 찾기
    project_dir = None
    jsonl_file = _find_session_jsonl(projects_dir, session_id)
    if jsonl_file is not None:
        project_dir = jsonl_file.parent
    else:
        matches = list(projects_dir.rglob(f"session-{session_id}.html"))
        if matches:
            project_dir = matches[0].parent
    if project_dir is None:
        return jsonify({"error": "session not found"}), 404

    # 2) JSONL + 세션 HTML 삭제
    if jsonl_file is not None:
        jsonl_file.unlink()
    session_html = project_dir / f"session-{session_id}.html"
    if session_html.exists():
        session_html.unlink()

    # 3) 프로젝트 캐시 전체 초기화 (SQLite)
    try:
        cm = CacheManager(project_dir, get_library_version())
        cm.clear_cache()  # 세션별 삭제가 아닌 전체 초기화 → 확실한 동기화
    except Exception:
        pass

    # 4) combined HTML + index.html 삭제
    for f in project_dir.glob("combined_transcripts*.html"):
        f.unlink()
    index_html = projects_dir / "index.html"
    if index_html.exists():
        index_html.unlink()

    # 5) 재생성
    process_projects_hierarchy(projects_dir, use_cache=True, silent=True)
    return jsonify({"status": "ok"})
```

> **핵심**: `cm.delete_session()` 대신 `cm.clear_cache()` 사용. `delete_session()`은 `projects.total_message_count`를 갱신하지 않아 캐시 불일치 발생.

#### 3-2. `claude_code_log/html/templates/components/session_nav.html`

원본:
```html
<button class='session-delete-btn' onclick='hideSession(event, this)' title='숨기기'>✕</button>
```
수정:
```html
<button class='session-delete-btn' title='삭제'>✕</button>
```

#### 3-3. `claude_code_log/html/templates/components/session_edit_script.js`

파일 맨 앞에 추가:
```javascript
document.querySelectorAll('.session-delete-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sessionLink = this.closest('.session-link');
        var sessionId = sessionLink.dataset.sessionId;
        if (!confirm('이 세션을 삭제하겠습니까?\n삭제된 세션은 복구할 수 없습니다.')) return;
        fetch('/api/sessions/' + sessionId, { method: 'DELETE' })
            .then(function (r) { if (r.ok) location.reload(); else alert('삭제 실패'); });
    });
});
```

---

## 4. Archived 세션 필터링

**목적**: JSONL이 삭제된 세션(archived)이 인덱스에 유령으로 남지 않도록 필터링.

### 수정 파일 (2개)

#### 4-1. `claude_code_log/converter.py` — 일반 프로젝트 세션 필터

`process_projects_hierarchy()` 내 세션 목록 생성부에 조건 추가:
```python
# valid_session_ids = {f.stem for f in jsonl_files}  ← 이미 존재하는 코드

# 세션 목록 list comprehension에 추가:
and session_data.session_id in valid_session_ids  # archived 세션 제외
```

#### 4-2. `claude_code_log/converter.py` — archived 프로젝트 제외

원본: archived 프로젝트를 `project_summaries`에 추가 (인덱스에 표시됨)
수정: 로그만 출력하고 `project_summaries`에 추가하지 않음:
```python
# Process archived projects
archived_project_count = 0
for archived_dir in sorted(archived_project_dirs):
    try:
        cache_manager = CacheManager(archived_dir, library_version)
        cached_project_data = cache_manager.get_cached_project_data()
        if cached_project_data is None:
            continue
        archived_project_count += 1
        print(f"  {archived_dir.name}: [ARCHIVED] (...)")
    except Exception:
        continue
# project_summaries.append(...) 제거됨
```

#### 4-3. `claude_code_log/html/templates/index.html` — 빈 프로젝트 카드 숨김

```html
{% for project in projects %}
{% if project.sessions %}      {# ← 이 줄 추가 #}
<div class='project-card ...'>
    ...
</div>
{% endif %}                    {# ← 이 줄 추가 #}
{% endfor %}
```

---

## 5. 실시간 동기화 (SSE)

**목적**: 세션 페이지를 열어두면, Claude Code 대화 시 브라우저에 실시간 반영.

### 아키텍처

```
JSONL 파일 변경
    ↓ (2초 폴링 + debounce)
SSE 엔드포인트 → {"type": "updated"} 이벤트 전송
    ↓
브라우저 EventSource 수신
    ↓
스크롤 위치 저장 → location.reload() → 스크롤 위치 복원
```

> **설계 결정**: 초기에는 `/api/sessions/{id}/render`를 fetch하여 DOMParser로 `messages-container` innerHTML을 교체하는 방식이었으나, 대용량 세션(3MB+ HTML)에서 DOMParser가 컨테이너를 불완전하게 파싱하는 문제 발견. `location.reload()` + 스크롤 위치 보존 방식으로 변경.

### 수정 파일 (2개)

#### 5-1. `claude_code_log/server.py` — 3개 엔드포인트

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

**SSE 엔드포인트** (debounce 포함):
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
                # Claude Code가 JSONL에 쓰는 도중 불완전한 파일을 읽는 것 방지
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

> **Debounce 이유**: Claude Code는 한 번의 응답에서 JSONL에 여러 항목(assistant, file-history-snapshot, tool_result 등)을 순차 기록함. 파일 변경 즉시 `updated`를 보내면 불완전한 JSONL을 읽게 됨. 1초간 추가 변경이 없을 때까지 대기하여 완전한 데이터만 전송.

**렌더 엔드포인트**:
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

#### 5-2. `claude_code_log/html/templates/transcript.html` — 3가지 변경

**messages-container 래퍼** (메시지 루프를 감쌈):
```html
<div id="messages-container">
{% for message, ... in messages %}
    ...
{% endfor %}
<div class='message user empty-prompt'>...</div>
</div>{# end messages-container #}
```

**EventSource JS** (`</body>` 직전):
```html
<script>
(function() {
    // SSE reload 후 스크롤 위치 복원
    var savedScroll = sessionStorage.getItem('sse-scroll');
    if (savedScroll) {
        sessionStorage.removeItem('sse-scroll');
        if (savedScroll === 'bottom') {
            window.scrollTo(0, document.body.scrollHeight);
        } else {
            window.scrollTo(0, parseInt(savedScroll, 10));
        }
    }

    var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
    if (!match) return;
    var sessionId = match[1];
    var source = new EventSource('/api/sessions/' + sessionId + '/stream');

    // LIVE 인디케이터
    var indicator = document.createElement('div');
    indicator.id = 'live-indicator';
    indicator.textContent = 'LIVE';
    indicator.style.cssText = 'position:fixed;top:10px;right:10px;background:#22c55e;color:#fff;...';
    document.body.appendChild(indicator);

    source.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (data.type === 'updated') {
            // 스크롤 위치 저장 후 페이지 새로고침
            var atBottom = (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 150;
            if (atBottom) {
                sessionStorage.setItem('sse-scroll', 'bottom');
            } else {
                sessionStorage.setItem('sse-scroll', String(window.scrollY));
            }
            location.reload();
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
})();
</script>
```

> **DOMParser 방식을 포기한 이유**: 대용량 세션(600+ 메시지, 3MB+ HTML)에서 `DOMParser.parseFromString()`이 `messages-container`의 innerHTML을 불완전하게 파싱하는 현상 발견. 서버는 정상 응답(메시지 수 증가)하지만 DOMParser 결과의 컨테이너 innerHTML이 일관되게 더 작았음. `location.reload()` + `sessionStorage` 스크롤 보존으로 안정적 업데이트 구현.

---

## 6. 인덱스 재생성 로딩 화면

**목적**: 세션 삭제 등으로 index.html이 재생성되는 동안 404 대신 로딩 화면 표시.

### 배경

세션 삭제 시 `index.html`을 먼저 삭제하고 `process_projects_hierarchy()`로 재생성하는데, 재생성에 7초 이상 걸림. 그 사이에 `/` 접속 시 404 발생.

### 수정 파일

**`claude_code_log/server.py`**

`create_app()` 내 `LOADING_HTML` 상수 추가 + `index()` 라우트 수정:
```python
LOADING_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Loading...</title>
<meta http-equiv="refresh" content="2">
<style>
body{display:flex;justify-content:center;align-items:center;height:100vh;margin:0;
font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0}
.loader{text-align:center}
.spinner{width:40px;height:40px;border:4px solid #333;border-top:4px solid #3b82f6;
border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body><div class="loader"><div class="spinner"></div><p>Regenerating index...</p></div></body>
</html>"""

@app.route("/")
def index() -> Response:
    index_file = projects_dir / "index.html"
    if index_file.exists():
        response = send_file(index_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    return Response(LOADING_HTML, mimetype="text/html")  # 404 대신 로딩 화면
```

> **핵심**: `<meta http-equiv="refresh" content="2">`로 2초마다 자동 새로고침. index.html이 생성되면 자동으로 정상 페이지 표시.

---

## 7. 색상 커스터마이징

**수정 파일**: `claude_code_log/html/templates/components/global_styles.css`

배경색, 세션 색상 등을 CSS 변수 또는 직접 수정으로 커스터마이징.
(커밋 `0643826 session 색상 변경`, `20303bd 배경색 수정`)

---

## 공통 인프라

### `_find_session_jsonl()` — 세션 JSONL 파일 탐색

`server.py` 상단. 삭제/수정/스트리밍 모든 API에서 공용:
```python
def _find_session_jsonl(projects_dir: Path, session_id: str) -> Optional[Path]:
    # 1차: 파일명으로 검색 (빠름)
    for jsonl_file in projects_dir.rglob(f"{session_id}.jsonl"):
        return jsonl_file
    # 2차: 파일 내용으로 검색 (sessionId 필드)
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        if session_id in jsonl_file.read_text(encoding="utf-8"):
            return jsonl_file
    return None
```

### Cache-Control 헤더

모든 HTML 응답에 `no-cache, no-store, must-revalidate` 설정:
- `index()` 라우트
- `serve_file()` 라우트 (HTML 파일만)
- 동적 렌더링 응답

---

## 커밋 히스토리 (시간순)

| 커밋 | 내용 |
|------|------|
| `20303bd` | 메인 대시보드 푸터, X버튼 추가, 배경색 수정 |
| `0643826` | 세션 색상 변경 |
| `0ba8e22` | 커스텀 세션 제목 지원 (Ctrl+R) |
| `17aa891` | 빈 User 입력 버블 추가 |
| `154cb15` | Flask 로컬 웹 서버 모드 (`--serve`) |
| `e2ca20c` | 세션 제목 인라인 편집 (Flask 기반) |
| `66fb011` | 세션 삭제 + 캐시 동기화 수정 |
| `e4d5501` | 실시간 동기화 (SSE) + 동적 세션 렌더링 |
| `27dc59a` | 세션 삭제 시 404 방지(로딩 화면), empty-prompt 항상 표시, SSE 디버그 로그 |
| (pending) | SSE debounce 추가, location.reload 방식으로 변경, render endpoint no-cache |

---

## 의존성

추가된 외부 의존성 **없음**. 모두 기존 의존성(Flask, Jinja2 등)만 사용.
