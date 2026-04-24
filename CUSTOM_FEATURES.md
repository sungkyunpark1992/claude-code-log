# claude-code-log 커스텀 기능 구현 가이드

> 원본 프로젝트([daaain/claude-code-log](https://github.com/daaain/claude-code-log))에 추가한 커스텀 기능들의 구현 방법.
> 새 환경에서 동일 기능을 재현할 때 참고용.

---

## 목차

1. [빈 User 메시지 풍선](#1-빈-user-메시지-풍선)
2. [세션 제목 수정](#2-세션-제목-수정)
3. [세션 삭제 (X 버튼)](#3-세션-삭제-x-버튼)
4. [Archived 세션 필터링](#4-archived-세션-필터링)
5. [실시간 동기화 (SSE)](LIVE_SYNC.md) — 별도 문서
6. [인덱스 재생성 로딩 화면](#6-인덱스-재생성-로딩-화면)
7. [색상 커스터마이징](#7-색상-커스터마이징)
8. [맨 아래로 이동 플로팅 버튼](#8-맨-아래로-이동-플로팅-버튼)
9. [인덱스 페이지 새로고침 시 자동 재생성](#9-인덱스-페이지-새로고침-시-자동-재생성)
10. [빈 말풍선 하단 고정 (Sticky Prompt)](#10-빈-말풍선-하단-고정-sticky-prompt)
11. [플로팅 버튼 우측 사이드바 고정](#11-플로팅-버튼-우측-사이드바-고정)
12. [User 메시지 긴 내용 접기](#12-user-메시지-긴-내용-접기)
13. [2000+ 메시지 세션 DOM 오염 수정](#13-2000-메시지-세션-dom-오염-수정)
14. [세션 페이지 홈 버튼](#14-세션-페이지-홈-버튼)
15. [인덱스 페이지 로딩 속도 최적화 (cache_only 모드)](#15-인덱스-페이지-로딩-속도-최적화-cache_only-모드)
16. [모델 배지 (Assistant 메시지)](#16-모델-배지-assistant-메시지)
17. [빈 프롬프트 실시간 모델 배지 (SSE)](#17-빈-프롬프트-실시간-모델-배지-sse)
18. [watchdog 파일 감시 (폴링 → OS 네이티브)](#18-watchdog-파일-감시-폴링--os-네이티브)
19. [미인식 엔트리 타입 경고 제거](#19-미인식-엔트리-타입-경고-제거)
20. [User 말풍선 간 이동 버튼 (▲▼)](#20-user-말풍선-간-이동-버튼-)

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

> **주의**: `window.initEmptyPrompt`로 전역 함수 선언 필수. SSE DOM 교체 후 재바인딩에 사용됨 (`ccl-live-prompt` 재생성 후 호출).

---

## 2. 세션 제목 수정

**목적**: 인덱스/세션 네비게이션에서 ✏️ 버튼으로 세션 제목을 인라인 편집. 수정된 제목은 브라우저 탭 제목과 VS Code Claude Code 확장에도 반영됨.

### 수정 파일 (3개)

#### 2-1. `claude_code_log/server.py` — API 엔드포인트

헬퍼 함수 2개:

```python
def _get_custom_title(jsonl_file: Path, session_id: str) -> Optional[str]:
    """JSONL에서 직접 custom title을 읽어 반환 (마지막 항목 기준).

    load_transcript()는 CustomTitleTranscriptEntry를 날짜 필터링 중 skip하므로
    JSONL을 직접 읽어야 함. 동일 sessionId 항목이 여러 개일 경우 마지막(최신)을 반환.
    """
    result: Optional[str] = None
    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
            if (
                data.get("type") == "custom-title"
                and data.get("sessionId") == session_id
            ):
                result = str(data["customTitle"])
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def _update_custom_title(jsonl_file: Path, session_id: str, new_title: str) -> None:
    """JSONL 파일의 custom-title 항목을 갱신.

    기존 custom-title 항목을 sessionId 무관하게 모두 삭제 후 새 항목을 맨 뒤에 추가.
    Claude Code가 자동으로 작성한 garbage 항목이 남아 있으면 VS Code 확장이
    첫 번째 항목을 읽어 잘못된 제목을 표시하는 버그를 방지.
    """
    lines = jsonl_file.read_text(encoding="utf-8").splitlines()
    new_entry = json.dumps(
        {"type": "custom-title", "customTitle": new_title, "sessionId": session_id},
        ensure_ascii=False,
    )
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            data = json.loads(stripped)
            if data.get("type") == "custom-title":
                continue  # 모든 custom-title 항목 제거
        except json.JSONDecodeError:
            pass
        new_lines.append(line)
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

세션 페이지 동적 렌더링 시 custom title을 `<title>` 태그에 반영 (serve_file, render_session, render_messages 세 곳 모두):
```python
messages = load_transcript(jsonl_file, silent=True)
renderer = HtmlRenderer()
custom_title = _get_custom_title(jsonl_file, session_id)
html = renderer.generate_session(messages, session_id, title=custom_title)
```

> **핵심 설계 결정**:
> - `_get_custom_title`은 마지막 항목을 반환 → ✏️ 이전에 Claude Code가 자동으로 쓴 garbage 항목보다 나중에 추가된 항목이 우선
> - `_update_custom_title`은 모든 `custom-title` 항목을 삭제 후 재추가 → sessionId가 다른 형식의 garbage 항목까지 완전히 제거. VS Code Claude Code 확장은 JSONL의 첫 번째 `custom-title` 항목을 읽으므로, 항목이 하나뿐이어야 VS Code에도 올바르게 반영됨.

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

> **별도 문서로 분리**: 아키텍처, 설계 결정, 디버깅 히스토리, 전체 코드를 포함한 상세 문서는 **[LIVE_SYNC.md](LIVE_SYNC.md)** 참조.

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
    from .converter import process_projects_hierarchy

    process_projects_hierarchy(projects_dir, use_cache=True, silent=True)
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

## 8. 맨 아래로 이동 플로팅 버튼

**목적**: 세션 페이지 우하단에 맨 아래/위로 이동하는 플로팅 버튼 쌍 구성. 기존 `<a>` 태그를 `<button>`으로 통일하고 동작 방식도 일관되게 정리.

### 수정 파일 (2개)

#### 8-1. `claude_code_log/html/templates/transcript.html` — 버튼 추가 및 통일

```html
<button class="scroll-top floating-btn" title="Scroll to top" onclick="window.scrollTo(0, 0)">⬆️</button>
<button class="scroll-bottom floating-btn" title="Scroll to bottom" onclick="window.scrollTo(0, document.body.scrollHeight)">⬇️</button>
```

> - 기존 scroll-top은 `<a href="#title">` → `<button onclick="window.scrollTo(0,0)">`으로 변경 (다른 플로팅 버튼들과 동일한 형태)
> - ⬇️가 맨 아래(시각적으로 하단), ⬆️가 그 위에 위치

#### 8-2. `claude_code_log/html/templates/components/global_styles.css` — 버튼 위치 CSS

플로팅 버튼 스택 순서 (아래에서 위 방향):
```css
.scroll-bottom.floating-btn {
    bottom: 20px;   /* 맨 아래 */
}

.scroll-top.floating-btn {
    bottom: 80px;   /* 그 위 */
}

.toggle-details.floating-btn {
    bottom: 140px;
}

.filter-messages.floating-btn {
    bottom: 200px;
}
```

---

## 9. 인덱스 페이지 새로고침 시 자동 재생성

**목적**: `http://localhost:5678/` 페이지를 수동 새로고침할 때 새 세션이 자동으로 반영되도록.

> 구현 상세 및 설계 결정은 **[LIVE_SYNC.md — 인덱스 페이지 업데이트 방식](LIVE_SYNC.md#9-인덱스-페이지-업데이트-방식)** 참조.

---

## 10. 빈 말풍선 하단 고정 (Sticky Prompt)

**목적**: 빈 User 입력 말풍선에 텍스트를 입력하기 시작하면, 헤더처럼 화면 하단에 고정되어 스크롤과 무관하게 항상 보이도록 함. 텍스트를 모두 지우면 일반 위치로 복귀.

### 동작

- 초기 상태: 세션 맨 하단에 반투명 빈 말풍선 (클릭 대기)
- 클릭 후 타이핑 시작: `#prompt-dock`에 `.sticky` 클래스 → 화면 하단 고정
- 텍스트 전부 삭제: 고정 해제, 원래 위치로 복귀
- 최대 16줄까지 자동 확장, 초과 시 스크롤바 표시
- SSE로 새 메시지 수신 시 고정 해제 + 새 말풍선 재생성
- 헤더 우측 `▼` 버튼으로 textarea 최소화/최대화 토글 (내용 유지)

### 핵심 설계: 래퍼 컨테이너 방식

`position: fixed`를 말풍선에 직접 적용하면 부모 컨텍스트를 벗어나 너비/위치가 틀어짐.
대신 `#prompt-dock` 래퍼에 fixed를 적용하고 내부는 body와 동일한 레이아웃 제약을 적용:

```css
#prompt-dock.sticky {
    position: fixed;
    bottom: 10px; /* body padding-bottom(10px)과 일치 — 0이면 sticky 전환 시 10px 점프 발생 */
    left: 0;
    right: 60px;  /* 우측 사이드바 너비 */
    z-index: 100;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 10px;
    border-radius: 8px 8px 0 0;
}
```

> `left: 50%; transform: translateX(-50%)` 방식은 스크롤바 너비 등으로 미세하게 어긋남.
> `left: 0; right: 0; margin: auto` 방식이 body 레이아웃과 픽셀 단위로 일치.

> **주의**: `bottom` 값은 반드시 `body`의 `padding-bottom`과 동일해야 함. 다르면 sticky 전환 순간 dock이 해당 차이만큼 점프함.

### 수정 파일 (2개)

#### 10-1. `claude_code_log/html/templates/transcript.html`

**HTML**: messages-container 닫는 태그 다음, `#sse-live-messages` 이전에 dock 래퍼 추가:
```html
</div><!-- @@CCL_END_CONTAINER@@ -->
<div id="prompt-dock">
    <div id='ccl-live-prompt' class='message user empty-prompt'>
        <div class='header'><span>🤷 User</span></div>
        <div class='content'>
            <textarea class='user-input' placeholder='메시지를 입력하세요...'></textarea>
        </div>
    </div>
</div>
```

**JS** (`initEmptyPrompt` 내부): dock sticky 토글 + body padding 보상:
```javascript
var dock = document.getElementById('prompt-dock');
textarea.addEventListener('input', function () {
    this.style.height = 'auto';
    var maxH = parseFloat(getComputedStyle(this).maxHeight);
    if (this.scrollHeight > maxH) {
        this.style.height = maxH + 'px';
        this.style.overflowY = 'auto';
    } else {
        this.style.height = this.scrollHeight + 'px';
        this.style.overflowY = 'hidden';
    }
    if (this.value.trim()) {
        if (!dock.classList.contains('sticky')) {
            // 최초 전환만: dock이 흐름에서 차지하던 공간 전체(gap 포함)를 paddingBottom으로
            // 보상한 뒤 sticky 적용 → 메시지 위치 변화 없음
            var dockAbsTop = dock.getBoundingClientRect().top + window.scrollY;
            var docHeight = document.documentElement.scrollHeight;
            document.body.style.paddingBottom = (docHeight - dockAbsTop) + 'px';
            dock.classList.add('sticky');
        }
        // 이후 키스트로크: dock이 이미 fixed(흐름 밖) → 레이아웃 변화 없음, 추가 처리 불필요
    } else {
        dock.classList.remove('sticky');
        document.body.style.paddingBottom = '';
    }
});
```

> **핵심 설계 결정**:
> - `paddingBottom = dock.offsetHeight`만 쓰면 dock 위의 gap이 보상에서 빠져 메시지가 dock에 붙어버림 → `docHeight - dockAbsTop`(dock 상단~문서 끝 전체)으로 보상.
> - sticky 전환은 **한 번만** 실행 (`!dock.classList.contains('sticky')` 가드). 매 키스트로크마다 실행하면 DOM 변경이 반복되어 브라우저가 `window.scrollTo` 없이는 화면을 위로 밀어버림.
> - `window.scrollTo`를 입력 핸들러에서 호출하지 않음 — 위 두 조건(pre-compensation + one-time)으로 자연스럽게 해결.

**JS** (SSE 코드): 기존 prompt 제거 및 dock 내에 새 prompt 재생성:
```javascript
// 기존 prompt 제거 + dock sticky 초기화
var oldPrompt = document.getElementById('ccl-live-prompt');
if (oldPrompt) oldPrompt.remove();
var dock = document.getElementById('prompt-dock');
if (dock) {
    dock.classList.remove('sticky');
    document.body.style.paddingBottom = '';
}

// SSE 메시지 삽입 후 dock 안에 새 prompt 재생성
var dock = document.getElementById('prompt-dock');
if (dock) {
    var promptDiv = document.createElement('div');
    promptDiv.id = 'ccl-live-prompt';
    promptDiv.className = 'message user empty-prompt';
    promptDiv.innerHTML = '...';
    dock.appendChild(promptDiv);
}
```

#### 10-2. `claude_code_log/html/templates/components/message_styles.css`

```css
/* 최소/최대화 토글 버튼 */
.prompt-minimize-btn {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.8em;
    color: var(--text-muted);
    padding: 2px 6px;
    border-radius: 4px;
    line-height: 1;
    flex-shrink: 0;
}
.prompt-minimize-btn:hover {
    background: rgba(0, 0, 0, 0.08);
}

/* 최소화 상태: content 숨김 */
#ccl-live-prompt.minimized .content {
    display: none;
}
#ccl-live-prompt.minimized {
    margin-bottom: 0;
}

/* Prompt dock: fixed bottom bar when user is typing */
#prompt-dock.sticky {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 60px; /* 우측 사이드바 너비만큼 띄움 */
    z-index: 100;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 10px;
    border-radius: 8px 8px 0 0;
}

/* textarea 최대 16줄, 초과 시 스크롤 */
.user-input {
    ...
    resize: none;
    overflow-y: hidden;
    max-height: calc(16 * 1.5em);
}
```

### 버그 수정 이력

#### sticky 전환 시 레이아웃 점프 (수정)

**증상**: 타이핑 시작 순간 메시지들이 dock 쪽으로 붙거나, 화면이 위로 살짝 밀리는 현상.

**원인 및 수정**:
- `dock.offsetHeight`만 보상 → dock 위 gap 포함 안 됨 → `docHeight - dockAbsTop` 전체로 변경
- sticky 전환이 매 키스트로크마다 실행 → 최초 1회 가드(`!dock.classList.contains('sticky')`) 추가
- `window.scrollTo` 매 키스트로크 호출 → 제거 (위 두 수정으로 불필요)
- `bottom: 0` → `bottom: 10px`: `body padding-bottom: 10px`과 불일치로 sticky 전환 시 10px 점프 발생

#### 페이지 로드 즉시 하단 고정 (기능 변경)

이전: 타이핑 시작 시 sticky 전환
현재: `initEmptyPrompt()` 호출 시점(페이지 로드 & SSE 후)에 즉시 sticky 적용

`input` 핸들러에서 sticky 토글 로직 완전 제거 — textarea 높이 조절만 담당.

#### 메시지 필터로 빈 말풍선이 숨겨지는 버그 (수정)

**증상**: 🔍 필터에서 user 타입을 비활성화하면 `#ccl-live-prompt`도 같이 `filtered-hidden` 처리되어 화면에서 사라짐.

**원인**: `applyFilter()`의 대상 쿼리 `.message:not(.session-header)`에 `#ccl-live-prompt`(.message.user)가 포함됨.

**수정**:
```javascript
// 수정 전
document.querySelectorAll('.message:not(.session-header)')
// 수정 후
document.querySelectorAll('.message:not(.session-header):not(#ccl-live-prompt)')
```

---

## 11. 플로팅 버튼 우측 사이드바 고정

**목적**: 기존에 각각 `position: fixed; bottom: Npx`으로 흩어져 있던 플로팅 버튼들을 `#floating-buttons` 컨테이너로 묶어 우측 사이드바처럼 고정. 본문/dock과 영역이 겹치지 않음.

### 동작

- 화면 우측에 60px 너비 사이드바로 항상 고정
- 버튼들은 사이드바 하단에 모여 있음 (`justify-content: flex-end`)
- 본문(`body`)은 `padding-right: 70px`으로 사이드바와 겹치지 않음
- `#prompt-dock.sticky`도 `right: 60px`으로 사이드바 침범 없음

### 수정 파일 (2개)

#### 11-1. `claude_code_log/html/templates/transcript.html` — 버튼 컨테이너로 묶기

```html
<div id="floating-buttons">
    <button class="timeline-toggle floating-btn" ...>📆</button>
    <button class="filter-messages floating-btn" ...>🔍</button>
    <button class="toggle-details floating-btn" ...>📋</button>
    <button class="scroll-top floating-btn" ...>⬆️</button>
    <button class="scroll-bottom floating-btn" ...>⬇️</button>
</div>
```

#### 11-2. `claude_code_log/html/templates/components/global_styles.css`

```css
/* 사이드바 컨테이너 */
#floating-buttons {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    width: 60px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;  /* 하단 배치 */
    padding-bottom: 20px;
    gap: 10px;
    z-index: 99;
}

/* 개별 버튼: position: fixed 제거, relative로 */
.floating-btn {
    position: relative;
    /* right, bottom 제거 */
}

/* 버튼 순서 (위→아래: 📆 🔍 📋 ⬆️ ⬇️) */
.timeline-toggle.floating-btn  { order: 1; }
.filter-messages.floating-btn  { order: 2; }
.toggle-details.floating-btn   { order: 3; }
.scroll-top.floating-btn       { order: 4; }
.scroll-bottom.floating-btn    { order: 5; }

/* 본문이 사이드바와 겹치지 않도록 */
body {
    padding: 10px 70px 10px 10px; /* right = 60px 사이드바 + 10px 여백 */
}
```

> **이전 방식의 문제**: 버튼들이 각각 독립적인 `position: fixed; bottom: Npx`로 관리되어, `#prompt-dock` 하단 고정 시 dock이 버튼을 덮어버리는 z-index 충돌 발생. JS로 버튼 위치를 동적 조정하는 복잡한 우회책이 필요했음.
>
> **사이드바 방식의 장점**: 레이아웃이 CSS만으로 완결. JS 동적 조정 코드 불필요.

---

## 12. User 메시지 긴 내용 접기

**목적**: Assistant 답변과 동일하게, User 메시지도 20줄 초과 시 자동으로 접히도록 변경.

### 배경

기존에 User 메시지는 `<pre>` 태그로 전문 출력했고, Assistant 메시지만 `render_markdown_collapsible()`을 통해 20줄 초과 시 `<details>`로 접혔음. 긴 질문을 입력한 경우 스크롤이 길어지는 문제.

### 수정 파일 (1개)

**`claude_code_log/html/user_formatters.py`** — `format_user_text_content()`:

```python
# 수정 전
def format_user_text_content(text: str) -> str:
    escaped_text = escape_html(text)
    return f"<pre>{escaped_text}</pre>"

# 수정 후
def format_user_text_content(text: str) -> str:
    return render_markdown_collapsible(text, "user-text", line_threshold=20)
```

> **부작용**: 기존 `<pre>` (날 텍스트)에서 마크다운 렌더링으로 변경됨. 메시지에 `**굵게**`, 코드블록 등이 있으면 렌더링되어 표시됨.

---

## 13. 2000+ 메시지 세션 DOM 오염 수정

**목적**: 2000개 이상 메시지가 있는 세션에서 `#floating-buttons`(우측 사이드바)와 `#prompt-dock`(하단 빈 말풍선)이 보이지 않는 버그 수정.

### 문제

대화 내용에 코드 블록 바깥에서 등장하는 HTML 태그(예: `<select>`, `<div style="...">`)가 마크다운 렌더링 시 이스케이프 없이 그대로 HTML로 출력됨 → 브라우저가 진짜 HTML 태그로 해석 → DOM 트리 구조가 오염되어 `position: fixed` 요소들이 깨진 DOM 안에 갇혀 보이지 않게 됨.

**콘솔 에러 증거**:
- `<select>` 태그 중첩 파싱 에러 (kyochon 세션)
- `TypeError: Cannot read properties of null (reading 'appendChild')` — `#sse-live-messages`가 DOM에서 사라짐 (claude-code-log 세션)

### 수정 파일 (3개)

**`claude_code_log/html/utils.py`** — `render_markdown()`, `render_markdown_collapsible()`:

```python
# 수정 전 — 대화 내용의 HTML 태그가 이스케이프 없이 DOM에 삽입
def render_markdown(text: str, escape_html: bool = False) -> str: ...
def render_markdown_collapsible(..., escape_html: bool = False) -> str: ...

# 수정 후 — HTML 태그를 &lt;select&gt; 형태로 이스케이프하여 텍스트로 표시
def render_markdown(text: str, escape_html: bool = True) -> str: ...
def render_markdown_collapsible(..., escape_html: bool = True) -> str: ...
```

> **주의**: `render_markdown`의 기본값만 바꾸면 효과 없음. 모든 포매터(`assistant_formatters`, `user_formatters`, `tool_formatters`)가 `render_markdown_collapsible`을 통해 렌더링하고, 이 함수가 자체 `escape_html` 기본값을 `render_markdown`에 명시적으로 전달하기 때문. **반드시 양쪽 모두** 변경해야 함.

> **코드 블록은 영향 없음**: mistune은 `` ```code``` `` 블록을 별도로 처리하여 `escape_html` 설정과 무관하게 항상 이스케이프.

**`claude_code_log/html/templates/components/global_styles.css`** — `#floating-buttons`:

```css
#floating-buttons {
    /* 기존 속성 생략 */
    will-change: transform; /* 추가: GPU 컴포지터 레이어 강제 — 보조적 방어 */
}
```

**`claude_code_log/html/templates/components/message_styles.css`** — `#prompt-dock.sticky`:

```css
#prompt-dock.sticky {
    /* 기존 속성 생략 */
    will-change: transform; /* 추가: GPU 컴포지터 레이어 강제 — 보조적 방어 */
}
```

> `will-change: transform`은 근본 해결(HTML 이스케이프)에 대한 **보조적 방어**. Chrome이 매우 긴 페이지에서 `position: fixed` 요소를 누락시키는 알려진 렌더링 버그를 예방.

---

## 14. 세션 페이지 홈 버튼

**목적**: 세션 페이지에서 메인 대시보드(`/`)로 바로 이동할 수 있는 홈 아이콘 제공.

### 수정 파일 (2개)

**`claude_code_log/html/templates/transcript.html`** — `<h1>` 태그 내 홈 링크 추가:

```html
<h1 id="title"><a href="/" class="home-btn" title="메인 대시보드">🏠</a>{{ title }}</h1>
```

**`claude_code_log/html/templates/components/global_styles.css`** — `.home-btn` 스타일:

```css
.home-btn {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    text-decoration: none;
    font-size: 0.7em;
    opacity: 0.6;
    transition: opacity 0.2s;
}
.home-btn:hover { opacity: 1.0; }
```

> `h1`에 `position: relative` 추가하여 `.home-btn`의 `absolute` 기준점으로 사용. 평소 반투명, hover 시 선명해지는 방식으로 제목 가독성에 방해되지 않게 처리.

---

## 15. 인덱스 페이지 로딩 속도 최적화 (cache_only 모드)

**목적**: `/` (메인 대시보드) 요청 시 인덱스 페이지 로딩 속도를 20초 → 5~7초로 단축.

### 문제

`/` 요청마다 `process_projects_hierarchy()`가 전체 프로젝트의 JSONL 파싱 + combined HTML + 개별 세션 HTML을 모두 재생성. 인덱스 페이지에 필요한 건 세션 메타데이터(요약, 타임스탬프, 토큰)뿐인데, 불필요한 HTML 생성이 대부분의 시간을 차지.

| 프로젝트 | 이전 (full) | 원인 |
|----------|------------|------|
| claude-code-log | 10.2s | 활성 JSONL 18.9MB 전체 파싱 + HTML 생성 |
| komis-fe | 9.9s | JSONL 변경 없지만 `combined_stale=True` → 25.6MB 재생성 |
| **합계** | **20.8s** | |

### 수정 파일 (2개)

**`claude_code_log/converter.py`** — `process_projects_hierarchy()`에 `cache_only` 파라미터 추가:

```python
def process_projects_hierarchy(..., cache_only: bool = False) -> Path:
```

`cache_only=True` 시:
- `needs_work` 조건에서 `combined_stale`, `stale_sessions` 제외 → 변경된 JSONL만 체크
- slow path에서 `convert_jsonl_to()` 대신 `ensure_fresh_cache()`만 호출 → 캐시 메타데이터만 갱신, HTML 생성 스킵

**`claude_code_log/server.py`** — `index()` 라우트:

```python
process_projects_hierarchy(projects_dir, use_cache=True, silent=True, cache_only=True)
```

> 제목 변경(`update_title`)과 세션 삭제(`delete_session`)의 호출은 기존 full 모드 유지 — 이들은 인덱스 HTML 재생성이 필요.

### 성능 측정 결과

| 시나리오 | 이전 | cache_only | 개선 |
|----------|------|-----------|------|
| 활성 대화 중 | 20.8s | 6.8s | **3배** |
| 2회차 호출 | 20.8s | 5.0s | **4배** |

---

## 16. 모델 배지 (Assistant 메시지)

**목적**: Assistant 메시지 헤더에 어떤 모델이 응답했는지 표시. `claude-sonnet-4-6` → `Sonnet 4.6`.

### 수정 파일 (4개)

#### 16-1. `claude_code_log/models.py` — `MessageMeta.model` 필드 추가

```python
@dataclass
class MessageMeta:
    ...
    model: Optional[str] = None  # ← 추가
```

#### 16-2. `claude_code_log/factories/meta_factory.py` — model 필드 채우기

```python
def create_meta(transcript: BaseTranscriptEntry) -> MessageMeta:
    model = None
    if isinstance(transcript, AssistantTranscriptEntry):
        model = getattr(transcript.message, "model", None)
    return MessageMeta(
        ...
        model=model,
    )
```

#### 16-3. `claude_code_log/renderer.py` — `_shorten_model_name()` + 배지 렌더링

```python
def _shorten_model_name(model: str) -> str:
    """Convert full model ID to short display label.
    Examples:
        "claude-sonnet-4-6"        -> "Sonnet 4.6"
        "claude-opus-4-7"          -> "Opus 4.7"
        "claude-haiku-4-5-20251001" -> "Haiku 4.5"
        "opus"                     -> "Opus"  (from ~/.claude/settings.json)
    """
    import re
    m = re.search(r"(opus|sonnet|haiku)-(\d+)-(\d+)", model, re.IGNORECASE)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}.{m.group(3)}"
    b = re.match(r"^(opus|sonnet|haiku)(?:plan)?$", model, re.IGNORECASE)
    if b:
        return b.group(1).capitalize()
    return model

# title_AssistantTextMessage() 내부:
def title_AssistantTextMessage(self, message: AssistantTextMessage) -> str:
    if message.meta.is_sidechain:
        return "Sub-assistant"
    if message.meta.model:
        short = _shorten_model_name(message.meta.model)
        return f'Assistant <span class="model-badge">{short}</span>'
    return "Assistant"
```

#### 16-4. `claude_code_log/html/templates/components/message_styles.css` — `.model-badge` 스타일

```css
.model-badge {
    font-size: 0.72em;
    font-weight: normal;
    color: #888;
    background: rgba(128, 128, 128, 0.12);
    border-radius: 4px;
    padding: 1px 5px;
    margin-left: 5px;
    vertical-align: middle;
}
```

---

## 17. 빈 프롬프트 실시간 모델 배지 (SSE)

**목적**: `🤷 User` 빈 말풍선 옆에 현재 선택된 모델을 실시간으로 표시. `/model opus`로 전환 시 즉시 반영.

### 동작

- SSE 연결 시 서버가 즉시 `{type: 'model', model: 'claude-sonnet-4-6'}` 이벤트 전송
- 사용자가 `/model opus` 실행 → `settings.json` 변경 → watchdog 감지 → `{type: 'model', model: 'opus'}` 이벤트
- 빈 말풍선 헤더에 `.prompt-model-badge` 배지 추가/갱신

### 모델 우선순위 (JSONL-first)

**문제**: `~/.claude/settings.json`은 **전역** 파일. A 프로젝트에서 opus로 바꾸면 B 프로젝트 세션 페이지에도 "Opus"가 표시됨.

**해결**: JSONL의 마지막 assistant 엔트리 모델을 우선, settings.json은 폴백(새 세션처럼 아직 assistant 엔트리가 없을 때만)으로 사용.

```python
def _get_latest_model(jsonl_file: Path) -> Optional[str]:
    """Priority:
    1. 마지막 assistant 엔트리의 model (세션-로컬, 다른 VSCode 인스턴스 무영향)
    2. ~/.claude/settings.json model (폴백: 새 세션에서 아직 응답 없을 때)
    """
    return _get_latest_model_from_jsonl(jsonl_file) or _get_current_model_from_settings()
```

### 수정 파일 (2개)

#### 17-1. `claude_code_log/server.py`

```python
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

def _get_current_model_from_settings() -> Optional[str]:
    """~/.claude/settings.json에서 현재 선택 모델 반환."""
    try:
        data = json.loads(_CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model = data.get("model")
    return str(model) if model else None

def _get_latest_model_from_jsonl(jsonl_file: Path) -> Optional[str]:
    """JSONL에서 마지막 assistant 엔트리의 model 반환."""
    for line in reversed(jsonl_file.read_text(...).splitlines()):
        data = json.loads(line)
        if data.get("type") == "assistant":
            model = data.get("message", {}).get("model")
            if model:
                return str(model)
    return None
```

SSE `generate()` 내부:
```python
# 연결 즉시 현재 모델 전송
last_model = _get_latest_model(jsonl_file)
if last_model:
    yield f"data: {json.dumps({'type': 'model', 'model': last_model})}\n\n"

# JSONL 변경 이벤트 전송 시 model 포함
yield f"data: {json.dumps({'type': 'updated', 'model': model})}\n\n"

# settings.json 변경 → 모델만 변경
current_model = _get_latest_model(jsonl_file)
if current_model != last_model:
    last_model = current_model
    yield f"data: {json.dumps({'type': 'model', 'model': current_model})}\n\n"
```

#### 17-2. `claude_code_log/html/templates/transcript.html`

```javascript
// 모델명 단축 (Python _shorten_model_name 미러)
function shortenModel(model) {
    if (!model) return null;
    var m = model.match(/(opus|sonnet|haiku)-(\d+)-(\d+)/i);
    if (m) return m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase()
                   + ' ' + m[2] + '.' + m[3];
    var b = model.match(/^(opus|sonnet|haiku)(?:plan)?$/i);
    if (b) return b[1].charAt(0).toUpperCase() + b[1].slice(1).toLowerCase();
    return model;
}

// 빈 말풍선 배지 업데이트
function updatePromptModel(model) {
    var ep = document.getElementById('ccl-live-prompt');
    if (!ep) return;
    var span = ep.querySelector('.header > span');
    if (!span) return;
    var badge = ep.querySelector('.prompt-model-badge');
    var label = shortenModel(model);
    if (label) {
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'prompt-model-badge model-badge';
            span.appendChild(badge);
        }
        badge.textContent = label;
    } else if (badge) {
        badge.remove();
    }
}

// SSE onmessage에서 처리
source.onmessage = function(e) {
    var data = JSON.parse(e.data);
    if (data.type === 'model') {
        updatePromptModel(data.model);
        return;
    }
    if (data.type === 'updated') {
        // ... 기존 처리 ...
        // 메시지 재생성 후 모델 배지 복원
        if (resp.model) updatePromptModel(resp.model);
    }
};
```

---

## 18. watchdog 파일 감시 (폴링 → OS 네이티브)

**목적**: SSE 파일 변경 감지를 2초 폴링에서 OS 네이티브 파일시스템 이벤트로 교체. 즉각 반응, 대기 중 CPU 사용 없음.

### 동작

- 이전: `time.sleep(2)` 루프에서 `os.stat()`로 파일 크기/mtime 비교 (2초 지연)
- 현재: watchdog `Observer`가 OS 이벤트로 즉각 감지, `Queue`로 SSE 루프에 전달

### 수정 파일 (2개)

#### 18-1. `claude_code_log/server.py`

새 import:
```python
from queue import Empty, Queue
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
```

`_SSEFileWatcher` 클래스 (모듈 레벨):
```python
class _SSEFileWatcher(FileSystemEventHandler):
    """watchdog 이벤트를 SSE Queue로 브리지."""

    def __init__(self, watched: dict[Path, str], queue: Queue[str]) -> None:
        super().__init__()
        self._watched = {p.resolve(): tag for p, tag in watched.items()}
        self._queue = queue

    def on_modified(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._notify(event)

    def _notify(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        try:
            src = Path(str(event.src_path)).resolve()
        except OSError:
            return
        tag = self._watched.get(src)
        if tag is not None:
            self._queue.put(tag)
```

`generate()` 내 watchdog 설정:
```python
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

    try:
        while True:
            try:
                tag = event_queue.get(timeout=15.0)  # 15s keepalive
            except Empty:
                yield ":\n\n"  # SSE keepalive
                continue

            # 버스트 드레인: 연속 쓰기를 묶음 처리
            tags = {tag}
            try:
                while True: tags.add(event_queue.get_nowait())
            except Empty:
                pass
            time_module.sleep(0.3)  # JSONL 쓰기 안정 대기
            try:
                while True: tags.add(event_queue.get_nowait())
            except Empty:
                pass

            if "jsonl" in tags:
                # ... updated 이벤트 전송 ...
            # settings.json 변경 또는 JSONL touch → 모델 재확인
            current_model = _get_latest_model(jsonl_file)
            if current_model != last_model:
                last_model = current_model
                yield f"data: {json.dumps({'type': 'model', 'model': current_model})}\n\n"
    finally:
        observer.stop()
        observer.join(timeout=2)
```

> **핵심 설계 결정**:
> - watchdog은 **디렉토리** 단위로 감시. `jsonl_file.parent`와 `_CLAUDE_SETTINGS_PATH.parent` 각각 schedule.
> - 같은 부모 디렉토리면 한 번만 schedule (`scheduled_dirs` 세트로 중복 방지).
> - 15s keepalive: watchdog이 즉각 이벤트를 보내므로 timeout은 순수 idle 시에만 발생.
> - 0.3s settle: Claude Code가 한 응답에서 JSONL을 여러 번 기록하므로 첫 이벤트 후 짧게 대기 후 재드레인.

#### 18-2. `pyproject.toml`

```toml
dependencies = [
    ...
    "watchdog>=4.0.0",
    ...
]
```

### 이전 방식과 비교

| 항목 | 이전 (폴링) | 현재 (watchdog) |
|------|------------|----------------|
| 감지 방식 | `time.sleep(2)` + `os.stat()` 비교 | OS 네이티브 이벤트 (`ReadDirectoryChangesW` / `FSEvents` / `inotify`) |
| 대기 시간 | 최대 2초 + 디바운스 5초 | 즉각 (ms 단위) + 0.3s settle |
| idle CPU | 2초마다 stat() 호출 | 이벤트 없으면 Queue.get으로 완전 블록 |
| keepalive | 2초 sleep 내에서 `:` 전송 | 15s timeout 후 `:` 전송 |
| settings.json 감시 | 없음 (모델 변경 미감지) | 동일 Observer로 함께 감시 |

---

## 19. 미인식 엔트리 타입 경고 제거

**목적**: 서버 터미널에 반복 출력되던 `not a recognised message type` 경고 제거.

### 배경

Claude Code는 대화 중 내부적으로 여러 타입의 JSONL 엔트리를 기록하는데, 그 중 일부가 기존 silent skip 목록에 없어 경고를 출력함.

**경고 유발 타입**:
- `last-prompt`: Claude Code가 내부적으로 기록하는 마지막 프롬프트 스냅샷
- `attachment`: 훅 컨텍스트, TODO 리마인더, 파일 참조 등 부가 정보 (subtypes: `hook_additional_context`, `todo_reminder`, `edited_text_file`, `file`, `compact_file_reference`, `deferred_tools_delta`, `skill_listing`, `date_change`)
- `ai-title`: Claude Code가 자동 생성하는 세션 제목 후보

### 수정 파일 (1개)

**`claude_code_log/converter.py`** — silent skip 집합에 추가:

```python
elif entry_type in {
    "file-history-snapshot",
    "progress",
    "last-prompt",   # ← 추가
    "attachment",    # ← 추가
    "ai-title",      # ← 추가
}:
    pass  # Silently skip internal message types we don't render
```

---

## 20. User 말풍선 간 이동 버튼 (▲▼)

**목적**: 세션 페이지 우측 사이드바에 ▲▼ 버튼을 추가해 User 말풍선 사이를 순서대로 이동.

### 동작

- **▲**: 현재 뷰포트 상단 기준 50px 이상 위에 있는 마지막 User 말풍선으로 이동
- **▼**: 현재 뷰포트 상단 기준 50px 아래에 있는 첫 번째 User 말풍선으로 이동
- 클릭 없이 현재 스크롤 위치 기준으로 자동 탐색
- `.empty-prompt`, `.session-header`, `.filtered-hidden` 제외

### 핵심 설계: ±50px 임계값

`scrollIntoView({ block: 'start' })` 후 해당 요소의 `getBoundingClientRect().top`이 정확히 0이 아니라 `-1~-3px`로 미세하게 음수로 남는 브라우저 특성이 있음. 임계값 없이 `top < 0`으로 탐지하면 같은 말풍선이 재탐지되어 ▲가 연속으로 작동하지 않는 버그 발생.

▼는 `top > 50`, ▲는 `top < -50`으로 대칭 설계하여 이 문제를 방지.

### 수정 파일 (2개)

#### 20-1. `claude_code_log/html/templates/transcript.html`

**HTML**: `#floating-buttons` 안에 버튼 추가 (📋 다음, ⬆️ 앞):
```html
<button class="prev-user-msg floating-btn" id="prevUserMsg" title="이전 질문으로">▲</button>
<button class="next-user-msg floating-btn" id="nextUserMsg" title="다음 질문으로">▼</button>
```

**JS**: DOMContentLoaded 블록 안에 IIFE로 추가:
```javascript
(function() {
    function getUserMsgs() {
        return Array.from(document.querySelectorAll(
            '.message.user:not(.empty-prompt):not(.session-header):not(.filtered-hidden)'
        ));
    }

    document.getElementById('prevUserMsg').addEventListener('click', function() {
        var msgs = getUserMsgs();
        if (!msgs.length) return;
        for (var i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].getBoundingClientRect().top < -50) {
                msgs[i].scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
        }
        msgs[0].scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    document.getElementById('nextUserMsg').addEventListener('click', function() {
        var msgs = getUserMsgs();
        if (!msgs.length) return;
        for (var i = 0; i < msgs.length; i++) {
            if (msgs[i].getBoundingClientRect().top > 50) {
                msgs[i].scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
        }
        msgs[msgs.length - 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
})();
```

#### 20-2. `claude_code_log/html/templates/components/global_styles.css`

버튼 순서 추가 (📋 다음, ⬆️⬇️ 앞):
```css
/* Floating buttons order (top→bottom: 📆 🔍 📋 ▲ ▼ ⬆️ ⬇️) */
.prev-user-msg.floating-btn    { order: 4; }
.next-user-msg.floating-btn    { order: 5; }
.scroll-top.floating-btn       { order: 6; }
.scroll-bottom.floating-btn    { order: 7; }
```

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
| `3f85f77` | iframe sandbox DOM 삽입, 마커 이름 `@@CCL_` 접두사로 변경, `rfind()` 안전장치, `updating` 플래그 리셋 버그 수정, `after>=total` 조기 반환, `source.onopen` 재연결 복구 |
| `47fdc2d` | 맨 아래로 이동 플로팅 버튼 추가, 맨 위로 버튼 이모지 변경 (🔝→⬆️) |
| `f62c312` | 플로팅 버튼 정리 (`<a>`→`<button>` 통일, scrollTo 방식 통일, ⬆️⬇️ 위치 조정) |
| `3dc6fef` | 인덱스 페이지 새로고침 시 자동 재생성 |
| `f203df8` | 세션 custom title을 브라우저 탭 제목에 반영, VS Code 연동 버그 수정 (`_get_custom_title` 마지막 항목 반환, `_update_custom_title` 전체 교체) |
| `1b201f4` | SSE 500 버그 수정 — `render_session`, `render_messages`에서 `_get_custom_title(messages, ...)` → `_get_custom_title(jsonl_file, ...)` 잘못된 인자 수정. 상세: [LIVE_SYNC.md Bug 6](LIVE_SYNC.md#bug-6-custom-title-기능-추가-후-sse-500-에러) |
| `2db16c5` | SSE 추가 메시지 타임스탬프 UTC 표시 수정 — `timezone_converter.js`에 `window.convertTimestamps` 전역 노출 추가. 상세: [LIVE_SYNC.md Bug 7](LIVE_SYNC.md#bug-7-sse로-추가된-메시지의-타임스탬프가-utc-그대로-표시) |
| `556e3b4` | 빈 말풍선 하단 고정 (sticky) — `#prompt-dock` 래퍼 방식, 최대 16줄, 헤더 ▼/▲ 토글 |
| `2f0726b` | 플로팅 버튼 우측 사이드바 고정 — `#floating-buttons` 컨테이너, `body padding-right: 70px`, dock `right: 60px` |
| `cbb193f` | SSE `total` 고정 버그 최종 해결 — HTML 마커 방식 완전 폐기, Python `TemplateMessage` 객체 기반 카운트(`get_template_messages()` + `render_fragment()`). `#sse-live-messages` DOM 순서 수정. 테스트 5개 수정. 상세: [LIVE_SYNC.md Bug 8](LIVE_SYNC.md#bug-8-total-값-고정--마커-오염-재발-최종-해결-마커-방식-완전-폐기) |
| `3a110cf` + `6177635` | sticky 전환 시 레이아웃 점프 버그 수정, 페이지 로드 즉시 dock 하단 고정, 필터 숨김 버그 수정 |
| `36084a4` | User 메시지 긴 내용 접기 — `format_user_text_content()` → `render_markdown_collapsible()` 로 변경, 20줄 초과 시 접힘 |
| `73b0fb3` | 2000+ 메시지 세션 DOM 오염 수정 — `render_markdown`/`render_markdown_collapsible` `escape_html` 기본값 `True`로 변경, `will-change: transform` 추가 |
| `12eeb26` | SSE 이벤트 누락 수정 — `pendingUpdate` 플래그 추가, Thinking만 표시되고 Text 누락되는 문제 해결. 상세: [LIVE_SYNC.md Bug 9](LIVE_SYNC.md#bug-9-sse-updating-플래그에-의한-이벤트-누락--thinking만-표시되고-assistant-응답-미표시) |
| `d1b0236` | SSE 동적 메시지 fold 토글 수정 — fold-bar 이벤트 리스너를 개별 바인딩에서 이벤트 위임으로 변경. 상세: [LIVE_SYNC.md Bug 10](LIVE_SYNC.md#bug-10-sse-동적-메시지의-fold-토글-미작동) |
| `6d5c034` | 세션 페이지 홈 버튼 — `<h1>` 왼쪽에 🏠 아이콘 추가, 클릭 시 메인 대시보드(`/`)로 이동 |
| `0757d84` | 인덱스 로딩 속도 최적화 — `process_projects_hierarchy(cache_only=True)` 추가, `/` 라우트에서 HTML 생성 스킵. 20.8s → 5~7s |
| (pending) | 모델 배지 — Assistant 메시지 헤더에 모델명 배지 표시 (`Sonnet 4.6`, `Opus 4.7` 등) |
| (pending) | 빈 프롬프트 실시간 모델 배지 + watchdog + JSONL-first 모델 우선순위 수정 + 미인식 타입 경고 제거 |
| (pending) | User 말풍선 간 이동 버튼 ▲▼ — 우측 사이드바에 추가, ±50px 임계값으로 연속 클릭 시 재탐지 버그 방지 |

---

## 의존성

추가된 외부 의존성:

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `watchdog` | `>=4.0.0` | OS 네이티브 파일 변경 감지 (Windows: ReadDirectoryChangesW, macOS: FSEvents, Linux: inotify). SSE 폴링 2초 → 즉각 반응으로 교체. |

나머지 기능은 모두 기존 의존성(Flask, Jinja2 등)만 사용.
