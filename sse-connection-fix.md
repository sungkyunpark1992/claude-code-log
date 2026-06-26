# SSE 연결 슬롯 한도 초과 (무한로딩) 수정 가이드

> 이 문서는 크롬 등 브라우저의 HTTP/1.1 동시 연결 한도(origin당 6개)에 SSE 연결이 갇혀
> 세션 페이지가 "무한로딩" 상태로 보이는 문제를 해결하기 위한 작업 가이드입니다.
> 적용 베이스 커밋: 페이지네이션 원복 직후 (`32bfafc` 역방향 적용 이후)

---

## 0. 문제 요약

세션 탭 여러 개(보통 7개 이상)를 띄워놓으면 일부 탭이 영원히 "로딩 중" 상태로 멈춤. 새로고침해도 같은 증상이 반복됨.

**오해**: 처음엔 HTML 크기/렌더링 비용 때문이라고 생각해서 페이지네이션을 만들었지만, 사후 확인 결과 **페이지네이션과 무관**한 문제임이 확인되어 페이지네이션은 원복됨.

---

## 1. 진짜 원인

### 1-1. 브라우저 HTTP/1.1 동시 연결 한도

크롬은 한 origin(`localhost:5678`)당 **동시 HTTP/1.1 연결을 6개로 제한**한다. SSE(`EventSource`) 연결도 일반 HTTP 연결로 잡혀서 이 6개 슬롯을 점유함.

```
세션 탭 1~6개  → SSE 1~6개 → 슬롯 1~6 점유 → 정상
세션 탭 7개째  → SSE 7번째   → 큐에서 대기      → 페이지 무한 로딩
```

### 1-2. 연결 정리가 늦음

새로고침/탭 닫기 시 기존 SSE 연결이 즉시 끊기지 않으면, 새 페이지가 만든 SSE도 큐에 갇힘. 두 가지 측면에서 정리가 늦어짐:

- **서버 측**: Flask가 응답 본문을 버퍼링하여 끊김 감지가 느림
- **클라이언트 측**: `EventSource`는 페이지 unload 시 즉시 닫히지 않고 브라우저 구현에 따라 잠시 살아남음

---

## 2. 수정 파일 목록 (2개)

| 파일 | 변경 |
|---|---|
| `claude_code_log/server.py` | `stream_session` 반환 `Response`에 `direct_passthrough=True` 추가 |
| `claude_code_log/html/templates/transcript.html` | SSE IIFE 안에 `pagehide` 이벤트 핸들러 추가 |

---

## 3. Fix 1: `claude_code_log/server.py` — `direct_passthrough=True`

### 위치

`stream_session(session_id)` 함수의 마지막 `return Response(...)` (현재 line ~428).

### BEFORE

```python
return Response(
    generate(),
    mimetype="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
)
```

### AFTER

```python
return Response(
    generate(),
    mimetype="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    direct_passthrough=True,  # Flask 버퍼링 비활성화 → 즉시 전송 + 끊김 빠른 감지
)
```

### 동작 원리

- Flask `Response`의 기본 `direct_passthrough=False`는 응답 본문을 **버퍼링**한다. 제너레이터가 `yield`한 데이터를 모았다가 한 번에 보내거나, 미들웨어가 끼어들 수 있음.
- SSE에는 부적합 — 메시지/keepalive(`:\n\n`)가 즉시 클라이언트로 가야 함.
- `X-Accel-Buffering: no` 헤더는 nginx한테만 "버퍼링 마라" 신호이고, **Flask 본인의 버퍼링은 못 막음**.
- `direct_passthrough=True`로 Flask가 제너레이터의 bytes를 즉시 통과시킴 → 클라이언트 끊김을 서버가 빠르게 감지 → 슬롯 회수가 빨라짐.

---

## 4. Fix 2: `claude_code_log/html/templates/transcript.html` — `pagehide` close

### 위치

`<!-- Live update via SSE -->` 블록의 IIFE 안, `var source = new EventSource(...)` **바로 뒤** (현재 line ~1227).

### BEFORE

```javascript
(function() {
    var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
    if (!match) return;
    var sessionId = match[1];
    var source = new EventSource('/api/sessions/' + sessionId + '/stream');
    var updating = false;
    // ... 이하 onmessage / onerror / onopen ...
})();
```

### AFTER

```javascript
(function() {
    var match = window.location.pathname.match(/session-([a-f0-9-]+)\.html/);
    if (!match) return;
    var sessionId = match[1];
    var source = new EventSource('/api/sessions/' + sessionId + '/stream');

    // 페이지를 떠날 때 SSE 명시적으로 close → 브라우저 6 슬롯이 즉시 비도록.
    // 'pagehide'는 'beforeunload'보다 신뢰성 높음 (모바일/bfcache 호환).
    window.addEventListener('pagehide', function() {
        try { source.close(); } catch (e) {}
    });

    var updating = false;
    // ... 이하 onmessage / onerror / onopen ...
})();
```

### 동작 원리

- `EventSource`는 페이지가 닫히면 알아서 닫혀야 하지만, **실제로는 즉시 닫히지 않는 경우가 많다**:
  - **새로고침** — 새 페이지 로드와 기존 페이지 정리가 겹쳐서 잠시 동안 SSE 2개가 동시에 존재 가능
  - **탭 닫기** — 브라우저 구현에 따라 TCP FIN이 늦게 감
- 크롬은 6 슬롯 제한이 엄격해서 이 잠시의 중복이 다음 연결을 큐에 갇히게 함.
- `pagehide` 핸들러에서 `source.close()`를 명시적으로 호출하면 클라이언트가 즉시 TCP 종료 신호를 보내 서버 슬롯이 빨리 회수됨.

