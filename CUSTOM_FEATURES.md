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
21. [질문 말풍선 순차 번호 (#1, #2, #3...)](#21-질문-말풍선-순차-번호-1-2-3)
22. [질문 북마크 기능 (📌 핀 + 🔖 패널)](#22-질문-북마크-기능--핀---패널)
23. [Old Sessions — JSONL 삭제 후 HTML만 잔존하는 세션 조회](#23-old-sessions--jsonl-삭제-후-html만-잔존하는-세션-조회)
24. [SSE 업데이트 시 입력 중인 textarea 내용 보존](#24-sse-업데이트-시-입력-중인-textarea-내용-보존)
25. [빈 프롬프트 입력 지우기 버튼 (🗑️)](#25-빈-프롬프트-입력-지우기-버튼-)
26. [검색 단축키 비활성화 (Ctrl+F, F3 — 브라우저 기본 찾기 사용)](#26-검색-단축키-비활성화-ctrlf-f3--브라우저-기본-찾기-사용)
27. [📂 도구 메시지 (Read/Edit/Bash 등) 보이기/숨기기 토글 버튼](#27--도구-메시지-readeditbash-등-보이기숨기기-토글-버튼)
28. [대시보드 검색 결과 — 세션 제목/ID/미리보기 표시](#28-대시보드-검색-결과--세션-제목id미리보기-표시)
29. [메시지 선택 후 HTML 내보내기 (체크박스 + 슬라이드 패널)](#29-메시지-선택-후-html-내보내기-체크박스--슬라이드-패널)
30. [대시보드에 원본 JSONL 디렉토리 경로 표시 + 복사 버튼](#30-대시보드에-원본-jsonl-디렉토리-경로-표시--복사-버튼)
31. [JSONL 자동 삭제 막기 (환경 설정)](#31-jsonl-자동-삭제-막기-환경-설정)
32. [세션 자동 제목 (ai-title) 표시](#32-세션-자동-제목-ai-title-표시)

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

> **변경 이력 (blur 복원)**: 클릭 후 내용을 지우고 외부를 클릭하면 `empty-prompt` 상태로 복원되도록 `blur` 리스너 추가. 이에 따라 `{ once: true }` 제거 — 복원 후 재클릭이 가능하도록 클릭 핸들러를 반복 실행 가능하게 변경. `input`/`blur`/`minimize` 리스너는 클릭 핸들러 밖으로 이동하여 한 번만 등록되도록 구조 변경.
> ```javascript
> // blur: 내용이 없으면 empty-prompt 복원
> textarea.addEventListener('blur', function () {
>     if (!this.value.trim()) {
>         ep.classList.add('empty-prompt');
>         this.style.height = '';
>     }
> });
> // 클릭: empty-prompt 상태일 때만 활성화 (once 제거)
> ep.addEventListener('click', function () {
>     if (!ep.classList.contains('empty-prompt')) return;
>     ep.classList.remove('empty-prompt');
>     textarea.focus();
> });
> ```

---

## 2. 세션 제목 수정

**목적**: 인덱스/세션 네비게이션에서 ✏️ 버튼으로 세션 제목을 인라인 편집. 수정된 제목은 브라우저 탭 제목과 VS Code Claude Code 확장에도 반영됨 — 단 **대화 중인 세션은 예외**다([한계](#한계--대화-중인-세션은-vs-code-에-반영되지-않는다) 참고).

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
    읽는 쪽은 마지막 항목을 쓰므로 새 제목이 최종값이 된다.
    (단, 세션이 VS Code 에서 열려 있으면 확장이 그 뒤에 계속 덧쓴다 — 아래 "한계" 참고)
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
> - `_update_custom_title`은 모든 `custom-title` 항목을 삭제 후 재추가 → sessionId가 다른 형식의 garbage 항목까지 완전히 제거. VS Code 확장도 **마지막** 항목을 쓰므로 항목이 하나뿐이면 확실하게 반영됨.

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

### 한계 — 대화 중인 세션은 VS Code 에 반영되지 않는다

대시보드에서 바꾼 제목이 VS Code 세션 목록에 안 나타나는 경우가 있다. **버그가 아니라
구조적 충돌**이고, 조건이 명확하다.

| 대상 | 결과 |
|---|---|
| VS Code 에서 열려 있지 않은 세션 | ✅ 반영됨 |
| **지금 대화 중인 세션** | ❌ 곧 옛 제목으로 덮임 |

#### 원인 — 확장이 자기 메모리 값을 매 턴 덧쓴다

VS Code 확장은 세션을 열 때 제목을 메모리에 올려두고(`this.customTitles`), 대화가 오갈
때마다 그 값을 JSONL 뒤에 append 한다. 파일을 외부에서 고쳐도 확장 메모리는 모른다.

실제로 관측한 파일 상태 — 대시보드가 1번 쓰는 사이 확장이 11번 덧썼다.

```
2906행 [대시보드]  새 제목            ← 여기서 수정
2907행 [VS Code ]  옛 제목
2921행 [VS Code ]  옛 제목
  ... 9번 더 ...
3087행 [VS Code ]  옛 제목            ← 마지막 = 최종값
```

읽는 쪽은 마지막 항목을 쓰므로 옛 제목이 이긴다.

```js
// 확장의 파싱 로직 — 순서대로 훑으며 덮어쓴다
if (c.type === "custom-title" && c.customTitle) o = c.customTitle, s = true;
else if (c.type === "ai-title" && c.aiTitle && !s) o = c.aiTitle;
```

#### `Developer: Reload Window` 는 해결책이 아니다

새로고침하면 확장이 파일을 **다시 읽는 것은 맞다.** 하지만 읽어봐야 마지막이 옛 제목이라
결과가 같다. "캐시 때문에 안 읽는다"는 진단은 틀렸다 — 읽되 읽을 값 자체가 옛 제목이다.

참고로 세션 목록에는 영구 캐시가 없다. 사이드카 mtime 이 JSONL 보다 오래되면 원본을
다시 읽는다.

```js
let f = p !== void 0 && d.mtime < p.mtime;   // 사이드카가 더 오래됐나
info: f ? void 0 : Yet(d, r)                  // 그러면 비우고
if (u.length > 0) await ide(e, u, n, r)       // JSONL 재파싱
```

#### 해결

**① VS Code 의 ✏️ 버튼을 쓴다** — 파일과 메모리를 함께 갱신하므로 충돌이 없다.
확장 UI 의 세션 목록 항목과 패널 상단 양쪽에 있다.

```js
appendFile(i, JSON.stringify(o) + "\n");   // 파일
this.customTitles.set(e, t);               // 메모리  ← 대시보드에는 없는 단계
```

> `package.json` 의 `contributes.commands` 에는 rename 명령이 없다. 이 버튼은
> webview 안에 있어서 명령 목록만 봐서는 없는 것처럼 보인다.

**② 대시보드로 바꾸려면 VS Code 를 닫고 한다** — `_update_custom_title` 이 기존 항목을
전부 지우므로, 확장이 안 돌고 있으면 우리 항목 하나만 남는다. 다음에 VS Code 를 열면
그 값을 읽는다.

#### 자동 제목(ai-title)은 사용자 제목을 덮지 않는다

확장의 자동 제목 생성은 `onlyIfNoCustomTitle = true` 로 호출되고, 파일 머리/꼬리에
`customTitle` 이 있으면 건너뛴다. 대시보드는 항상 꼬리에 하나를 남기므로 안전하다.

```js
if (ia(s.tail, "customTitle") || ia(s.head, "customTitle")) return true;  // skip
```

> 조사 대상: `~/.vscode/extensions/anthropic.claude-code-2.1.226-win32-x64/`
> (`extension.js`, `webview/index.js`)

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
    # 파일명이 정확히 일치할 때만 지운다 (아래 "사고" 절 참고)
    if jsonl_file is not None:
        if jsonl_file.stem != session_id:
            return jsonify({"error": "filename does not match session id"}), 409
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

### 사고 — 엉뚱한 세션이 삭제된 문제

Old Session([23번](#23-old-sessions--jsonl-삭제-후-html만-잔존하는-세션-조회)) 하나를 X 버튼으로 지웠더니,
**전혀 다른, 진행 중이던 대화의 JSONL 이 삭제됐다.** 4.9 MB 짜리가 18 KB 로 잘려 나갔다.

#### 원인 — 내용 검색이 "언급"만으로 매치했다

`_find_session_jsonl()` 의 2차 검색이 파일 전체 텍스트를 문자열로 훑고 있었다.

```python
# 문제의 코드
for jsonl_file in projects_dir.rglob("*.jsonl"):
    if session_id in jsonl_file.read_text(encoding="utf-8"):
        return jsonl_file          # 그냥 언급만 해도 매치
```

지우려던 세션은 JSONL 이 이미 없어(Old Session) 1차 파일명 검색이 실패했고, 2차로 넘어갔다.
그런데 **진행 중이던 대화가 마침 그 세션 ID 를 화면에 출력한 적이 있어서**, 그 대화의 JSONL 이
"이 세션을 담은 파일"로 오인됐다.

실측:

| 판정 방식 | 결과 |
|---|---|
| 단순 문자열 포함 (기존) | `True` — 대화 본문에 ID 가 적혀 있다는 이유만으로 |
| `sessionId` 필드 일치 | **0건** — 실제로는 무관한 파일 |

`project_dir = jsonl_file.parent` 도 함께 틀어진다. 다른 프로젝트의 파일이 매치됐다면
**그 프로젝트의 캐시와 `combined_transcripts.html` 까지** 지워졌을 것이다.

#### 수정 1 — 필드로 매칭

```python
for line in text.splitlines():
    if session_id not in line:      # 빠른 사전 필터 (대부분 여기서 걸러짐)
        continue
    raw = json.loads(line)
    if isinstance(raw, dict) and raw.get("sessionId") == session_id:
        return jsonl_file
```

#### 수정 2 — 파괴적 동작에 파일명 가드

되돌릴 수 없는 동작이므로 한 겹 더 확인한다. **제목 수정(`PUT /title`)도 JSONL 을 다시 쓰므로
같은 위험**이 있어 함께 막았다.

```python
if jsonl_file.stem != session_id:
    return jsonify({"error": "filename does not match session id"}), 409
```

#### 발동 조건 — 평소엔 드러나지 않는다

지우려는 세션 ID 가 **다른 JSONL 본문에 텍스트로 적혀 있어야** 터진다.
그래서 대부분의 삭제는 멀쩡히 동작하고, 하필 그 세션을 화제로 삼은 대화가 있을 때만 사고가 난다.

> 수정 후 실제로 Old Session 을 하나 더 삭제해 확인했다. 해당 HTML 만 지워지고
> 다른 JSONL 은 그대로였다.


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

### 수정 파일 (3개)

접기만 얻고 마크다운 해석은 피하기 위해, 마크다운 없는 접기 함수를 따로 둔다.

#### 12-1. `claude_code_log/html/utils.py` — `render_text_collapsible()` 추가

`render_markdown_collapsible()` 과 형태는 같되 본문을 마크다운으로 파싱하지 않고
이스케이프해 `<pre>` 에 넣는다. 기존 함수는 그대로 두어 Assistant 메시지가 계속 쓴다.

```python
# 수정 전
def format_user_text_content(text: str) -> str:
    escaped_text = escape_html(text)
    return f"<pre>{escaped_text}</pre>"

# 수정 후
def render_text_collapsible(raw_content, css_class, line_threshold=20, preview_line_count=5):
    full_html = f"<pre>{escape_html(raw_content)}</pre>"
    lines = raw_content.splitlines()
    if len(lines) <= line_threshold:
        return f'<div class="{css_class}">{full_html}</div>'
    preview_text = "\n".join(lines[:preview_line_count]) + "\n\n..."
    preview_html = f"<pre>{escape_html(preview_text)}</pre>"
    collapsible = render_collapsible_code(preview_html, full_html, len(lines), is_markdown=False)
    return f'<div class="{css_class}">{collapsible}</div>'
```

#### 12-2. `claude_code_log/html/user_formatters.py` — 호출 교체

```python
# 최초 원본
def format_user_text_content(text: str) -> str:
    return f"<pre>{escape_html(text)}</pre>"          # 접기 없음

# 1차 변경 (마크다운 부작용 발생)
    return render_markdown_collapsible(text, "user-text", line_threshold=20)

# 현재
    return render_text_collapsible(text, "user-text", line_threshold=20)
```

#### 12-3. `components/message_styles.css` — 글꼴·색상 유지

`<pre>` 로 바뀌면 `.content pre` 규칙 때문에 고정폭 글꼴에 연한 회색(`#555`)이 된다.
마크다운이던 때와 같은 모양을 유지하려면 되돌려줘야 한다.

```css
.user-text pre {
    font-family: var(--font-ui);
    color: var(--text-primary);
}
```

### 왜 마크다운을 쓰면 안 되는가

1차 변경 때는 부작용을 "`**굵게**` 등이 렌더링되어 보인다"는 **모양 문제**로만 파악했으나,
실제로는 **글자가 사라진다**:

| 입력 | 마크다운 렌더링 결과 | 문제 |
|---|---|---|
| `C:\Users\user\.claude` | `C:\Users\user.claude` | 백슬래시 소실 — 경로가 틀린 값이 됨 |
| `test\__snapshots__` | `test__snapshots__` | 동일 |
| 빈 줄 뒤 4칸 이상 들여쓴 줄 | 중간만 음영 처리된 코드 블록 | 붙여넣은 HTML·로그가 뜬금없이 잘림 |
| `# 주석` | 큰 제목(`<h1>`) | 모양 변형 |
| `1. 문장` / `- 문장` | 번호·글머리 목록 | 모양 변형 |

`\` 는 마크다운에서 "다음 글자를 그대로 취급하라"는 이스케이프 기호라 자신이 먹힌다.
실측: 한 세션의 user 메시지 58건 중 10건에서 글자 소실, 전부 윈도우 경로였다.

> 원본 프로젝트에 `test_user_message_not_markdown_rendered` 테스트가 있는 이유가 이것이다.
> Assistant 응답은 마크다운으로 작성되지만, user 입력은 그냥 텍스트다.

### 검증

| 항목 | 결과 |
|---|---|
| 실제 세션 user 메시지 68건, 문자 단위 대조 | 전부 원문과 완전 동일 |
| 생성 HTML 의 user 말풍선 44개 | `<h1>` / `<strong>` / `<ol>` / 코드블록 **0건** |
| 백슬래시 경로 | 손상 0건 |
| 20줄 초과 접기 | 그대로 동작 |
| 북마크 미리보기 (`.user-text`) | 정상 — 클래스를 유지했으므로 |
| Assistant 메시지 | 영향 없음 — `render_markdown_collapsible()` 을 그대로 두었다 |
| 전체 테스트 | 693 passed, 0 failed |

보류 상태였던 `test_user_message_not_markdown_rendered` 가 이 변경으로 통과한다.

> **주의**: 파이썬 코드가 바뀌므로 확인하려면 **서버 재시작**이 필요하다.
> 템플릿만 바뀐 경우와 달리 하드 리프레시로는 반영되지 않는다.

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
- 사용자가 `/model opus` 실행 → `settings.json` **즉시** 변경 → 2초 이내 mtime 폴링 감지 → `{type: 'model', model: 'opus'}` 이벤트
- `/model default` 실행 → `settings.json`에서 `"model"` 키 **삭제** → `None` 반환 → `_DEFAULT_MODEL`("claude-sonnet-4-6") 매핑 → `{type: 'model', model: 'claude-sonnet-4-6'}` 이벤트
- 빈 말풍선 헤더에 `.prompt-model-badge` 배지 추가/갱신

> **핵심 설계**: JSONL은 `/model` 실행 즉시 기록되지 않고 **다음 메시지를 보낼 때** 기록됨. 따라서 JSONL-first 방식(세션-로컬 정확도)은 유지하되, `/model` 즉시 반영은 `settings.json` mtime 2초 폴링으로 처리.

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
# /model default 선택 시 settings.json에서 "model" 키가 사라짐 → None 반환 → 이 값으로 매핑
_DEFAULT_MODEL = "claude-sonnet-4-6"
# JSONL user 엔트리의 <local-command-stdout> 내 "Set model to X" 패턴 스캔
_MODEL_CMD_RE = re.compile(r"Set model to (\S+)")

def _get_current_model_from_settings() -> Optional[str]:
    """~/.claude/settings.json에서 현재 선택 모델 반환."""
    try:
        data = json.loads(_CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model = data.get("model")
    return str(model) if model else None

def _get_latest_model_from_jsonl(jsonl_file: Path) -> Optional[str]:
    """JSONL 역순 스캔, 두 가지 소스에서 모델 반환.

    1. assistant 엔트리의 message.model (응답 모델, 세션-로컬)
    2. user 엔트리의 'Set model to X' 패턴 (응답 전에도 /model 명령 반영)
    """
    for line in reversed(jsonl_file.read_text(...).splitlines()):
        data = json.loads(line)
        entry_type = data.get("type")
        if entry_type == "assistant":
            model = data.get("message", {}).get("model")
            if model:
                return str(model)
        if entry_type == "user":
            content = data.get("message", {}).get("content", "")
            if isinstance(content, str):
                m = _MODEL_CMD_RE.search(content)
                if m:
                    return m.group(1)
    return None
```

SSE `generate()` 내부 (하이브리드 폴링 루프):
```python
last_settings_mtime = (
    _CLAUDE_SETTINGS_PATH.stat().st_mtime if _CLAUDE_SETTINGS_PATH.exists() else 0.0
)
last_model = _get_latest_model(jsonl_file)

# 연결 즉시 현재 모델 전송
if last_model:
    yield f"data: {json.dumps({'type': 'model', 'model': last_model})}\n\n"

last_keepalive = time_module.time()

while True:
    # 2s timeout: watchdog 즉각 감지 + Windows VSCode 열린 파일 미감지 보완
    try:
        tag = event_queue.get(timeout=2.0)
        tags = {tag}
        got_event = True
    except Empty:
        tags = set()
        got_event = False

    # 버스트 드레인 + settle
    ...

    # JSONL stat() 직접 폴링 (watchdog에만 의존하지 않음)
    stat = jsonl_file.stat()
    if stat.st_size != last_size or stat.st_mtime != last_mtime:
        last_size = stat.st_size
        last_mtime = stat.st_mtime
        model = _get_latest_model(jsonl_file)
        last_model = model
        yield f"data: {json.dumps({'type': 'updated', 'model': model})}\n\n"
        last_keepalive = time_module.time()
        continue

    # settings.json mtime 폴링: /model 실행 즉시 반영 (JSONL은 메시지 전송 후 기록)
    try:
        settings_mtime = _CLAUDE_SETTINGS_PATH.stat().st_mtime
    except OSError:
        settings_mtime = last_settings_mtime

    if settings_mtime != last_settings_mtime:
        last_settings_mtime = settings_mtime
        # /model default → settings.json의 "model" 키 삭제됨 → None → _DEFAULT_MODEL 매핑
        current_model = _get_current_model_from_settings() or _DEFAULT_MODEL
        if current_model != last_model:
            last_model = current_model
            yield f"data: {json.dumps({'type': 'model', 'model': current_model})}\n\n"
            last_keepalive = time_module.time()
            continue

    # 변경 없음 — 15초마다 SSE keepalive 전송
    now = time_module.time()
    if now - last_keepalive >= 15.0:
        yield ":\n\n"
        last_keepalive = now
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
- **이동 대상은 `data-authored` 속성으로 판별** (아래 "핵심 설계: 화이트리스트" 참고)

### 핵심 설계: 화이트리스트 (`data-authored`)

초기 구현은 `:not(.slash-command)` 처럼 **제외할 타입을 나열하는 블랙리스트**였다.
이 방식은 새 메시지 타입이 생길 때마다 뚫린다 — 실제로 슬래시 명령의 결과 말풍선
(`user command-output`)이 걸러지지 않아 `/model` 실행 결과에서 이동이 멈추는 버그가 있었다.

`user` CSS 클래스는 7종이 공유하므로 클래스만으로는 구분할 수 없다:

```
UserTextMessage         → user              ← 진짜 사용자 입력
UserMemoryMessage       → user              ← 같은 클래스, 구분 불가
UserSteeringMessage     → user steering
SlashCommandMessage     → user slash-command
UserSlashCommandMessage → user slash-command
CompactedSummaryMessage → user compacted
CommandOutputMessage    → user command-output
```

그래서 **Python이 렌더링 시점에 `data-authored` 표식을 붙이고, JS는 그것만 고른다.**
새 타입이 생겨도 기본이 "이동 대상 아님"이 된다.

> **CSS 클래스가 아니라 `data-` 속성인 이유**: `css_class_from_message()` 결과는
> `class=` 뿐 아니라 `data-border-color=` 에도 쓰이는데, `message_styles.css` 가
> `[data-border-color="user"]` 처럼 **정확히 일치**로 매칭한다. 클래스를 추가하면
> 값이 `"user user-authored"` 가 되어 접기 막대 색상이 조용히 깨진다.

#### 판별 기준

| 대상 | 이동 |
|---|---|
| 텍스트가 있는 사용자 메시지 | ✅ |
| 이미지만 붙여넣은 메시지 | ✅ |
| IDE 알림만 있는 말풍선 (🤖 파일 열림 / 📝 선택 영역) | ❌ |
| 슬래시 명령 호출 + 그 결과 | ❌ |
| `/compact` 자동 요약, 메모리, 빈 입력창 | ❌ |
| 서브에이전트(sidechain) 프롬프트 | ❌ |

### 핵심 설계: ±50px 임계값

`scrollIntoView({ block: 'start' })` 후 해당 요소의 `getBoundingClientRect().top`이 정확히 0이 아니라 `-1~-3px`로 미세하게 음수로 남는 브라우저 특성이 있음. 임계값 없이 `top < 0`으로 탐지하면 같은 말풍선이 재탐지되어 ▲가 연속으로 작동하지 않는 버그 발생.

▼는 `top > 50`, ▲는 `top < -50`으로 대칭 설계하여 이 문제를 방지.

### 수정 파일 (5개)

#### 20-1. `claude_code_log/html/utils.py` — 판별 함수

```python
def is_user_authored(msg: "TemplateMessage") -> bool:
    """사용자가 직접 입력한 말풍선인지 판별."""
    if msg.is_sidechain:          # 서브에이전트 프롬프트는 사용자 입력이 아님
        return False
    content = msg.content
    if not isinstance(content, UserTextMessage):
        return False
    for item in content.items:
        if isinstance(item, ImageContent):
            return True           # 스크린샷만 붙여넣은 경우도 포함
        if isinstance(item, TextContent) and item.text.strip():
            return True
    return False                  # IDE 알림만 있는 말풍선은 제외
```

`ImageContent`, `TextContent` 임포트 추가 필요.
`UserSteeringMessage` 는 `UserTextMessage` 를 상속하므로 자동 포함된다.

#### 20-2. `claude_code_log/html/renderer.py` — Jinja에 노출

`css_class_from_message` 와 동일한 방식으로 3곳:
임포트 + `generate_html()` / `generate_messages_fragment()` 의 `template.render(...)` 에
`is_user_authored=is_user_authored` 추가. (`html/__init__.py` 재익스포트도 함께)

#### 20-3. 템플릿 2개 — 속성 부착

`transcript.html` 과 **`messages_fragment.html` 둘 다** message div에 추가:
```jinja
<div class='message {{ msg_css_class }}...' data-message-id='...'{% if is_user_authored(message) %} data-authored{% endif %}>
```

> `messages_fragment.html` 은 SSE 실시간 추가에 쓰인다. 빼먹으면 **대화 중 새로 온
> 메시지만 이동이 안 되는** 증상이 나온다.

#### 20-4. `claude_code_log/html/templates/transcript.html` — 버튼과 JS

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
            '.message[data-authored]:not(.filtered-hidden)'
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

#### 20-5. `claude_code_log/html/templates/components/global_styles.css`

버튼 순서 추가 (📋 다음, ⬆️⬇️ 앞):
```css
/* Floating buttons order (top→bottom: 📆 🔍 📋 ▲ ▼ ⬆️ ⬇️) */
.prev-user-msg.floating-btn    { order: 4; }
.next-user-msg.floating-btn    { order: 5; }
.scroll-top.floating-btn       { order: 6; }
.scroll-bottom.floating-btn    { order: 7; }
```

---

## 21. 질문 말풍선 순차 번호 (#1, #2, #3...)

**목적**: 각 User 질문 말풍선 헤더에 순차 번호를 표시. 북마크 기능의 시각적 식별자로 사용.

### 동작

- `🤷 User #3` 형태로 표시 (번호는 "User" 텍스트 오른쪽)
- 페이지 로드 시 + SSE로 메시지 추가 시 모두 자동 재계산
- **`data-authored` 가 붙은 말풍선만** DOM 순서대로 1부터 부여 (섹션 20 참고)
- 필터 적용 후 숨겨진 메시지도 번호 유지 (북마크 안정성을 위해 `:not(.filtered-hidden)` 미사용)

> **선택자는 ▲▼·북마크와 반드시 같아야 한다.** 어긋나면 "▲▼로 #5에 갔는데
> 북마크 패널에는 #4로 보이는" 식으로 번호가 꼬인다. 현재 4곳이 모두
> `.message[data-authored]` 를 쓴다 — 번호매기기, 북마크 상태 복원,
> 북마크 패널 수집, ▲▼ 이동(여기에만 `:not(.filtered-hidden)` 추가).

### 수정 파일 (2개)

#### 21-1. `claude_code_log/html/templates/transcript.html`

```javascript
window.numberUserMessages = function() {
    document.querySelectorAll('.msg-number, .bookmark-pin').forEach(function(el) { el.remove(); });
    document.querySelectorAll(
        '.message[data-authored]'
    ).forEach(function(msg, i) {
        var header = msg.querySelector('.header');
        if (!header) return;
        var span = header.querySelector('span');
        if (!span) return;
        var n = i + 1;
        msg.dataset.userMsgNumber = String(n);
        // (북마크 핀도 함께 삽입 — 섹션 22 참고)
        var badge = document.createElement('span');
        badge.className = 'msg-number';
        badge.textContent = '#' + n;
        span.appendChild(badge);
    });
    if (typeof window.applyBookmarkState === 'function') window.applyBookmarkState();
};
window.numberUserMessages();
```

SSE 업데이트 후 재호출:
```javascript
if (typeof window.numberUserMessages === 'function') window.numberUserMessages();
```

#### 21-2. `claude_code_log/html/templates/components/message_styles.css`

```css
.msg-number {
    font-size: 0.72em;
    font-weight: normal;
    color: #888;
    margin-left: 20px;
    margin-right: 6px;
    user-select: none;
    flex-shrink: 0;
}
```

> **설계 결정**:
> - 번호는 DOM 순서 기반 (위치 순서) — 필터링 후에도 변하지 않음. 북마크는 별도로 UUID 기반(섹션 22)으로 저장하므로 이 번호는 UI 표시용으로만 사용.
> - 페이지 단위 카운트 (combined transcripts에서는 모든 세션 메시지에 걸쳐 1, 2, 3...). 세션별 리셋이 필요하면 별도 작업 필요.

---

## 22. 질문 북마크 기능 (📌 핀 + 🔖 패널)

**목적**: 질문 말풍선마다 북마크를 토글하고, 우측 슬라이드 패널에서 북마크 목록을 확인 + 클릭으로 해당 질문으로 이동.

### 동작

- 각 질문 말풍선 헤더에 `📌` 핀 버튼 (번호 왼쪽에 위치)
  - **사선** (rotate 0deg, opacity 0.4) = 비활성
  - **직각** (rotate -30deg, opacity 1.0 + drop-shadow) = 활성 (북마크됨)
- 클릭 시 `localStorage`에 UUID 저장/제거 + 핀 클래스 토글
- 우측 사이드바 `🔖` 버튼 → 우측 패널 슬라이드 인/아웃 (280px 너비)
- 패널 항목 클릭 → 해당 메시지로 스무스 스크롤 + 1.4초간 노란 펄스 강조
- 항목 호버 시 우측에 `✕` 표시 → 클릭으로 북마크 해제

### 데이터 저장

- localStorage 키: `ccl:bookmarks:{sessionId}` → `[uuid1, uuid2, ...]`
- 세션별 분리 저장 (combined_transcripts에서도 메시지의 sessionId로 분리)
- 메시지의 sessionId는 DOM에서 `data-session-id` 없는 user 메시지에 대해 가장 가까운 이전 `.session-header[data-session-id]`를 walk-up하여 결정

### 패널 항목 표시 (두 줄)

- **Line 1**: `#3 · 2025-12-04 14:30` (번호 + 표시되는 타임스탬프)
- **Line 2**: 질문 미리보기 (60자, ellipsis)
- **미리보기 추출**: `.content .user-text` 내부 텍스트만 사용
  - `.ide-notification` (IDE 자동 컨텍스트), tool 결과 등 자동 주입 컨텐츠 제외
  - `Array.prototype.map.call(userTexts, ...)` 으로 NodeList 처리

### 수정 파일 (3개)

#### 22-1. `claude_code_log/html/templates/transcript.html`

**HTML**: `#floating-buttons`에 북마크 버튼 + 패널:
```html
<button class="bookmark-toggle floating-btn" id="toggleBookmarks" title="북마크 보기">🔖</button>

<div id="bookmark-panel" aria-hidden="true">
    <div class="bookmark-panel-header">
        <span>🔖 북마크 <span id="bookmark-count">0</span></span>
        <button class="bookmark-panel-close" title="닫기">✕</button>
    </div>
    <div class="bookmark-panel-list" id="bookmark-list">
        <div class="bookmark-empty">아직 북마크가 없습니다...</div>
    </div>
</div>
```

**JS** (핵심 로직 IIFE):
```javascript
(function() {
    var STORAGE_PREFIX = 'ccl:bookmarks:';

    function getMsgSessionId(msg) {
        var node = msg;
        while (node && node.previousElementSibling) {
            node = node.previousElementSibling;
            if (node.classList && node.classList.contains('session-header')) {
                return node.dataset.sessionId || null;
            }
        }
        var hdr = document.querySelector('.message.session-header[data-session-id]');
        return hdr ? hdr.dataset.sessionId : null;
    }

    function loadBookmarks(sessionId) { /* JSON.parse(localStorage[...]) */ }
    function saveBookmarks(sessionId, uuids) { /* JSON.stringify → setItem */ }

    function toggleBookmark(sessionId, uuid) {
        var arr = loadBookmarks(sessionId);
        var idx = arr.indexOf(uuid);
        if (idx >= 0) arr.splice(idx, 1); else arr.push(uuid);
        saveBookmarks(sessionId, arr);
        return idx < 0;
    }

    // numberUserMessages가 호출 → 모든 핀의 .bookmarked 클래스 갱신 + 패널 새로고침
    window.applyBookmarkState = function() { /* ... */ };

    // 이벤트 위임 (SSE 추가 메시지에도 적용됨)
    document.body.addEventListener('click', function(e) {
        var pin = e.target.closest('.bookmark-pin');
        if (!pin) return;
        // ... toggle + classList + refreshPanel
    });

    // 패널 항목 클릭 → 스크롤 + 펄스 / ✕ → 해제
    panelList.addEventListener('click', function(e) {
        var rm = e.target.closest('.bookmark-item-remove');
        var row = e.target.closest('.bookmark-item');
        if (rm) { toggleBookmark(...); window.applyBookmarkState(); return; }
        scrollToMessage(row.dataset.uuid);
    });

    // 미리보기 추출: .user-text만 사용 (IDE notification 등 제외)
    var userTexts = msg.querySelectorAll('.content .user-text');
    var preview = Array.prototype.map.call(userTexts, function(el) {
        return el.textContent;
    }).join(' ').replace(/\s+/g, ' ').trim().slice(0, 60);
})();
```

**핀 삽입** (`numberUserMessages` 안에서, 번호보다 먼저 추가):
```javascript
var pin = document.createElement('button');
pin.className = 'bookmark-pin';
pin.type = 'button';
pin.title = '북마크 토글';
pin.textContent = '📌';
span.appendChild(pin);
```

#### 22-2. `claude_code_log/html/templates/components/message_styles.css`

```css
.bookmark-pin {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0 2px;
    margin-left: 12px;
    font-size: 0.85em;
    line-height: 1;
    opacity: 0.4;
    transform: rotate(0deg);
    transition: transform 0.2s ease, opacity 0.15s ease;
}
.bookmark-pin:hover { opacity: 0.85; }
.bookmark-pin.bookmarked {
    opacity: 1;
    transform: rotate(-30deg);
    filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.2));
}
```

#### 22-3. `claude_code_log/html/templates/components/global_styles.css`

플로팅 버튼 순서에 북마크 추가 (order 3):
```css
.bookmark-toggle.floating-btn  { order: 3; }
.bookmark-toggle.floating-btn.active {
    background: rgba(255, 200, 100, 0.25);
}
```

패널 슬라이드:
```css
#bookmark-panel {
    position: fixed;
    top: 0;
    right: -300px;        /* 닫힌 상태: 오프스크린 */
    bottom: 0;
    width: 280px;
    background: #fff;
    border-left: 1px solid #ddd;
    box-shadow: -4px 0 12px rgba(0, 0, 0, 0.08);
    transition: right 0.25s ease;
    z-index: 98;
    display: flex;
    flex-direction: column;
}
#bookmark-panel.open { right: 60px; }   /* 열린 상태: 사이드바 옆 */

.bookmark-item { position: relative; padding: 8px 28px 8px 10px; ... }
.bookmark-item-line1 { font-size: 0.78em; color: #888; font-weight: 600; }
.bookmark-item-line2 { font-size: 0.85em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 호버 시에만 ✕ 표시 */
.bookmark-item-remove { opacity: 0; transition: opacity 0.15s; ... }
.bookmark-item:hover .bookmark-item-remove { opacity: 1; }

/* 클릭 후 노란 펄스 */
.message.bookmark-highlight {
    animation: bookmarkPulse 1.4s ease-out;
}
@keyframes bookmarkPulse {
    0%   { box-shadow: 0 0 0 4px rgba(255, 180, 60, 0.6); }
    100% { box-shadow: 0 0 0 0 rgba(255, 180, 60, 0); }
}
```

### 핵심 설계 결정

- **UUID로 저장, 번호로 표시**: 번호(섹션 21)는 위치 기반이므로 메시지 추가/삭제 시 변할 수 있음. 영구 식별자는 UUID(`data-message-id`) 사용. 북마크가 안정적으로 유지됨.
- **이벤트 위임**: 핀 클릭과 패널 항목 클릭 모두 `document.body` / `panelList`에 위임 — SSE로 추가되는 신규 메시지의 핀도 별도 바인딩 없이 동작.
- **미리보기는 `.user-text`만**: 자동 주입되는 `.ide-notification`, 도구 훅 결과 등을 제외하여 실제 사용자 입력만 미리보기로 표시.
- **세션 ID 추론**: 단일 세션 페이지에서는 첫 `.session-header[data-session-id]`, combined transcripts에서는 메시지 직전 `.session-header`를 walk-up.
- **패널 위치**: `right: -300px` ↔ `right: 60px`(사이드바 너비) 슬라이드 — 평소 오프스크린이라 레이아웃 영향 없음.

---

## 23. Old Sessions — JSONL 삭제 후 HTML만 잔존하는 세션 조회

**목적**: Claude Code의 `cleanupPeriodDays`(기본 30일) 자동 삭제로 JSONL은 없어졌지만 HTML 파일이 남아있는 세션을 대시보드에서 조회.

### 배경

- JSONL 삭제 → 캐시 DB에서도 제거 → 인덱스에서 사라짐
- HTML 파일은 `session-{id}.html`로 프로젝트 디렉토리에 남아있어 직접 서빙 가능
- 관련 분석: [missing-old-sessions.md](missing-old-sessions.md)
- **사전 대책**: 애초에 JSONL이 안 지워지게 하려면 → [31번](#31-jsonl-자동-삭제-막기-환경-설정) / [JSONL_RETENTION.md](JSONL_RETENTION.md)

### 동작

1. 대시보드 프로젝트 카드의 **Sessions** 토글 아래 **Old Sessions (N)** 토글 표시 (JSONL 없는 HTML이 있을 때만)
2. 목록 클릭 → 정적 HTML 파일 서빙 (JSONL 없어도 브라우저에서 열람 가능)
3. 각 항목: HTML `<title>` 태그에서 요약 추출 + 파일 mtime을 타임스탬프로 표시
4. 프로젝트의 JSONL이 **전부** 사라진 경우도 `Archived` 배지를 달아 카드로 표시 → [23-6](#23-6-확장--프로젝트-전체가-archived-인-경우)

### 수정 파일 (5개 + 확장 3개)

> 23-1~5 는 JSONL이 일부라도 남은 프로젝트를 다룬다.
> 프로젝트 전체가 비는 경우는 [23-6](#23-6-확장--프로젝트-전체가-archived-인-경우) 에서 별도로 처리한다.

#### 23-1. `claude_code_log/converter.py`

`_scan_old_sessions(project_dir, valid_session_ids)` 헬퍼 추가:
- `project_dir.glob("session-*.html")` 파일 목록에서 `valid_session_ids`(현재 JSONL 목록)에 없는 것만 추출
- HTML `<title>` 파싱으로 요약 추출, 파일 mtime을 timestamp로 사용
- `first_timestamp` desc 정렬

`process_projects_hierarchy()` 수정:
- `project_summaries` 딕셔너리에 `"old_sessions"` 필드 추가
- 인덱스 재생성 조건에 `or cache_only` 추가 → `/` 요청마다 old_sessions 변화 즉시 반영

#### 23-2. `claude_code_log/renderer.py`

`TemplateProject.__init__`에 `old_sessions` 필드 추가:
```python
self.old_sessions = project_data.get("old_sessions", [])
```

#### 23-3. `claude_code_log/html/templates/index.html`

Sessions `<details>` 아래 Old Sessions `<details>` 추가:
```html
{% if project.old_sessions and project.old_sessions|length > 0 %}
<details class='old-sessions'>
    <summary>Old Sessions ({{ project.old_sessions|length }})
        <span class='old-sessions-hint'>JSONL 삭제됨, HTML만 잔존</span>
    </summary>
    {{ render_session_nav(project.old_sessions, "expandable", project.name + "/") }}
</details>
{% endif %}
```

#### 23-4. `claude_code_log/html/templates/components/project_card_styles.css`

Old Sessions 스타일 추가 (회색, opacity 0.7, 점선 구분선, hover 시 opacity 1.0):
```css
.project-sessions details.old-sessions summary { color: #999; border-top: 1px dashed #ddd; }
.project-sessions details.old-sessions .old-sessions-hint { font-size: 0.75em; color: #b0b0b0; }
.project-sessions details.old-sessions .session-link { opacity: 0.7; }
```

#### 23-5. `claude_code_log/server.py`

`serve_file`에서 content-only JSONL 매치 시 동적 렌더링 스킵:
```python
# 파일명이 session_id와 일치할 때만 동적 렌더링
# 내용에서만 발견된 경우(다른 파일이 이 ID를 언급) → 정적 HTML 서빙으로 fallthrough
if jsonl_file is not None and jsonl_file.stem == session_id:
```

> 이 조건이 없으면 `_find_session_jsonl`의 2차 content 검색이 다른 파일을 반환해 빈 세션 페이지가 동적으로 생성됨.

> ⚠️ **여기서 조회 쪽에만 가드를 넣고 삭제 쪽에는 넣지 않았다.** 나중에 X 버튼으로 Old Session 을
> 지웠을 때 진행 중이던 다른 대화의 JSONL 이 삭제되는 사고로 이어졌다 →
> [3번 "사고 — 엉뚱한 세션이 삭제된 문제"](#사고--엉뚱한-세션이-삭제된-문제)
>
> 같은 함수를 쓰는 곳이 6군데였고, 그중 파일을 **쓰는** 것이 삭제와 제목 수정 2곳이었다.
> 한 곳만 막으면 나머지가 남는다.

---

### 23-6. 확장 — 프로젝트 **전체**가 archived 인 경우

23-1~5 는 "JSONL 이 일부라도 남은 프로젝트" 안에서만 동작한다.
프로젝트의 JSONL 이 **전부** 사라지면 카드 자체가 안 만들어져 Old Sessions 도 함께 묻힌다.

실제로 이 상태의 프로젝트가 5개, 갇힌 세션 HTML 이 22개 있었다.

#### 막힌 곳이 3중이었다

archived 프로젝트가 화면에 나오려면 관문을 셋 지나야 하는데, 셋 다 막혀 있었다.

```
① 데이터 만들기        →  ② 카드 그리기         →  ③ 목록 그리기
   converter.py             index.html 카드 조건      index.html Old Sessions 위치
```

**하나만 뚫어서는 아무 변화가 없다.** ① 만 고쳤을 때 로그에는
`[ARCHIVED] (7 session HTML)` 이 정상 출력되는데 화면은 그대로였고,
②③ 은 실제로 돌려보고 단계별로 짚어야 드러났다.

**① 데이터 자체가 안 만들어짐** — `converter.py` archived 루프

```python
for archived_dir in ...:
    archived_project_count += 1      # 개수만 세고
    print("[ARCHIVED] ...")          # 출력만 하고 끝
    # 화면에 넘길 project_summaries 에 안 넣는다
```

세어놓고 버렸다. 렌더러에는 애초에 데이터가 가지 않았다.

**② 카드를 안 그림** — `index.html` 카드 조건

```jinja
{% if project.sessions %}     ← 활성 세션이 있어야만 카드를 그림
```

archived 는 JSONL 이 전부 없어서 `sessions` 가 빈 목록이다. 조건에 걸려 카드가 통째로 빠진다.

**③ 목록을 안 그림** — `index.html` 의 Old Sessions 위치

```jinja
{% if project.sessions %}              ← 바깥 조건
    <details>Sessions ...</details>
    {% if project.old_sessions %}      ← Old Sessions 가 이 안에 갇혀 있었다
        <details>Old Sessions ...</details>
    {% endif %}
{% endif %}
```

바깥이 거짓이면 안쪽은 평가될 기회조차 없다.

#### ③ 이 여태 안 드러난 이유

| | `sessions` | 바깥 조건 | Old Sessions |
|---|---|---|---|
| 활성 프로젝트 | 있음 | 참 | 잘 보임 |
| archived 프로젝트 | **비어 있음** | **거짓** | 통째로 사라짐 |

`sessions` 가 비는 상황은 archived 프로젝트뿐이다. 활성 프로젝트는 언제나 바깥 조건이
참이라 중첩돼 있어도 멀쩡히 보였고, 그래서 이 중첩이 문제라는 걸 알 수 없었다.
① 을 고쳐 archived 데이터가 처음 흘러들어온 순간에야 표면화됐다.

> 자물쇠가 이중으로 걸려 있는데 바깥 자물쇠가 늘 열려 있어서 안쪽의 존재를 몰랐던 상황이다.
> 바깥이 처음 잠기자 안쪽도 함께 드러났다.

#### 23-6-1. `claude_code_log/converter.py` — archived 루프에서 요약 추가

`archived_project_count += 1` 만 하고 버리던 자리에서 `project_summaries.append(...)` 한다.

```python
old_sessions = _scan_old_sessions(archived_dir, set())   # 유효 JSONL 이 없으므로 빈 집합
if not old_sessions:
    continue                                             # 열 것이 없으면 카드도 만들지 않음

# JSONL 이 없으니 last_modified 를 남은 세션 HTML 의 mtime 으로 대신한다.
# 0.0 으로 두면 카드에 1970년이 찍히고 정렬도 맨 아래로 밀린다.
html_files = list(archived_dir.glob("session-*.html"))
archived_last_modified = max(h.stat().st_mtime for h in html_files) if html_files else 0.0

project_summaries.append({
    ...,
    "jsonl_count": 0,
    "last_modified": archived_last_modified,
    "is_archived": True,
    "sessions": [],                # 살아있는 JSONL 이 없음
    "old_sessions": old_sessions,  # 남은 HTML 전부
})
```

#### 23-6-2. `claude_code_log/renderer.py` — `is_archived` 필드 추가

템플릿이 `project.is_archived` 를 참조하는데 `TemplateProject` 에 **없어서 항상 거짓**이었다.
Jinja2 는 없는 속성을 Undefined(=falsy)로 처리하므로 조용히 배지가 안 떴다.

```python
self.is_archived = project_data.get("is_archived", False)
```

#### 23-6-3. `claude_code_log/html/templates/index.html` — 표시 조건 2곳

```jinja
{# 카드: sessions 가 비어도 old_sessions 가 있으면 그린다 #}
{% if project.sessions or project.old_sessions %}

{# Old Sessions: Sessions 안에 중첩하지 않고 형제로 둔다 #}
<div class='project-sessions'>
    {% if project.sessions %}   <details>Sessions ...</details>   {% endif %}
    {% if project.old_sessions %} <details class='old-sessions'>...</details> {% endif %}
</div>
```

#### 결과

대시보드 카드 **2개 → 7개**, 세션 HTML 링크 26개. archived 카드에는 `Archived` 배지가 붙는다.
세션 HTML 이 하나도 없는 프로젝트는 카드를 만들지 않는다(`no session HTML left`).

> 스냅샷 diff 는 5줄 추가이나 `git diff -w` 로 보면 변경 0 — 들여쓰기 변화뿐이다.

---

## 24. SSE 업데이트 시 입력 중인 textarea 내용 보존

**목적**: 빈 프롬프트(`#ccl-live-prompt`)의 textarea에 입력 중일 때 SSE 라이브 업데이트가 와도 입력 내용/포커스/커서가 사라지지 않도록.

### 증상

세션 페이지에서 textarea(`<textarea class='user-input'>`)에 메시지를 타이핑하고 있는 동안 Claude Code 측에서 새 응답이 도착하면, 입력 중이던 텍스트가 흔적도 없이 날아갔음.

### 원인

기존 SSE update 핸들러는 새 메시지 삽입 후 **프롬프트 element를 통째로 삭제하고 재생성**하는 구조였음:

```javascript
// (원래 코드)
var oldPrompt = document.getElementById('ccl-live-prompt');
if (oldPrompt) oldPrompt.remove();        // ← textarea가 통째로 소멸
// ... 새 메시지 삽입 ...
// 새 promptDiv 생성 → dock.appendChild(promptDiv);
window.initEmptyPrompt();                  // 리스너 재바인딩
```

근본 이유는 **`initEmptyPrompt()` 함수가 idempotent하지 않았기 때문**:
- 도크의 sticky-bottom `padding-bottom` 재계산 로직 (필요)
- textarea의 `input` / `blur` / 부모 `click` / minimize 버튼 `click` 리스너 등록 (재호출 시 중복 누적)

위 두 가지가 한 함수에 묶여 있어서, padding을 다시 계산하려면 `initEmptyPrompt()`를 다시 불러야 했고, 다시 부르면 리스너가 중복되므로 element를 새로 만들어야 했음. **그 부작용으로 textarea 내용이 날아가는 게 비의도적이지만 불가피한 결과**가 됨.

### 수정

`SSE updated 이벤트` 핸들러에서 프롬프트 element를 건드리지 않고, sticky-padding 재계산만 inline으로 수행하도록 변경.

#### 수정 파일 (1개)

**`claude_code_log/html/templates/transcript.html`** — SSE `onmessage` → `data.type === 'updated'` 분기 안의 `iframe.onload` 콜백

**제거**: 옛 프롬프트 `remove()` + 새 `promptDiv` 생성 + `dock.appendChild()` + `initEmptyPrompt()` 재호출

**추가**: 메시지 삽입 후 도크 padding만 inline으로 재계산
```javascript
// 모델 배지만 갱신 (프롬프트 element는 그대로)
if (resp.model) updatePromptModel(resp.model);

// ... convertTimestamps / numberUserMessages ...

// sticky-bottom 도크 padding 재계산 (문서 높이가 새 메시지로 늘어남)
// initEmptyPrompt는 호출하지 않음 — 이미 붙은 input/blur/click 리스너가 중복으로 또 붙어 동작이 이상해질 수 있음
var dock = document.getElementById('prompt-dock');
if (dock && dock.classList.contains('sticky')) {
    document.body.style.paddingBottom = '';
    var dockAbsTop = dock.getBoundingClientRect().top + window.scrollY;
    var docHeight = document.documentElement.scrollHeight;
    document.body.style.paddingBottom = (docHeight - dockAbsTop) + 'px';
}
```

### 결과

| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| textarea 입력 텍스트 | 사라짐 | 그대로 보존 |
| 포커스 / 커서 위치 | 잃음 | 그대로 |
| 입력창 auto-grow 높이 | 리셋 | 그대로 |
| minimized 상태 (▲) | 리셋 | 그대로 |
| empty-prompt 활성화 여부 | 리셋 | 그대로 |
| 이벤트 리스너 | 매번 재바인딩 | 한 번만 (DOMContentLoaded 시) |
| 모델 배지 갱신 | OK | OK (`updatePromptModel`만 호출) |
| 도크 sticky padding 재계산 | OK (initEmptyPrompt 부수효과) | OK (inline) |

DOM 구조상 새 메시지는 `#sse-live-messages` 컨테이너로 들어가고 프롬프트는 그 아래의 `#prompt-dock` 안에 별도로 있으므로, 프롬프트를 지우지 않아도 새 메시지가 프롬프트 위쪽에 자연스럽게 표시됨.

### 설계 메모

상태 초기화(side-effect-free)와 이벤트 바인딩(side-effect-heavy)이 같은 함수에 묶이면, 부분 호출이 불가능해져 element 재생성 같은 우회 수단을 쓰게 되고 부작용이 따라옴. 두 책임을 분리해 inline 호출 가능하게 만든 사례.

---

## 25. 빈 프롬프트 입력 지우기 버튼 (🗑️)

**목적**: 빈 프롬프트의 헤더에 🗑️ 휴지통 버튼을 추가해 클릭 한 번으로 입력 중이던 textarea 내용을 비울 수 있게.

### 동작

1. 빈 프롬프트 헤더에 `🤷 User | 🗑️ | ▼` 순서로 버튼 배치 (지우기 버튼은 minimize 왼쪽)
2. 🗑️ 클릭 시 textarea 내용 비우기 → height auto-grow가 한 줄로 리셋 → textarea에 포커스 유지 (바로 다시 타이핑 가능)
3. **Ctrl+Z 로 복원 가능** — `document.execCommand('selectAll' → 'delete')` 사용으로 native undo stack에 정상 등록됨 (`textarea.value = ''` 직접 할당은 undo stack에 안 들어가므로 사용 안 함)
4. textarea가 이미 비어있으면 클릭해도 아무 일 없음
5. 빈 프롬프트 비활성 상태(empty-prompt 클래스)에선 `.user.empty-prompt *` 의 `pointer-events: none` 으로 자동 비활성 → 별도 가시성 토글 불필요

### 설계 결정

| 옵션 | 선택 | 이유 |
|---|---|---|
| 아이콘 | 🗑️ | 직관적 (✕는 닫기 의미와 혼동) |
| 위치 | minimize(▼) 왼쪽 | 헤더 좌측 액션 영역에 자연스럽게 배치 |
| 클릭 후 포커스 | 유지 | 실수로 지웠을 때 바로 다시 타이핑 가능 |
| 비우기 방식 | `execCommand('selectAll'/'delete')` | native undo stack 등록 → Ctrl+Z 복원 가능 |
| 확인 다이얼로그 | 없음 | UX 거추장, Ctrl+Z 로 충분 |
| 표시 조건 | 항상 | `pointer-events: none` 으로 빈 상태에선 자동 비활성 |

### Ctrl+Z 복원 원리

`textarea.value = ''` 같은 직접 프로퍼티 할당은 브라우저 native undo stack에 기록되지 않음 → 사용자가 Ctrl+Z를 눌러도 복원 안 됨. 반면 `document.execCommand('delete')`는 "사용자 편집 명령"으로 간주되어 undo stack에 정상 등록됨. `execCommand`는 명세상 "deprecated" 표기되어 있지만, 이는 contenteditable의 서식 명령(`bold`/`italic` 등) 때문이며 textarea의 `selectAll`/`delete`는 여전히 안정적이고 모든 주요 브라우저에서 native undo와 정상 연동됨.

```
사용자가 "안녕" 입력 → undo stack: [insert "안녕"]
🗑️ 클릭 (selectAll + delete) → undo stack: [insert "안녕", selectAll, delete]
Ctrl+Z (delete 취소) → "안녕" 복원
Ctrl+Z (selectAll 취소) → 선택 해제
```

### 수정 파일 (2개)

#### 25-1. `claude_code_log/html/templates/transcript.html`

**HTML** — `#ccl-live-prompt > .header` 안에 minimize 버튼 왼쪽으로 추가:
```html
<div class='header'>
    <span>🤷 User</span>
    <button class='prompt-clear-btn' title='입력 내용 지우기'>🗑️</button>
    <button class='prompt-minimize-btn' title='최소화'>▼</button>
</div>
```

**JS** — `initEmptyPrompt()` 안의 minimize 핸들러 바로 앞에 click 핸들러 추가:
```javascript
var clearBtn = ep.querySelector('.prompt-clear-btn');
if (clearBtn) {
    clearBtn.addEventListener('click', function (e) {
        e.stopPropagation();  // .empty-prompt 부모 click 핸들러로 버블링 방지
        if (!textarea.value) return;
        textarea.focus();  // execCommand는 포커스된 element 대상
        // 1) 전체 선택 → 2) 삭제 (두 명령 모두 native undo stack에 기록됨 → Ctrl+Z 복원 가능)
        try {
            document.execCommand('selectAll', false);
            document.execCommand('delete', false);
        } catch (err) {
            // execCommand 미지원 환경 fallback (Ctrl+Z 안 됨)
            textarea.value = '';
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        }
        // execCommand('delete')는 input 이벤트를 자동 발화하지만 일부 브라우저는
        // 빈 textarea에선 안 쏘기도 함 → 수동 보강으로 height auto-grow 트리거
        if (textarea.value === '') {
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });
}
```

리스너는 `DOMContentLoaded` 시 `initEmptyPrompt()`가 한 번만 호출되므로 (#24 수정 이후) 중복 등록 우려 없음.

#### 25-2. `claude_code_log/html/templates/components/message_styles.css`

기존 `.prompt-minimize-btn` 셀렉터를 그룹화하여 두 버튼 모두에 동일 스타일 적용 (CSS 중복 방지):

```css
/* Header action buttons in prompt header (clear, minimize) */
.prompt-clear-btn,
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
.prompt-clear-btn:hover,
.prompt-minimize-btn:hover {
    background: rgba(0, 0, 0, 0.08);
}
```

### #24와의 시너지

이 기능은 #24 (SSE 업데이트 시 textarea 보존) 위에 자연스럽게 얹힘:
- #24 이전: 프롬프트 element가 SSE update마다 재생성됐으므로 🗑️ 버튼의 click 리스너도 매번 다시 붙여야 했을 것
- #24 이후: 프롬프트 element가 영구히 유지되므로 `DOMContentLoaded` 시 한 번 바인딩으로 충분

---

## 26. 검색 단축키 비활성화 (Ctrl+F, F3 — 브라우저 기본 찾기 사용)

**목적**: 커스텀 `.filter-toolbar` 검색이 정상 동작하지 않는 동안 브라우저 기본 Ctrl+F 찾기가 제대로 동작하도록 임시 비활성화.

### 배경

`search.html`의 `handleKeyboardShortcuts`가 Ctrl+F / Cmd+F / F3을 가로채서 `e.preventDefault()`로 브라우저 기본 찾기를 막고 `.filter-toolbar`를 띄우는 구조였음. 그런데 커스텀 검색이 어색하게 동작하여 페이지 본문 검색이 사실상 불가능해짐.

### 동작

- Ctrl+F / Cmd+F / F3 핸들러 블록을 주석 처리하여 브라우저 기본 동작 복원
- 우측 하단 🔍 플로팅 버튼은 그대로 유지 → 필요 시 커스텀 filter-toolbar 사용 가능
- 검색창 내부의 Enter/Escape는 그대로 유지 (검색창 포커스 시에만 발화하므로 일반 페이지 간섭 없음)

### 수정 파일 (1개)

**`claude_code_log/html/templates/components/search.html`** — `handleKeyboardShortcuts()` 안의 Ctrl+F / F3 블록을 코드 삭제가 아닌 **주석 처리**로 비활성화. 검색 기능을 제대로 고친 뒤 빠르게 재활성화할 수 있도록 코드는 보존:

```javascript
// Ctrl+F / Cmd+F / F3 가로채기 비활성화 (브라우저 기본 찾기 사용)
// — 커스텀 filter-toolbar 검색이 동작이 어색하다는 피드백으로 임시 비활성화.
//   다시 활성화하려면 아래 블록의 주석을 해제하면 됨.
//
// if ((e.ctrlKey || e.metaKey) && e.key === 'f') { ... }
// if (e.key === 'F3') { ... }
```

---

## 27. 📂 도구 메시지 (Read/Edit/Bash 등) 보이기/숨기기 토글 버튼

**목적**: 메시지 본문 영역에서 도구 호출/결과(`tool_use` + `tool_result`)만 일괄 표시·숨김. user / assistant / thinking은 항상 보이게 유지하고, 사용자가 원할 때만 도구 메시지(Read/Edit/Bash 등)를 한 번에 끄거나 켤 수 있음.

### 배경 — 초기 설계가 잘못된 이유

처음엔 메시지 **트리 구조**를 기준으로 접고 펼치는 방식이었음(`setInitialFoldState`/`expandAll`/`collapseToInitial`). 그러나 Claude Code의 메시지 트리는 도구 사용을 거치면 깊이가 길어짐:

```
User (질문)                           ← depth 1
  └─ Assistant text (첫 응답)         ← depth 2  ← User의 직계 자식
       └─ Tool use (도구 호출)         ← depth 3
            └─ Tool result (도구 결과) ← depth 4
                 └─ Assistant text (최종 답변) ← depth 5  ← 직계 자식이 아님 → 접기 시 사라짐
```

트리 기반 "직계 자식만 보이게" 로직이 깊이 5의 마지막 Assistant 답변까지 같이 숨겨버려, 사용자가 가장 보고 싶어하는 최신 답변이 사라지는 부작용이 있었음. 또한 사용자의 의도는 "트리 깊이"가 아니라 "메시지 종류"였음.

**개선 방향**: 트리 깊이를 무시하고 메시지의 CSS 클래스(`.tool_use` / `.tool_result`)만 보고 토글.

### 동작

| 클릭 | 동작 | 아이콘 변경 |
|---|---|---|
| 도구 메시지가 보이는 상태에서 클릭 | 모든 `.tool_use` / `.tool_result` 에 `display: none` | 📁 → 📂 |
| 도구 메시지가 숨어있는 상태에서 클릭 | 모든 `.tool_use` / `.tool_result` 의 `display` 해제 | 📂 → 📁 |
| 페이지 로드 직후 | `syncIcon()` 가 현재 가시성 보고 아이콘 결정 | 자동 |

| 메시지 종류 | 동작 |
|---|---|
| 👤 user, 🤖 assistant, 💭 thinking | **항상 보임** — 버튼이 건드리지 않음 |
| 🛠️ tool_use, tool_result (Read/Edit/Bash/Write/Grep/...) | 버튼으로 일괄 토글 |
| fold-bar (▼/▶) | **독립 동작** — 사용자가 개별로 계속 사용 가능 |
| 메시지 안의 `<details>` (긴 코드 펼침 등) | **그대로** — 📋 버튼이 담당 |

### 수정 파일 (1개)

**`claude_code_log/html/templates/transcript.html`**:

- `#floating-buttons` 영역에 버튼 추가: `<button class="expand-collapse-all floating-btn" id="toggleExpandAll" title="도구 메시지 (Read/Edit/Bash 등) 보이기/숨기기">📂</button>`
- DOMContentLoaded 안에 IIFE로 `anyToolVisible` / `showAllTools` / `hideAllTools` / `syncIcon` + 클릭 핸들러 정의
- CSS는 기존 `.floating-btn` 스타일 그대로 재사용 (별도 CSS 없음)

```javascript
var toolSel = '.message.tool_use, .message.tool_result';

function anyToolVisible() {
    var tools = document.querySelectorAll(toolSel);
    for (var i = 0; i < tools.length; i++) {
        if (tools[i].style.display !== 'none') return true;
    }
    return false;
}
function showAllTools() {
    document.querySelectorAll(toolSel).forEach(function(m) { m.style.display = ''; });
    btn.textContent = '📁';
}
function hideAllTools() {
    document.querySelectorAll(toolSel).forEach(function(m) { m.style.display = 'none'; });
    btn.textContent = '📂';
}
syncIcon();  // 초기에 fold-bar 상태로 숨어있을 수 있으므로 아이콘 동기화
btn.addEventListener('click', function() {
    if (anyToolVisible()) hideAllTools(); else showAllTools();
});
```

### 핵심 설계

| 항목 | 결정 | 이유 |
|---|---|---|
| 토글 단위 | 메시지 CSS 클래스 (`.tool_use` / `.tool_result`) | 사용자가 생각하는 단위는 "메시지 종류"이지 "트리 깊이"가 아님 |
| 토글 범위 | 도구 메시지만 | thinking은 본문 일부로 인식되므로 항상 보임 |
| 다른 토글 기능 침범 | 없음 — fold-bar / `<details>` 건드리지 않음 | 직교성 유지 (fold-bar는 개별 메시지 트리, 📋 버튼은 본문 details) |
| 아이콘 초기 동기화 | `syncIcon()` 으로 현재 DOM 상태 검사 | 페이지 로드 직후 도구는 fold-bar로 인해 숨어있을 수 있어 초기엔 📂 가 맞음 |

---

## 28. 대시보드 검색 결과 — 세션 제목/ID/미리보기 표시

**목적**: `class="search-result-group"` 안의 개별 검색 결과 항목에서 어떤 세션인지 식별이 어렵던 문제 해결.

### 배경

기존 결과는 `💬 Session abc12345`처럼 URL에서 잘라낸 짧은 ID 8자만 보였음. 세션 제목이나 어떤 질문이었는지 알 수 없어서 결과를 보고도 클릭해야 확인 가능했음.

### 동작

각 세션 매치 항목이 이제 이렇게 표시됨:

```
┌─ search-result-item ─────────────────────────────────────────┐
│ 💬 [세션 제목]                                  #ab2c1c60    │  ← 같은 줄 (제목 좌측, ID 우측)
│ 첫 user 질문 미리보기 (60자, 검색어 하이라이트)              │  ← 회색 이탤릭
│ ...검색어가 포함된 본문 발췌...                              │  ← 기존 excerpt
│ 3 matches    2026-06-21 11:32 • 28 messages                 │
└──────────────────────────────────────────────────────────────┘
```

- 세션 제목 — `.session-title[data-title]`에서 추출. `custom_title` > `summary` > "Session abc12345" 폴백
- 세션 ID — `.session-link[data-session-id]`의 전체 UUID에서 앞 8자. ID 칩 hover 시 전체 UUID tooltip
- 미리보기 — `sessionPreview` (있을 때만 표시, 없으면 생략)
- 검색어 하이라이트 — 제목/미리보기/excerpt 세 곳 모두 노란 형광펜

### 수정 파일 (2개)

#### 28-1. `claude_code_log/html/templates/components/search.html`

**인덱싱** (`buildSearchIndex` 안): 세션 카드의 `.session-link`에서 깨끗한 메타 추출:
```javascript
const sessionTitle = (link.querySelector('.session-title')?.dataset?.title || '').trim();
const sessionFullId = link.dataset?.sessionId || '';
searchState.searchIndex.push({
    ...,
    sessionTitle: sessionTitle,
    sessionFullId: sessionFullId,
});
```

**렌더링** (`groups.sessions.forEach` 안): 같은 줄 레이아웃 + 미리보기 줄:
```javascript
const fullId = match.sessionFullId || /* URL fallback */;
const shortId = fullId.substring(0, 8);
const title = match.sessionTitle || `Session ${shortId}`;
html += `
    <div class="search-result-item">
        <a href="${match.link}">
            <div class="search-result-session">
                <span class="search-result-session-title">💬 ${highlightText(title, query)}</span>
                <span class="search-result-session-id" title="${fullId}">#${shortId}</span>
            </div>
            ${match.sessionPreview ? `<div class="search-result-preview">${highlightText(match.sessionPreview, query)}</div>` : ''}
            ...
        </a>
    </div>
`;
```

#### 28-2. `claude_code_log/html/templates/components/search_styles.css`

`.search-result-session`을 flex container로 변경 + 신규 클래스 추가:

- `.search-result-session` — `display: flex; justify-content: space-between` (제목 좌측 길게, ID 우측 끝 고정)
- `.search-result-session-title` — `flex: 1` + `text-overflow: ellipsis` (제목 길면 `...` 처리, ID 영역 침범 방지)
- `.search-result-session-id` — 모노스페이스 폰트 + 회색 배경 칩 스타일
- `.search-result-preview` — 회색 이탤릭, 1줄 ellipsis
- 새 세 클래스 모두 `.search-highlight` 적용 가능

---

## 29. 메시지 선택 후 HTML 내보내기 (체크박스 + 슬라이드 패널)

**목적**: 세션에서 원하는 메시지만 체크박스로 골라, 선택된 것만 추려 CSS가 인라인된 **독립 실행 HTML 파일**로 내보내기. (예: Q&A 발췌본을 팀에 공유)

### 동작 (북마크 패널과 동일한 UX)

- 우측 사이드바 `☑️` 버튼 → **선택 패널**(`#export-panel`)이 오른쪽에서 슬라이드 인 + 선택 모드 ON → 각 메시지 헤더 좌측에 체크박스 표시
- 체크박스 체크 = **표시만** (초록 테두리 `msg-selected` + 패널에 짧은 미리보기 항목 추가 + 카운트 badge 갱신). **추출 안 함**
- 패널 내장 컨트롤: **전체 선택** / **선택 해제** / **📤 HTML로 내보내기** (버튼은 패널 안에만, 플로팅 버튼은 `☑️` 하나로 축소)
- 패널 리스트: 선택된 각 메시지를 `라벨(🤖 Assistant 등) + 60자 미리보기`로 표시. 항목 클릭 → 해당 메시지로 스크롤(하이라이트), `✕` → 선택 해제
- `📤` 클릭 시에만 HTML 다운로드 (`exported-messages-{timestamp}.html`)
- 좌측 가장자리 드래그로 패널 너비 조절 (localStorage `ccl:export:panel-width`)
- 북마크 패널과 도킹 위치(`right:60px`)가 같아, 선택 패널을 열면 북마크 패널은 자동으로 닫힘
- SSE로 추가된 메시지에도 체크박스 자동 부착 (`window.addSelectionCheckboxes` 재호출)

> **설계 결정 1 (2단계 분리)**: 체크는 마킹만 하고, 실제 추출은 반드시 `📤` 클릭이라는 별도 행위로 트리거. 체크 즉시 추출은 성급하다는 판단.
>
> **설계 결정 2 (패널 방식)**: 초기엔 선택 모드에서 보조 플로팅 버튼(전체선택/해제/내보내기)이 추가로 뜨는 방식이었으나, 사이드바가 번잡해져 북마크 패널처럼 **창 하나에 모든 컨트롤 + 선택 목록**을 담는 방식으로 재설계.

### 내보내기 산출물

- 페이지의 모든 `<style>` 태그를 수집해 `<head>`에 인라인 → **파일 하나로 완결** (외부 CSS 불필요)
- 클론에서 제거: `.msg-select-checkbox`, `.bookmark-pin`, `.fold-bar` (UI 전용 요소)
- fold로 `display:none` 처리된 요소는 표시 복원, `<details>`는 `open` 처리 → 접힌 내용도 다 보이게
- DOM 순서(`:checked` 순회) 유지 → 대화 순서 보존. 자식 메시지는 형제 div라 부모 선택 시 중복 없음

### 수정 파일 (4개)

#### 29-1. `claude_code_log/html/templates/components/export_styles.css` (신규)

체크박스(`.msg-select-checkbox`, `body.selection-mode`에서만 표시), 선택 하이라이트(`.message.msg-selected`), 토글 버튼 카운트 badge(`.sel-count-badge`), **선택 패널**(`#export-panel` — `#bookmark-panel` 스타일 미러링: 헤더/액션 버튼/리스트 항목/resize 핸들).

#### 29-2. `claude_code_log/html/templates/components/message_export.html` (신규)

체크박스 주입(`window.addSelectionCheckboxes`, 멱등), 패널 open/close(`body.selection-mode` 토글 + 북마크 패널 닫기), `refreshPanel()`(선택 항목 라벨/미리보기 렌더 + 배지), `buildExportDoc()`(CSS 수집 + 클론 정리 + `<details>` open), `exportSelected()`(Blob 다운로드), `selectAllVisible()`/`clearSelection()`, resize 핸들. 체크박스 `change`는 이벤트 위임으로 하이라이트 + 패널 갱신.

#### 29-3. `claude_code_log/html/templates/transcript.html`

- `<style>`에 `{% include 'components/export_styles.css' %}` 추가
- `#floating-buttons`에 `☑️`(+`#selCountBadge`) 버튼 **하나만** 추가
- `#bookmark-panel` 다음에 `#export-panel` 마크업 추가 (헤더 + 전체선택/해제/📤 버튼 + 리스트)
- 검색 스크립트 다음에 `{% include 'components/message_export.html' %}`
- SSE `iframe.onload` 후처리에 `window.addSelectionCheckboxes()` 호출 추가

#### 29-4. `claude_code_log/html/templates/components/global_styles.css`

`.floating-btn` order 목록에 `☑️`(`.toggle-selection`) 편입, 전체 order 재정렬(1~10). (기존에 order 없던 `.expand-collapse-all`도 이때 order 5로 편입)

> **순수 클라이언트 사이드**: Python/서버 변경 없음. 브라우저 `Blob` + `URL.createObjectURL`로 다운로드.

---

## 30. 대시보드에 원본 JSONL 디렉토리 경로 표시 + 복사 버튼

**목적**: 대시보드에서 실제 파일 위치를 바로 확인·복사할 수 있게 하기. 파일 탐색기에 붙여넣어서 원본 JSONL 을 열람하거나 백업할 때 유용.

**범위**: 프로젝트 디렉토리 경로 → 이후 **세션별 JSONL / HTML 파일 경로**까지 확장했다([아래](#확장--세션별-jsonl--html-경로-session-navigation)).

### 배경

기존 대시보드는 프로젝트 이름 (`c--Users-User-Desktop-kyochon-prj`) 만 표시. 실제 JSONL이 어디 있는지 알려면 사용자가 `~/.claude/projects/<프로젝트명>/` 를 직접 계산해서 파일 탐색기에 붙여넣어야 했음. 원본 파일 접근성이 낮았음.

### 동작

**두 곳에 표시**:

1. **`summary-stats` 아래**: 모든 프로젝트의 공통 부모 경로 한 줄
   ```
   📂 All JSONL files under: C:\Users\User\.claude\projects\  [📋]
   ```

2. **각 `project-card`의 프로젝트 이름 밑**: 해당 프로젝트의 절대 경로 (회색 작은 monospace)
   ```
   📁 kyochon-prj  (← open combined transcript)
      C:\Users\User\.claude\projects\c--Users-User-Desktop-kyochon-prj  [📋]
   ```

**복사 버튼 (📋)**:
- 클릭 시 `navigator.clipboard.writeText()` 로 경로를 클립보드에 복사
- 성공 시 버튼이 `✓` (초록색 배경) 로 1.2초 바뀌었다 원상 복귀
- Clipboard API 차단 환경 (HTTP + non-localhost 등) 에서는 hidden `<textarea>` + `document.execCommand('copy')` 로 fallback

### 하드코딩 없음 — 완전한 런타임 파생

경로는 100% 실행 시점에 결정됨. 다른 컴퓨터/OS 에서도 그 환경의 실제 경로가 자동 반영됨.

**데이터 흐름**:
1. CLI 진입점에서 `projects_dir = Path.home() / ".claude" / "projects"` (사용자 홈 기준)
2. `converter.py` 가 `projects_path.iterdir()` 로 실제 디렉토리 순회
3. 각 project_summary에 `"path": project_dir` (실제 `Path` 객체) 저장
4. `TemplateProject.jsonl_dir = str(project_data["path"])` — 런타임 값을 문자열 변환

**OS별 자동 대응** (`Path` 가 알아서 처리):
| OS | 표시 예시 |
|---|---|
| Windows | `C:\Users\User\.claude\projects\c--Users-User-Desktop-kyochon-prj` |
| macOS | `/Users/john/.claude/projects/-Users-john-Desktop-my-proj` |
| Linux | `/home/alice/.claude/projects/-home-alice-work-repo` |

### 수정 파일 (3개)

프로젝트 단위 경로 표시까지의 변경. 세션 단위 확장은 [아래](#확장--세션별-jsonl--html-경로-session-navigation)에서
같은 3개 파일을 다시 손댄다 (30-4 ~ 30-6).

#### 30-1. `claude_code_log/renderer.py`

`TemplateProject` 에 프로젝트별 절대 경로 필드 추가:

```python
def __init__(self, project_data: dict[str, Any]):
    ...
    # 원본 JSONL 파일들이 저장된 절대 경로 (index.html 카드 표시 + 복사 버튼용)
    self.jsonl_dir = str(project_data["path"])
    ...
```

`TemplateSummary` 에 모든 프로젝트의 공통 부모 경로 필드 추가:

```python
def __init__(self, project_summaries: list[dict[str, Any]]):
    ...
    # 모든 프로젝트 디렉토리의 공통 부모 (~/.claude/projects/)
    if project_summaries:
        self.jsonl_root = str(project_summaries[0]["path"].parent)
    else:
        self.jsonl_root = ""
```

> `project_data["path"]` 는 이미 `converter.py` 에서 `Path` 객체로 저장하고 있으므로 (line 1954, 2069) 별도 데이터 흐름 변경 불필요.

#### 30-2. `claude_code_log/html/templates/index.html`

**summary-stats 안** — `<div class='summary-stats'>` 닫힌 직후에:

```jinja
{% if summary.jsonl_root %}
<div class='summary-jsonl-root'>
    📂 All JSONL files under:
    <code class='jsonl-path'>{{ summary.jsonl_root }}</code>
    <button class='jsonl-path-copy' type='button' title='경로 복사' data-copy='{{ summary.jsonl_root }}'>📋</button>
</div>
{% endif %}
```

**project-card 안** — `<div class='project-name'>` 닫힌 직후에:

```jinja
{% if project.jsonl_dir %}
<div class='project-jsonl-dir'>
    <code class='jsonl-path'>{{ project.jsonl_dir }}</code>
    <button class='jsonl-path-copy' type='button' title='경로 복사' data-copy='{{ project.jsonl_dir }}'>📋</button>
</div>
{% endif %}
```

**하단 `<script>` 안 DOMContentLoaded 리스너**에 복사 버튼 이벤트 위임 핸들러 추가:

```javascript
// JSONL 경로 복사 버튼 (project-card + summary-stats 공용) — 이벤트 위임
document.body.addEventListener('click', function(e) {
    var btn = e.target.closest('.jsonl-path-copy');
    if (!btn) return;
    var path = btn.getAttribute('data-copy') || '';
    if (!path) return;

    var showCopied = function() {
        var original = btn.textContent;
        btn.classList.add('copied');
        btn.textContent = '✓';
        setTimeout(function() {
            btn.classList.remove('copied');
            btn.textContent = original;
        }, 1200);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(path).then(showCopied).catch(function() {
            fallbackCopy(path, showCopied);
        });
    } else {
        fallbackCopy(path, showCopied);
    }
});

function fallbackCopy(text, onSuccess) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    try {
        if (document.execCommand('copy')) onSuccess();
    } catch (err) {}
    document.body.removeChild(ta);
}
```

#### 30-3. `claude_code_log/html/templates/components/project_card_styles.css`

`.project-jsonl-dir`, `.summary-jsonl-root`, `.jsonl-path`, `.jsonl-path-copy` (+ `:hover`, `.copied`) 스타일 추가. 회색 작은 monospace 텍스트 + 은은한 복사 버튼:

```css
/* 원본 JSONL 디렉토리 경로 표시 (project-name 밑 회색 작은 줄) */
.project-jsonl-dir {
    font-size: 0.75em;
    color: #888;
    margin: -6px 0 10px 0;
    display: flex;
    align-items: center;
    gap: 6px;
    word-break: break-all;
}
.project-jsonl-dir .jsonl-path {
    background: transparent;
    padding: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #666;
}
.jsonl-path-copy {
    background: none;
    border: 1px solid #00000022;
    border-radius: 4px;
    padding: 2px 6px;
    cursor: pointer;
    font-size: 0.9em;
    color: #666;
    flex-shrink: 0;
    line-height: 1;
    transition: background 0.15s ease, border-color 0.15s ease;
}
.jsonl-path-copy:hover {
    background: #00000011;
    border-color: #00000044;
}
.jsonl-path-copy.copied {
    background: #22c55e33;
    border-color: #22c55e;
    color: #16a34a;
}
/* summary-stats 아래 JSONL 루트 경로 표시 */
.summary-jsonl-root {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid #00000011;
    font-size: 0.85em;
    color: #666;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}
.summary-jsonl-root .jsonl-path {
    background: #00000008;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #444;
}
```

### 핵심 설계

| 항목 | 결정 | 이유 |
|---|---|---|
| 표시 위치 | project-card = 주 정보, summary-stats = 부가 정보 | 프로젝트별 경로가 다르므로 카드가 주. summary는 부모 뿌리 안내 |
| 복사 방식 | Clipboard API + execCommand fallback | HTTPS/localhost 에서는 Clipboard API 우선. 오래된 브라우저/차단 환경도 지원 |
| 복사 성공 피드백 | 아이콘 잠시 변경 (✓ + 초록) | 별도 toast/dialog 없이 은은한 표시 |
| 이벤트 등록 | body 이벤트 위임 | project-card N개 + summary 1개에 리스너 하나로 처리. SSE로 카드가 재렌더링돼도 자동 동작 |
| 하드코딩 | 없음 — 모두 `Path` 객체 → `str()` | 다른 컴퓨터/OS 어디서 실행해도 그 환경 실제 경로 자동 반영 |
| 경로 표기 | Windows `\`, macOS/Linux `/` | `str(Path)` 가 OS별 구분자 자동 사용 |

### 확장 — 세션별 JSONL / HTML 경로 (Session Navigation)

프로젝트 **디렉토리** 경로만으로는 특정 대화의 파일을 찾으려면 여전히 세션 ID 를 조합해야
했다. Session Navigation 의 각 세션 항목 아래에 **파일 두 개의 절대 경로**를 직접 표시한다.

```
💬 회사 프로젝트 코드 구조 및 스택 분석  #dab3147c
   2026-08-05 09:16 · 1075 messages
   JSONL  C:\Users\user\.claude\projects\c--kyo-prj-chicken-proj2\dab3147c-….jsonl        [📋]
   HTML   C:\Users\user\.claude\projects\c--kyo-prj-chicken-proj2\session-dab3147c-….html [📋]
```

#### 30-4. `claude_code_log/renderer.py` — 세션 dict 에 경로 주입

`TemplateProject` 가 이미 `jsonl_dir` 을 알고 있으므로 파일명만 붙이면 된다.
프로젝트 경로와 마찬가지로 **런타임 파생**이라 하드코딩이 없다.

```python
def _attach_session_paths(self, sessions, with_jsonl: bool) -> None:
    base = Path(self.jsonl_dir)
    for session in sessions:
        session_id = session.get("id")
        if not session_id:
            continue
        session["html_path"] = str(base / f"session-{session_id}.html")
        if with_jsonl:
            session["jsonl_path"] = str(base / f"{session_id}.jsonl")

self._attach_session_paths(self.sessions, with_jsonl=True)
self._attach_session_paths(self.old_sessions, with_jsonl=False)
```

**`old_sessions` 는 `with_jsonl=False`** — JSONL 이 이미 지워지고 HTML 만 남은 세션
([23번](#23-old-sessions--jsonl-삭제-후-html만-잔존하는-세션-조회))이라 없는 파일 경로를
보여주면 안 된다.

#### 30-5. `components/session_nav.html` — 표시

```jinja
{% if session.jsonl_path %}
<div class='session-file-path'>
    <span class='session-file-label'>JSONL</span>
    <code class='jsonl-path'>{{ session.jsonl_path }}</code>
    <button class='jsonl-path-copy' type='button' data-copy='{{ session.jsonl_path }}'>📋</button>
</div>
{% endif %}
```

> **복사 기능은 새로 만들지 않았다.** `index.html` 의 body 이벤트 위임 핸들러가
> `.jsonl-path-copy` 를 잡으므로, 같은 클래스와 `data-copy` 만 붙이면 클립보드 복사와
> `✓` 피드백이 그대로 동작한다. 위임을 쓴 원래 설계 덕분에 얻은 것.

#### 30-6. `components/project_card_styles.css` — 스타일

경로는 복사해서 쓰라고 있는 것이므로 **줄이거나 감추지 않는다.** 좁으면 그 줄만 가로
스크롤한다 (`overflow-x: auto` + `white-space: nowrap`). 페이지 전체가 가로로 밀리지
않는지 확인했다.

#### 검증

`index.html` 에 렌더된 경로가 **실제 파일을 가리키는지** 전수 확인했다.

| 항목 | 결과 |
|---|---|
| 경로 31건이 실제 존재 | 31/31 |
| 활성 세션 (JSONL + HTML) | 5개 |
| archived 세션 (HTML 만) | 21개 |
| 복사 버튼 — 클립보드 내용 일치 | PASS |
| 복사 피드백 (`✓` + 초록) | PASS |
| 페이지 가로 스크롤 없음 | PASS |

복사 검증은 Playwright 로 실제 클릭 후 `navigator.clipboard.readText()` 와 표시된 경로를
대조했다. 세션 목록이 `<details>` 안에 있으므로 `el.open = true` 로 펼친 뒤 확인해야 한다.

---

## 31. JSONL 자동 삭제 막기 (환경 설정)

**목적**: Claude Code가 30일 지난 JSONL을 자동 삭제해 세션이 통째로 사라지는 것을 막음.
23번(Old Sessions)이 삭제된 뒤의 사후 대책이라면, 이건 애초에 안 지워지게 하는 사전 대책.

> 이 프로젝트 코드 수정이 아니라 **Claude Code 자체 설정**이다. 새 컴퓨터마다 따로 해야 한다.

`%USERPROFILE%\.claude\settings.json` 에 한 줄 추가:

```json
{
  "cleanupPeriodDays": 3650
}
```

기본값 30일 → 3650일(~10년). 최소 1이며 `0`/끄기는 불가.
앞 줄 끝 **쉼표를 빠뜨리면 JSON이 깨져 해당 파일 설정이 통째로 무시**되므로 주의.

### 2단계 방어 — 백업 자동화 (선택)

위 설정 **자체가 사라지는 경우**(Claude Code 재설치, 설정 초기화)를 대비한 백업.
`C:\claude-backup\backup-jsonl.bat` + Windows 예약 작업(로그온 시 실행) 구성.

- **핵심 원칙**: 단방향 누적 복사 — 원본에서 사라져도 백업에서는 안 지움
- **`/MIR`, `/PURGE` 절대 금지** — 목적과 정반대로 동작함
- 상주 프로세스 없음. 실행 시간 1초 미만

**상세: [JSONL_RETENTION.md](JSONL_RETENTION.md)**

---

## 32. 세션 자동 제목 (ai-title) 표시

**목적**: VSCode 의 Claude Code 가 대화를 요약해 자동 생성하는 제목을 대시보드 세션 목록에 표시.

### 배경 — 제목이 첫 질문으로 나오던 문제

대시보드 세션 제목의 우선순위는 `custom_title → summary → 첫 질문` 이었는데, 두 값이 모두 비어
첫 질문이 그대로 제목이 되고 있었다.

| 값 | 출처 | 이 프로젝트 세션에서 |
|---|---|---|
| `custom_title` | 대시보드에서 직접 수정하거나 Ctrl+R 로 이름 변경 | 수정한 세션만 |
| `summary` | `/compact` 로 대화를 압축할 때 생기는 옛 형식 | **0건** |
| `ai-title` | Claude Code 가 자동 생성 | **세션마다 존재** |

`ai-title` 은 JSONL 에 실제로 들어있었는데 `converter.py` 가 **의도적으로 버리고 있었다**.

```python
elif entry_type in {
    "file-history-snapshot", "progress", "last-prompt", "attachment",
    "ai-title",          # ← 여기서 스킵되고 있었다
}:
    pass
```

```json
{"type": "ai-title", "aiTitle": "CSS selector :not(.slash-command) 추가 이유 확인", "sessionId": "ba1ea00b-..."}
```

`custom-title` 과 구조가 같아서 `sessionId` 를 직접 갖는다 — `summary` 처럼 `leafUuid` 매핑이 필요 없다.
세션이 길어지며 여러 번 기록되므로 **마지막 값이 최신**이다 (`custom_titles` 와 동일한 규칙).

### 설계 — `summary` 재활용 대신 별도 컬럼

두 방법을 놓고 골랐다.

| | A: `summary` 자리에 얹기 | B: `ai_title` 컬럼 추가 |
|---|---|---|
| 수정 범위 | 2개 파일 | 6개 파일 + 마이그레이션 |
| DB 스키마 | 변경 없음 | `ALTER TABLE` 한 줄 |
| `/compact` 를 쓰기 시작하면 | 진짜 요약과 같은 칸을 두고 충돌 | 문제없음 |

**B 를 택했다.** 커밋 `0ba8e22`(`custom_title` 도입)가 정확히 같은 7단계를 이미 밟았고,
변경 규모도 그때(+78/-6)와 비슷한 수준(+66/-13)이다. 새 패턴이 아니라 기존 패턴을 따른 것.

### 수정 파일 (7개 + 마이그레이션)

값이 지나는 길목을 순서대로 손봐야 한다.

```
JSONL 파싱 → 모델 → 수집 → DB 컬럼 → DB 읽기 → 화면 전달 → 템플릿
```

`server.py` 는 이 흐름을 타지 않고 JSONL 을 직접 읽는 별도 경로다
([세션 페이지에도 같은 우선순위](#세션-페이지에도-같은-우선순위를-적용-후속) 참고).

#### 32-1. `claude_code_log/models.py`

```python
class AiTitleTranscriptEntry(BaseModel):
    type: Literal["ai-title"]
    aiTitle: str
    sessionId: str
```

`TranscriptEntry` union 에도 추가한다.

#### 32-2. `claude_code_log/factories/transcript_factory.py`

```python
ENTRY_CREATORS = {
    ...,
    "ai-title": lambda data: AiTitleTranscriptEntry.model_validate(data),
}
```

#### 32-3. `claude_code_log/migrations/005_ai_title.sql` (신규)

```sql
ALTER TABLE sessions ADD COLUMN ai_title TEXT;
```

#### 32-4. `claude_code_log/cache.py`

`SessionCacheData.ai_title` 필드 + INSERT 컬럼/값 + `SELECT *` 결과 매핑 2곳.
`row["ai_title"] if "ai_title" in row.keys() else None` 형태로 옛 DB 도 견딘다.

#### 32-5. `claude_code_log/converter.py`

- **파싱 허용 목록에 `"ai-title"` 추가** (스킵 목록에서 빼는 것만으로는 부족 — 아래 함정 참고)
- 날짜 필터에서 제외 (timestamp 가 없는 항목)
- `ai_titles` 수집 2곳 + 캐시/화면 전달 3곳

#### 32-6. `claude_code_log/renderer.py`

렌더 대상에서 제외 2곳. 빼먹으면 아래 함정 ②가 터진다.

#### 32-7. `components/session_nav.html`

```jinja
{# 제목 우선순위: 직접 수정 > Claude Code 자동 생성 > 압축 요약 > 첫 질문 #}
{% if session.custom_title %} ... {% elif session.ai_title %} ... {% elif session.summary %} ...
```

### 세션 페이지에도 같은 우선순위를 적용 (후속)

위까지만 하면 **대시보드 목록에만** 반영된다. 개별 세션 페이지(`session-*.html`)의
`<h1 id="title">` 과 브라우저 탭 제목은 별도 경로라서 그대로 첫 질문이나 세션 ID 가 나온다.

**제목을 만드는 경로가 세 군데다.** 하나만 고치면 나머지가 어긋난다.

| 경로 | 파일 | 언제 쓰이나 |
|---|---|---|
| 대시보드 목록 | `session_nav.html` | `index.html` 의 세션 목록 |
| 정적 세션 HTML | `converter.py` | `claude-code-log` 로 파일 생성할 때 |
| **동적 세션 렌더** | `server.py` | **브라우저가 `localhost:5678` 로 볼 때** |

#### `converter.py` — 정적 생성

`summary` 만 보고 있어서 요즘 세션(=`summary` 가 없는)은 전부 폴백으로 떨어졌다.

```python
chosen_title = (
    session_cache.custom_title
    or session_cache.ai_title
    or session_cache.summary
)
if chosen_title:
    session_title = f"{project_title}: {chosen_title}"
else:
    ...  # 첫 질문 → 그것도 없으면 f"Session {session_id[:8]}"
```

#### `server.py` — 동적 렌더 (실제로 브라우저가 받는 것)

`_get_custom_title()` 만 읽어서 넘기고 있었다. 직접 수정한 적 없는 세션은 `None` 이 되고,
`generate_session()` 이 곧바로 `f"Session {session_id[:8]}"` — **해시**로 떨어진다.

```python
def _get_title_entry(jsonl_file, session_id, entry_type, field): ...  # 공통 헬퍼
def _get_custom_title(...):  # "custom-title" / "customTitle"
def _get_ai_title(...):      # "ai-title"     / "aiTitle"
def _get_session_title(...): return _get_custom_title(...) or _get_ai_title(...)
```

두 곳에 적용한다 — `serve_file`(브라우저 직접 접근)과 `/api/sessions/<id>/render`.

> ⚠️ **`localhost:5678` 의 세션 페이지는 정적 파일이 아니다.** `serve_file` 이 요청마다
> JSONL 을 다시 읽어 렌더한다. 정적 `session-*.html` 을 열어 확인하면 고쳐진 것처럼
> 보이지만 브라우저에는 반영되지 않는다. **검증은 반드시 서버 응답으로 해야 한다.**
>
> ```python
> app = create_app(PROJECTS)
> html = app.test_client().get(f"/{proj}/session-{sid}.html").get_data(as_text=True)
> re.search(r'<h1 id="title">(.*?)</h1>', html, re.S)
> ```

#### 캐시된 HTML 이 갱신되지 않는 경우

정적 경로에서 세션 HTML 이 JSONL 보다 오래됐는데도 다시 만들어지지 않는 일이 있었다.

```
JSONL   15:57:03   ← 제목 수정으로 갱신
HTML    15:42:24   ← 더 오래됐는데 그대로
```

해당 HTML 을 지우고 재생성하면 반영된다. 캐시 신선도 판정에 빈틈이 있는 것으로 보이나
원인은 아직 확인하지 않았다.

### 함정 2가지

둘 다 실제로 돌려보고서야 드러났다.

**① 허용 목록과 스킵 목록이 따로 있다**

`converter.py` 에는 "파싱할 타입" 목록과 "조용히 버릴 타입" 목록이 **각각** 있다.
스킵 목록에서 `ai-title` 을 빼도 허용 목록에 없으면 여전히 파싱되지 않는다.
(빼기만 했을 때 `AiTitle 파싱됨: 0` 이었다.)

**② 새 엔트리 타입은 렌더러도 알아야 한다**

```
AttributeError: 'AiTitleTranscriptEntry' object has no attribute 'message'
```

`renderer.py` 의 `_filter_messages()` 가 모르는 타입을 만나 터졌고, **대시보드가 통째로 비었다.**
`CustomTitleTranscriptEntry` 를 걸러내던 2곳에 함께 넣어야 한다.

> 새 `TranscriptEntry` 타입을 추가할 때는 `grep -rn "CustomTitleTranscriptEntry" claude_code_log/`
> 로 기존 타입이 다뤄지는 모든 지점을 훑는 것이 안전하다.

### 결과

대시보드 목록, 정적 세션 HTML, 서버가 렌더하는 세션 페이지 셋 다 같은 제목을 쓴다.
`<h1 id="title">` 과 브라우저 탭 제목도 포함된다.

```
dab3147c  →  회사 프로젝트 코드 구조 및 스택 분석          (이전: Session dab3147c)
23a08897  →  VSCode Claude 확장 프로그램 알림 설정 복구    (이전: 첫 질문)
7caad578  →  C:\a 폴더 내용 확인 및 설치 내역 파악 - fuz사 프린트   (custom_title 우선)
ba1ea00b  →  (직접 수정한 제목 유지 — custom_title 우선)
```

### 캐시 재생성이 필요하다

마이그레이션은 기존 DB 에 컬럼만 추가하므로 값은 비어 있다. `ai_title` 을 채우려면 JSONL 을
다시 읽어야 한다.

> ⚠️ **캐시 DB 를 지워서 재생성하면 안 된다.** archived 프로젝트([23-6](#23-6-확장--프로젝트-전체가-archived-인-경우))는
> 캐시에만 기록돼 있어서, 지우면 대시보드에서 사라진다. JSONL 이 없어 재스캔으로도 복구되지 않는다.
> 실제로 이 작업 중에 그렇게 잃었다.

---

## 공통 인프라

### `_find_session_jsonl()` — 세션 JSONL 파일 탐색

`server.py` 상단. 삭제/수정/스트리밍/렌더 6곳에서 공용이라, 여기가 틀리면 그 6곳이 함께
틀어진다. 실제로 두 번 사고가 났고 그때마다 한 겹씩 늘었다.

```python
def _find_session_jsonl(projects_dir, session_id, prefer_dir=None) -> Optional[Path]:
    # 0차: 요청 URL 이 프로젝트를 알려준 경우 그 폴더를 먼저 본다
    if prefer_dir is not None:
        candidate = prefer_dir / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate

    # 1차: 파일명으로 검색
    named = sorted(projects_dir.rglob(f"{session_id}.jsonl"))
    if len(named) == 1:
        return named[0]
    if named:
        # 같은 이름이 여러 폴더에 — 빈 껍데기를 집지 않도록 내용을 본다
        for jsonl_file in named:
            if _has_conversation(jsonl_file):
                return jsonl_file
        return max(named, key=lambda p: p.stat().st_size)

    # 2차: sessionId 필드가 실제로 일치하는 파일 (문자열 포함이 아니라 필드 비교)
    ...
```

#### 세 겹이 각각 다른 사고를 막는다

| 겹 | 막는 것 | 유래 |
|---|---|---|
| 0차 `prefer_dir` | 같은 세션이 두 폴더에 있을 때 엉뚱한 쪽 선택 | 아래 "복사해서 이어가기" |
| 1차 내용 확인 | Claude Code 가 만든 200바이트 껍데기 선택 | 아래 "복사해서 이어가기" |
| 2차 필드 비교 | 대화 본문에 ID 를 언급했을 뿐인 파일 선택 | [3번 사고](#사고--엉뚱한-세션이-삭제된-문제) |

### 시나리오 — JSONL 을 복사해 다른 폴더에서 대화 이어가기

Claude Code 는 **현재 작업 디렉토리를 슬러그로 바꾼 폴더**에 세션을 저장한다
(`:` 와 `\` 를 `-` 로 치환. `c:\kyo-prj\chicken-proj2` → `c--kyo-prj-chicken-proj2`).

그래서 다른 프로젝트 폴더에서 같은 대화를 이어가려면 JSONL 을 그쪽 슬러그 폴더로
복사하면 된다. 실제로 동작한다 — 기억이 그대로 이어지는 것을 확인했다.

```powershell
$src = "...\projects\c--kyo-prj-chicken-proj2"
$dst = "...\projects\C--kyo-prj-kyochon"
Copy-Item "$src\<세션ID>.jsonl" $dst              # 대화 본문
Copy-Item "$src\<세션ID>"       $dst -Recurse     # tool-results (JSONL 밖의 대용량 출력)
Copy-Item "$src\memory"         $dst -Recurse     # 프로젝트 메모리 (원하면)
```

> `<세션ID>.jsonl` 파일 옆에 **확장자 없는 같은 이름의 폴더**가 따로 있다. 그 안의
> `tool-results/` 에 JSONL 에 담기엔 큰 출력물이 빠져 있으므로 함께 옮겨야 한다.

#### 그 결과 대시보드가 깨진다 — 두 단계로

**① 같은 이름의 JSONL 이 두 폴더에 생긴다**

`rglob` 은 알파벳 순으로 훑고 첫 번째를 반환하므로, 어느 쪽이 걸릴지는 폴더명 순서가
정한다. 새 대화가 쌓이는 쪽이 뒤에 오면 **어떤 URL 로 들어가도 옛 내용만** 보인다.

```
c--kyo-prj-chicken-proj2/<세션ID>.jsonl   48.5 MB   ← 먼저 걸림 (옛 대화)
C--kyo-prj-kyochon/<세션ID>.jsonl         49.2 MB   ← 새 대화. 안 보임
```

URL 의 프로젝트 폴더는 무시되므로 `/C--kyo-prj-kyochon/session-….html` 로 들어가도
같은 결과다.

**② 원본을 치워도 껍데기가 되살아난다**

옛 폴더의 JSONL 을 옮겨서 해결했는데, **그 프로젝트를 VSCode 로 열었다 닫자 다시 생겼다.**

```json
{"type":"ai-title","aiTitle":"회사 프로젝트 코드 구조 및 스택 분석","sessionId":"dab3147c-…"}
{"type":"mode","mode":"normal","sessionId":"dab3147c-…"}
```

218바이트. 제목과 모드만 있고 **대화가 하나도 없다.** Claude Code 는 폴더를 여는 것만으로
이 껍데기를 쓴다. 알파벳 순으로 먼저 오니 이번에도 이겼고, 화면에는 **제목만 뜨고 본문이
텅 빈** 페이지가 나왔다.

> 증상이 "아무것도 안 보인다" 라서 렌더링 실패로 오해하기 쉽다. 실제로는 **올바른 파일을
> 렌더링하고 있지 않았다.** 서버 응답 크기가 27 MB 인지 수십 KB 인지 보면 바로 갈린다.

#### 수정 — URL 우선 + 내용 확인

두 가지가 필요하다. 하나만으로는 부족하다.

**`prefer_dir` (URL 우선)** — 정확하지만 URL 을 아는 곳에서만 쓸 수 있다.
6개 호출부 중 `serve_file` 하나뿐이고, 나머지 5개(`/api/sessions/<id>/…`)는 세션 ID 만 받는다.

```python
session_match = re.match(r"(.+)/session-([a-f0-9-]+)\.html$", filepath)
prefer_dir = (projects_dir / session_match.group(1)).resolve()
if not str(prefer_dir).startswith(str(projects_dir.resolve())):
    prefer_dir = None          # 경로 탈출 시도는 무시
jsonl_file = _find_session_jsonl(projects_dir, session_id, prefer_dir)
```

**`_has_conversation()` (내용 확인)** — 나머지 5곳을 위한 그물.

```python
def _has_conversation(jsonl_file: Path, probe_lines: int = 400) -> bool:
    """앞부분만 읽어 user/assistant 항목이 있는지 본다."""
```

파일 **앞 400줄만** 읽는다. 진짜 대화는 앞쪽에 user/assistant 가 나오고, 이 파일들은 수십
MB 라 전부 읽으면 안 된다.

#### 검증 — 껍데기를 실제로 만들어 확인

| 케이스 | 결과 |
|---|---|
| `prefer_dir` 없음 (API 5곳) | 대화가 있는 쪽 선택 |
| `prefer_dir` = 껍데기 폴더 | 지정을 존중 |
| `/C--kyo-prj-kyochon/…` | 대화 있음, message 2334개 |
| `/c--kyo-prj-chicken-proj2/…` | 껍데기 그대로 (URL 존중) |

#### 남는 함정

- **두 폴더에서 각각 대화를 이어가면 내용이 갈라진다.** 옛 프로젝트 창은 닫는 편이 안전하다.
- JSONL 안에 옛 절대경로가 그대로 박혀 있다(한 세션에서 1,846회). 기억은 이어지지만 그
  경로로 파일을 읽으려 하면 실패하므로, 재개 후 새 경로를 한 줄 알려주는 게 좋다.
- `~/.claude/history.jsonl`(↑ 키 프롬프트 이력)은 프로젝트 경로별로 기록되어 따라오지 않는다.

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
| (pending) | 빈 프롬프트 실시간 모델 배지 + watchdog settings.json 감시 + `_DEFAULT_MODEL`(/model default 지원) + JSONL user 엔트리 /model 스캔(`_MODEL_CMD_RE`) + JSONL-first 우선순위 + 미인식 타입 경고 제거 |
| (pending) | User 말풍선 간 이동 버튼 ▲▼ — 우측 사이드바에 추가, ±50px 임계값으로 연속 클릭 시 재탐지 버그 방지 |
| (pending) | 빈 말풍선 blur 복원 — 내용 없이 외부 클릭 시 `empty-prompt` 상태로 복원, `{ once: true }` 제거로 재클릭 가능 |
| `09976ae` | 질문 말풍선 순차 번호 + 북마크 기능 — 각 user 말풍선 헤더에 `📌 #N` 표시, 사선↔직각(-30deg) 토글로 북마크, 우측 슬라이드 패널(280px)에 두 줄(번호·시각 / 미리보기 60자) 목록, 클릭 시 스크롤 + 펄스, localStorage(`ccl:bookmarks:{sessionId}`) 영구 저장. 미리보기는 `.user-text`만(IDE 자동 컨텍스트 제외) |
| `0087c13` | Old Sessions — `_scan_old_sessions()` 추가, `TemplateProject.old_sessions`, 인덱스 Old Sessions 토글, `serve_file` content-only 매치 시 정적 HTML 서빙 |
| `32bfafc` | 단일 세션 페이지네이션 + 북마크 미리보기 IDE 알림 제외 (**나중에 원복됨** — 무한로딩 문제와 무관함이 확인되어 페이지네이션은 제거, 북마크 IDE 알림 필터는 함수 자체와 함께 제거) |
| `7e6f0ce` | SSE 업데이트 시 입력 중인 textarea 보존 — 프롬프트 element 재생성 폐기, sticky-bottom padding 재계산만 inline으로 분리 (`initEmptyPrompt` 미호출) |
| `da3fca9` | 빈 프롬프트 입력 지우기 버튼 — 헤더에 🗑️ 추가 (minimize 왼쪽), 클릭 시 textarea 비우기 + height 리셋 + 포커스 유지. CSS는 `.prompt-minimize-btn` 셀렉터 그룹화로 공유 |
| `98d57ae` | 🗑️ 지우기 버튼 Ctrl+Z 복원 지원 — `textarea.value = ''` 대신 `document.execCommand('selectAll' → 'delete')` 사용으로 native undo stack에 등록 → 키보드 Ctrl+Z 로 지운 내용 복원 가능. execCommand 실패 시 직접 비우기 fallback |
| `4457889` | 검색 단축키 비활성화 — `handleKeyboardShortcuts`의 Ctrl+F / Cmd+F / F3 가로채기 블록 주석 처리 → 브라우저 기본 찾기 동작. 우측 🔍 플로팅 버튼은 그대로 유지 (재활성화 위해 코드 보존) |
| `a7b814f` | 📂 모든 메시지 펼치기/접기 통합 토글 버튼 — `#toggleExpandAll` floating 버튼 + `setInitialFoldState` 전역 노출. fold-bar + `<details>` 두 종류 토글을 한 버튼으로 처리. (**나중에 재설계됨** — 트리 깊이 기반이 잘못된 접근이라 메시지 타입 기반으로 변경) |
| `6800b89` | 대시보드 검색 결과 — 세션 제목/ID/미리보기 표시. `.session-link[data-title]`/`[data-session-id]` 추출 → 같은 줄에 `💬 제목` (좌측) + `#abcd1234` 칩 (우측). flex 레이아웃 + ellipsis. 미리보기 60자 + 검색어 하이라이트 |
| (pending) | 페이지네이션 원복 (`32bfafc` 역방향) — 무한로딩의 진짜 원인이 브라우저 SSE 동시 연결 한도 초과(여러 탭) 였음이 확인됨. 페이지네이션은 무한로딩 해결에 기여하지 않는 부수 기능이므로 제거. renderer.py 헬퍼 4개 + `generate()`/`generate_session()` 시그니처 + server.py `?page=` 파싱 + transcript.html JS 변수/매크로/페이지 분기 + CSS 페이지네이션 블록 모두 제거. CUSTOM_FEATURES.md §26 제거. **단, server.py의 `jsonl_file.stem == session_id` 안전장치는 Old Sessions 기능 유지를 위해 보존**. `pagenation.md`는 향후 재적용 가능성을 위해 워킹트리에 보존 |
| (pending) | 📂 토글 재설계 — 트리 깊이 기반(`setInitialFoldState` 호출) → 메시지 타입 기반(`.tool_use`/`.tool_result` 직접 선택) 으로 변경. 깊이 5에 있던 마지막 Assistant 답변이 사라지던 버그 해결. user/assistant/thinking은 항상 보임. fold-bar/`<details>`는 건드리지 않고 직교성 유지. CUSTOM_FEATURES.md §27 갱신 |
| (pending) | SSE 무한로딩 fix 가이드 문서(`sse-connection-fix.md`) 추가 — 진짜 원인(크롬 6 슬롯 한도)과 두 가지 fix(server.py `direct_passthrough=True` + transcript.html `pagehide` 시 `source.close()`) 적용 가이드. 실 적용은 별도 작업으로 미룸 |
| (pending) | 대시보드에 원본 JSONL 디렉토리 경로 표시 + 복사 버튼 — `TemplateProject.jsonl_dir` + `TemplateSummary.jsonl_root` 노출. summary-stats 아래 부모 경로, 각 project-card 밑에 프로젝트별 절대 경로. 📋 버튼 클릭 시 `navigator.clipboard.writeText()` (fallback: `execCommand('copy')`). 하드코딩 없음 — `Path` 객체 기반이라 다른 컴퓨터/OS 어디서 실행해도 그 환경의 실제 경로 자동 반영 |

---

## 의존성

추가된 외부 의존성:

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `watchdog` | `>=4.0.0` | OS 네이티브 파일 변경 감지 (Windows: ReadDirectoryChangesW, macOS: FSEvents, Linux: inotify). SSE 폴링 2초 → 즉각 반응으로 교체. |

나머지 기능은 모두 기존 의존성(Flask, Jinja2 등)만 사용.
