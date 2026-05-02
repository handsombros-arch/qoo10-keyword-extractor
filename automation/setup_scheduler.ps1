# Qoo10 야간 자동화 — Windows 작업 스케줄러 등록 스크립트
#
# 사용법 (관리자 PowerShell):
#   cd C:\Users\Admin\qoo10-keyword-extractor\automation
#   .\setup_scheduler.ps1                          # 기본 새벽 03:00
#   .\setup_scheduler.ps1 -Time "19:00"            # 저녁 19:00
#   .\setup_scheduler.ps1 -Time "01:30" -Force     # 기존 등록 덮어쓰기
#
# 동작:
#   - 매일 지정 시간에 daily_workflow.py 자동 실행
#   - 작업 이름: "Qoo10DailyWorkflow"
#   - PC 부팅 직후 누락된 시간 있으면 즉시 실행 (RunOnceMissed)
#   - 실패 시 자동 1회 재시도 (3분 후)
#   - 로그: C:\Users\Admin\qoo10-keyword-extractor\logs\automation_YYYYMMDD.log
#
# 제거: Unregister-ScheduledTask -TaskName "Qoo10DailyWorkflow" -Confirm:$false

[CmdletBinding()]
param(
    [string]$Time = "03:00",
    [switch]$Force,
    [switch]$DryRun,
    [switch]$IncludeChromeDebug,
    [switch]$UseLegacyWorkflow  # R-4: 래퍼 미사용, daily_workflow 직접 호출
)

$ErrorActionPreference = "Stop"

$TaskName = "Qoo10DailyWorkflow"
$ProjectRoot = "C:\Users\Admin\qoo10-keyword-extractor"
# R-4 (2026-05-01): daily_workflow → run_nightly 래퍼 (자동 검증 + 회복 포함).
if ($UseLegacyWorkflow) {
    $ScriptPath = Join-Path $ProjectRoot "automation\daily_workflow.py"
} else {
    $ScriptPath = Join-Path $ProjectRoot "automation\run_nightly.py"
}

# Python 실행 파일 — pythonw 우선 (창 안 뜸)
$PythonExe = "pythonw.exe"
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    $PythonExe = "python.exe"
}
$PythonFull = (Get-Command $PythonExe).Source

# 스크립트 존재 확인
if (-not (Test-Path $ScriptPath)) {
    Write-Error "daily_workflow.py 가 없습니다: $ScriptPath"
    exit 1
}

# 시간 파싱
try {
    $TriggerTime = [datetime]::Parse($Time)
} catch {
    Write-Error "Time 형식 오류 (HH:mm 예: '03:00'): $Time"
    exit 1
}

Write-Host "=== Qoo10 야간 자동화 스케줄러 등록 ===" -ForegroundColor Cyan
Write-Host "  TaskName : $TaskName"
Write-Host "  Time     : $Time (매일)"
Write-Host "  Python   : $PythonFull"
Write-Host "  Script   : $ScriptPath"
Write-Host "  WorkDir  : $ProjectRoot"
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] 실제 등록 안 함." -ForegroundColor Yellow
    exit 0
}

# 기존 작업 확인
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    if ($Force) {
        Write-Host "[기존 작업 발견 — Force 옵션으로 덮어쓰기]" -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    } else {
        Write-Host "[ERR] 이미 '$TaskName' 작업이 등록되어 있습니다. 덮어쓰려면 -Force 옵션 추가." -ForegroundColor Red
        exit 1
    }
}

# Action — pythonw daily_workflow.py
$Action = New-ScheduledTaskAction `
    -Execute $PythonFull `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory $ProjectRoot

# Trigger — 매일 지정 시간
$Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime

# Settings — 누락 실행 처리, 실패 재시도, 6시간 제한 (이전 2h 는 LLM 분류 도중 강제 종료 발생)
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 3) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

# Principal — 현재 사용자, 최고 권한 X (브라우저 GUI 띄울 수 있도록 INTERACTIVE)
$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

# 등록
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Qoo10 키워드 추출 + AI 분류 + 매칭 + 추천 빌드 (매일 $Time)" `
    | Out-Null

# Chrome 디버그 부팅 자동시작 (선택)
if ($IncludeChromeDebug) {
    $ChromeTaskName = "Qoo10ChromeDebug"
    $ChromeBat = Join-Path $ProjectRoot "automation\launch_chrome_debug.bat"

    if (-not (Test-Path $ChromeBat)) {
        Write-Host "[WARN] launch_chrome_debug.bat 없음 — Chrome 디버그 자동시작 스킵" -ForegroundColor Yellow
    } else {
        $ExistingChrome = Get-ScheduledTask -TaskName $ChromeTaskName -ErrorAction SilentlyContinue
        if ($ExistingChrome -and $Force) {
            Unregister-ScheduledTask -TaskName $ChromeTaskName -Confirm:$false
            $ExistingChrome = $null
        }

        if ($ExistingChrome) {
            Write-Host "[기존 $ChromeTaskName 작업 발견 — 스킵 (덮어쓰려면 -Force)]" -ForegroundColor Yellow
        } else {
            $ChromeAction = New-ScheduledTaskAction `
                -Execute "cmd.exe" `
                -Argument "/c `"$ChromeBat`"" `
                -WorkingDirectory $ProjectRoot
            # 트리거 2개: AtLogOn (사용자 로그인) + AtStartup (PC 부팅, SYSTEM 로그인 X 사용자 로그인 전 보장)
            # AtLogOn 만 있으면 PC 가 계속 켜져있고 사용자 재로그인 안 하면 안 돔 → 4/29 case
            $ChromeTrigger1 = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
            $ChromeTrigger2 = New-ScheduledTaskTrigger -AtStartup
            try {
                $ChromeTrigger1.Delay = "PT1M"
                $ChromeTrigger2.Delay = "PT2M"  # 부팅 후 2분 대기 (네트워크/드라이버 준비)
            } catch {
                Write-Host "[INFO] Delay 미지원 — 즉시 시작" -ForegroundColor Yellow
            }
            $ChromeSettings = New-ScheduledTaskSettingsSet `
                -StartWhenAvailable `
                -DontStopIfGoingOnBatteries `
                -AllowStartIfOnBatteries

            Register-ScheduledTask `
                -TaskName $ChromeTaskName `
                -Action $ChromeAction `
                -Trigger @($ChromeTrigger1, $ChromeTrigger2) `
                -Settings $ChromeSettings `
                -Principal $Principal `
                -Description "Qoo10 자동화용 디버그 Chrome (포트 9222, PC 부팅 + 사용자 로그인 시 자동 시작)" `
                | Out-Null
            Write-Host "[OK] '$ChromeTaskName' 등록 완료 — PC 부팅 + 사용자 로그인 시 자동 시작" -ForegroundColor Green
        }
    }
}

Write-Host ""
Write-Host "[OK] 등록 완료. 매일 $Time 에 자동 실행됩니다." -ForegroundColor Green
Write-Host ""
Write-Host "수동 테스트:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "상태 확인:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "제거:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
