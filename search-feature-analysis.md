# 검색 기능(filter-messages floating-btn) 분석 Q&A

> `#filterMessages` (🔍 플로팅 버튼) 로 여는 커스텀 검색/필터 툴바와,
> 이 안의 `#searchInput` 검색 기능에 대한 분석 대화 기록.
> 원저자가 만든 기능이라 커스텀 히스토리엔 없어서 소스코드 + README 로 역추적.
>
> 관련 파일:
> - [claude_code_log/html/templates/components/search.html](claude_code_log/html/templates/components/search.html)
> - [claude_code_log/html/templates/components/search_inline.html](claude_code_log/html/templates/components/search_inline.html)
> - [claude_code_log/html/templates/components/search_styles.css](claude_code_log/html/templates/components/search_styles.css)
> - [claude_code_log/html/templates/components/search_results_panel.html](claude_code_log/html/templates/components/search_results_panel.html)

---

## Q1. 왜 커스텀 검색 결과 개수가 Chrome Ctrl+F와 다른가? searchNext 스크롤은 왜 안 되나?

### 질문 원문

> `filter-messages floating-btn active` 버튼 기능에 대해서 점검해줘.
> 내가 만든 건 아니고 원래 있던 검색필터 기능인데, 실제로 키워드를 입력해보면 제대로 검색이 안 되는 것들이 많아.
>
> 일례로 `pop`을 검색해보면 `filter-messages floating-btn active` 를 통해 검색된 pop의 개수(231개)와 Chrome 브라우저 기본 기능 Ctrl+F 검색(726개)의 결과 개수가 달라.
>
> 그리고 `id="searchContainer"` div 내부의 `id="searchNext"` 버튼을 누르면 키워드 쪽으로 화면이 내려가야 하는데 제대로 내려가지 않는 경우가 많아. 왜 그런 거야?

### 답변

#### Issue 1: 카운트 불일치 (231 vs 726)

##### 원인 A: SSE로 추가된 새 메시지는 인덱스에 안 들어감 ⭐ (가장 큰 원인일 가능성)

