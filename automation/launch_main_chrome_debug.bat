@echo off
REM Restart MAIN Chrome with debug port 9222 (default profile)

echo Closing all Chrome...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 3 /nobreak >nul

set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

set PSEXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe

"%PSEXE%" -NoProfile -Command "Start-Process -FilePath '%CHROME%' -ArgumentList '--remote-debugging-port=9222','--restore-last-session','--no-first-run','--no-default-browser-check'"

echo.
echo Chrome relaunched with debug port 9222
echo Login + tabs preserved. Automation will use new tabs in this Chrome.
exit /b 0
