"""
엘비텐 (LV10) - CMD 없이 실행
더블클릭하면 백엔드 + 디버그 Chrome (9222) 자동 시작 + 브라우저 열림.
"""
import os
import socket
import sys
import time
import webbrowser
import subprocess
import threading
import urllib.request

# 경로 설정
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
CHROME_DEBUG_BAT = os.path.join(ROOT_DIR, "automation", "launch_chrome_debug.bat")

# 런처는 .pyw 더블클릭 시 전역 pythonw 로 뜨지만, 의존성은 backend/.venv 에만
# 설치되므로(SETUP.md) 항상 .venv Python 을 쓰도록 강제한다. 없으면 전역으로 폴백.
_venv_python = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_python):
    python_exe = _venv_python
else:
    python_exe = sys.executable.replace("pythonw.exe", "python.exe")


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def run_server():
    # host 0.0.0.0 — Tailscale 통해 노트북에서도 접근 가능. 사장님 PC 방화벽이
    # 8000 inbound 허용해야 동작 (Tailscale 인터페이스만 노출되도록 룰 권장).
    subprocess.run(
        [python_exe, "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", "8000"],
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


def ensure_chrome_debug():
    """9222 디버그 Chrome 살아있지 않으면 launch_chrome_debug.bat 실행.

    Chrome 자체는 백엔드와 별도 프로세스 — 백엔드 재시작해도 Chrome 살아있음
    (쿠키/captcha 풀이 누적 보존).
    """
    if _port_open(9222):
        return  # 이미 살아있음 — 쿠키 누적된 Chrome 그대로 사용
    if not os.path.exists(CHROME_DEBUG_BAT):
        return
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            ["cmd.exe", "/c", CHROME_DEBUG_BAT],
            cwd=ROOT_DIR,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        )
    except Exception:
        pass


# 1) 백엔드 + Chrome 디버그 동시 시작 (Chrome 은 별도 프로세스로 detached)
server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
ensure_chrome_debug()

# 2) 백엔드 ready 후 브라우저 띄움
if wait_for_server():
    webbrowser.open("http://localhost:8000")

server_thread.join()
