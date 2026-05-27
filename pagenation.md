# 단일 세션 페이지네이션 구현 가이드

> 이 문서는 작업했던 페이지네이션 코드를 그대로 복원할 수 있도록 정리한 백업본입니다.
> 적용 베이스 커밋: `09976ae` (feat: 질문 말풍선 순차 번호 + 북마크 기능)

---

## 0. 동작 요약

- 단일 세션 HTML을 user 질문 **200개 단위**로 잘라 페이지네이션
- URL: `session-{id}.html` = 마지막 페이지 (기본), `?page=N` = N페이지
- 질문 번호 `#N`은 페이지 오프셋 적용 (페이지 2 → #201부터)
- 북마크 패널은 **전체 세션**의 북마크 표시, 다른 페이지 항목 클릭 시 자동 이동
- SSE 라이브 동기화는 **마지막 페이지에서만** 동작 (옛 페이지엔 `📖 과거 페이지` 표시)
- 4,566 entries 세션 기준 HTML 크기: 13MB → 3.6MB (마지막 페이지)

**페이지 크기 변경**: [claude_code_log/html/renderer.py](claude_code_log/html/renderer.py) 의 `USER_MSGS_PER_PAGE = 200` 한 줄만 수정.

---

## 1. 수정 파일 목록 (4개)

| 파일 | 변경 |
|---|---|
| `claude_code_log/html/renderer.py` | 페이지 분할 헬퍼 + `generate()`/`generate_session()` 파라미터 |
| `claude_code_log/server.py` | `serve_file`에서 `?page=` 쿼리 읽기 |
| `claude_code_log/html/templates/transcript.html` | JS 변수 주입 + nav 매크로 + 북마크 크로스페이지 + SSE 가드 |
| `claude_code_log/html/templates/components/page_nav_styles.css` | 단일 세션 nav + 다른 페이지 북마크 스타일 |

---

## 2. `claude_code_log/html/renderer.py`

### 2-1. 파일 상단에 헬퍼 추가

위치: `from ..utils import format_timestamp` 줄 **바로 다음**, `from .system_formatters import ...` 줄 **직전**.

```python
from ..utils import format_timestamp

# =============================================================================
# 단일 세션 페이지네이션 설정
# =============================================================================
# 한 페이지에 표시할 user 질문 개수. 200개 단위로 자르면 12MB HTML이 ~600KB로 줄어듦.
# ↓↓↓ 페이지당 질문 개수를 바꾸려면 이 숫자만 수정 ↓↓↓
USER_MSGS_PER_PAGE = 200
# ↑↑↑ 페이지당 질문 개수를 바꾸려면 이 숫자만 수정 ↑↑↑


def _is_user_question(msg: "TemplateMessage") -> bool:
    """numberUserMessages() JS 셀렉터 '.message.user:not(.empty-prompt):not(.session-header)'
    와 동일 정의. session-header / live empty-prompt 만 제외하고 모든 user 메시지를 셈."""
    return msg.type == "user" and not msg.is_session_header


def _compute_session_pages(
    template_messages: list[Tuple["TemplateMessage", str, str, str]],
    page_size: int = USER_MSGS_PER_PAGE,
) -> list[Tuple[int, int, int, int]]:
    """user 메시지 개수 기준으로 슬라이스 경계를 계산.

    Returns:
        list of (start_idx, end_idx, first_user_num, last_user_num)
        — template_messages[start_idx:end_idx]이 페이지 콘텐츠.
        — first_user_num/last_user_num은 1-based user 번호 범위.

    경계 규칙:
      - user 메시지 N개씩 그룹 → 페이지마다 user msg 1~200, 201~400 …
      - 각 페이지는 자신의 첫 user 메시지에서 시작
      - 페이지 끝 = 다음 페이지의 첫 user 메시지 직전 (= 이 페이지 마지막 user의
        모든 응답/tool/thinking 포함)
      - 첫 페이지는 그 앞의 session-header 등도 포함
    """
    user_indices = [
        i for i, (msg, _, _, _) in enumerate(template_messages) if _is_user_question(msg)
    ]
    if not user_indices:
        return [(0, len(template_messages), 0, 0)]

    pages: list[Tuple[int, int, int, int]] = []
    total_users = len(user_indices)
    for chunk_start in range(0, total_users, page_size):
        chunk_end = min(chunk_start + page_size, total_users)
        first_user_num = chunk_start + 1
        last_user_num = chunk_end
        start_idx = user_indices[chunk_start]
        if chunk_start == 0:
            start_idx = 0  # 첫 페이지는 헤더 포함
        if chunk_end < total_users:
            end_idx = user_indices[chunk_end]  # 다음 페이지 첫 user 직전까지
        else:
            end_idx = len(template_messages)
        pages.append((start_idx, end_idx, first_user_num, last_user_num))
    return pages


def _build_bookmark_index(
    template_messages: list[Tuple["TemplateMessage", str, str, str]],
    pages: list[Tuple[int, int, int, int]],
) -> list[dict[str, Any]]:
    """모든 user 메시지의 (uuid, n, page, ts, preview) 인덱스 생성 — 북마크 패널이
    다른 페이지의 북마크도 표시/이동할 수 있게 클라이언트에 주입."""
    import re

    # idx → (page_number 1-based, user_n 1-based) 매핑
    idx_to_page_and_n: dict[int, Tuple[int, int]] = {}
    for page_i, (start_idx, end_idx, first_u, _last_u) in enumerate(pages):
        # 이 페이지의 user 메시지들에 번호 부여
        user_n = first_u
        for i in range(start_idx, end_idx):
            msg = template_messages[i][0]
            if _is_user_question(msg):
                idx_to_page_and_n[i] = (page_i + 1, user_n)
                user_n += 1

    # IDE 알림(🤖 The user opened the file..., 📝 selection, diagnostics 등)은
    # 사용자가 작성한 컨텐츠가 아니므로 미리보기에서 제외.
    # 형식: <div class='ide-notification ...'>...</div> (단일 따옴표, 중첩 div 없음)
    ide_notification_re = re.compile(
        r"<div class='ide-notification[^']*'>.*?</div>", re.DOTALL
    )
    tag_re = re.compile(r"<[^>]+>")
    ws_re = re.compile(r"\s+")
    index: list[dict[str, Any]] = []
    for i, (msg, _title, html, ts) in enumerate(template_messages):
        if not _is_user_question(msg):
            continue
        page_n, user_n = idx_to_page_and_n.get(i, (1, 0))
        # 미리보기: IDE 알림 제거 → HTML 태그 제거 → 공백 정규화 → 60자
        cleaned_html = ide_notification_re.sub(" ", html or "")
        text = tag_re.sub(" ", cleaned_html)
        preview = ws_re.sub(" ", text).strip()[:60]
        index.append({
            "uuid": msg.message_id,
            "n": user_n,
            "page": page_n,
            "ts": ts or "",
            "preview": preview,
        })
    return index
```

### 2-2. `HtmlRenderer.generate()` 시그니처 + 본문 교체

**BEFORE:**
```python
    def generate(
        self,
        messages: list[TranscriptEntry],
        title: Optional[str] = None,
        combined_transcript_link: Optional[str] = None,
        output_dir: Optional[Path] = None,
        page_info: Optional[dict[str, Any]] = None,
        page_stats: Optional[dict[str, Any]] = None,
    ) -> str:
        """Generate HTML from transcript messages.
        ...
        """
        import time

        t_start = time.time()

        # Set output directory for image export (used in "referenced" mode)
        self._output_dir = output_dir
        self._image_counter = 0

        if not title:
            title = "Claude Transcript"

        # Get root messages (tree) and session navigation from format-neutral renderer
        root_messages, session_nav, _ = generate_template_messages(messages)

        # Flatten tree via pre-order traversal, formatting content along the way
        with log_timing("Content formatting (pre-order)", t_start):
            template_messages = self._flatten_preorder(root_messages)

        # Render template
        with log_timing("Template environment setup", t_start):
            env = get_template_environment()
            template = env.get_template("transcript.html")

        with log_timing(
            lambda: f"Template rendering ({len(html_output)} chars)", t_start
        ):
            html_output = str(
                template.render(
                    title=title,
                    messages=template_messages,
                    sessions=session_nav,
                    combined_transcript_link=combined_transcript_link,
                    library_version=get_library_version(),
                    css_class_from_message=css_class_from_message,
                    get_message_emoji=get_message_emoji,
                    is_session_header=is_session_header,
                    page_info=page_info,
                    page_stats=page_stats,
                )
            )

        return html_output
```

**AFTER:**
```python
    def generate(
        self,
        messages: list[TranscriptEntry],
        title: Optional[str] = None,
        combined_transcript_link: Optional[str] = None,
        output_dir: Optional[Path] = None,
        page_info: Optional[dict[str, Any]] = None,
        page_stats: Optional[dict[str, Any]] = None,
        # === 단일 세션 페이지네이션 (user 질문 N개 기준) ===
        # user_msgs_per_page가 None이면 페이지네이션 안 함 (기존 combined_transcripts 동작 유지).
        # 값이 주어지면 user 질문 N개 단위로 잘라서 current_page만 렌더링.
        user_msgs_per_page: Optional[int] = None,
        current_page: Optional[int] = None,  # 1-based. None=마지막 페이지.
        page_base_url: str = "",  # prev/next 링크의 베이스 (보통 빈 문자열 → ?page=N)
    ) -> str:
        """Generate HTML from transcript messages.

        Args:
            messages: List of transcript entries to render.
            title: Optional title for the output.
            combined_transcript_link: Optional link to combined transcript.
            output_dir: Optional output directory for referenced images.
            page_info: Optional pagination info (page_number, prev_link, next_link).
            page_stats: Optional page statistics (message_count, date_range, token_summary).
            user_msgs_per_page: 단일 세션 페이지네이션 활성화 (예: 200).
            current_page: 현재 페이지 (1-based). None이면 마지막 페이지.
            page_base_url: prev/next 링크의 베이스 URL (빈 문자열 시 ?page=N).
        """
        import time

        t_start = time.time()

        # Set output directory for image export (used in "referenced" mode)
        self._output_dir = output_dir
        self._image_counter = 0

        if not title:
            title = "Claude Transcript"

        # Get root messages (tree) and session navigation from format-neutral renderer
        root_messages, session_nav, _ = generate_template_messages(messages)

        # Flatten tree via pre-order traversal, formatting content along the way
        with log_timing("Content formatting (pre-order)", t_start):
            template_messages = self._flatten_preorder(root_messages)

        # === 단일 세션 페이지네이션 처리 ===
        # 페이지네이션이 켜져 있으면 슬라이스 후 page_info를 만들어 템플릿에 전달.
        # 북마크 인덱스(전체 세션의 user 메시지 메타데이터)는 페이지와 무관하게 항상 빌드.
        bookmark_index: list[dict[str, Any]] = []
        user_msg_start_number = 1
        if user_msgs_per_page is not None:
            pages = _compute_session_pages(template_messages, user_msgs_per_page)
            total_pages = len(pages)
            bookmark_index = _build_bookmark_index(template_messages, pages)

            if total_pages > 1:
                # 기본값: 마지막 페이지 (최신 메시지)
                cp = total_pages if current_page is None else current_page
                cp = max(1, min(cp, total_pages))
                start_idx, end_idx, first_u, last_u = pages[cp - 1]
                template_messages = template_messages[start_idx:end_idx]
                user_msg_start_number = first_u

                def _link(n: int) -> str:
                    # 베이스 URL이 비어 있으면 동일 경로의 쿼리만 변경
                    if page_base_url:
                        sep = "&" if "?" in page_base_url else "?"
                        return f"{page_base_url}{sep}page={n}"
                    return f"?page={n}"

                page_info = {
                    "page_number": cp,
                    "total_pages": total_pages,
                    "prev_link": _link(cp - 1) if cp > 1 else None,
                    "next_link": _link(cp + 1) if cp < total_pages else None,
                    "is_last_page": cp == total_pages,
                    "is_single_session_pagination": True,
                    "first_user_num": first_u,
                    "last_user_num": last_u,
                }

        # Render template
        with log_timing("Template environment setup", t_start):
            env = get_template_environment()
            template = env.get_template("transcript.html")

        with log_timing(
            lambda: f"Template rendering ({len(html_output)} chars)", t_start
        ):
            html_output = str(
                template.render(
                    title=title,
                    messages=template_messages,
                    sessions=session_nav,
                    combined_transcript_link=combined_transcript_link,
                    library_version=get_library_version(),
                    css_class_from_message=css_class_from_message,
                    get_message_emoji=get_message_emoji,
                    is_session_header=is_session_header,
                    page_info=page_info,
                    page_stats=page_stats,
                    user_msg_start_number=user_msg_start_number,
                    bookmark_index=bookmark_index,
                )
            )

        return html_output
```

### 2-3. `HtmlRenderer.generate_session()` 교체

**BEFORE:**
```python
    def generate_session(
        self,
        messages: list[TranscriptEntry],
        session_id: str,
        title: Optional[str] = None,
        cache_manager: Optional["CacheManager"] = None,
        output_dir: Optional[Path] = None,
    ) -> str:
        """Generate HTML for a single session."""
        # Filter messages for this session (SummaryTranscriptEntry.sessionId is always None)
        session_messages = [msg for msg in messages if msg.sessionId == session_id]

        # Get combined transcript link if cache manager is available
        combined_link = None
        if cache_manager is not None:
            try:
                project_cache = cache_manager.get_cached_project_data()
                if project_cache and project_cache.sessions:
                    combined_link = "combined_transcripts.html"
            except Exception:
                pass

        return self.generate(
            session_messages,
            title or f"Session {session_id[:8]}",
            combined_transcript_link=combined_link,
            output_dir=output_dir,
        )
```

**AFTER:**
```python
    def generate_session(
        self,
        messages: list[TranscriptEntry],
        session_id: str,
        title: Optional[str] = None,
        cache_manager: Optional["CacheManager"] = None,
        output_dir: Optional[Path] = None,
        # === 단일 세션 페이지네이션 ===
        # page: 1-based 페이지 번호. None이면 마지막 페이지 (활성 세션 UX).
        # page_size: 페이지당 user 질문 개수. None이면 USER_MSGS_PER_PAGE (200).
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> str:
        """Generate HTML for a single session."""
        # Filter messages for this session (SummaryTranscriptEntry.sessionId is always None)
        session_messages = [msg for msg in messages if msg.sessionId == session_id]

        # Get combined transcript link if cache manager is available
        combined_link = None
        if cache_manager is not None:
            try:
                project_cache = cache_manager.get_cached_project_data()
                if project_cache and project_cache.sessions:
                    combined_link = "combined_transcripts.html"
            except Exception:
                pass

        return self.generate(
            session_messages,
            title or f"Session {session_id[:8]}",
            combined_transcript_link=combined_link,
            output_dir=output_dir,
            user_msgs_per_page=page_size if page_size is not None else USER_MSGS_PER_PAGE,
            current_page=page,
        )
```

---

## 3. `claude_code_log/server.py`

### `serve_file` 안의 session_match 블록 교체

위치: `@app.route("/<path:filepath>")` 데코레이터 아래 `def serve_file(filepath: str) -> Response:` 함수 시작 부분.

> ⚠️ **중요**: `jsonl_file.stem == session_id` 체크는 **Old Sessions 기능에서 도입된 안전장치**입니다 (JSONL 삭제 후 정적 HTML만 남은 세션 보호). 페이지네이션 제거/적용 어느 쪽이든 이 체크는 **반드시 보존**해야 합니다.

**BEFORE (페이지네이션 없음, stem 체크는 그대로 유지):**
```python
        # 세션 페이지는 동적 렌더링 (항상 JSONL에서 최신 내용 생성)
        session_match = re.match(r".+/session-([a-f0-9-]+)\.html$", filepath)
        if session_match:
            session_id = session_match.group(1)
            jsonl_file = _find_session_jsonl(projects_dir, session_id)
            # Only render dynamically when the JSONL filename matches the session_id.
            # Content-only matches (another JSONL that mentions this ID) must not be used
            # because they produce empty pages — fall through to serve the static HTML instead.
            if jsonl_file is not None and jsonl_file.stem == session_id:
                from .converter import load_transcript
                from .html.renderer import HtmlRenderer

                messages = load_transcript(jsonl_file, silent=True)
                renderer = HtmlRenderer()
                custom_title = _get_custom_title(jsonl_file, session_id)
                html = renderer.generate_session(messages, session_id, title=custom_title)
                print(f"[serve_file] session={session_id[:8]}, messages={len(messages)}, html_len={len(html)}, jsonl_size={jsonl_file.stat().st_size}")
                return Response(
                    html,
                    mimetype="text/html",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
```

**AFTER (페이지네이션 + stem 체크 모두 유지):**
```python
        # 세션 페이지는 동적 렌더링 (항상 JSONL에서 최신 내용 생성)
        session_match = re.match(r".+/session-([a-f0-9-]+)\.html$", filepath)
        if session_match:
            session_id = session_match.group(1)
            jsonl_file = _find_session_jsonl(projects_dir, session_id)
            # Only render dynamically when the JSONL filename matches the session_id.
            # Content-only matches (another JSONL that mentions this ID) must not be used
            # because they produce empty pages — fall through to serve the static HTML instead.
            if jsonl_file is not None and jsonl_file.stem == session_id:
                from .converter import load_transcript
                from .html.renderer import HtmlRenderer

                # ?page=N (1-based) 또는 ?page=last → 페이지 슬라이스.
                # 파라미터 없거나 last → renderer가 마지막 페이지로 기본 처리.
                page_param = request.args.get("page", "").strip().lower()
                page_num: Optional[int] = None
                if page_param and page_param != "last":
                    try:
                        page_num = int(page_param)
                    except ValueError:
                        page_num = None

                messages = load_transcript(jsonl_file, silent=True)
                renderer = HtmlRenderer()
                custom_title = _get_custom_title(jsonl_file, session_id)
                html = renderer.generate_session(
                    messages, session_id, title=custom_title, page=page_num,
                )
                print(f"[serve_file] session={session_id[:8]}, page={page_num or 'last'}, messages={len(messages)}, html_len={len(html)}, jsonl_size={jsonl_file.stat().st_size}")
                return Response(
                    html,
                    mimetype="text/html",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
```

### BEFORE↔AFTER 핵심 차이 (페이지네이션만 추가/제거되는 부분)

```python
# 페이지네이션 ON일 때 추가되는 블록 (이 블록만 빼면 BEFORE = AFTER)
                # ?page=N (1-based) 또는 ?page=last → 페이지 슬라이스.
                # 파라미터 없거나 last → renderer가 마지막 페이지로 기본 처리.
                page_param = request.args.get("page", "").strip().lower()
                page_num: Optional[int] = None
                if page_param and page_param != "last":
                    try:
                        page_num = int(page_param)
                    except ValueError:
                        page_num = None

# 그리고 generate_session 호출 시그니처:
# - 페이지네이션 OFF: renderer.generate_session(messages, session_id, title=custom_title)
# - 페이지네이션 ON : renderer.generate_session(messages, session_id, title=custom_title, page=page_num)

# print 라인의 page={page_num or 'last'} 부분도 페이지네이션 ON일 때만 추가.
```

> `Optional` 이미 `from typing import Optional` 으로 임포트되어 있음 (server.py 라인 11). 추가 임포트 불필요.
> `jsonl_file.stem == session_id` 체크 + 그 위 영문 주석 3줄은 **건드리지 말 것** (Old Sessions 기능 안전장치).

---

## 4. `claude_code_log/html/templates/transcript.html`

### 4-1. `<body>` 직후에 JS 변수 주입 + 페이지 nav 매크로 + 상단 호출

**BEFORE:**
```html
<body>
    <h1 id="title"><a href="/" class="home-btn" title="메인 대시보드">🏠</a>{{ title }}</h1>

    {% if page_info %}
    <!-- Page Navigation -->
    <div class="page-navigation">
        <div class="page-header">
            <div class="page-title">Page {{ page_info.page_number }}</div>
            {% if page_stats %}
            <div class="page-stats">
                <span class="stat">💬 {{ page_stats.message_count }} messages</span>
                <span class="stat">🕒 {{ page_stats.date_range }}</span>
                {% if page_stats.token_summary %}
                <span class="stat">🪙 {{ page_stats.token_summary }}</span>
                {% endif %}
            </div>
            {% endif %}
        </div>
        <div class="page-nav-links">
            {% if page_info.prev_link %}
            <a href="{{ page_info.prev_link }}" class="page-nav-link prev">← Previous</a>
            {% endif %}
            <!-- PAGINATION_NEXT_LINK_START -->
            <a href="{{ page_info.next_link }}" class="page-nav-link next{% if page_info.is_last_page %} last-page{% endif %}">Next →</a>
            <!-- PAGINATION_NEXT_LINK_END -->
        </div>
    </div>
    {% endif %}

    <!-- Timeline Component -->
    {% include 'components/timeline.html' %}
```

**AFTER:**
```html
<body>
    {# === 단일 세션 페이지네이션 JS 변수 주입 === #}
    {# user_msg_start_number: 페이지 N의 첫 user 메시지 번호 (예: 페이지 2면 201) #}
    {# bookmark_index: 전체 세션의 user 메시지 메타데이터 (북마크 패널이 다른 페이지 항목도 표시) #}
    <script>
        window.__userMsgStartNumber = {{ user_msg_start_number | default(1) }};
        window.__bookmarkIndex = {{ bookmark_index | default([]) | tojson }};
        window.__currentPage = {{ (page_info.page_number if page_info else 1) | tojson }};
    </script>

    <h1 id="title"><a href="/" class="home-btn" title="메인 대시보드">🏠</a>{{ title }}</h1>

    {# === 페이지 네비게이션 매크로 (상/하단에서 재사용) === #}
    {% macro render_page_nav() %}
    {% if page_info %}
    <div class="page-navigation">
        <div class="page-header">
            <div class="page-title">
                Page {{ page_info.page_number }}{% if page_info.total_pages %} / {{ page_info.total_pages }}{% endif %}
                {% if page_info.is_single_session_pagination %}
                <span class="page-user-range">(질문 #{{ page_info.first_user_num }} ~ #{{ page_info.last_user_num }})</span>
                {% endif %}
            </div>
            {% if page_stats %}
            <div class="page-stats">
                <span class="stat">💬 {{ page_stats.message_count }} messages</span>
                <span class="stat">🕒 {{ page_stats.date_range }}</span>
                {% if page_stats.token_summary %}
                <span class="stat">🪙 {{ page_stats.token_summary }}</span>
                {% endif %}
            </div>
            {% endif %}
        </div>
        <div class="page-nav-links">
            {% if page_info.prev_link %}
            <a href="{{ page_info.prev_link }}" class="page-nav-link prev">← Previous</a>
            {% endif %}
            {% if page_info.is_single_session_pagination %}
                {# 단일 세션: 마지막 페이지면 Next 숨김 #}
                {% if page_info.next_link %}
                <a href="{{ page_info.next_link }}" class="page-nav-link next">Next →</a>
                {% endif %}
            {% else %}
                {# combined_transcripts: 기존 동작 유지 (last-page 클래스 토글) #}
                <!-- PAGINATION_NEXT_LINK_START -->
                <a href="{{ page_info.next_link }}" class="page-nav-link next{% if page_info.is_last_page %} last-page{% endif %}">Next →</a>
                <!-- PAGINATION_NEXT_LINK_END -->
            {% endif %}
        </div>
    </div>
    {% endif %}
    {% endmacro %}

    {{ render_page_nav() }}

    <!-- Timeline Component -->
    {% include 'components/timeline.html' %}
```

### 4-2. 메시지 루프 종료 직후 하단 nav 호출 추가

**BEFORE:**
```html
    {% endif %}
    {% endfor %}
    </div>
    <!-- Clean container for SSE live messages — must be before #prompt-dock so new messages appear above the dock -->
    <div id="sse-live-messages"></div>
<div id="prompt-dock">
```

**AFTER:**
```html
    {% endif %}
    {% endfor %}
    </div>
    <!-- Clean container for SSE live messages — must be before #prompt-dock so new messages appear above the dock -->
    <div id="sse-live-messages"></div>

    {# 하단 페이지 네비게이션 — 긴 페이지 끝에서 다음 페이지로 빠르게 이동 #}
    {{ render_page_nav() }}
<div id="prompt-dock">
```

### 4-3. `numberUserMessages()` 오프셋 적용

**BEFORE:**
```javascript
            // Sequential numbering for user message bubbles + bookmark pins
            window.numberUserMessages = function() {
                document.querySelectorAll('.msg-number, .bookmark-pin').forEach(function(el) { el.remove(); });
                document.querySelectorAll(
                    '.message.user:not(.empty-prompt):not(.session-header)'
                ).forEach(function(msg, i) {
                    var header = msg.querySelector('.header');
                    if (!header) return;
                    var span = header.querySelector('span');
                    if (!span) return;
                    var n = i + 1;
```

**AFTER:**
```javascript
            // Sequential numbering for user message bubbles + bookmark pins.
            // 페이지네이션 시: 페이지 N에서는 #(N-1)*200+1 부터 시작 → window.__userMsgStartNumber 사용.
            window.numberUserMessages = function() {
                document.querySelectorAll('.msg-number, .bookmark-pin').forEach(function(el) { el.remove(); });
                var startN = (typeof window.__userMsgStartNumber === 'number') ? window.__userMsgStartNumber : 1;
                document.querySelectorAll(
                    '.message.user:not(.empty-prompt):not(.session-header)'
                ).forEach(function(msg, i) {
                    var header = msg.querySelector('.header');
                    if (!header) return;
                    var span = header.querySelector('span');
                    if (!span) return;
                    var n = i + startN;
```

### 4-4. `gatherBookmarksOnPage()` 인덱스 기반으로 교체

**BEFORE:**
```javascript
                function gatherBookmarksOnPage() {
                    var items = [];
                    document.querySelectorAll(
                        '.message.user:not(.empty-prompt):not(.session-header)'
                    ).forEach(function(msg) {
                        var sid = getMsgSessionId(msg);
                        var uuid = msg.dataset.messageId;
                        if (!sid || !uuid) return;
                        if (loadBookmarks(sid).indexOf(uuid) < 0) return;
                        var n = msg.dataset.userMsgNumber || '?';
                        var ts = msg.querySelector('.timestamp');
                        var tsText = ts ? ts.textContent.trim() : '';
                        var userTexts = msg.querySelectorAll('.content .user-text');
                        var preview = Array.prototype.map.call(userTexts, function(el) {
                            return el.textContent;
                        }).join(' ').replace(/\s+/g, ' ').trim().slice(0, 60);
                        items.push({ sid: sid, uuid: uuid, n: n, ts: tsText, preview: preview });
                    });
                    return items;
                }
```

**AFTER:**
```javascript
                // 북마크 패널 항목 수집.
                // 페이지네이션 시 다른 페이지의 북마크도 표시 → window.__bookmarkIndex (서버 주입)
                // 에서 메타데이터(uuid/n/page/ts/preview)를 가져옴. DOM에 메시지가 있으면 그 정보로
                // 보강 (사용자가 편집해도 최신값 반영).
                function gatherBookmarksOnPage() {
                    var items = [];
                    var idx = window.__bookmarkIndex || [];
                    var hasIndex = idx && idx.length > 0;

                    if (hasIndex) {
                        // 단일 세션 페이지네이션 모드: 인덱스 기반
                        var sessionHeader = document.querySelector('.message.session-header[data-session-id]');
                        var sid = sessionHeader ? sessionHeader.dataset.sessionId : null;
                        if (!sid) return items;
                        var bookmarked = loadBookmarks(sid);
                        if (!bookmarked.length) return items;
                        idx.forEach(function(entry) {
                            if (bookmarked.indexOf(entry.uuid) < 0) return;
                            items.push({
                                sid: sid,
                                uuid: entry.uuid,
                                n: entry.n,
                                ts: entry.ts,
                                preview: entry.preview || '(내용 없음)',
                                page: entry.page,
                            });
                        });
                    } else {
                        // 기존 동작: DOM 스캔 (페이지네이션 없는 환경)
                        document.querySelectorAll(
                            '.message.user:not(.empty-prompt):not(.session-header)'
                        ).forEach(function(msg) {
                            var sid = getMsgSessionId(msg);
                            var uuid = msg.dataset.messageId;
                            if (!sid || !uuid) return;
                            if (loadBookmarks(sid).indexOf(uuid) < 0) return;
                            var n = msg.dataset.userMsgNumber || '?';
                            var ts = msg.querySelector('.timestamp');
                            var tsText = ts ? ts.textContent.trim() : '';
                            var userTexts = msg.querySelectorAll('.content .user-text');
                            var preview = Array.prototype.map.call(userTexts, function(el) {
                                return el.textContent;
                            }).join(' ').replace(/\s+/g, ' ').trim().slice(0, 60);
                            items.push({ sid: sid, uuid: uuid, n: n, ts: tsText, preview: preview, page: null });
                        });
                    }
                    // 번호 오름차순으로 정렬
                    items.sort(function(a, b) { return (parseInt(a.n, 10) || 0) - (parseInt(b.n, 10) || 0); });
                    return items;
                }
```

### 4-5. `refreshPanel()` 안의 항목 생성 부분 교체

**BEFORE:**
```javascript
                    panelList.innerHTML = '';
                    items.forEach(function(item) {
                        var row = document.createElement('div');
                        row.className = 'bookmark-item';
                        row.dataset.uuid = item.uuid;
                        row.dataset.sid = item.sid;
                        var l1 = document.createElement('div');
                        l1.className = 'bookmark-item-line1';
                        l1.textContent = '#' + item.n + (item.ts ? ' · ' + item.ts : '');
                        var l2 = document.createElement('div');
                        l2.className = 'bookmark-item-line2';
                        l2.textContent = item.preview || '(내용 없음)';
                        var rm = document.createElement('button');
                        rm.className = 'bookmark-item-remove';
                        rm.type = 'button';
                        rm.title = '북마크 해제';
                        rm.textContent = '✕';
                        row.appendChild(l1);
                        row.appendChild(l2);
                        row.appendChild(rm);
                        panelList.appendChild(row);
                    });
                }
```

**AFTER:**
```javascript
                    panelList.innerHTML = '';
                    var curPage = window.__currentPage || 1;
                    items.forEach(function(item) {
                        var row = document.createElement('div');
                        row.className = 'bookmark-item';
                        row.dataset.uuid = item.uuid;
                        row.dataset.sid = item.sid;
                        if (item.page) row.dataset.page = String(item.page);
                        // 다른 페이지 북마크는 시각적 구분
                        if (item.page && item.page !== curPage) {
                            row.classList.add('bookmark-item-other-page');
                        }
                        var l1 = document.createElement('div');
                        l1.className = 'bookmark-item-line1';
                        var line1Text = '#' + item.n + (item.ts ? ' · ' + item.ts : '');
                        if (item.page && item.page !== curPage) {
                            line1Text += ' (p.' + item.page + ')';
                        }
                        l1.textContent = line1Text;
                        var l2 = document.createElement('div');
                        l2.className = 'bookmark-item-line2';
                        l2.textContent = item.preview || '(내용 없음)';
                        var rm = document.createElement('button');
                        rm.className = 'bookmark-item-remove';
                        rm.type = 'button';
                        rm.title = '북마크 해제';
                        rm.textContent = '✕';
                        row.appendChild(l1);
                        row.appendChild(l2);
                        row.appendChild(rm);
                        panelList.appendChild(row);
                    });
                }
```

### 4-6. 북마크 패널 클릭 핸들러 — 다른 페이지면 이동

**BEFORE:**
```javascript
                if (panelList) {
                    panelList.addEventListener('click', function(e) {
                        var rm = e.target.closest('.bookmark-item-remove');
                        var row = e.target.closest('.bookmark-item');
                        if (!row) return;
                        if (rm) {
                            e.stopPropagation();
                            toggleBookmark(row.dataset.sid, row.dataset.uuid);
                            window.applyBookmarkState();
                            return;
                        }
                        scrollToMessage(row.dataset.uuid);
                    });
                }
```

**AFTER:**
```javascript
                if (panelList) {
                    panelList.addEventListener('click', function(e) {
                        var rm = e.target.closest('.bookmark-item-remove');
                        var row = e.target.closest('.bookmark-item');
                        if (!row) return;
                        if (rm) {
                            e.stopPropagation();
                            toggleBookmark(row.dataset.sid, row.dataset.uuid);
                            window.applyBookmarkState();
                            return;
                        }
                        // 다른 페이지 북마크 → ?page=N#msg-<uuid>로 이동
                        var targetPage = parseInt(row.dataset.page, 10);
                        var curPage = window.__currentPage || 1;
                        if (targetPage && targetPage !== curPage) {
                            var loc = window.location;
                            // 현재 경로 유지, page 쿼리만 갱신, 해시는 UUID
                            var params = new URLSearchParams(loc.search);
                            params.set('page', String(targetPage));
                            window.location.href = loc.pathname + '?' + params.toString() + '#msg-' + row.dataset.uuid;
                            return;
                        }
                        scrollToMessage(row.dataset.uuid);
                    });
                }
```

### 4-7. 북마크 IIFE 마지막 — URL 해시 처리 추가

`window.applyBookmarkState();` 호출 **바로 뒤**, IIFE 닫는 `})();` **직전**.

**BEFORE:**
```javascript
                // Initial state apply (numberUserMessages already called above)
                window.applyBookmarkState();
            })();
```

**AFTER:**
```javascript
                // Initial state apply (numberUserMessages already called above)
                window.applyBookmarkState();

                // 크로스 페이지 북마크 점프: URL 해시 #msg-<uuid> 처리 → 해당 메시지로 스크롤 + 펄스
                if (window.location.hash && window.location.hash.indexOf('#msg-') === 0) {
                    var hashUuid = window.location.hash.slice(5); // remove '#msg-'
                    // 약간 지연 후 실행 (이미지/타임라인 로딩 후 정확한 위치 계산)
                    setTimeout(function() { scrollToMessage(hashUuid); }, 200);
                }
            })();
```

### 4-8. SSE 스크립트 시작부 — 비-마지막 페이지에서 SSE 끔

위치: `<!-- Live update via SSE -->` 블록 안, `var sessionId = match[1];` **직후**, `var source = new EventSource(...)` **직전**.

**BEFORE:**
```javascript
    (function() {
        // Extract session ID from URL: session-{uuid}.html
        var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
        if (!match) return;
        var sessionId = match[1];
        var source = new EventSource('/api/sessions/' + sessionId + '/stream');
        var updating = false;
```

**AFTER:**
```javascript
    (function() {
        // Extract session ID from URL: session-{uuid}.html
        var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
        if (!match) return;
        var sessionId = match[1];

        // 페이지네이션 시: 비-마지막 페이지에서 SSE 자동 append를 끔.
        // 옛 페이지에 새 메시지를 append하면 페이지 경계가 깨지므로 라이브 업데이트를 받지 않음.
        // 마지막 페이지에서만 라이브 동기화 유지 (활성 채팅 UX 보장).
        {% if page_info and page_info.is_single_session_pagination and not page_info.is_last_page %}
        var indicator = document.createElement('div');
        indicator.id = 'live-indicator';
        indicator.textContent = '📖 과거 페이지';
        indicator.title = '이 페이지는 과거 기록입니다. 라이브 동기화는 마지막 페이지에서만 작동합니다.';
        indicator.style.cssText = 'position:fixed;top:10px;right:10px;background:#888;color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:bold;z-index:9999;opacity:0.85;cursor:help;';
        document.body.appendChild(indicator);
        return;
        {% endif %}

        var source = new EventSource('/api/sessions/' + sessionId + '/stream');
        var updating = false;
```

---

## 5. `claude_code_log/html/templates/components/page_nav_styles.css`

파일 **끝**에 추가:

```css
/* 단일 세션 페이지네이션 — user 질문 번호 범위 표시 */
.page-user-range {
    font-size: 0.7em;
    color: var(--text-muted);
    font-weight: 400;
    margin-left: 8px;
}

/* 북마크 패널: 다른 페이지의 북마크 항목은 흐리게 표시 */
.bookmark-item.bookmark-item-other-page {
    opacity: 0.65;
    border-left: 3px solid #ccc;
}
.bookmark-item.bookmark-item-other-page:hover {
    opacity: 1;
    border-left-color: var(--system-warning-color, #f39c12);
}
```

---

## 6. 동작 검증 스크립트

다시 적용한 후 아래 스니펫으로 페이지 분할이 정상인지 확인:

```python
python -c "
from claude_code_log.html.renderer import _compute_session_pages

class MockMsg:
    def __init__(self, type_, is_header=False):
        self.type = type_
        self.is_session_header = is_header
        self.message_id = f'm{id(self)}'

msgs = [(MockMsg('session-header', True), '', '', '')]
for u in range(500):
    msgs.append((MockMsg('user'), '', '', ''))
    msgs.append((MockMsg('assistant'), '', '', ''))
    msgs.append((MockMsg('tool_use'), '', '', ''))

pages = _compute_session_pages(msgs, page_size=200)
print(f'Total pages: {len(pages)}')
for i, (s, e, fu, lu) in enumerate(pages):
    print(f'  Page {i+1}: msgs[{s}:{e}] = {e-s} entries, user #{fu}~#{lu}')
"
```

**기대 출력:**
```
Total pages: 3
  Page 1: msgs[0:601] = 601 entries, user #1~#200
  Page 2: msgs[601:1201] = 600 entries, user #201~#400
  Page 3: msgs[1201:1501] = 300 entries, user #401~#500
```

---

## 7. 동작/한계 메모

### 작동
- `session-xxx.html` → 마지막 페이지 (활성 채팅 기본 UX)
- `?page=N` → N페이지로 직접 이동
- 페이지 2 이상의 질문 번호 = 페이지 시작값부터 (예: #201, #202, …)
- 북마크 패널은 전체 세션의 북마크를 보여주고, 다른 페이지 항목엔 `(p.N)` 표시 + 흐리게
- 북마크 클릭 → 같은 페이지면 스크롤, 다른 페이지면 `?page=N#msg-uuid`로 자동 이동
- 페이지 이동 후 URL 해시(`#msg-<uuid>`)가 있으면 200ms 후 해당 메시지로 스크롤 + 펄스
- 비-마지막 페이지에선 SSE 라이브 동기화 꺼짐 (`📖 과거 페이지` 인디케이터)

### 한계
- **브라우저 Ctrl+F 검색**: 현재 페이지 DOM에만 적용 (모든 페이지 검색은 불가)
- **SSE 라이브 sync**: 마지막 페이지에서만 작동 (옛 페이지 보기 모드)
- **페이지 경계 변화**: SSE로 새 메시지가 마지막 페이지에 200개 한도를 넘으면 다음 새로고침에서 새 페이지로 분할됨. 그 사이엔 페이지에 200+개 표시되어도 동작은 정상
- **combined_transcripts**: 기존 세션 단위 페이지네이션은 그대로 유지 (`is_single_session_pagination` 플래그로 구분)

### 무한로딩 문제와의 관계
- 이 페이지네이션은 **무한로딩 문제와 직접 무관**함이 사후 확인됨
- 무한로딩의 진짜 원인: SSE 연결이 새로고침 시 제때 정리되지 않아 브라우저 동시 연결 슬롯 6개 한도 초과 (특히 여러 탭 환경)
- 진짜 fix는 `server.py`의 SSE keepalive timeout 단축 + `direct_passthrough=True` (별도 작업)
- 본 페이지네이션은 큰 세션의 초기 렌더링 속도/메모리 절감 측면에서 부수적 이득

---

## 8. 후속 수정 이력

### 8-1. 북마크 미리보기에서 IDE 알림 제외 (renderer.py `_build_bookmark_index`)

**증상**: 북마크 패널의 미리보기에 사용자가 작성하지 않은 IDE 알림(`🤖 The user opened the file ... in the IDE`, `📝 selection`, diagnostics)이 그대로 표시됨.

**원인**: 서버 측 `_build_bookmark_index`가 메시지 HTML 전체를 단순히 `<[^>]+>` 정규식으로 태그만 제거해서 미리보기 60자를 만들었음. 클라이언트 측 fallback 코드(`gatherBookmarksOnPage`)는 `.content .user-text`만 골라 뽑기 때문에 정상이었지만, 페이지네이션 도입 후 서버 인덱스(`window.__bookmarkIndex`)를 우선 사용하게 되면서 필터가 빠진 경로가 노출됨.

**수정**: 태그 제거 전에 `<div class='ide-notification ...'>...</div>` 블록을 먼저 정규식으로 통째 제거.

```python
# IDE 알림(🤖 The user opened the file..., 📝 selection, diagnostics 등)은
# 사용자가 작성한 컨텐츠가 아니므로 미리보기에서 제외.
# 형식: <div class='ide-notification ...'>...</div> (단일 따옴표, 중첩 div 없음)
ide_notification_re = re.compile(
    r"<div class='ide-notification[^']*'>.*?</div>", re.DOTALL
)
# ...
cleaned_html = ide_notification_re.sub(" ", html or "")
text = tag_re.sub(" ", cleaned_html)
preview = ws_re.sub(" ", text).strip()[:60]
```

해당 div은 단일 따옴표로 열리고 내부에 중첩 `<div>`가 없음(`format_ide_notification_content` 구현 확인)이라 non-greedy `.*?</div>` 매칭으로 안전하게 잘림.