[search.html:78-90](claude_code_log/html/templates/components/search.html#L78-L90) — `buildSearchIndex()` 호출 시점:

- **`DOMContentLoaded`** (페이지 로드 시 1회)
- **필터 클래스 변경 시** (단, `searchInFiltered` 모드 켜져 있을 때만 — [line 762-768](claude_code_log/html/templates/components/search.html#L762-L768))

즉 SSE `iframe.onload` 콜백에는 `buildSearchIndex()` 재호출이 **없음**. 페이지를 열어놓은 채로 Claude와 대화하면서 계속 새 메시지가 SSE로 추가되면, **그 메시지들은 커스텀 검색 인덱스에 없음** → 검색 안 됨. 하지만 Chrome Ctrl+F는 DOM에 있는 모든 텍스트를 봄.

스크린샷의 메시지 수(User 101 + Assistant 232 + Thinking 263 + Tool 826 + Sub-assistant 201 = 약 1623개) 규모로 볼 때 세션이 오래됐고 SSE로 상당히 많이 추가됐을 가능성 큼. 495개 격차의 대부분이 여기서 나올 것.

##### 원인 B: 인덱스가 `.message` 내부 텍스트만 스캔

[search.html:141](claude_code_log/html/templates/components/search.html#L141):

```javascript
document.querySelectorAll('.message:not(.session-header)').forEach(...)
```

**포함되지 않는 것들** (Chrome은 봄):

- `.message.session-header` — 세션 헤더 (세션 제목/요약 포함)
- `<h1 id="title">` — 페이지 상단 세션 제목
- `.session-nav` — 세션 간 이동 네비게이션 (여러 세션의 제목 목록)
- `#bookmark-panel` 내부 항목 — 각 북마크 미리보기 60자
- `.filter-toolbar` 자체 — "Search & Filter" 헤더, 필터 버튼 라벨 등
- `#floating-buttons` — 버튼 title 속성 등

##### 원인 C: `.header span` 셀렉터가 첫 번째 span만 잡음

[search.html:142](claude_code_log/html/templates/components/search.html#L142):

```javascript
const header = message.querySelector('.header span')?.textContent || '';
```

`querySelector`(단수)라서 헤더 안의 **첫 번째 `<span>` 만** 가져옴. 헤더는 실제로 여러 span으로 구성:

- 첫 번째: 역할 이름 (`🤖 Assistant`)
- 두 번째~: `model-badge`, `timestamp`, `token-usage`, `msg-number`, `bookmark-pin` 등

이 케이스에서 "popup"이 헤더 span에 있을 가능성은 낮지만, 다른 검색어에선 문제될 수 있음. 안전을 위해 `.header` 전체 텍스트를 잡아야 함.

##### 원인 D: 카운트 표시 자체의 부정확성

[search.html:645](claude_code_log/html/templates/components/search.html#L645):

```javascript
searchResultCount.textContent = `${searchState.currentMatchIndex + 1} of ${searchState.matches.length} matches`;
```

**`matches.length` = 검색어가 등장한 메시지 개수** (총 occurrence 수가 아님). "24 of 231 matches" 는 "24번째 메시지 / 총 231개 메시지"로 읽어야 하는데 UI가 "matches" 라고 표기해서 오해를 낳음.

한편 `totalMatchCount` ([라인 388](claude_code_log/html/templates/components/search.html#L388)에서 계산) 는 **실제 총 occurrence 수**를 담고 있는데 이건 UI에 표시 안 됨. 스크린샷의 "231"은 messages 수인지 occurrence 수인지 확인 필요 (아마 이 케이스에선 messages 수).

#### Issue 2: `searchNext` 버튼이 제대로 스크롤 안 됨

##### 원인 A: 접힌 `<details>` 안의 매치는 `scrollIntoView` 무시됨

[search.html:512-519](claude_code_log/html/templates/components/search.html#L512-L519):

```javascript
const highlights = match.element.querySelectorAll('.search-highlight');
if (highlights.length > 0) {
    highlights[0].classList.add('current');
    highlights[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
}
```

- Tool 메시지의 결과가 `<details>` 안에 접혀있는 경우 (Read 결과, Bash 출력 등), 그 안의 `.search-highlight` 요소는 **레이아웃 박스가 없음** (`<details>` 접힘 상태에선 자식이 렌더링 안 됨).
- 브라우저의 `scrollIntoView` 는 레이아웃 박스가 없는 요소에 대해서는 **아무 일도 안 함** (스크롤 이동 없음).

##### 원인 B: fold-bar로 숨긴 메시지 안의 매치도 마찬가지

fold-bar 로 `.message` 자체에 `style.display = 'none'` 이 걸린 경우, 그 안의 `.search-highlight` 는 사용자한테 보이지 않고 스크롤 대상도 없음.

##### 원인 C: 최근 §27 재설계로 만들어진 `.tool_use / .tool_result` 숨김 상태도 같음

📂 토글로 도구 메시지가 `display: none` 이면 그 안의 매치는 접근 불가.

##### 원인 D: 매치가 있는데 스킵되는 UX 문제

동일 메시지 안에 "popup"이 10개 있어도 "next" 클릭 시 **다음 메시지로 점프** (occurrence 단위가 아니라 message 단위 이동). Chrome Ctrl+F 는 개별 occurrence 단위로 이동해서 사용자가 익숙한 동작과 다름. 이건 원인 A/B/C 와 별개로 **의도적 설계**지만 사용자에겐 혼란스러움.

#### 종합 표

| 문제 | 근본 원인 | 심각도 |
|---|---|---|
| 카운트 격차 495 | SSE 추가 메시지 미인덱싱 (A) 가 대부분, 세션 헤더/네비 제외 (B) 도 일부 | 높음 |
| 카운트 라벨 오해 | messages 수를 "matches" 로 표기 (D) | 중간 |
| Next 스크롤 실패 | 접힌 details / 숨은 fold / 도구 숨김 안의 매치 (A/B/C) | 높음 |
| Next 가 occurrence 단위 아님 | 설계상 message 단위 (D) | 중간 |

#### 참고

**이 검색 기능은 원래 있던 코드**여서, 커스터마이징 이력에 없는 원본 저자의 설계에 여러 갭이 있어 보임. 큰 수정이 필요하다면 [현재 disable된 Ctrl+F 단축키](claude_code_log/html/templates/components/search.html#L664-L684) 부활을 결정하기 전에 이 근본 이슈들을 다 손보는 게 순서.

#### 수정 옵션 (요약)

- **작은 fix**: SSE `iframe.onload` 에서 `buildSearchIndex()` 재호출 추가 (원인 1-A만 해결) — 5분 작업
- **중간 fix**: 인덱싱 범위 확장 (`.header` 전체, session-header 포함) + 카운트 라벨 정정 — 15분 작업
- **큰 fix**: 스크롤 시 접힌 details 자동 open + 숨은 메시지 부모 unfold, occurrence 단위 네비게이션으로 재설계 — 1시간+ 작업

---

## Q2. 그럼 애초에 이 검색 기능을 왜 만든 건가? Ctrl+F로 충분하지 않나?

### 질문 원문

> 그 전에 `filter-messages floating-btn active` 기능을 만든 의도가 궁금해.
> 그냥 브라우저 기본 검색 기능 Ctrl+F를 이용해도 될 텐데 굳이 `filter-messages floating-btn active` 를 만든 이유가 뭐야? 제대로 동작하는 것 같지도 않은데…
> README.md 같은 거 읽어서 혹은 너가 코드분석해서 스스로 판단해봐.

### 답변

#### 원저자의 의도 — 3가지 근거

##### 근거 1: README.md 명시적 목표

원저자가 이 도구가 답하려는 질문 중 하나로 명시 ([README.md:60](README.md#L60)):

> **"How can I search through my entire Claude Code history?"**

즉 개별 페이지 안이 아니라 **"전체 Claude Code 히스토리에 걸친 검색"** 이 애초의 목표. Ctrl+F로는 절대 못 하는 일.

##### 근거 2: search input placeholder

[search_inline.html:7](claude_code_log/html/templates/components/search_inline.html#L7):

```html
<input placeholder="Search conversations... (Ctrl+F)">
```

원저자는 이 UI를 **Ctrl+F의 대체품**으로 설계했음. 그래서 이전 `handleKeyboardShortcuts` 가 Ctrl+F 를 가로챘던 것 (우리가 §26에서 비활성화한 그 로직).

##### 근거 3: `isIndexPage` 분기 로직

[search.html:57](claude_code_log/html/templates/components/search.html#L57):

```javascript
isIndexPage: window.location.pathname.includes('index.html') || ...
```

`isIndexPage` 여부에 따라 **완전히 다른 UI/데이터**를 씀:

- **인덱스 페이지**: 프로젝트/세션 카드를 인덱싱 → 여러 세션에 걸친 크로스 세션 검색 결과 패널 (`displayIndexSearchResults`)
- **세션 페이지**: 각 `.message` 를 인덱싱 → 현재 페이지 안 매치 하이라이트/네비게이션

#### Ctrl+F가 못 하는 4가지 (기획상)

| 기능 | Chrome Ctrl+F | 커스텀 검색 (기획 의도) |
|---|---|---|
| **크로스 세션 검색** — 대시보드에서 여러 세션 전체를 한 번에 훑기 | ❌ 현재 DOM만 봄 | ✅ 인덱스 페이지에서 전체 세션 메타/미리보기를 인덱싱 |
| **"Visible only" 모드** — filter-toolbar 로 숨긴 메시지 타입은 검색에서도 제외 | ❌ 숨긴 Thinking/Tool 안 텍스트도 다 매치 | ✅ `searchInFiltered=true` 로 필터 상태 존중 |
| **정규식(Regex) 검색** | 브라우저 따라 다름 (Chrome은 없음) | ✅ `useRegex` 체크박스 |
| **메시지 단위 그룹핑 카운트** — "n messages contain X" | ❌ 개별 occurrence 만 셈 | ✅ 메시지 단위 매치 개수 표시 |

#### 특히 "Visible only" 모드는 진짜 가치 있음

filter-toolbar에서 💭 Thinking / 🛠️ Tool 을 끄고 대화 본문만 보고 있을 때:

- **Chrome Ctrl+F** → 숨겨진 thinking/tool의 텍스트에도 매치가 뜸. "이 매치는 어디 있지?" 하고 스크롤해도 안 보임 (숨어있으니까). 짜증남.
- **커스텀 검색 (기획대로 동작한다면)** → "지금 화면에 보이는 메시지들 중에서만" 검색. 매치 위치가 항상 보임.

#### 그럼 지금 왜 이렇게 안 좋게 느껴지나?

**의도는 좋았는데 구현이 완결되지 못했음.** Q1에서 분석한 문제들:

- 카운트 231 vs Chrome 726 격차 → **SSE 추가 메시지 미인덱싱** + 세션 헤더/네비 제외 + 헤더 첫 span만 잡음
- Next 버튼 스크롤 실패 → 접힌 `<details>` / 숨은 fold-bar / 도구 숨김 안의 매치 처리 없음
- "24 of 231 matches" 라벨 오해 → 실은 메시지 수인데 "matches" 라고 표기

이 세 갭 때문에 사용자가 "제대로 안 됨" 을 체감하고 Ctrl+F 로 회귀 (실제로 사용자가 §26에서 Ctrl+F 가로채기를 비활성화한 이유).

#### 그럼 이걸 계속 유지할 가치가 있나?

**있음. 단, 조건부**:

- **인덱스 페이지의 크로스 세션 검색은 대체 불가능** — Ctrl+F로는 열지 않은 세션의 내용은 못 봄. 이 기능은 원저자가 README에서 강조한 핵심 가치. 유지 가치 확실.
- **세션 페이지의 검색은 "Visible only" + Regex 가 킬링 피처** — 필터와 조합하면 Ctrl+F로 못 하는 걸 함. 다만 이 두 킬링 피처가 제대로 작동해야 의미 있음. 현재 상태로는 오히려 Ctrl+F가 더 나음.

#### 판단

원저자의 설계 자체는 옳았음. 원인은 **원저자가 완성 못 하고 남긴 갭들**이 SSE 라이브 sync 같은 후속 기능 도입으로 더 크게 벌어진 것 (SSE 메시지 미인덱싱은 SSE 이후에 생긴 새 문제).

##### 대응 옵션

- **A. 유지 + 수리** — 앞서 제시한 작은/중간/큰 fix 중 하나로 완성. 크로스 세션 검색이 살아남으니 도구의 원래 가치 보전.
- **B. 인덱스 페이지만 유지, 세션 페이지는 폐기** — 세션 페이지에서는 Ctrl+F 그대로 쓰게 하고, 크로스 세션 검색만 대시보드에 남김. 코드 삭제량 큼.
- **C. 전부 폐기** — 크로스 세션 검색 편의를 포기하고 Ctrl+F에 위임. 완전 삭제.

원저자의 설계 의도(README에 명시된 "전체 히스토리 검색")를 존중한다면 **A** 가 정답.
사용 안 하는 기능이면 **C**. 실용주의로 가시면 **B**.

---

## 부록 A. 관련 커스텀 이력

- `4457889` — **검색 탭 기능 분리 (Ctrl+F, F3 가로채기 해제)**: 커스텀 검색이 어색하다는 피드백으로 Ctrl+F가 브라우저 기본 찾기로 되돌아가도록 [handleKeyboardShortcuts](claude_code_log/html/templates/components/search.html#L664-L684) 블록 주석 처리. 재활성화하려면 주석 해제만 하면 됨. (CUSTOM_FEATURES.md §26)
- `6800b89` — **대시보드 검색 결과 항목에 세션 제목/ID/미리보기 표시**: 인덱스 페이지 크로스 세션 검색 결과가 어떤 세션인지 식별하기 쉽게 렌더링 개선. (CUSTOM_FEATURES.md §28)

## 부록 B. `search.html` 주요 함수 매핑

| 함수 | 위치 | 역할 |
|---|---|---|
| `initSearch` | line 78 | `DOMContentLoaded` 시 진입점 — 인덱스 빌드 + state 복원 + 리스너 세팅 |
| `buildSearchIndex` | line 93 | `isIndexPage` 여부에 따라 프로젝트/세션 카드 or 메시지를 `searchState.searchIndex` 배열에 축적 |
| `performSearch` | line ~326 | 쿼리 문자열로 인덱스 순회 + `matches` 배열 + `highlightInElement` 호출 |
| `highlightInElement` | line 426 | `TreeWalker` 로 텍스트 노드 훑고 `<span class="search-highlight">` 으로 감쌈 |
| `clearHighlights` | line 480 | 하이라이트 span 제거 후 `parent.normalize()` |
| `navigateMatch` | line 489 | prev/next 버튼 핸들러 — `currentMatchIndex` 를 ±1 |
| `navigateToMatch` | line 504 | `match.element` 안의 첫 `.search-highlight` 로 `scrollIntoView({block:'center'})` |
| `countMatches` | line 236 | 텍스트 안 매치 개수 세기 (Regex/plain 지원, 항상 case-insensitive) |
| `createExcerpt` | line 174 | 매치 주변 ±50자 컨텍스트 추출, 중첩 범위 제거 |
| `displayIndexSearchResults` | line 525 | 인덱스 페이지 전용 — 프로젝트 그룹핑 결과 패널에 렌더 |
| `handleKeyboardShortcuts` | line 657 | Ctrl+F/F3 처리 — **현재 주석 처리됨** (§26) |
| `saveSearchState`/`restoreSearchState` | line 706~ | localStorage 로 검색 상태 지속 |
