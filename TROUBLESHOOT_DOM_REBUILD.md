# 1초마다 화면을 다시 그리면 드래그 선택이 풀린다

> 카운트다운을 붙였더니 목록의 글자를 마우스로 긁어 복사할 수 없게 됐다.
> 드래그가 곧바로 풀리거나 엉뚱한 영역까지 잡혔다.
>
> **원인은 카운트다운이 아니라, 매초 `innerHTML` 을 통째로 다시 쓴 것이었다.**

---

## 목차

1. [증상](#1-증상)
2. [원인 — DOM 이 매초 사라졌다 다시 생긴다](#2-원인--dom-이-매초-사라졌다-다시-생긴다)
3. [왜 선택이 풀리는가](#3-왜-선택이-풀리는가)
4. [기존 방식 vs 수정 방식](#4-기존-방식-vs-수정-방식)
5. [수정한 파일과 위치](#5-수정한-파일과-위치)
6. [수정한 코드](#6-수정한-코드)
7. [검증 방법](#7-검증-방법)
8. [일반화 — 언제 이 문제가 생기나](#8-일반화--언제-이-문제가-생기나)

---

## 1. 증상

세션 유지용 자동 메시지 목록에 1초마다 갱신되는 카운트다운을 넣었다.

```
57:54   C:\a 폴더 내용 확인 및 설치 내역 파악
        7caad578 · C--Users-user
0/12 회 · 주기 58:00 · 다음 16:41:27
```

그런데 `C--Users-user` 나 `0/12 회 · 주기 58:00` 같은 글자를 마우스로 긁으려 하면

- 드래그하던 중 선택이 **툭 풀리고**
- 다시 긁으면 **엉뚱한 문단까지** 통째로 잡히고
- 복사가 사실상 불가능했다

"목업이라 대충 만들어서 그런가?" 싶지만 **아니다.** 실제 기능을 붙여도 그대로 남았을 구조적 결함이다.

---

## 2. 원인 — DOM 이 매초 사라졌다 다시 생긴다

문제의 코드는 한 줄이다.

```javascript
setInterval(render, 1000);
```

그리고 `render()` 는 이렇게 생겼다.

```javascript
function render() {
    var items = load();
    listEl.innerHTML = items.length
        ? items.map(itemHtml).join('')      // ← 문자열로 HTML 전체를 다시 만든다
        : '<div class="ka-empty">등록된 세션이 없습니다.</div>';
}
```

`innerHTML` 에 값을 대입하면 브라우저는 **그 안의 모든 자식 노드를 버리고, 문자열을 새로 파싱해 노드를 처음부터 만든다.**

즉 1초마다 이런 일이 벌어진다.

```
0.0초   <div class="ka-status-line">0/12 회 · 주기 58:00</div>   ← 이 노드를 드래그 중
1.0초   기존 노드 전부 폐기
        똑같이 생겼지만 완전히 다른 새 노드 생성
2.0초   또 폐기, 또 생성
```

**겉보기에 같은 글자라도 브라우저에게는 매번 다른 물건이다.**

---

## 3. 왜 선택이 풀리는가

브라우저의 텍스트 선택(`Selection`)은 **"어느 노드의 몇 번째 글자부터 몇 번째까지"** 라는 방식으로 기억한다.

```
Selection = { 시작: (노드A, 3글자), 끝: (노드A, 12글자) }
```

그런데 노드A 가 사라지면 이 좌표가 가리킬 곳이 없어진다. 브라우저는 선택을 버리거나,
가장 가까운 조상 노드로 범위를 넓혀 잡는다. 그래서 두 증상이 나타난다.

| 증상 | 브라우저가 한 일 |
|---|---|
| 드래그가 풀림 | 선택 범위가 가리키던 노드가 사라져 선택을 폐기 |
| 엉뚱한 영역까지 잡힘 | 사라진 노드 대신 살아있는 조상으로 범위를 확대 |

마우스를 누른 채 드래그하는 중에도 1초 뒤 노드가 교체되므로, **긁는 동작 자체가 중간에 끊긴다.**

> 책의 한 문장에 손가락을 얹어뒀는데, 1초마다 누가 그 책을 똑같이 생긴 새 책으로
> 바꿔치기하는 상황이다. 내용은 같아도 손가락이 짚고 있던 자리는 사라진다.

---

## 4. 기존 방식 vs 수정 방식

핵심은 **"매초 실제로 바뀌는 것이 무엇인가"** 를 따지는 것이다.

목록 한 줄에서 1초마다 바뀌는 값은 딱 두 개다.

```
57:54                                    ← 카운트다운 숫자
0/12 회 · 주기 58:00 · 다음 16:41:27      ← 상태 줄 (다음 전송 시각)
```

제목, 세션 ID, 프로젝트명, 버튼, 토큰 표시는 **데이터가 바뀌기 전까지 그대로**다.
그런데 기존 방식은 바뀌지 않는 것까지 전부 다시 만들었다.

| | 기존 (`render` 매초) | 수정 (`tick` 매초) |
|---|---|---|
| 매초 하는 일 | `innerHTML` 전체 재작성 | 글자 2개만 `textContent` 교체 |
| 만들어지는 노드 | 항목당 십수 개 × 매초 | **0개** |
| 드래그 선택 | 매초 파괴 | 유지 |
| 버튼 | 매초 새로 생성 | 그대로 (포커스도 유지) |
| 스크롤·입력 상태 | 초기화 위험 | 영향 없음 |
| 전체 재작성 시점 | 매초 | 데이터가 바뀔 때만 (등록·삭제·토글) |

### 그림으로

```
[기존]  매초 ────────────────────────────────
        ┌─────────────────────────────┐
        │ 전부 버림 → 문자열 파싱 → 전부 생성 │   ← 선택·포커스가 여기서 증발
        └─────────────────────────────┘

[수정]  매초 ────────────────────────────────
        카운트다운.textContent = "57:54"      ← 글자만 갈아끼움. 노드는 그대로
        상태줄.textContent    = "0/12 회 …"

        데이터 변경 시에만 ──────────────────
        ┌─────────────────────────────┐
        │ 전부 버림 → 파싱 → 전부 생성      │   ← 이때는 어차피 화면이 바뀌어야 함
        └─────────────────────────────┘
```

---

## 5. 수정한 파일과 위치

### 고친 파일 — 1개

```
claude_code_log/html/templates/components/keepalive_script.js
```

이 파일 하나만 고쳤다. CSS·HTML 은 건드리지 않았다 — **문제는 보이는 모양이 아니라
갱신 방식**이었기 때문이다.

| 위치 | 변경 |
|---|---|
| `itemHtml()` | 상태 계산을 밖으로 빼고, 항목에 `data-ka-id` 부착 |
| **`computeState()`** | **신규** — 상태 판정을 한 곳으로 모음 |
| **`statusLine()`** | **신규** — 상태 줄 문자열 생성 분리 |
| **`tick()`** | **신규** — 매초 글자만 교체 |
| 마지막 줄 | `setInterval(render, 1000)` → `setInterval(tick, 1000)` |

### 전후 대조용 전문

발췌가 아니라 **관련 코드 전체**를 따로 보관해 두었다. 나란히 열어 비교할 수 있다.

| | 파일 |
|---|---|
| 수정 이전 | [`dev-docs/troubleshoot/dom-rebuild-BEFORE.js`](dev-docs/troubleshoot/dom-rebuild-BEFORE.js) |
| 수정 이후 | [`dev-docs/troubleshoot/dom-rebuild-AFTER.js`](dev-docs/troubleshoot/dom-rebuild-AFTER.js) |

두 파일은 **보관용이라 빌드에 들어가지 않고 실행되지도 않는다.** 같은 순서로 배치해
두었으므로 위에서 아래로 대조하면 무엇이 달라졌는지 바로 보인다.

```bash
# 차이만 보고 싶다면
diff dev-docs/troubleshoot/dom-rebuild-BEFORE.js dev-docs/troubleshoot/dom-rebuild-AFTER.js
```

---

## 6. 수정한 코드

### ① 상태 계산을 함수로 분리

`render()` 안에 있던 계산을 꺼내서 `render()` 와 `tick()` 이 **함께 쓰도록** 했다.
같은 규칙을 두 곳에 복사하면 언젠가 어긋나기 때문이다.

```javascript
function computeState(it, info) {
    var now = Date.now();
    var base = it.lastAt ? Date.parse(it.lastAt) : now;
    var nextAt = base + it.interval * 1000;
    var left = Math.round((nextAt - now) / 1000);
    ...
    return { cls: '', text: fmtDuration(left), note: '', nextAt: nextAt };
}
```

### ② 항목마다 식별자를 붙임

나중에 그 노드를 **찾아가려면** 표식이 있어야 한다.

```javascript
'<div class="ka-item" data-ka-id="' + it.id + '">'
```

### ③ `tick()` — 글자만 교체

```javascript
// 매초 하는 일은 "숫자 갱신"뿐이다.
// innerHTML 을 다시 쓰면 DOM 이 통째로 교체되어 드래그 선택이 풀리고 복사를 할 수 없다.
// 그래서 바뀌는 글자만 textContent 로 갈아끼운다.
function tick() {
    var items = load();
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var node = listEl.querySelector('.ka-item[data-ka-id="' + it.id + '"]');
        if (!node) continue;
        var st = computeState(it, lookupSession(it.id));

        var cd = node.querySelector('.ka-countdown');
        if (cd && cd.textContent !== st.text) cd.textContent = st.text;   // ← 값이 같으면 손도 안 댄다

        var line = node.querySelector('.ka-status-line');
        var text = statusLine(it, info, st);
        if (line && line.textContent !== text) line.textContent = text;

        var want = 'ka-item' + (st.cls ? ' ' + st.cls : '');
        if (node.className !== want) node.className = want;
    }
}
```

**`!==` 비교를 넣은 이유** — 같은 값을 다시 대입해도 브라우저는 텍스트 노드를 교체한다.
1초에 한 번이라도 불필요한 교체는 줄이는 게 맞다.

### ④ 호출을 바꿈

```javascript
// 기존
setInterval(render, 1000);

// 수정
setInterval(tick, 1000);      // 매초는 글자만
// render() 는 등록·삭제·토글 등 데이터가 바뀔 때만 호출
```

---

## 7. 검증 방법

눈으로 보는 대신 **선택 내용이 유지되는지**를 코드로 확인했다.

```python
# 상태 줄 전체를 프로그램으로 선택
await page.evaluate("""() => {
    const el = document.querySelector('.ka-status-line');
    const r = document.createRange();
    r.selectNodeContents(el);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
}""")

sel_before = await page.evaluate("window.getSelection().toString().trim()")
await page.wait_for_timeout(3200)          # tick 3회 이상 발생
sel_after = await page.evaluate("window.getSelection().toString().trim()")

assert sel_before == sel_after             # 선택이 살아있어야 한다
```

동시에 **카운트다운은 계속 흘러야** 한다 — 선택을 지키느라 갱신을 멈춘 게 아님을 확인한다.

```
[PASS] 3초 후 선택 유지: 유지됨
       선택 내용: 0/12 회 · 주기 58:00 · 다음 16:41:27
[PASS] 카운트다운은 계속 진행: 57:56 → 57:54
[PASS] 카운트다운 갱신 후에도 선택 유지
```

---

## 8. 일반화 — 언제 이 문제가 생기나

`innerHTML` 재작성은 **간단해서 자주 쓰이지만**, 주기적으로 반복하면 다음이 전부 날아간다.

| 잃는 것 | 사용자에게 보이는 증상 |
|---|---|
| 텍스트 선택 | 드래그가 풀림 (이번 사례) |
| 포커스 | 입력 중이던 칸에서 커서가 빠짐 |
| 입력값 | `<input>` 에 치던 글자가 사라짐 |
| 스크롤 위치 | 목록이 맨 위로 튐 |
| CSS 트랜지션 | 애니메이션이 매번 처음부터 |
| 이벤트 리스너 | 개별 바인딩이면 끊김 (이벤트 위임이면 무사) |

### 판단 기준

> **"이 갱신에서 실제로 바뀌는 값이 무엇인가?"**
>
> - 값 몇 개뿐이면 → `textContent` 교체
> - 구조 자체가 바뀌면(항목 추가·삭제·순서 변경) → 그때만 전체 재작성

### 이 저장소의 다른 사례

같은 함정을 [24번 기능](CUSTOM_FEATURES.md)에서 이미 겪었다. SSE 로 새 메시지가 올 때마다
빈 프롬프트 말풍선을 **지우고 새로 만들던** 탓에, 입력 중이던 내용이 사라졌다.

그때의 해결도 같았다 — **element 를 재생성하지 않고 필요한 값만 갱신**하도록 바꿨다.

> 두 사례 모두 "새로 만드는 게 편하다"에서 출발해 "사용자가 손대고 있던 것을 잃는다"로
> 끝났다. 화면을 다시 그리기 전에 **지금 사용자가 그 화면과 무엇을 하고 있는지** 생각해야 한다.

---

## 관련 문서

- [CUSTOM_FEATURES.md](CUSTOM_FEATURES.md) — 24번(SSE 시 textarea 보존), 35번(세션 유지용 자동 메시지)
- [LIVE_SYNC.md](LIVE_SYNC.md) — SSE 로 DOM 을 갱신하는 전반 구조
