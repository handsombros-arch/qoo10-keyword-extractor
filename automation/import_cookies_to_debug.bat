@echo off
REM Copy main Chrome cookies to debug profile (qoo10-chrome-debug-profile)
REM One-time. Re-run when main Chrome's Naver session expires (~7 days)

echo ============================================================
echo   Main Chrome cookies -^> Debug profile import
echo ============================================================
echo.

echo [1/4] Closing all Chrome instances...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 3 /nobreak >nul
echo       OK
echo.

set MAIN_PROFILE=%LOCALAPPDATA%\Google\Chrome\User Data\Default
set DEBUG_PROFILE=%USERPROFILE%\qoo10-chrome-debug-profile\Default

set MAIN_NET=%MAIN_PROFILE%\Network
set DEBUG_NET=%DEBUG_PROFILE%\Network

echo [2/4] Path check
echo       MAIN : %MAIN_NET%
echo       DEBUG: %DEBUG_NET%

if not exist "%MAIN_NET%\Cookies" (
    echo.
    echo [ERROR] Main Chrome cookies file not found
    echo         Open main Chrome once, then re-run this script
    pause
    exit /b 1
)

if not exist "%DEBUG_PROFILE%" mkdir "%DEBUG_PROFILE%"
if not exist "%DEBUG_NET%" mkdir "%DEBUG_NET%"
echo       OK
echo.

echo [3/4] Copying cookies to debug profile...
copy /Y "%MAIN_NET%\Cookies" "%DEBUG_NET%\Cookies" >nul
if exist "%MAIN_NET%\Cookies-journal" copy /Y "%MAIN_NET%\Cookies-journal" "%DEBUG_NET%\Cookies-journal" >nul

set MAIN_LOCAL_STATE=%LOCALAPPDATA%\Google\Chrome\User Data\Local State
set DEBUG_LOCAL_STATE=%USERPROFILE%\qoo10-chrome-debug-profile\Local State
if exist "%MAIN_LOCAL_STATE%" copy /Y "%MAIN_LOCAL_STATE%" "%DEBUG_LOCAL_STATE%" >nul
echo       debug profile OK

REM Also copy to naver-browser-profile (used by naver_fetch_v2)
echo [3b/4] Copying cookies to naver-browser-profile...
set NAVER_PROFILE=C:\Users\Admin\qoo10-keyword-extractor\data\naver-browser-profile\Default
set NAVER_NET=%NAVER_PROFILE%\Network
if not exist "%NAVER_PROFILE%" mkdir "%NAVER_PROFILE%"
if not exist "%NAVER_NET%" mkdir "%NAVER_NET%"
copy /Y "%MAIN_NET%\Cookies" "%NAVER_NET%\Cookies" >nul
if exist "%MAIN_NET%\Cookies-journal" copy /Y "%MAIN_NET%\Cookies-journal" "%NAVER_NET%\Cookies-journal" >nul
set NAVER_LOCAL_STATE=C:\Users\Admin\qoo10-keyword-extractor\data\naver-browser-profile\Local State
if exist "%MAIN_LOCAL_STATE%" copy /Y "%MAIN_LOCAL_STATE%" "%NAVER_LOCAL_STATE%" >nul
echo       naver-browser-profile OK
echo.

echo [4/4] Restarting debug Chrome (port 9222)...
call "%~dp0launch_chrome_debug.bat"
echo.

echo ============================================================
echo   Import done. Restart your main Chrome separately.
echo ============================================================
pause
exit /b 0
