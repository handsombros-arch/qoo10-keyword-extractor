Add-Type -AssemblyName PresentationFramework

[System.Media.SystemSounds]::Exclamation.Play()
Start-Sleep -Milliseconds 600
[System.Media.SystemSounds]::Exclamation.Play()
Start-Sleep -Milliseconds 600
[System.Media.SystemSounds]::Exclamation.Play()

$msg = @"
키워드 자동화 돌리세요!

실행 방법:
  1) start.pyw 더블클릭
  2) 또는 PowerShell:
     python C:\Users\Admin\qoo10-keyword-extractor\automation\daily_workflow.py

(이 알림은 매일 오전 11시에 표시됩니다)
"@

[System.Windows.MessageBox]::Show(
    $msg,
    "Qoo10 키워드 자동화 알림 - $(Get-Date -Format 'HH:mm')",
    [System.Windows.MessageBoxButton]::OK,
    [System.Windows.MessageBoxImage]::Warning
) | Out-Null
