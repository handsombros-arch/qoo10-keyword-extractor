@echo off
echo Qoo10 키워드 추출기 시작 중...
cd /d "%~dp0backend"
start http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
