---
name: powershell-ps1-utf8-bom
description: Windows PowerShell 5.1 에서 한글 포함 .ps1 작성 시 UTF-8 BOM 필수
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 18b0aa8f-49a8-4f16-af32-80afe55eab2e
---

Windows PowerShell 5.1 (powershell.exe) 은 .ps1 파일에 UTF-8 BOM 이 없으면 ANSI(cp949) 로 읽음. 한글 포함 스크립트는 BOM 없으면 MessageBox / Write-Host 출력 한글이 깨짐.

**Why:** 5/21 Qoo10KeywordAlert 팝업이 사장님 화면에 ?쇼?쟬?? 같은 깨진 한글로 표시됨. 원인은 `automation/alert_keyword_run.ps1` 이 UTF-8 no-BOM 으로 저장됨. BOM 추가 후 정상 표시 확인.

**How to apply:** 한글이 들어가는 .ps1 / .bat 파일을 새로 만들거나 편집할 때:
- Write 도구로 저장하면 BOM 없는 UTF-8 → PS 5.1 에서 깨짐
- 검증: `[System.IO.File]::ReadAllBytes($path)[0..2]` → `EF BB BF` 면 OK
- 추가 방법:
  ```powershell
  $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
  $utf8WithBom = New-Object System.Text.UTF8Encoding($true)
  [System.IO.File]::WriteAllText($path, $content, $utf8WithBom)
  ```
- 또는 PowerShell `Out-File -Encoding utf8` (PS 5.1 의 utf8 은 BOM 포함)
- PS 7+ (pwsh.exe) 은 BOM 없는 UTF-8 도 정상 처리 — but Task Scheduler 기본은 powershell.exe (5.1)

관련: [[project_qoo10_automation_off]]
