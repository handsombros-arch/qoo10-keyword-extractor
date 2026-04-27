@echo off
echo.
echo ============================================================
echo   Qoo10 자동화용 디버그 Chrome (별도 프로필, 포트 9222)
echo ============================================================
echo.
echo - 별도 프로필이라 평소 Chrome 안 닫아도 OK
echo - 처음 한 번: 네이버/쿠팡 등 로그인해두면 다음부터 쿠키 누적
echo - 자동화가 차단(번호 입력 등)되면 이 창에서 직접 풀어주세요
echo - 백엔드가 9222 포트로 attach
echo.
echo ============================================================
echo.

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

set DBGDIR=%USERPROFILE%\qoo10-chrome-debug-profile
if not exist "%DBGDIR%" mkdir "%DBGDIR%"

start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="%DBGDIR%" --no-first-run --no-default-browser-check

echo Chrome 실행됨 (포트 9222, 프로필 = %DBGDIR%).
echo 이 창 닫으셔도 됩니다.
echo.
timeout /t 5
