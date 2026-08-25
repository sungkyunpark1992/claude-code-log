// ─────────────────────────────────────────────────────────────
//  수정 "이후" 코드 — 선택이 유지되는 버전
//
//  실제 파일: claude_code_log/html/templates/components/keepalive_script.js
//  해결      : 매초는 글자만 교체하고, 전체 재작성은 데이터가 바뀔 때만
//  상세      : ../../TROUBLESHOOT_DOM_REBUILD.md
//
//  ⚠️ 이 파일은 보관용이다. 빌드에 포함되지 않으며 실행되지도 않는다.
//     BEFORE 와 대조할 수 있게 같은 순서로 배치했다.
// ─────────────────────────────────────────────────────────────

// ── 1. 상태 계산을 함수로 꺼냈다 ─────────────────────────────
//     render() 와 tick() 이 같은 규칙을 공유한다.
//     복사해두면 언젠가 한쪽만 고쳐 어긋나기 때문에 반드시 한 곳에 둔다.

function computeState(it, info) {
    var now = Date.now();
    var base = it.lastAt ? Date.parse(it.lastAt) : now;
    var nextAt = base + it.interval * 1000;
    var left = Math.round((nextAt - now) / 1000);
    var done = it.count >= it.max;

    if (!info) return { cls: 'error', text: '오류', note: '', nextAt: nextAt };
    if (done) return { cls: 'done', text: '완료', note: '', nextAt: nextAt };
    if (it.stopped) return { cls: 'stopped', text: '중지', note: '', nextAt: nextAt };
    if (!it.enabled) {
        var frozen = typeof it.pausedLeft === 'number' ? it.pausedLeft : Math.max(left, 0);
        return { cls: 'paused', text: fmtDuration(frozen), note: '(일시정지)', nextAt: nextAt };
    }
    if (left <= 0) return { cls: 'due', text: '전송 대기', nextAt: nextAt, note: '' };
    return { cls: '', text: fmtDuration(left), note: '', nextAt: nextAt };
}

// 상태 줄도 마찬가지로 분리했다 — tick() 이 이 문자열만 갈아끼운다.
function statusLine(it, info, st) {
    if (!info) return '세션을 찾을 수 없습니다 — 삭제되었을 수 있습니다';
    var parts = [it.count + '/' + it.max + ' 회', '주기 ' + fmtDuration(it.interval)];
    if (it.enabled && it.count < it.max) parts.push('다음 ' + fmtClock(st.nextAt));
    if (it.lastSentAt) parts.push('마지막 전송 ' + fmtClock(Date.parse(it.lastSentAt)));
    return parts.join(' · ');
}


// ── 2. itemHtml() — 항목에 식별자를 붙였다 ────────────────────
//     data-ka-id 가 있어야 tick() 이 그 노드를 다시 찾아갈 수 있다.
//     매초 바뀌는 값은 각각 전용 span 으로 감쌌다.

function itemHtml(it) {
    var info = lookupSession(it.id);
    var st = computeState(it, info);
    var missing = !info;

    var running = it.enabled && !it.stopped;
    var toggle = missing ? '' :
        '<button data-act="toggle" data-id="' + it.id + '" class="ka-toggle" title="' +
        (running ? '일시정지' : '재개') + '">' + (running ? '⏸' : '▶') + '</button>';
    var stop = (missing || it.stopped) ? '' :
        '<button data-act="stop" data-id="' + it.id + '" class="ka-toggle" title="정지">⏹</button>';
    var skip = (missing || !running) ? '' :
        '<button data-act="skip" data-id="' + it.id + '">건너뛰기</button>';
    var del = '<button data-act="del" data-id="' + it.id + '" class="danger">삭제</button>';

    return '<div class="ka-item' + (st.cls ? ' ' + st.cls : '') + '" data-ka-id="' + it.id + '">' +
        //                                                        ↑ 식별자
        '<div class="ka-item-main">' +
            '<span class="ka-meta">' +
                '<span class="ka-meta-main">' + escapeHtml((info && info.title) || '(제목 없음)') + '</span>' +
                '<span class="ka-meta-sub">' +
                    '<span class="ka-sid">' + escapeHtml(it.id.slice(0, 8)) + '</span>' +
                    (info && info.project ? ' · ' + escapeHtml(info.project) : '') +
                    '<span class="ka-countdown">' + st.text + '</span>' +       // ← 매초 바뀜
                    '<span class="ka-countdown-note">' + st.note + '</span>' +  // ← 매초 바뀜
                '</span>' +
            '</span>' +
        '</div>' +
        '<div class="ka-item-second">' +
            '<span class="ka-status-line">' + escapeHtml(statusLine(it, info, st)) + '</span>' +
            //     ↑ 매초 바뀜 (다음 전송 시각)
            '<span class="ka-btns">' + toggle + stop + skip + del + '</span>' +
        '</div>' +
    '</div>';
}


// ── 3. render() — 그대로 두되, 호출 시점을 바꿨다 ─────────────
//     구조가 바뀔 때(등록·삭제·토글)만 부른다. 매초 부르지 않는다.

function render() {
    var items = load();
    countEl.textContent = String(items.length);
    listEl.innerHTML = items.length
        ? items.map(itemHtml).join('')
        : '<div class="ka-empty">등록된 세션이 없습니다.</div>';
}


// ── 4. tick() — 새로 만든 함수. 매초 하는 일은 이것뿐 ─────────
//     노드를 만들지 않는다. 이미 있는 노드의 글자만 바꾼다.
//     그래서 드래그 선택·포커스·스크롤이 그대로 유지된다.

function tick() {
    var items = load();
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var node = listEl.querySelector('.ka-item[data-ka-id="' + it.id + '"]');
        if (!node) continue;                       // 아직 안 그려졌으면 건너뛴다
        var info = lookupSession(it.id);
        var st = computeState(it, info);

        // 값이 같으면 손도 대지 않는다.
        // 같은 값을 다시 대입해도 브라우저는 텍스트 노드를 교체한다.
        var cd = node.querySelector('.ka-countdown');
        if (cd && cd.textContent !== st.text) cd.textContent = st.text;

        var note = node.querySelector('.ka-countdown-note');
        if (note && note.textContent !== st.note) note.textContent = st.note;

        var line = node.querySelector('.ka-status-line');
        var text = statusLine(it, info, st);
        if (line && line.textContent !== text) line.textContent = text;

        var want = 'ka-item' + (st.cls ? ' ' + st.cls : '');
        if (node.className !== want) node.className = want;
    }
}


// ── 5. 호출 ─────────────────────────────────────────────────

render();                       // 처음 한 번
refreshForm();
setInterval(tick, 1000);        // ← 매초는 글자만. render 가 아니다

// render() 는 아래 시점에만 호출된다:
//   · 세션 등록      (addBtn 클릭)
//   · 삭제·토글·정지 (listEl 클릭 핸들러)
// 즉 "화면 구조가 실제로 달라지는" 순간에만 다시 그린다.
