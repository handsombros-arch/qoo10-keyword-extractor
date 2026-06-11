@echo off
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo [오류] backend\.venv 가 없습니다. 먼저 셋업하세요:
  echo   cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
  pause
  exit /b 1
)
echo 엘비텐(LV10) 시작 중...
start http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
