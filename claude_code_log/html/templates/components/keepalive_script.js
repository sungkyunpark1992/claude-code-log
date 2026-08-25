// 세션 유지용 자동 메시지 — 화면단.
// 등록/해제/카운트다운과 상태 표시까지 담당하고, 실제 전송은 서버가 맡는다(아직 미구현).
// 서버 API 가 붙기 전까지 설정은 localStorage 에 두고, 전송 이력은 목업으로 보여준다.
(function () {
    'use strict';

    var STORE = 'ccl:keepalive';
    var listEl = document.getElementById('kaList');
    var addBtn = document.getElementById('kaAdd');
    if (!listEl || !addBtn) return;

    var idInput = document.getElementById('kaSessionId');
    var idHint = document.getElementById('kaSessionHint');
    var minInput = document.getElementById('kaIntervalMin');
    var secInput = document.getElementById('kaIntervalSec');
    var intervalHint = document.getElementById('kaIntervalHint');
    var maxInput = document.getElementById('kaMaxCount');
    var msgInput = document.getElementById('kaMessage');
    var statusEl = document.getElementById('kaStatus');
    var countEl = document.getElementById('kaCount');

    var UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
    // 경로 구분자. RegExp 문자열 안에서는 백슬래시를 두 번 써야 리터럴 한 글자가 된다.
    var BS = String.fromCharCode(92);
    var PATH_SEP = new RegExp('[' + BS + BS + '/]');
    var MIN_INTERVAL = 20;

    function load() {
        try {
            var raw = localStorage.getItem(STORE);
            var arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function save(items) {
        try {
            localStorage.setItem(STORE, JSON.stringify(items));
        } catch (e) {
            /* 용량 초과 등 — 저장 실패는 조용히 넘긴다 */
        }
    }

    function setStatus(text, kind) {
        if (!statusEl) return;
        statusEl.className = 'fork-status' + (kind ? ' ' + kind : '');
        statusEl.textContent = text;
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // 입력값에서 세션 ID 를 뽑는다. 셋 다 받는다:
    //   1) 전체 UUID
    //   2) JSONL 전체 경로 (목록의 📋 버튼으로 복사한 것)
    //   3) 앞 8자리 (목록에 표시되는 짧은 형태)
    // 손으로 UUID 를 골라 복사하는 수고를 없애려는 것이다.
    function extractSessionId(raw) {
        var v = String(raw || '').trim().replace(/^["']|["']$/g, '');
        if (!v) return null;

        if (UUID_RE.test(v)) return v;

        // 경로 → 마지막 조각에서 .jsonl 을 떼어낸다
        if (PATH_SEP.test(v)) {
            var parts = v.split(PATH_SEP);
            var base = parts[parts.length - 1].replace(/\.jsonl$/i, '');
            if (UUID_RE.test(base)) return base;
        }

        // 앞 8자리 → 화면의 세션 목록에서 찾아 완성한다
        if (/^[0-9a-fA-F]{8}$/.test(v)) {
            var nodes = document.querySelectorAll('.session-link[data-session-id]');
            for (var i = 0; i < nodes.length; i++) {
                var sid = nodes[i].getAttribute('data-session-id') || '';
                if (sid.slice(0, 8).toLowerCase() === v.toLowerCase()) return sid;
            }
        }
        return null;
    }

    // 대시보드에 이미 렌더된 세션 목록에서 정보를 찾는다.
    // 서버 API 없이도 "실제로 있는 세션인가"를 확인할 수 있다.
    function lookupSession(sid) {
        var el = document.querySelector('.session-link[data-session-id="' + sid + '"]');
        if (!el) return null;
        var titleEl = el.querySelector('.session-title');
        var metaEl = el.querySelector('.session-link-meta');
        var stamps = el.querySelectorAll('.timestamp[data-timestamp]');
        var card = el.closest('.project-card');
        var pathEl = card ? card.querySelector('.project-jsonl-dir .jsonl-path') : null;
        var project = '';
        if (pathEl) {
            var parts = pathEl.textContent.trim().split(PATH_SEP);
            project = parts[parts.length - 1] || '';
        }
        // 카운트다운의 기준점은 "마지막 응답 시각"이다.
        // 질문 시각을 쓰면 도구를 많이 쓴 긴 작업에서 최대 15분 일찍 발동한다.
        var last = null;
        if (stamps.length) {
            var el2 = stamps[stamps.length - 1];
            last = el2.getAttribute('data-timestamp-end') || el2.getAttribute('data-timestamp');
        }
        var msgCount = 0;
        if (metaEl) {
            var m = metaEl.textContent.match(/(\d[\d,]*)\s*messages/);
            if (m) msgCount = parseInt(m[1].replace(/,/g, ''), 10);
        }
        return {
            title: (titleEl && titleEl.dataset.title) || '',
            project: project,
            messages: msgCount,
            lastAt: last
        };
    }

    function fmtDuration(sec) {
        if (sec < 0) sec = 0;
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = Math.floor(sec % 60);
        var mm = (m < 10 ? '0' : '') + m;
        var ss = (s < 10 ? '0' : '') + s;
        return h > 0 ? h + ':' + mm + ':' + ss : mm + ':' + ss;
    }

    function fmtClock(ms) {
        var d = new Date(ms);
        var p = function (n) { return (n < 10 ? '0' : '') + n; };
        return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }

    function fmtTokens(n) {
        if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
        if (n >= 1000) return Math.round(n / 1000) + 'K';
        return String(n);
    }

    function readInterval() {
        var m = parseInt(minInput.value, 10);
        var s = parseInt(secInput.value, 10);
        if (isNaN(m) || m < 0) m = 0;
        if (isNaN(s) || s < 0) s = 0;
        return m * 60 + s;
    }

    function describeInterval() {
        var total = readInterval();
        if (total < MIN_INTERVAL) {
            intervalHint.textContent = MIN_INTERVAL + '초 이상이어야 합니다.';
            intervalHint.className = 'fork-hint warn';
            return false;
        }
        intervalHint.textContent = '총 ' + total.toLocaleString() + '초마다 전송';
        intervalHint.className = 'fork-hint ok';
        return true;
    }

    function refreshForm() {
        var raw = idInput.value.trim();
        var sid = extractSessionId(raw);
        var okInterval = describeInterval();
        var problem = null;

        if (!raw) {
            idHint.textContent = '세션 ID · 앞 8자리 · JSONL 전체 경로 모두 인식합니다.';
            idHint.className = 'fork-hint';
            problem = '세션 ID 를 입력하세요.';
        } else if (!sid) {
            idHint.textContent = '세션 ID 를 알아낼 수 없습니다. UUID, 앞 8자리, 또는 JSONL 경로를 넣으세요.';
            idHint.className = 'fork-hint warn';
            problem = '세션 ID 형식이 올바르지 않습니다.';
        } else {
            var info = lookupSession(sid);
            var already = load().some(function (x) { return x.id === sid; });
            if (!info) {
                idHint.textContent = '이 대시보드에서 찾을 수 없는 세션입니다. 새로고침 후 다시 확인하세요.';
                idHint.className = 'fork-hint warn';
                problem = '존재하지 않는 세션입니다.';
            } else if (already) {
                idHint.textContent = '이미 등록된 세션입니다.';
                idHint.className = 'fork-hint warn';
                problem = '이미 등록되어 있습니다.';
            } else {
                idHint.textContent = sid.slice(0, 8) + ' · ' +
                    (info.project ? info.project + ' · ' : '') +
                    (info.title || '(제목 없음)');
                idHint.className = 'fork-hint ok';
            }
        }

        if (!problem && !okInterval) problem = '전송 주기를 확인하세요.';
        if (!problem && !msgInput.value.trim()) problem = '보낼 메시지를 입력하세요.';
        if (!problem && !(parseInt(maxInput.value, 10) > 0)) problem = '최대 횟수를 확인하세요.';

        addBtn.disabled = !!problem;
        setStatus(raw && problem ? problem : '', null);
    }

    // ── 목업 데이터 ──────────────────────────────────────────
    // 서버 API 가 붙으면 JSONL 의 usage 를 읽어 실제값으로 바뀐다.
    // 지금은 세션 크기(메시지 수)에 비례한 그럴듯한 값을 만들어 화면 구성을 확인한다.
    //
    // 각 값은 "프롬프트 1개에 딸린 모든 응답의 합"이다. 응답 하나하나가 아니다.
    function mockUsage(info, seedStr) {
        var seed = 0;
        for (var i = 0; i < seedStr.length; i++) seed = (seed * 31 + seedStr.charCodeAt(i)) % 100000;
        var base = Math.max(20000, (info.messages || 20) * 9000);
        var rows = [];
        for (var k = 0; k < 3; k++) {
            var jitter = 0.75 + (((seed + k * 7919) % 1000) / 1000) * 0.5;
            var cacheRead = Math.round(base * jitter);
            rows.push({
                cacheRead: cacheRead,
                output: 1200 + ((seed + k * 13) % 4000)
            });
        }
        return rows;
    }

    function usageHtml(it, info) {
        var rows = mockUsage(info, it.id);
        var perCycle = rows[0].cacheRead;
        var left = Math.max(it.max - it.count, 0);

        var cells = rows.map(function (r, i) {
            var total = r.cacheRead + r.output;
            return '<div class="ka-usage-row">' +
                '<span class="ka-usage-label">직전 ' + (i + 1) + '</span>' +
                '<span class="ka-usage-detail">이전 대화 다시 읽기 ' + fmtTokens(r.cacheRead) +
                    ' + 답변 생성 ' + fmtTokens(r.output) + ' = </span>' +
                '<span class="ka-usage-val">' + fmtTokens(total) + '</span>' +
            '</div>';
        }).join('');

        var badge = it.needsReload
            ? '<div class="ka-reload-badge" title="자동 메시지가 나간 뒤 VS Code 를 새로고침해야 ' +
              '대화가 갈라지지 않습니다">VS Code<br>재실행 필요</div>'
            : '';

        return '<div class="ka-usage">' +
            '<div class="ka-usage-rows">' +
            '<div class="ka-usage-head">' +
                '<span class="ka-usage-title">최근 프롬프트별 소비 토큰 <span class="ka-mock">목업</span> :</span>' +
                '<span class="ka-usage-summary">자동 메시지 1회당 이전 대화 다시 읽기 약 ' +
                    fmtTokens(perCycle) + ' · 남은 횟수 ' + left + '회면 약 ' +
                    fmtTokens(perCycle * left) + '</span>' +
            '</div>' +
            cells +
            '</div>' +
            badge +
        '</div>';
    }

    // 사용자가 실제로 질문을 보내면 자동 메시지 예산을 되돌린다.
    //
    // 횟수 상한은 "사람이 없는 동안 몇 번까지 캐시를 지킬까"를 정한 것이다.
    // 사람이 돌아와 대화를 이어갔다면 그 전제가 사라지므로 처음부터 다시 센다.
    //
    // 판별은 대시보드가 보여주는 세션의 마지막 응답 시각(info.lastAt)이
    // 우리가 마지막으로 본 값과 달라졌는지로 한다. 자동 메시지는 우리가
    // 직접 lastAt 을 갱신하므로 seenAt 과 함께 맞춰 두어 구분된다.
    function syncWithRealActivity(items) {
        var changed = false;
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var info = lookupSession(it.id);
            if (!info || !info.lastAt) continue;
            if (it.seenAt === undefined) {
                it.seenAt = info.lastAt;
                changed = true;
                continue;
            }
            if (info.lastAt !== it.seenAt) {
                it.seenAt = info.lastAt;
                it.lastAt = info.lastAt;   // 카운트다운도 그 시각부터 다시
                it.count = 0;              // 예산 원복
                delete it.needsReload;     // 사람이 이미 대화를 이어갔다
                changed = true;
            }
        }
        if (changed) save(items);
        // 호출자가 "다시 그려야 하는지"를 알 수 있어야 한다.
        // 횟수 초기화는 글자뿐 아니라 버튼·요약까지 바꾸기 때문이다.
        syncWithRealActivity.changed = changed;
        return items;
    }

    // 상태 계산은 render() 와 tick() 이 공유한다 — 매초 다시 그리지 않기 위해서다.
    function computeState(it, info) {
        var now = Date.now();
        var base = it.lastAt ? Date.parse(it.lastAt) : now;
        var nextAt = base + it.interval * 1000;
        var left = Math.round((nextAt - now) / 1000);
        var done = it.count >= it.max;

        if (!info) return { cls: 'error', text: '오류', note: '', nextAt: nextAt };
        if (done) return { cls: 'done', text: '완료', note: '', nextAt: nextAt };
        // 중지: 기능을 끈 상태. 남은 시간이 의미 없으므로 숫자를 보여주지 않는다.
        if (it.stopped) return { cls: 'stopped', text: '중지', note: '', nextAt: nextAt };
        if (!it.enabled) {
            // 일시정지해도 시계는 계속 간다. 우리가 전송을 멈춘다고 캐시가 남아 있는 것은
            // 아니기 때문이다. 숫자를 얼려두면 "아직 여유가 있다"고 오해하게 된다.
            // 0 에 닿으면 그 시점부터 캐시가 사라졌다는 뜻이므로 표식을 바꾼다.
            if (left <= 0) return { cls: 'expired', text: '00:00', note: '(캐시만료)', nextAt: nextAt };
            return { cls: 'paused', text: fmtDuration(left), note: '(일시정지)', nextAt: nextAt };
        }
        // 이미 주기가 지났다. 오래 손대지 않은 세션을 등록하면 바로 이 상태가 된다.
        // 00:00 으로 두면 "곧 0이 된다"는 뜻으로 오해되므로 상태를 글자로 보여준다.
        if (left <= 0) return { cls: 'due', text: '전송 대기', note: '', nextAt: nextAt };
        return { cls: '', text: fmtDuration(left), note: '', nextAt: nextAt };
    }

    function statusLine(it, info, st) {
        if (!info) return '세션을 찾을 수 없습니다 — 삭제되었을 수 있습니다';
        // 소진량이 아니라 남은 양을 보여준다 — 판단에 필요한 값은 "앞으로 몇 번"이다
        var remaining = Math.max(it.max - it.count, 0);
        var parts = ['남은 횟수 ' + remaining + '/' + it.max, '주기 ' + fmtDuration(it.interval)];
        if (it.enabled && it.count < it.max) parts.push('다음 ' + fmtClock(st.nextAt));
        if (it.lastSentAt) parts.push('마지막 전송 ' + fmtClock(Date.parse(it.lastSentAt)));
        return parts.join(' · ');
    }

    function itemHtml(it) {
        var info = lookupSession(it.id);
        var st = computeState(it, info);
        var missing = !info;

        // 진행 ↔ 일시정지는 한 버튼으로 토글하고, 기능을 끄는 '정지'는 따로 둔다.
        // 일시정지는 잠깐 멈추는 것, 정지는 이 세션의 자동 전송을 그만두는 것이다.
        var running = it.enabled && !it.stopped;
        var toggle = missing ? '' :
            '<button data-act="toggle" data-id="' + it.id + '" class="ka-toggle" title="' +
            (running ? '일시정지' : '재개') + '">' + (running ? '⏸' : '▶') + '</button>';
        var stop = (missing || it.stopped) ? '' :
            '<button data-act="stop" data-id="' + it.id + '" class="ka-toggle" title="정지">⏹</button>';
        // TODO: 실제 전송 기능을 붙이면 이 버튼은 지운다 (목업 확인용)
        var mock = missing ? '' :
            '<button data-act="mock" data-id="' + it.id + '" title="전송된 것처럼 상태를 갱신합니다">전송 시늉</button>';
        // 횟수를 다 쓴 뒤에도 되살릴 수단이 필요하다.
        // 재개(▶)와는 다른 결정이라 — 12회를 새로 쓰겠다는 뜻이므로 — 버튼을 따로 둔다.
        var reset = missing ? '' :
            '<button data-act="reset" data-id="' + it.id + '" title="남은 횟수를 ' +
            it.max + '회로 되돌립니다">↺ 횟수 초기화</button>';
        var del = '<button data-act="del" data-id="' + it.id + '" class="danger">삭제</button>';

        return '<div class="ka-item' + (st.cls ? ' ' + st.cls : '') + '" data-ka-id="' + it.id + '">' +
            '<div class="ka-item-main">' +
                '<span class="ka-meta">' +
                    '<span class="ka-meta-main">' + escapeHtml((info && info.title) || '(제목 없음)') + '</span>' +
                    '<span class="ka-meta-sub">' +
                        '<span class="ka-sid">' + escapeHtml(it.id.slice(0, 8)) + '</span>' +
                        (info && info.project ? ' · ' + escapeHtml(info.project) : '') +
                        // 카운트다운은 프로젝트명 바로 옆에 둔다 — 멀리 떨어지면 어느 줄의 값인지 읽기 어렵다
                        '<span class="ka-countdown">' + st.text + '</span>' +
                        '<span class="ka-countdown-note">' + st.note + '</span>' +
                    '</span>' +
                '</span>' +
            '</div>' +
            // 프로젝트 이름이 길어져도 밀리지 않도록 상태와 버튼은 다음 줄에 둔다
            '<div class="ka-item-second">' +
                '<span class="ka-status-line">' + escapeHtml(statusLine(it, info, st)) + '</span>' +
                '<span class="ka-btns">' + toggle + stop + reset + mock + del + '</span>' +
            '</div>' +
            (missing ? '' : usageHtml(it, info)) +
        '</div>';
    }

    function render() {
        var items = syncWithRealActivity(load());
        countEl.textContent = String(items.length);
        listEl.innerHTML = items.length
            ? items.map(itemHtml).join('')
            : '<div class="ka-empty">등록된 세션이 없습니다.</div>';
    }

    // 매초 하는 일은 "숫자 갱신"뿐이다.
    // innerHTML 을 다시 쓰면 DOM 이 통째로 교체되어 드래그 선택이 풀리고 복사를 할 수 없다.
    // 그래서 바뀌는 글자만 textContent 로 갈아끼운다.
    function tick() {
        var items = syncWithRealActivity(load());
        if (syncWithRealActivity.changed) {
            // 실제 대화가 감지되어 횟수가 되돌아갔다 — 구조가 바뀌었으므로 전체를 다시 그린다.
            // 이때만큼은 innerHTML 재작성이 맞다(선택을 잃더라도 화면이 정확해야 한다).
            render();
            return;
        }
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var node = listEl.querySelector('.ka-item[data-ka-id="' + it.id + '"]');
            if (!node) continue;
            var info = lookupSession(it.id);
            var st = computeState(it, info);

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

    addBtn.addEventListener('click', function () {
        if (addBtn.disabled) return;
        var sid = extractSessionId(idInput.value);
        if (!sid) return;
        var info = lookupSession(sid);
        var items = load();
        items.push({
            id: sid,
            interval: readInterval(),
            max: parseInt(maxInput.value, 10),
            message: msgInput.value.trim(),
            enabled: true,
            count: 0,
            lastAt: info ? info.lastAt : null,
            seenAt: info ? info.lastAt : undefined,
            lastSentAt: null
        });
        save(items);
        idInput.value = '';
        render();
        refreshForm();
        setStatus('등록했습니다. 전송 로직이 연결되면 실제로 동작합니다.', 'success');
    });

    listEl.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-act]');
        if (!btn) return;
        var id = btn.getAttribute('data-id');
        var act = btn.getAttribute('data-act');
        var items = load();
        var idx = -1;
        for (var i = 0; i < items.length; i++) {
            if (items[i].id === id) { idx = i; break; }
        }
        if (idx < 0) return;

        if (act === 'del') {
            items.splice(idx, 1);
        } else if (act === 'toggle') {
            var target = items[idx];
            if (target.enabled && !target.stopped) {
                // 일시정지 — 전송만 멈춘다. 카운트다운은 그대로 흐른다.
                target.enabled = false;
            } else if (target.stopped) {
                // 정지 상태에서 재개하면 주기를 처음부터 다시 센다
                target.stopped = false;
                target.enabled = true;
                target.lastAt = new Date().toISOString();
            } else {
                // 일시정지에서 재개 — 시계는 멈춘 적이 없으므로 되돌릴 것이 없다
                target.enabled = true;
            }
        } else if (act === 'reset') {
            // 예산만 되돌린다. 진행/정지 상태와 주기는 건드리지 않는다.
            items[idx].count = 0;
        } else if (act === 'stop') {
            // 정지: 이 세션의 자동 전송을 그만둔다. 남은 시간도 버린다.
            items[idx].stopped = true;
            items[idx].enabled = false;
        } else if (act === 'mock') {
            // 목업: 실제로 보내지 않고 "보낸 것처럼" 상태만 갱신한다.
            // 전송이 일어났다는 것은 곧 동작 중이라는 뜻이므로,
            // 멈춰 있었더라도 진행 상태로 되돌리고 주기를 다시 센다.
            var nowIso = new Date().toISOString();
            items[idx].count = Math.min(items[idx].count + 1, items[idx].max);
            items[idx].lastAt = nowIso;
            items[idx].lastSentAt = nowIso;
            items[idx].enabled = true;
            items[idx].stopped = false;
            // 자동 메시지가 나가면 VS Code 의 메모리와 파일이 어긋난다.
            // 사용자가 다시 대화하기 전에 새로고침해야 대화가 갈라지지 않는다.
            items[idx].needsReload = true;
        }
        save(items);
        render();
        refreshForm();
    });

    [idInput, minInput, secInput, maxInput, msgInput].forEach(function (el) {
        if (el) el.addEventListener('input', refreshForm);
    });

    render();
    refreshForm();
    setInterval(tick, 1000);
})();
