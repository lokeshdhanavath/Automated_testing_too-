"""
Launcher script to run both the FastAPI backend and Vite frontend dev server.

Usage:
    python run_dashboard.py
"""
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "dashboard" / "backend"
FRONTEND_DIR = ROOT / "dashboard" / "frontend"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

python_bin = str(VENV_PYTHON if VENV_PYTHON.is_file() else sys.executable)


def main():
    print("=" * 60)
    print(" Starting Veriqon Automated Testing Platform")
    print("=" * 60)

    # 1. Start FastAPI backend
    print("[1/2] Starting backend on http://127.0.0.1:8000 ...")
    backend_cmd = [
        python_bin,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    backend_proc = subprocess.Popen(backend_cmd, cwd=BACKEND_DIR)

    # 2. Start Vite frontend
    print("[2/2] Starting frontend on http://127.0.0.1:5173 ...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend_cmd = [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
    frontend_proc = subprocess.Popen(frontend_cmd, cwd=FRONTEND_DIR)

    # Wait for FastAPI backend to be fully listening before opening the browser
    print("Waiting for FastAPI backend to be ready...")
    import urllib.request
    backend_ready = False
    for attempt in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1) as resp:
                if resp.status == 200:
                    backend_ready = True
                    print("Backend is ready and connected!")
                    break
        except Exception:
            time.sleep(0.5)

    if not backend_ready:
        print("Warning: Backend is taking longer than usual to report healthy.")

    print("\n" + "=" * 60)
    print(" Veriqon Platform is running!")
    print(" Frontend: http://127.0.0.1:5173")
    print(" Backend:  http://127.0.0.1:8000 (Docs: http://127.0.0.1:8000/docs)")
    print(" Press Ctrl+C to stop both servers.")
    print("=" * 60 + "\n")

    try:
        webbrowser.open("http://127.0.0.1:5173")
    except Exception:
        pass

    try:
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print("Backend process exited.")
                break
            if frontend_proc.poll() is not None:
                print("Frontend process exited.")
                break
    except KeyboardInterrupt:
        print("\nShutting down servers...")
    finally:
        for proc in (backend_proc, frontend_proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("Servers stopped.")


if __name__ == "__main__":
    main()

