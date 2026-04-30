@echo off
REM Qoo10 Debug Chrome launcher (port 9222)

set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

set DBGDIR=%USERPROFILE%\qoo10-chrome-debug-profile
if not exist "%DBGDIR%" mkdir "%DBGDIR%"

set PSEXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe

"%PSEXE%" -NoProfile -Command "if ((Test-NetConnection -ComputerName localhost -Port 9222 -InformationLevel Quiet -WarningAction SilentlyContinue)) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo Chrome 9222 already running - skip
    exit /b 0
)

"%PSEXE%" -NoProfile -Command "Start-Process -FilePath '%CHROME%' -ArgumentList '--remote-debugging-port=9222',('--user-data-dir=' + '%DBGDIR%'),'--no-first-run','--no-default-browser-check'"

echo Chrome launch requested (port 9222, profile = %DBGDIR%)
exit /b 0
