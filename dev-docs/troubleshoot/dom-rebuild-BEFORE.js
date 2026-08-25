// ─────────────────────────────────────────────────────────────
//  수정 "이전" 코드 — 문제가 있던 버전
//
//  실제 파일: claude_code_log/html/templates/components/keepalive_script.js
//  문제      : 매초 innerHTML 을 통째로 다시 써서 드래그 선택이 풀린다
//  상세      : ../../TROUBLESHOOT_DOM_REBUILD.md
//
//  ⚠️ 이 파일은 보관용이다. 빌드에 포함되지 않으며 실행되지도 않는다.
//     문제의 구조를 보여주기 위해 관련 부분만 발췌했다.
// ─────────────────────────────────────────────────────────────

// ── 1. 상태 계산이 itemHtml() 안에 묻혀 있었다 ────────────────
//     render() 만 이 계산을 할 수 있어서, "글자만 갱신"하는 길이 없었다.

function itemHtml(it) {
    var info = lookupSession(it.id);
    var missing = !info;
    var now = Date.now();
    var base = it.lastAt ? Date.parse(it.lastAt) : now;
    var nextAt = base + it.interval * 1000;
    var left = Math.round((nextAt - now) / 1000);
    var done = it.count >= it.max;

    // 상태 판정도 여기 섞여 있다
    var cls = 'ka-item';
    var countdown;
    if (missing) {
        cls += ' error';
        countdown = '오류';
    } else if (done) {
        cls += ' done';
        countdown = '완료';
    } else if (!it.enabled) {
        cls += ' paused';
        countdown = '중지';
    } else if (left <= 0) {
        cls += ' due';
        countdown = '전송 대기';
    } else {
        countdown = fmtDuration(left);
    }

    var sub;
    if (missing) {
        sub = '세션을 찾을 수 없습니다 — 삭제되었을 수 있습니다';
    } else {
        sub = (info.project ? info.project + ' · ' : '') +
            it.count + '/' + it.max + ' 회 · 주기 ' + fmtDuration(it.interval);
        if (it.enabled && !done) sub += ' · 다음 ' + fmtClock(nextAt);
        if (it.lastSentAt) sub += ' · 마지막 전송 ' + fmtClock(Date.parse(it.lastSentAt));
    }

    var live = it.enabled
        ? '<button data-act="skip" data-id="' + it.id + '">건너뛰기</button>' +
          '<button data-act="pause" data-id="' + it.id + '">중지</button>'
        : '<button data-act="resume" data-id="' + it.id + '">재개</button>';
    var del = '<button data-act="del" data-id="' + it.id + '" class="danger">삭제</button>';
    var btns = missing ? del : live + del;

    // 항목을 식별할 표식(data-ka-id)이 없다 → 나중에 찾아갈 수 없다
    return '<div class="' + cls + '">' +
        '<span class="ka-countdown">' + countdown + '</span>' +
        '<span class="ka-meta">' +
            '<span class="ka-meta-main">' + escapeHtml((info && info.title) || '(제목 없음)') + '</span>' +
            '<span class="ka-meta-sub"><span class="ka-sid">' + escapeHtml(it.id.slice(0, 8)) +
                '</span> · ' + escapeHtml(sub) + '</span>' +
        '</span>' +
        '<span class="ka-btns">' + btns + '</span>' +
    '</div>';
}


// ── 2. render() — 목록 전체를 문자열로 다시 만든다 ────────────
//     innerHTML 대입은 기존 자식 노드를 전부 버리고 새로 파싱한다.

function render() {
    var items = load();
    countEl.textContent = String(items.length);
    listEl.innerHTML = items.length
        ? items.map(itemHtml).join('')
        : '<div class="ka-empty">등록된 세션이 없습니다.</div>';
}


// ── 3. 문제의 한 줄 ──────────────────────────────────────────
//     1초마다 DOM 전체를 폐기·재생성한다.
//
//     그 결과:
//       · 드래그하던 텍스트 선택이 매초 사라진다
//       · 버튼 포커스가 풀린다
//       · CSS 트랜지션이 매번 처음부터 시작한다
//
//     매초 실제로 바뀌는 값은 카운트다운 숫자와 "다음 HH:MM:SS" 뿐인데,
//     제목·세션ID·프로젝트명·버튼까지 전부 다시 만들고 있었다.

render();
refreshForm();
setInterval(render, 1000);      // ← 여기가 원인
