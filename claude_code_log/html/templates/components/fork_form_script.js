// JSONL 세션 복제 폼 — 화면단 (검증 + 슬러그 미리보기). 전송은 아직 미구현.
(function () {
    'use strict';

    var srcInput = document.getElementById('forkSource');
    var tgtInput = document.getElementById('forkTarget');
    var slugHint = document.getElementById('forkSlugPreview');
    var submitBtn = document.getElementById('forkSubmit');
    var statusEl = document.getElementById('forkStatus');
    if (!srcInput || !tgtInput || !submitBtn) return;

    // Claude Code 의 슬러그 규칙: 경로의 ':' 와 '\' 를 '-' 로 바꾼다.
    // 예) C:\kyo-prj\kyochon-prac  ->  C--kyo-prj-kyochon-prac
    function toSlug(projectPath) {
        // RegExp 문자열 안에서는 백슬래시를 두 번 써야 리터럴 한 글자가 된다.
        var BS = String.fromCharCode(92);
        var SEP = new RegExp('[:' + BS + BS + '/]', 'g');   // 수량자 없음 — 한 글자당 '-' 하나
        return projectPath.trim().replace(SEP, '-');
    }

    // 원본은 <projects>/<슬러그>/<세션ID>.jsonl 형태여야 한다.
    var _BS = String.fromCharCode(92);
    var SESSION_FILE = new RegExp('[' + _BS + _BS + '/]([0-9a-fA-F-]{36})[.]jsonl$');

    function sourceProblem(value) {
        var v = value.trim();
        if (!v) return '경로를 입력하세요.';
        if (!/[.]jsonl$/i.test(v)) return '.jsonl 파일 경로여야 합니다.';
        if (!SESSION_FILE.test(v)) return '파일명이 세션 ID(UUID) 형식이 아닙니다.';
        return null;
    }

    function setHint(el, text, kind) {
        el.textContent = text;
        el.classList.remove('ok', 'warn');
        if (kind) el.classList.add(kind);
    }

    function refresh() {
        var tgt = tgtInput.value.trim();
        if (!tgt) {
            setHint(slugHint, '실제 작업 폴더 경로를 넣으면 저장 위치를 미리 보여줍니다.', null);
        } else {
            setHint(slugHint, '저장 위치: ' + toSlug(tgt) + '  폴더', 'ok');
        }

        var problem = sourceProblem(srcInput.value) || (tgt ? null : '대상 프로젝트 경로를 입력하세요.');
        submitBtn.disabled = !!problem;
        if (statusEl) {
            // 입력 중에는 실패 사유만 조용히 안내한다
            statusEl.className = 'fork-status';
            statusEl.textContent = srcInput.value.trim() && problem ? problem : '';
        }
    }

    srcInput.addEventListener('input', refresh);
    tgtInput.addEventListener('input', refresh);
    refresh();

    submitBtn.addEventListener('click', function () {
        if (statusEl) {
            statusEl.className = 'fork-status';
            statusEl.textContent = '화면만 구현된 상태입니다 — 복제 API는 아직 연결되지 않았습니다.';
        }
    });
})();
