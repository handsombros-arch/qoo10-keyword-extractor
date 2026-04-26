@echo off
echo.
echo ============================================================
echo   Starting Chrome in DEBUG mode (port 9222)
echo ============================================================
echo.
echo NOTE: Close ALL existing Chrome windows first,
echo       otherwise the debug option will be ignored.
echo.
echo After Chrome opens, use it normally.
echo Automation will attach via CDP and open a new tab.
echo.
echo ============================================================
echo.

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

start "" %CHROME% --remote-debugging-port=9222

echo Chrome launched in debug mode on port 9222.
echo You can close this window.
echo.
timeout /t 5