### 왜 `pagehide`? `beforeunload`가 아닌 이유

- `beforeunload`는 **모바일 사파리에서 발화 안 됨** (실패)
- `beforeunload`는 **bfcache(뒤로가기 캐시)와 충돌**해서 페이지가 캐시되지 않게 만듦 (성능 손실)
- `pagehide`는 위 두 문제 모두 없고, 페이지 unload + bfcache 진입 모두에서 안정적으로 발화함
- `pagehide` 핸들러 안에서 `EventSource.close()`만 호출하므로 bfcache 차단 부작용 없음

---

## 5. 동작 검증 시나리오

1. 서버 재기동: `claude-code-log --serve`
2. 크롬에서 **세션 탭 7개** 열기 (모두 `localhost:5678/.../session-xxx.html`)
3. 마지막(7번째) 탭이 정상 로드되는지 확인
4. 7번째 탭에서 새로고침 → 무한로딩 없이 즉시 로드되는지 확인
5. 크롬 DevTools → Network → "EventStream" 필터 → 각 탭마다 활성 SSE 1개씩, 페이지 unload 시 즉시 `(canceled)` 또는 `(closed)`로 끝나는지 확인
6. 서버 로그에서 `[SSE] watchdog watching ...` 메시지 직후 페이지 닫으면 짧은 간격 안에 keepalive 멈춤 + 연결 닫힘이 보여야 함

---

## 6. 동작/한계 메모

### 작동

- 세션 탭 1~6개 환경에서는 fix 없이도 정상 동작 (슬롯 한도 미도달)
- 세션 탭 7개 이상 환경에서 fix 적용 후 무한로딩 사라짐 (테스트 필요)
- 새로고침 빠르게 반복해도 슬롯 누적 없음
- 페이지 닫기 시 서버 측 SSE 제너레이터의 `finally` 블록이 빠르게 실행됨 → `observer.stop()`이 즉시 호출됨

### 한계

- **근본적으로 HTTP/1.1의 6 연결 한도가 원인** — 두 fix는 슬롯 회전을 빠르게 할 뿐, 한도 자체는 그대로
- **동시에 7+ 탭 사용 시 잠깐 큐 대기**: fix 적용해도 7번째 탭 SSE는 어쩔 수 없이 6개 중 하나가 끝날 때까지 기다림. 다만 보통 keepalive 코멘트만 흐르는 idle 슬롯이라 곧 회전됨
- **`window.close()` 호출 시 발화 안 함**: 사용자가 X로 닫을 때만 `pagehide` 발화. JS `window.close()`로 강제 닫기는 핸들러 우회. 일반적 사용엔 무관
- **SSE 자체의 자동 재연결**: `EventSource`는 네트워크 끊기면 3초 후 자동 재연결을 시도. fix와 무관하게 동작

### 더 근본적인 fix (필요 시)

- **HTTP/2 또는 HTTP/3 사용**: 크롬이 origin당 ~100개 동시 스트림 허용. Flask 개발 서버는 HTTP/2 미지원 → ASGI 서버(`hypercorn`, `uvicorn`)로 전환하거나 nginx 앞단 두기. 작업 규모 큼.
- **단일 SSE 채널로 다중화**: 세션별 `/api/sessions/{id}/stream` 대신 전역 `/api/stream` 하나만 사용하고 메시지에 `{sessionId, type}` 포함. 슬롯 1개만 사용. 코드 구조 변경 필요.
- **WebSocket으로 전환**: SSE는 단방향이라 단순한 다중화도 어려움. WS는 양방향 + 다중화 친화적. 다만 클라이언트/서버 양쪽 코드 모두 바꿔야 함.

세션 탭을 일상적으로 6개 이하로 쓰면 본 fix만으로 충분. 7+ 탭을 정기적으로 띄울 일이 있으면 HTTP/2 전환이 정답.

---

## 7. 적용 체크리스트

작업 진행 시 순서대로:

- [ ] `claude_code_log/server.py` `stream_session` 함수 — `Response(...)`에 `direct_passthrough=True` 추가
- [ ] `claude_code_log/html/templates/transcript.html` SSE IIFE — `var source = new EventSource(...)` 직후에 `pagehide` 핸들러 추가
- [ ] 서버 재기동
- [ ] 크롬에서 세션 탭 7개 열기 → 마지막 탭 정상 로드 확인
- [ ] 새로고침 반복 → 무한로딩 없는지 확인
- [ ] DevTools Network 패널에서 SSE 종료 타이밍 확인
- [ ] `CUSTOM_FEATURES.md`에 항목 추가 (커밋 히스토리 표 + 필요 시 별도 섹션)
- [ ] 본 가이드 문서 (`sse-connection-fix.md`) 삭제 또는 "완료" 표기

---

## 부록: 페이지네이션과 같이 했을 때 잘못 알았던 점

페이지네이션 도입(`32bfafc`) 당시 "큰 페이지면 무한로딩"이라고 진단했지만, 실제로는 페이지 크기 자체와 무관했음. 원인 분석을 다시 했을 때 [pagenation.md](pagenation.md) 의 "무한로딩 문제와의 관계" 섹션에 다음과 같이 정리됨:

> - 이 페이지네이션은 무한로딩 문제와 직접 무관함이 사후 확인됨
> - 무한로딩의 진짜 원인: SSE 연결이 새로고침 시 제때 정리되지 않아 브라우저 동시 연결 슬롯 6개 한도 초과
> - 진짜 fix는 server.py의 SSE keepalive timeout 단축 + direct_passthrough=True (별도 작업)

이 별도 작업이 본 문서의 fix.
