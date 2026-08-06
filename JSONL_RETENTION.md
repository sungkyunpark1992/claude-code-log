# JSONL 대화 기록 보존

> Claude Code가 30일 지난 대화 기록(JSONL)을 자동 삭제하는 것을 막는 방법.
> 새 컴퓨터를 세팅할 때 **가장 먼저** 해두는 것을 권장.

두 단계로 구성된다:

| 단계 | 내용 | 필수 여부 |
|---|---|---|
| 1 | [`cleanupPeriodDays` 설정](#해결-1단계) — 자동 삭제 자체를 막음 | **필수** |
| 2 | [백업 자동화](#백업-자동화-2단계-방어) — 설정이 사라지는 경우 대비 | 선택 |

---

## 문제

Claude Code는 `~/.claude/projects/**/*.jsonl` 대화 기록을 **기본 30일**만 보관하고 자동 삭제한다.
옵션이 아니라 기본 동작이며, 삭제 시 알림도 없다.

claude-code-log 입장에서는 이렇게 이어진다:

```
JSONL 삭제 → 캐시 DB에서 제거 → 인덱스에서 세션 사라짐 → HTML만 고아로 남음
```

[CUSTOM_FEATURES.md 23번 (Old Sessions)](CUSTOM_FEATURES.md#23-old-sessions--jsonl-삭제-후-html만-잔존하는-세션-조회)은 이미 삭제된 뒤의 **사후 대책**이고,
이 문서는 애초에 삭제되지 않게 하는 **사전 대책**이다.

---

## 해결 (1단계)

`%USERPROFILE%\.claude\settings.json` 에 `cleanupPeriodDays` 한 줄 추가.

파일이 없으면 새로 만든다:

```json
{
  "cleanupPeriodDays": 3650
}
```

이미 다른 설정이 있으면 **앞 줄 끝 쉼표에 주의**해서 추가:

```json
{
  "effortLevel": "high",
  "theme": "light",
  "tui": "fullscreen",
  "model": "opus",
  "cleanupPeriodDays": 3650
}
```

Claude Code 재시작 후 적용된다. 필요한 작업은 이게 전부다.

### 값 사양

| 항목 | 값 |
|---|---|
| 기본값 | `30` (일) |
| 최소값 | `1` — `0`이나 "끄기"는 불가 |
| 최대값 | `9007199254740991` |
| 권장값 | `3650` (~10년). Claude Code 공식 안내가 예시로 드는 값 |

> `--no-session-persistence` 플래그도 있지만 이건 **JSONL을 아예 안 만드는** 옵션이라 정반대다.

---

## 주의사항

- **컴퓨터마다 따로 설정해야 한다.** `~/.claude/settings.json`은 각 PC 로컬 파일이며 동기화되지 않는다.
- **이미 삭제된 JSONL은 복구되지 않는다.** 이 설정은 앞으로의 삭제만 막는다.
- **JSON 문법이 깨지면 해당 파일의 설정이 통째로 무시된다.** 에러 메시지 없이 조용히 실패하므로 쉼표를 특히 주의할 것.
- Claude Code 재설치나 설정 초기화 시 이 값이 날아가 기본 30일로 돌아갈 수 있다.

---

## 확인 방법 (선택)

필수는 아니다. JSON 문법과 값을 한 번에 검증하려면:

```powershell
# PowerShell (Windows 기본 내장)
(Get-Content "$env:USERPROFILE\.claude\settings.json" -Raw | ConvertFrom-Json).cleanupPeriodDays
```

```bash
# jq 설치되어 있는 경우
jq -e '.cleanupPeriodDays' ~/.claude/settings.json
```

`3650`이 출력되면 정상. 값이 안 나오면 키 이름 오타, 에러가 나면 JSON 문법 오류다.

### 정리 작업 실행 이력

`~/.claude/.last-cleanup` 파일에 마지막 정리 시각이 UTC로 기록된다. 삭제가 언제 일어났는지 확인할 때 참고.

---

# 백업 자동화 (2단계 방어)

위의 `cleanupPeriodDays` 설정만으로도 자동 삭제는 막힌다. 백업은 **그 설정 자체가 사라지는 경우**를 대비한 2단계 방어다.

| 남은 위험 | 백업이 막아주나 |
|---|---|
| Claude Code 재설치 / 설정 초기화 → 30일 기본값 복귀 | ✅ |
| 실수로 `.claude` 폴더 삭제 | ✅ |
| 디스크 고장 | 다른 물리 드라이브에 백업한 경우만 |

**규모 참고**: JSONL은 세션당 약 170 KB로 매우 작다. HTML·캐시 DB를 제외하고 `*.jsonl`만 백업하면 세션 1000개도 200 MB 미만이다.

---

## 핵심 원칙 — 단방향 누적 복사

> **원본에서 사라져도 백업에서는 지우지 않는다.**

```
원본:  A B C D   →  (30일 경과, A B 삭제)  →  C D
백업:  A B C D   →  A B C D  ← 유지되어야 함 (정답)
                 →  C D      ← 같이 사라짐 (미러링, 오답)
```

그래서 robocopy에 **`/MIR`, `/PURGE`를 절대 쓰지 않는다.** 이 둘이 원본에서 사라진 파일을 백업에서도 삭제하는 옵션이며, 이 백업의 목적과 정면으로 배치된다.

---

## 구성 (Windows)

### 1. 폴더

```
C:\claude-backup\
├── backup-jsonl.bat     실행 스크립트
├── backup.log           실행 기록 (자동 생성)
└── jsonl\               백업본 (robocopy가 자동 생성, 원본 폴더 구조 유지)
```

### 2. `backup-jsonl.bat`

> 배치 파일 내용은 **ASCII로만** 작성한다. 한글 주석을 넣으면 cmd.exe 코드페이지(949)와 파일 인코딩(UTF-8)이 어긋나 깨진다.

```bat
@echo off
setlocal

set "SRC=%USERPROFILE%\.claude\projects"
set "DST=C:\claude-backup\jsonl"
set "LOG=C:\claude-backup\backup.log"

echo.>>"%LOG%"
echo ===== %DATE% %TIME% =====>>"%LOG%"

if not exist "%SRC%" (
    echo [ERROR] source folder not found: %SRC%>>"%LOG%"
    exit /b 1
)

robocopy "%SRC%" "%DST%" *.jsonl /S /XO /R:2 /W:5 /NP /LOG+:"%LOG%"

if %ERRORLEVEL% GEQ 8 exit /b %ERRORLEVEL%
exit /b 0
```

#### 플래그

| 플래그 | 의미 | 이유 |
|---|---|---|
| `*.jsonl` | JSONL만 복사 | HTML·캐시 DB는 재생성 가능. 원본만 지키면 됨 |
| `/S` | 하위 폴더 포함 | 프로젝트별 폴더 구조 유지 |
| `/XO` | 백업본이 더 최신이면 건너뜀 | 오래된 원본이 최신 백업을 덮는 사고 방지 |
| `/R:2 /W:5` | 재시도 2회, 5초 간격 | **필수.** 기본값이 100만 회 × 30초라 파일이 잠기면 사실상 무한 대기 |
| `/NP` | 진행률 % 미출력 | 로그 가독성 |
| `/LOG+:` | 로그 누적 | 실행 이력 추적 |

#### 마지막 2줄이 중요한 이유

**robocopy는 정상 동작에도 0이 아닌 값을 반환한다.**

| 반환값 | 의미 |
|---|---|
| 0 | 변경 없음 |
| 1 | 파일 복사함 ← **정상** |
| 2 | 목적지에 원본에 없는 파일 있음 ← **정상, 오히려 의도한 상태** |
| 8+ | 실제 오류 |

`if %ERRORLEVEL% GEQ 8` 로 감싸지 않으면 백업이 잘 되고 있는데도 작업 스케줄러가 **매번 실패로 표시**한다.

### 3. 예약 작업 등록

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\claude-backup\backup-jsonl.bat"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT1M"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "ClaudeCodeJsonlBackup" `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description "Claude Code JSONL transcripts backup (one-way additive copy)"
```

관리자 권한 불필요. 로그온 1분 뒤 실행되며, 실행 시간은 1초 미만이다.

#### `-AtStartup`이 아니라 `-AtLogOn`인 이유

**부팅 시점 실행은 SYSTEM 계정으로 돌아간다.** 그러면 `%USERPROFILE%`이 `C:\Windows\system32\config\systemprofile`로 잡혀서 원본을 찾지 못한다. 더 나쁜 건 이때 **에러 없이 "성공"으로 끝난다**는 점이다 — 백업이 비어 있는 걸 한참 뒤에나 알게 된다.

스크립트의 `if not exist "%SRC%"` 가드가 이 경우를 로그에 남기는 안전장치다.

---

## 검증 방법

### 작업이 제대로 등록됐는지

```powershell
$t = Get-ScheduledTask -TaskName "ClaudeCodeJsonlBackup"
$t.Triggers.CimClass.CimClassName   # MSFT_TaskLogonTrigger 여야 함
$t.Triggers.UserId                  # 본인 계정
(Get-ScheduledTaskInfo -TaskName "ClaudeCodeJsonlBackup").LastTaskResult   # 0
```

`MSFT_TaskBootTrigger`가 나오면 위의 SYSTEM 계정 문제가 발생한다.

### 핵심 속성 — 원본 삭제 후 백업 생존

이 백업의 존재 이유이므로 한 번은 확인할 가치가 있다. 실제 `.claude` 폴더가 아닌 임시 폴더에서 동일 플래그로 재현한다.

1. 임시 `src`에 `old.jsonl`, `keep.jsonl` 생성 → robocopy 실행 → 백업본에 2개 확인
2. `src`에서 `old.jsonl` 삭제 (30일 자동 삭제 흉내)
3. robocopy 재실행 → **백업본에 `old.jsonl`이 그대로 남아 있으면 정상**

3단계에서 robocopy가 반환값 2를 내는데, 이는 "목적지에 원본에 없는 파일이 있다"는 뜻으로 정확히 의도한 상태다. `/MIR`을 썼다면 이 시점에 백업본이 삭제된다.

---

## 되돌리기

```powershell
Unregister-ScheduledTask -TaskName "ClaudeCodeJsonlBackup" -Confirm:$false
Remove-Item "C:\claude-backup" -Recurse
```

레지스트리나 시스템 설정을 건드리지 않으므로 폴더 하나와 작업 하나만 지우면 흔적 없이 원복된다.

---

## 알아둘 점

- **상주 프로세스가 아니다.** 작업 스케줄러 서비스는 Windows에 원래 항상 떠 있고, 등록된 작업은 프로세스가 아니라 등록부의 한 줄이다. 실행 시각에만 1초 미만 동작하고 종료된다.
- **실행 중인 세션의 JSONL도 대부분 정상 복사된다.** 잠겨서 실패하더라도 다음 실행 때 복사되므로 문제없다. `/R:2 /W:5`가 이때 무한 대기를 막는다.
- **로그온 직후 검은 창이 1초 미만 깜빡인다.** 배치 파일 특성이며, 거슬리면 실행 방식을 바꿔 숨길 수 있다.
- **백업 위치가 같은 물리 드라이브면 디스크 고장은 못 막는다.** 다른 드라이브나 클라우드 동기화 폴더를 쓰면 이것까지 대비된다.
- 주기 실행(N분마다)으로 바꾸려면 트리거를 `-Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)` 으로 교체하면 된다. 상주 프로세스는 여전히 생기지 않는다.

---

## 관련 문서

- [CUSTOM_FEATURES.md](CUSTOM_FEATURES.md) — claude-code-log 커스텀 기능 전체
- [missing-old-sessions.md](missing-old-sessions.md) — JSONL 삭제로 세션이 사라지는 현상 분석
