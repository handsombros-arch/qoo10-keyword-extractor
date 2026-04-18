"""
Qoo10 키워드 추출기 - CMD 없이 실행
더블클릭하면 백엔드 서버가 시작되고 브라우저가 자동으로 열립니다.
"""
import os
import sys
import time
import webbrowser
import subprocess
import threading
import urllib.request

# 경로 설정
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

# pythonw.exe 대신 python.exe 사용 (uvicorn 호환)
python_exe = sys.executable.replace("pythonw.exe", "python.exe")

def run_server():
    subprocess.run(
        [python_exe, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

def wait_for_server(url="http://127.0.0.1:8000/api/auth/status", timeout=30):
    for _ in range(timeout):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(1)
    return False

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

if wait_for_server():
    webbrowser.open("http://localhost:8000")

server_thread.join()
