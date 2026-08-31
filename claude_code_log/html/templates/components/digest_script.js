// 문답만 추려 .md 로 받기 — 대시보드 쪽.
//
// 세션 화면(message_export.html)에도 같은 버튼이 있다. 쓰임이 달라 둘 다 둔다:
// 대시보드는 "어느 세션이든 골라서", 세션 화면은 "보던 대화를 바로".
(function () {
    'use strict';

    var idInput = document.getElementById('digestSessionId');
    var hintEl = document.getElementById('digestHint');
    var allBox = document.getElementById('digestAll');
    var btn = document.getElementById('digestSubmit');
    var statusEl = document.getElementById('digestStatus');
    if (!idInput || !btn) return;

    var UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
    // 경로 구분자. RegExp 문자열 안에서는 백슬래시를 두 번 써야 리터럴 한 글자가 된다.
    var BS = String.fromCharCode(92);
    var PATH_SEP = new RegExp('[' + BS + BS + '/]');

    // 세션 유지 패널과 같은 규칙 — UUID · 전체 경로 · 앞 8자리를 모두 받는다.
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

    function lookupTitle(sid) {
        var el = document.querySelector('.session-link[data-session-id="' + sid + '"]');
        if (!el) return null;
        var t = el.querySelector('.session-title');
        return (t && t.dataset.title) || '';
    }

    function setStatus(text, kind) {
        if (!statusEl) return;
        statusEl.className = 'fork-status' + (kind ? ' ' + kind : '');
        statusEl.textContent = text;
    }

    function refresh() {
        var raw = idInput.value.trim();
        var sid = extractSessionId(raw);
        if (!raw) {
            hintEl.textContent = '세션 ID · 앞 8자리 · JSONL 전체 경로 모두 인식합니다.';
            hintEl.className = 'fork-hint';
            btn.disabled = true;
            return;
        }
        if (!sid) {
            hintEl.textContent = '세션 ID 를 알아낼 수 없습니다.';
            hintEl.className = 'fork-hint warn';
            btn.disabled = true;
            return;
        }
        var title = lookupTitle(sid);
        hintEl.textContent = sid.slice(0, 8) + ' · '
            + (title === null ? '(이 대시보드에 없는 세션 — 그래도 시도합니다)'
                              : (title || '(제목 없음)'));
        hintEl.className = 'fork-hint ' + (title === null ? 'warn' : 'ok');
        btn.disabled = false;
    }

    idInput.addEventListener('input', refresh);
    if (allBox) allBox.addEventListener('change', refresh);

    btn.addEventListener('click', function () {
        var sid = extractSessionId(idInput.value);
        if (!sid) return;
        btn.disabled = true;
        setStatus('문답만 추리는 중…');
        // 원본 JSONL 옆에 저장한다 — 다운로드 폴더로 흩어지지 않게.
        var url = '/api/sessions/' + sid + '/digest?save=1'
            + (allBox && allBox.checked ? '&all=1' : '');
        fetch(url)
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, d: d }; });
            })
            .then(function (res) {
                if (!res.ok) throw new Error(res.d.error || '추리지 못했습니다');
                var d = res.d;
                var extra = (d.all_messages > d.chain && !(allBox && allBox.checked))
                    ? ' · 사슬 밖 ' + (d.all_messages - d.chain) + '건은 제외'
                    : '';
                setStatus(
                    '문답 ' + d.messages + '건 · ' + d.chars.toLocaleString()
                    + '자 (원본 ' + d.total_chars.toLocaleString() + '자의 '
                    + (d.ratio * 100).toFixed(1) + '%)' + extra
                    + ' → ' + d.saved_to, 'success');
            })
            .catch(function (err) {
                setStatus(String(err.message || err), 'error');
            })
            .then(function () { btn.disabled = false; });
    });

    refresh();
})();
