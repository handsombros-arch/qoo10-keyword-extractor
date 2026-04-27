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
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$TaskName = "Qoo10DailyWorkflow"
$ProjectRoot = "C:\Users\Admin\qoo10-keyword-extractor"
$ScriptPath = Join-Path $ProjectRoot "automation\daily_workflow.py"

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

# Settings — 누락 실행 처리, 실패 재시도, 30분 안에 끝나면 끝나는 대로 종료
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 3) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
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
