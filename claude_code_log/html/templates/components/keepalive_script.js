// 세션 유지용 자동 메시지 — 화면.
//
// 설정과 전송 이력은 서버(keepalive.json)가 가진다. 이 스크립트는 그것을 읽어 그리고,
// 등록·토글·정지·초기화·삭제를 API 로 넘긴다. 실제 전송은 서버 워커가 한다.
(function () {
    'use strict';

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
    var panelEl = document.getElementById('kaPanel');

    var UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
    // 경로 구분자. RegExp 문자열 안에서는 백슬래시를 두 번 써야 리터럴 한 글자가 된다.
    var BS = String.fromCharCode(92);
    var PATH_SEP = new RegExp('[' + BS + BS + '/]');
    var MIN_INTERVAL = 20;

    // 서버가 준 마지막 목록. tick 이 매초 이 값으로 숫자만 갱신한다.
    var items = [];

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
    //   1) 전체 UUID   2) JSONL 전체 경로   3) 앞 8자리
    // 손으로 UUID 를 골라 복사하는 수고를 없애려는 것이다.
    function extractSessionId(raw) {
        var v = String(raw || '').trim().replace(/^["']|["']$/g, '');
        if (!v) return null;
        if (UUID_RE.test(v)) return v;

        if (PATH_SEP.test(v)) {
            var parts = v.split(PATH_SEP);
            var base = parts[parts.length - 1].replace(/\.jsonl$/i, '');
            if (UUID_RE.test(base)) return base;
        }

        if (/^[0-9a-fA-F]{8}$/.test(v)) {
            var nodes = document.querySelectorAll('.session-link[data-session-id]');
            for (var i = 0; i < nodes.length; i++) {
                var sid = nodes[i].getAttribute('data-session-id') || '';
                if (sid.slice(0, 8).toLowerCase() === v.toLowerCase()) return sid;
            }
        }
        return null;
    }

    // 대시보드에 이미 렌더된 세션 목록에서 제목을 찾는다.
    function lookupTitle(sid) {
        var el = document.querySelector('.session-link[data-session-id="' + sid + '"]');
        if (!el) return null;
        var titleEl = el.querySelector('.session-title');
        return (titleEl && titleEl.dataset.title) || '';
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

    // 토큰 수는 자릿수만 맞으면 된다. 89,231 보다 89.2K 가 한눈에 들어온다.
    function fmtTokens(n) {
        n = n || 0;
        if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return String(n);
    }

    // 이 기능의 성패는 직전 문답이 캐시를 맞혔는지 하나로 갈린다.
    // 맞히면 생성이 100 토큰 안쪽, 틀리면 수십만 토큰이 든다.
    function usageVerdict(u) {
        if (!u) return null;
        var read = u.cache_read || 0;
        var made = u.cache_creation || 0;
        if (!read && !made && !(u.output || 0)) {
            return { cls: 'bad', text: '응답 실패 · 한도 초과' };
        }
        if (made > read) return { cls: 'bad', text: '캐시 재작성 — 비쌈' };
        if (made > 5000) return { cls: 'warn', text: '일부 재작성' };
        return { cls: 'good', text: '캐시 적중' };
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
            var title = lookupTitle(sid);
            var already = items.some(function (x) { return x.session_id === sid; });
            if (title === null) {
                idHint.textContent = '이 대시보드에서 찾을 수 없는 세션입니다. 새로고침 후 다시 확인하세요.';
                idHint.className = 'fork-hint warn';
                problem = '존재하지 않는 세션입니다.';
            } else if (already) {
                idHint.textContent = '이미 등록된 세션입니다.';
                idHint.className = 'fork-hint warn';
                problem = '이미 등록되어 있습니다.';
            } else {
                idHint.textContent = sid.slice(0, 8) + ' · ' + (title || '(제목 없음)');
                idHint.className = 'fork-hint ok';
            }
        }

        if (!problem && !okInterval) problem = '전송 주기를 확인하세요.';
        if (!problem && !msgInput.value.trim()) problem = '보낼 메시지를 입력하세요.';
        if (!problem && !(parseInt(maxInput.value, 10) > 0)) problem = '최대 횟수를 확인하세요.';

        addBtn.disabled = !!problem;
        setStatus(raw && problem ? problem : '', null);
    }

    // ── 상태 계산 — render() 와 tick() 이 함께 쓴다 ─────────
    function computeState(it) {
        var now = Date.now();
        var base = Date.parse(it.resume_at || it.last_response_at || '') || now;
        var nextAt = base + (it.interval || 0) * 1000;
        var left = Math.round((nextAt - now) / 1000);
        var done = (it.count || 0) >= (it.max || 0);

        if (it.missing || it.error) return { cls: 'error', text: '오류', note: '', nextAt: nextAt };
        if (done) return { cls: 'done', text: '완료', note: '', nextAt: nextAt };
        if (it.stopped) return { cls: 'stopped', text: '중지', note: '', nextAt: nextAt };
        if (!it.enabled) {
            // 일시정지해도 시계는 계속 간다. 우리가 전송을 멈춘다고 캐시가 남아 있는 것은
            // 아니기 때문이다. 0 에 닿으면 그 시점부터 캐시가 사라졌다는 뜻이다.
            if (left <= 0) return { cls: 'expired', text: '00:00', note: '(캐시만료)', nextAt: nextAt };
            return { cls: 'paused', text: fmtDuration(left), note: '(일시정지)', nextAt: nextAt };
        }
        if (left <= 0) return { cls: 'due', text: '전송 대기', note: '', nextAt: nextAt };
        return { cls: '', text: fmtDuration(left), note: '', nextAt: nextAt };
    }

    function statusLine(it, st) {
        if (it.missing) return '세션을 찾을 수 없습니다 — 삭제되었을 수 있습니다';
        if (it.error) return '오류: ' + it.error;
        // 대화 기록에 남은 마지막 실패(주로 사용 한도). 우리가 보낸 것이 아니어도
        // 캐시가 안 만들어진 상태이므로 알려야 한다.
        if (it.last_error) return '마지막 응답이 막힘 — ' + it.last_error;
        // 소진량이 아니라 남은 양을 보여준다 — 판단에 필요한 값은 "앞으로 몇 번"이다
        var remaining = Math.max((it.max || 0) - (it.count || 0), 0);
        var parts = ['남은 횟수 ' + remaining + '/' + it.max, '주기 ' + fmtDuration(it.interval)];
        if (it.enabled && !it.stopped && remaining > 0) parts.push('다음 ' + fmtClock(st.nextAt));
        if (it.last_sent_at) parts.push('마지막 전송 ' + fmtClock(Date.parse(it.last_sent_at)));
        return parts.join(' · ');
    }

    function itemHtml(it) {
        var st = computeState(it);
        var sid = it.session_id;
        var project = '';
        if (it.cwd) {
            var seg = String(it.cwd).split(PATH_SEP);
            project = seg[seg.length - 1] || '';
        }

        // 캐시가 이미 사라진 세션은 워커가 건너뛴다 — 보내봐야 새로 쓰게 되기 때문이다.
        // 그래서 "지금부터 지키겠다"는 결정은 사람이 이 버튼으로 내린다.
        // 캐시가 살아있는 동안에는 필요 없으므로 나타나지 않는다.
        // 조작 버튼(.ka-btns) 바깥에 둔다. 안에 두면 이 버튼이 사라질 때 그룹 폭이
        // 줄어 나머지 버튼이 통째로 밀리고, 방금 누르려던 자리에 다른 버튼이 온다.
        var prime = (it.missing || !it.cache_expired) ? '' :
            '<button data-act="prime" data-id="' + sid + '" class="ka-prime" ' +
            'title="캐시를 다시 만들기 위해 지금 한 번 보냅니다. 이 한 번은 비용이 큽니다.">' +
            '캐시 만료 후 메시지 보내기</button>';

        // 진행 ↔ 일시정지는 한 버튼으로 토글하고, 기능을 끄는 '정지'는 따로 둔다.
        var running = it.enabled && !it.stopped;
        var toggle = it.missing ? '' :
            '<button data-act="toggle" data-id="' + sid + '" class="ka-toggle" title="' +
            (running ? '일시정지' : '재개') + '">' + (running ? '⏸' : '▶') + '</button>';
        // 이미 정지 상태여도 버튼을 없애지 않고 잠근다. 없애면 그룹 폭이 바뀌어
        // 옆 버튼들이 밀리고, 누르려던 자리에 엉뚱한 버튼이 들어온다.
        var stop = it.missing ? '' :
            '<button data-act="stop" data-id="' + sid + '" class="ka-toggle" title="' +
            (it.stopped ? '이미 정지됨' : '정지') + '"' + (it.stopped ? ' disabled' : '') +
            '>⏹</button>';
        var reset = it.missing ? '' :
            '<button data-act="reset" data-id="' + sid + '" title="남은 횟수를 ' +
            it.max + '회로 되돌립니다">↺ 횟수 초기화</button>';
        var del = '<button data-act="delete" data-id="' + sid + '" class="danger">삭제</button>';

        // 직전 문답에서 실제로 쓴 토큰. 예상값이 아니라 JSONL 에 기록된 실측이다.
        var u = it.last_usage;
        var verdict = usageVerdict(u);
        var usageRow = '';
        if (u && verdict) {
            var total = (u.cache_read || 0) + (u.cache_creation || 0) +
                (u.input || 0) + (u.output || 0);
            usageRow =
                '<div class="ka-usage-row">' +
                    '<span class="ka-usage-label">직전 문답</span>' +
                    '<span class="ka-usage-val">' + fmtTokens(total) + '</span>' +
                    '<span class="ka-usage-detail">' +
                        '캐시읽기 ' + fmtTokens(u.cache_read) +
                        ' · 캐시생성 ' + fmtTokens(u.cache_creation) +
                        ' · 입력 ' + fmtTokens(u.input) +
                        ' · 출력 ' + fmtTokens(u.output) +
                    '</span>' +
                    '<span class="ka-usage-summary ka-verdict-' + verdict.cls + '">' +
                        escapeHtml(verdict.text) +
                    '</span>' +
                '</div>';
        }

        var reload = it.needs_reload
            ? '<div class="ka-reload-badge" title="자동 메시지가 나간 뒤 ' +
              'VS Code 를 새로고침해야 대화가 갈라지지 않습니다">VS Code<br>재실행 필요</div>'
            : '';

        var badge = (usageRow || reload)
            ? '<div class="ka-usage"><div class="ka-usage-rows">' + usageRow + '</div>' +
              reload + '</div>'
            : '';

        var title = lookupTitle(sid);
        var modelTag = it.model ? ' · ' + escapeHtml(it.model) : '';

        return '<div class="ka-item' + (st.cls ? ' ' + st.cls : '') + '" data-ka-id="' + sid + '">' +
            '<div class="ka-item-main">' +
                '<span class="ka-meta">' +
                    '<span class="ka-meta-main">' + escapeHtml(title || '(제목 없음)') + '</span>' +
                    '<span class="ka-meta-sub">' +
                        '<span class="ka-sid">' + escapeHtml(sid.slice(0, 8)) + '</span>' +
                        (project ? ' · ' + escapeHtml(project) : '') + modelTag +
                        // 카운트다운은 프로젝트명 바로 옆 — 멀리 떨어지면 어느 줄의 값인지 읽기 어렵다
                        '<span class="ka-countdown">' + st.text + '</span>' +
                        '<span class="ka-countdown-note">' + st.note + '</span>' +
                    '</span>' +
                '</span>' +
            '</div>' +
            // 프로젝트 이름이 길어져도 밀리지 않도록 상태와 버튼은 다음 줄에 둔다
            '<div class="ka-item-second">' +
                '<span class="ka-status-line">' + escapeHtml(statusLine(it, st)) + '</span>' +
                '<span class="ka-prime-slot">' + prime + '</span>' +
                '<span class="ka-btns">' + toggle + stop + reset + del + '</span>' +
            '</div>' +
            badge +
        '</div>';
    }

    function render() {
        countEl.textContent = String(items.length);
        listEl.innerHTML = items.length
            ? items.map(itemHtml).join('')
            : '<div class="ka-empty">등록된 세션이 없습니다.</div>';
    }

    // 매초 하는 일은 "숫자 갱신"뿐이다.
    // innerHTML 을 다시 쓰면 DOM 이 통째로 교체되어 드래그 선택이 풀리고 복사를 할 수 없다.
    // 그래서 바뀌는 글자만 textContent 로 갈아끼운다.
    // 상세: TROUBLESHOOT_DOM_REBUILD.md
    function tick() {
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var node = listEl.querySelector('.ka-item[data-ka-id="' + it.session_id + '"]');
            if (!node) continue;
            var st = computeState(it);

            var cd = node.querySelector('.ka-countdown');
            if (cd && cd.textContent !== st.text) cd.textContent = st.text;

            var note = node.querySelector('.ka-countdown-note');
            if (note && note.textContent !== st.note) note.textContent = st.note;

            var line = node.querySelector('.ka-status-line');
            var text = statusLine(it, st);
            if (line && line.textContent !== text) line.textContent = text;

            var want = 'ka-item' + (st.cls ? ' ' + st.cls : '');
            if (node.className !== want) node.className = want;
        }
    }

    // ── 서버와 주고받기 ─────────────────────────────────────
    // 패널을 열지 닫을지는 등록된 세션 수로 정한다. 하나라도 있으면 카운트다운을
    // 봐야 하므로 열고, 없으면 접어 자리를 비운다. 새로고침해도 같은 규칙이 다시
    // 적용되니 사람이 매번 열어줄 필요가 없다.
    // 다만 "비었다/찼다"가 바뀔 때만 건드린다 — 그 사이에 직접 접은 것은 그대로 둔다.
    var hadAny = null;

    function syncPanelOpen() {
        if (!panelEl) return;
        var any = items.length > 0;
        if (hadAny === any) return;
        hadAny = any;
        panelEl.open = any;
    }

    function applySessions(next) {
        var before = JSON.stringify(items);
        items = Array.isArray(next) ? next : [];
        // 목록이 실제로 달라졌을 때만 다시 그린다 — 선택과 포커스를 지키기 위해서다
        if (JSON.stringify(items) !== before) render();
        syncPanelOpen();
        refreshForm();
    }

    function fetchSessions() {
        return fetch('/api/keepalive')
            .then(function (r) { return r.json(); })
            .then(function (d) { applySessions(d.sessions); })
            .catch(function () { /* 서버가 잠깐 멈춘 경우 — 다음 주기에 다시 시도 */ });
    }

    function post(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        }).then(function (r) {
            return r.json().then(function (j) { return { ok: r.ok, data: j }; });
        });
    }

    addBtn.addEventListener('click', function () {
        if (addBtn.disabled) return;
        var sid = extractSessionId(idInput.value);
        if (!sid) return;
        addBtn.disabled = true;
        setStatus('등록 중…', null);

        post('/api/keepalive', {
            session_id: sid,
            interval: readInterval(),
            max: parseInt(maxInput.value, 10),
            message: msgInput.value.trim()
        }).then(function (res) {
            if (!res.ok) {
                setStatus(res.data.error || '등록에 실패했습니다.', 'error');
                refreshForm();
                return;
            }
            idInput.value = '';
            applySessions(res.data.sessions);
            setStatus('등록했습니다.', 'success');
        }).catch(function (err) {
            setStatus('요청 실패: ' + err, 'error');
            refreshForm();
        });
    });

    listEl.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-act]');
        if (!btn) return;
        var id = btn.getAttribute('data-id');
        var act = btn.getAttribute('data-act');
        btn.disabled = true;
        if (act === 'prime') {
            // 실제 전송이라 7~8초 걸린다. 아무 반응이 없으면 눌린 줄 모른다.
            btn.textContent = '보내는 중…';
            setStatus('캐시를 만드는 중입니다 — 잠시 걸립니다.', null);
        }
        post('/api/keepalive/' + id, { action: act }).then(function (res) {
            if (!res.ok) {
                setStatus(res.data.error || '변경에 실패했습니다.', 'error');
                if (res.data.sessions) applySessions(res.data.sessions);
                btn.disabled = false;
                return;
            }
            // applySessions 안의 refreshForm 이 상태 문구를 지운다.
            // 알릴 말이 있으면 목록을 갱신한 뒤에 쓴다.
            applySessions(res.data.sessions);
            if (act === 'prime') setStatus('캐시를 만들었습니다. 이제 자동으로 유지됩니다.', 'success');
        }).catch(function (err) {
            setStatus('요청 실패: ' + err, 'error');
            btn.disabled = false;
        });
    });

    [idInput, minInput, secInput, maxInput, msgInput].forEach(function (el) {
        if (el) el.addEventListener('input', refreshForm);
    });

    render();
    refreshForm();
    fetchSessions();
    setInterval(tick, 1000);
    // 서버가 전송하거나 사람이 대화를 이어가면 상태가 바뀐다. 주기적으로 받아온다.
    setInterval(fetchSessions, 5000);
})();
