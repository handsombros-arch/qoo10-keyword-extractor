@echo off
REM Open Chrome with naver-browser-profile (separate from main Chrome)
REM 사장님 직접 로그인 → cookies 영구 저장 → 창 닫기

set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

set PROFILE=C:\Users\Admin\qoo10-keyword-extractor\data\naver-browser-profile

echo Opening Chrome with naver-browser-profile...
echo Profile: %PROFILE%
echo.
echo  STEPS:
echo  1. Login at the page below (check "Keep me logged in")
echo  2. Browse around naver.com to make sure session is real
echo  3. Close this Chrome window (X button)
echo  4. Cookies saved automatically
echo  5. Run [URL ?? SEO ???] in sheet again

set PSEXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
"%PSEXE%" -NoProfile -Command "Start-Process -FilePath '%CHROME%' -ArgumentList '--user-data-dir=%PROFILE%','--no-first-run','--no-default-browser-check','https://nid.naver.com/nidlogin.login'"

echo.
echo Chrome launched. Login and close window when done.
exit /b 0
