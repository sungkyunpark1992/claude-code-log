document.querySelectorAll('.session-delete-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();

        var sessionLink = this.closest('.session-link');
        var sessionId = sessionLink.dataset.sessionId;

        if (!confirm('이 세션을 삭제하겠습니까?\n삭제된 세션은 복구할 수 없습니다.')) {
            return;
        }

        fetch('/api/sessions/' + sessionId, {
            method: 'DELETE',
        })
            .then(function (resp) {
                if (resp.ok) {
                    location.reload();
                } else {
                    alert('세션 삭제에 실패했습니다.');
                }
            })
            .catch(function () {
                alert('서버 연결 오류가 발생했습니다.');
            });
    });
});

document.querySelectorAll('.session-edit-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();

        var sessionLink = this.closest('.session-link');
        var sessionId = sessionLink.dataset.sessionId;
        var titleSpan = sessionLink.querySelector('.session-title');
        var currentTitle = titleSpan.dataset.title || '';

        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'session-title-input';
        input.value = currentTitle;

        var confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'session-title-confirm-btn';
        confirmBtn.textContent = '✓';
        confirmBtn.title = '저장';

        var wrapper = document.createElement('span');
        wrapper.className = 'session-title-edit-wrapper';
        wrapper.appendChild(input);
        wrapper.appendChild(confirmBtn);
        titleSpan.replaceWith(wrapper);
        input.focus();
        input.select();

        var isConfirming = false;

        function cancel() {
            wrapper.replaceWith(titleSpan);
        }

        function save() {
            var newTitle = input.value.trim();
            if (!newTitle || newTitle === currentTitle) {
                cancel();
                return;
            }

            fetch('/api/sessions/' + sessionId + '/title', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            })
                .then(function (resp) {
                    if (resp.ok) {
                        location.reload();
                    } else {
                        alert('제목 수정에 실패했습니다.');
                        cancel();
                    }
                })
                .catch(function () {
                    alert('서버 연결 오류가 발생했습니다.');
                    cancel();
                });
        }

        confirmBtn.addEventListener('mousedown', function () {
            isConfirming = true;
        });

        confirmBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            isConfirming = false;
            save();
        });

        input.addEventListener('blur', function () {
            if (!isConfirming) {
                cancel();
            }
            isConfirming = false;
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                save();
            }
            if (e.key === 'Escape') {
                cancel();
            }
        });
    });
});
