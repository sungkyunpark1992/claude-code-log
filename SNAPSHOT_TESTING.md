# 스냅샷 테스트와 `-n auto` 함정

> `--snapshot-update` 를 병렬(`-n auto`)로 실행하면 정답지 파일 대부분이 **조용히 삭제**된다.
> 그런데도 pytest 는 전부 통과했다고 보고한다.
>
> **결론부터**: 스냅샷 갱신은 반드시 직렬로. `just update-snapshot` 또는
> `uv run pytest -m snapshot --snapshot-update -v`

---

## 목차

1. [스냅샷 테스트란](#1-스냅샷-테스트란)
2. [실제 대화 기록과의 관계 — 무관하다](#2-실제-대화-기록과의-관계--무관하다)
3. [문제](#3-문제)
4. [실측값](#4-실측값)
5. [왜 지금까지 안 걸렸나](#5-왜-지금까지-안-걸렸나)
6. [실제 위험](#6-실제-위험)
7. [원인은 문서였다](#7-원인은-문서였다)
8. [재현 방법](#8-재현-방법)
9. [올바른 사용법](#9-올바른-사용법)

---

## 1. 스냅샷 테스트란

이 프로젝트는 **"정답지"** 파일을 하나 갖고 있다.

```
test/__snapshots__/test_snapshot_html.ambr    (약 29,800줄 / 1.1 MB)
```

동작 원리는 단순하다.

```
고정된 가짜 대화(test/test_data/*.jsonl)
        ↓  코드 통과
      HTML 생성
        ↓  정답지와 한 글자씩 비교
   같으면 통과 / 다르면 실패
```

다르면 "너 의도한 변경 맞아?" 하고 물어보는 것이고, 의도한 변경이면
`--snapshot-update` 로 정답지를 새로 쓴다.

### 입력이 고정이어야 하는 이유

`test/test_data/` 의 JSONL 들은 git 에 커밋된 고정 파일이다. 누가 언제 어느 컴퓨터에서
돌리든 내용이 같다. `"Hello Claude! Can you help me understand how Python decorators work?"`
는 영원히 그 문장이다.

입력이 매번 달라지면 출력이 달라졌을 때 **"코드가 바뀐 건지, 입력이 바뀐 건지"**
구분할 수 없다. 그래서 입력을 못 박고 출력만 비교한다.

---

## 2. 실제 대화 기록과의 관계 — 무관하다

혼동하기 쉬운 부분이라 명확히 해둔다. **두 파일은 완전히 별개다.**

| | 스냅샷 정답지 | 실제 세션 HTML |
|---|---|---|
| 위치 | `test/__snapshots__/test_snapshot_html.ambr` | `~/.claude/projects/<프로젝트>/session-*.html` |
| 원재료 | `test/test_data/*.jsonl` (가짜 대화) | 내 진짜 대화 JSONL |
| 내용 예시 | "Hello Claude! Can you help me understand how Python decorators work?" | 실제로 주고받은 대화 |
| 용도 | 코드 회귀 감지 | 기록 열람 |
| 갱신 시점 | `--snapshot-update` 실행 시 | 서버가 JSONL 읽어 매번 생성 |

**이 함정으로 실제 대화 기록이 손상되는 일은 없다.** 정답지 파일 하나만 영향받는다.

### 스냅샷 안의 HTML 을 눈으로 보려면

`.ambr` 은 HTML 파일이 아니라 **5개의 HTML 을 2칸 들여쓰기해 담아둔 상자**다.
브라우저로 열면 소스가 텍스트로 보일 뿐이다. 꺼내려면 `# name:` 구분자로 잘라서
들여쓰기를 제거하면 된다.

```
# name: TestTranscriptHTMLSnapshots.test_representative_messages_html
  <!DOCTYPE html>        ← 앞의 2칸이 syrupy 가 붙인 들여쓰기
  ...
# ---
```

담긴 스냅샷은 5개다 — 대표 메시지, 예외 상황, 다중 세션, 단일 세션 페이지, 대시보드 인덱스.

---

## 3. 문제

`--snapshot-update` 를 `-n auto`(pytest-xdist 병렬)와 함께 쓰면
정답지 대부분이 삭제된다.

원인은 **워커들이 서로 뭘 했는지 모른다**는 점이다.

```
작업자1 (테스트 A,B 담당)  →  "C,D 항목은 내가 안 썼네, 미사용이군"  →  삭제
작업자2 (테스트 C,D 담당)  →  "A,B 항목은 내가 안 썼네, 미사용이군"  →  삭제
                                        ↓
                                  정답지가 반토막
```

syrupy 는 `--snapshot-update` 시 "사용되지 않은" 스냅샷을 정리하는 동작을 한다.
그런데 각 워커는 자기가 실행한 테스트만 알기 때문에, 나머지를 미사용으로 오판한다.

---

## 4. 실측값

정답지를 낡은 상태로 만든 뒤 병렬/직렬을 각각 측정했다.

| 실행 | 줄 수 | `timelineItems.push` | 소요 |
|---|---:|---:|---:|
| 원본 (커밋 상태) | 29787 | 4 | — |
| **병렬 갱신 (`-n auto`)** | **16149** | **2** | 4.98s |
| 직렬 갱신 | 29791 | 4 | 1.74s |

- **내용의 46% 소실.** `<script>` 블록이 통째로 사라졌다
- **직렬이 3배 가까이 빠르다.** 스냅샷 테스트는 5개뿐이라 xdist 기동 비용이 병렬화 이득을 넘어선다

---

## 5. 왜 지금까지 안 걸렸나

두 겹으로 숨어 있다.

**① pytest 가 성공했다고 보고한다**

```
5 passed in 4.98s
```

파일을 반토막 내는 중에도 이렇게 나온다. 실패가 아니므로 아무도 확인하지 않는다.

**② 정답지를 실제로 다시 쓸 때만 발생한다**

이미 최신 상태에서 병렬 갱신하면 파일을 건드리지 않으므로 아무 일도 안 일어난다.
그래서 평소엔 티가 안 나고, 하필 **코드를 고쳐서 갱신이 필요한 순간**에만 터진다.

> 실제로 이 문제를 조사할 때도 처음엔 재현되지 않았다.
> 템플릿에 주석 한 줄을 넣어 정답지를 일부러 낡게 만든 뒤에야 재현됐다.

---

## 6. 실제 위험

**이미 만들어진 결과물이 손상되는 게 아니다.** 반토막 난 정답지를 커밋하면
그때부터 **회귀 감지 기능이 죽는다.** 나중에 진짜로 HTML 이 깨져도 정답지에
그 부분이 없으니 테스트가 통과해버린다.

> 집이 무너진 게 아니라, **화재경보기 배터리가 빠진 상태**가 된다.

---

## 7. 원인은 문서였다

`justfile` 은 **원래부터 올발랐다**:

```make
# Update snapshot tests (runs serially for deterministic file ordering)
update-snapshot:
    uv run pytest -m snapshot --snapshot-update -v      # -n auto 없음
```

이유 주석까지 달려 있다. **문서 3곳만 이와 어긋나 있었다.**

| 문서 | 잘못된 안내 |
|---|---|
| `CLAUDE.md` | **"Always use `-n auto` for parallel test execution"** — 예외 언급 없음 |
| `CONTRIBUTING.md` | `uv run pytest -n auto test/test_snapshot_html.py --snapshot-update` |
| `test/README.md` | 동일 |

특히 `CLAUDE.md` 는 AI 에이전트가 읽고 작업하는 문서다. 그 지침을 그대로 따르다가
실제로 정답지를 날렸다.

---

## 8. 재현 방법

직접 확인하고 싶다면:

```bash
# 1) 정답지를 낡은 상태로 만든다 (템플릿에 주석 한 줄 추가)
printf '\n<!-- probe -->\n' >> claude_code_log/html/templates/transcript.html

# 2) 병렬로 갱신 — 손상됨
uv run pytest -n auto test/test_snapshot_html.py --snapshot-update -q
wc -l < test/__snapshots__/test_snapshot_html.ambr          # 약 16000
grep -c "timelineItems.push" test/__snapshots__/test_snapshot_html.ambr   # 2

# 3) 되돌리고 직렬로 갱신 — 정상
git checkout test/__snapshots__/
uv run pytest -m snapshot --snapshot-update -q
wc -l < test/__snapshots__/test_snapshot_html.ambr          # 약 29800
grep -c "timelineItems.push" test/__snapshots__/test_snapshot_html.ambr   # 4

# 4) 실험 원복
git checkout test/__snapshots__/ claude_code_log/html/templates/transcript.html
```

---

## 9. 올바른 사용법

### 읽기 전용 실행은 병렬 OK

```bash
uv run pytest -n auto test/test_snapshot_html.py -v
```

정답지를 쓰지 않으므로 안전하다.

### 갱신은 반드시 직렬

```bash
just update-snapshot
# just CLI 가 없다면:
uv run pytest -m snapshot --snapshot-update -v
```

### 갱신 후에는 diff 크기를 확인한다

```bash
git diff --stat test/__snapshots__/
```

**변경 규모가 내가 고친 것보다 훨씬 크다면 둘 중 하나다:**

- 정답지가 이전부터 낡아 있었다 (누군가 갱신을 빼먹음)
- 방금 갱신이 손상됐다

어느 쪽이든 **그냥 커밋하면 안 된다.** 원인을 확인해야 한다.

> 참고로 이 프로젝트의 정답지는 실제로 낡은 상태였다. 2026-08-06 에 갱신했을 때
> 순수 코드 변경분은 16줄이었는데 전체 diff 는 6295줄이었다. 나머지는 이전
> 커밋들에서 누적된 것이다.

---

## 관련 문서

- [CONTRIBUTING.md](CONTRIBUTING.md) — 테스트 실행 전반
- [test/README.md](test/README.md) — 테스트 구조 상세
- [CLAUDE.md](CLAUDE.md) — AI 에이전트용 지침
