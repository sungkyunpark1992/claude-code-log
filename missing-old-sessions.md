# 오래된 세션이 대시보드에서 사라지는 문제

## 증상

메인 대시보드(`http://localhost:5678/`)에서 비교적 최신 세션은 보이지만,
예전에 진행했던 세션들이 목록에 나타나지 않음.

---

## 원인

### 1. Claude Code 자동 cleanup

Claude Code는 `cleanupPeriodDays` 설정에 따라 오래된 세션의 JSONL 파일을 자동으로 삭제한다.
`~/.claude/settings.json`에 이 값이 없으면 **기본값 30일**이 적용된다.

### 2. 인덱스 필터링 로직

`claude_code_log/converter.py`의 인덱스 생성 로직은 **현재 디스크에 JSONL 파일이 존재하는 세션만** 표시한다.

```python
# converter.py:1771
valid_session_ids = {f.stem for f in jsonl_files}  # 현재 존재하는 JSONL 파일 목록

# converter.py:1932
and session_data.session_id in valid_session_ids  # JSONL 없으면 인덱스에서 제외
```

JSONL이 삭제된 세션은 캐시 DB에는 남아 있지만 `valid_session_ids`에 포함되지 않아
"archived" 상태로 처리되고 대시보드에서 보이지 않는다.

### 요약

```
JSONL 파일 자동 삭제 (30일 후)
    → valid_session_ids에서 제외
    → 인덱스에서 필터링
    → 대시보드에서 사라짐
```

---

## 현재 상태 확인

JSONL 없이 HTML만 남아 있는 세션 예시 (`komis-be` 프로젝트):

| 파일 | JSONL | HTML |
|------|-------|------|
| `96bf2c36-...` | ❌ 삭제됨 | ✅ 잔존 |
| `98735bdc-...` | ❌ 삭제됨 | ✅ 잔존 |
| `481a88d6-...` | ✅ 존재 | ✅ 존재 |
| `fafdf841-...` | ✅ 존재 | ✅ 존재 |

HTML 파일은 남아 있으므로 직접 열어서 내용 확인은 가능하다.

---

## 해결 방법

### 자동 삭제 비활성화 (권장)

`~/.claude/settings.json`에 다음 설정 추가:

```json
{
  "cleanupPeriodDays": 0
}
```

`0`으로 설정하면 JSONL 파일이 자동으로 삭제되지 않는다.

### 보존 기간 연장

무기한 보존 대신 기간만 늘리고 싶다면:

```json
{
  "cleanupPeriodDays": 365
}
```

---

## 주의사항

JSONL 파일을 무기한 보존할 경우:

- 파일이 계속 쌓이면 디스크 공간을 차지한다 (활성 세션 하나가 수십 MB 이상일 수 있음)
- 인덱스 로딩 시간이 파일 수에 비례해 늘어날 수 있다 (`cache_only` 최적화로 완화됨)
- 주기적으로 불필요한 오래된 JSONL을 직접 정리하는 것이 좋다
