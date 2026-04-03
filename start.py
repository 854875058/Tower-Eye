#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
LOG_DIR = ROOT / "logs"
BACKEND_PORT = 50805
FRONTEND_PORT = 50803


def _print(msg: str) -> None:
    print(msg, flush=True)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def find_python() -> str:
    current = Path(sys.executable or "")
    if current.exists():
        return str(current)
    for candidate in ("python", "python3"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Python 3 is required but was not found in PATH.")


def is_tcp_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def http_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except URLError:
        return False
    except Exception:
        return False


def wait_http(url: str, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if http_ready(url):
            return True
        time.sleep(1)
    return False


def ensure_backend_deps(python_bin: str) -> None:
    check_code = (
        "import importlib.util as u; "
        "mods=['fastapi','uvicorn','pydantic_settings','sentence_transformers','lancedb']; "
        "raise SystemExit(0 if all(u.find_spec(m) for m in mods) else 1)"
    )
    result = subprocess.run(
        [python_bin, "-c", check_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        return
    _print("Detected missing backend dependencies. Installing from backend/requirements.txt ...")
    subprocess.run(
        [python_bin, "-m", "pip", "install", "-r", str(BACKEND_DIR / "requirements.txt")],
        check=True,
    )


def ensure_frontend_deps() -> None:
    vite_bin = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_bin.exists():
        return
    _print("Detected missing frontend dependencies. Running npm install ...")
    subprocess.run(
        ["npm", "install", "--no-fund", "--no-audit"],
        cwd=FRONTEND_DIR,
        check=True,
    )


def spawn_process(cmd: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = open(stdout_path, "a", encoding="utf-8")
    stderr_handle = open(stderr_path, "a", encoding="utf-8")
    kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "stdout": stdout_handle,
        "stderr": stderr_handle,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def write_pid(path: Path, pid: int) -> None:
    path.write_text(str(pid), encoding="utf-8")


def start_backend(python_bin: str) -> bool:
    if http_ready(f"http://127.0.0.1:{BACKEND_PORT}/health"):
        _print(f"Backend already healthy on http://127.0.0.1:{BACKEND_PORT}/health")
        return True
    if is_tcp_open(BACKEND_PORT):
        _print(f"Backend port {BACKEND_PORT} is already in use but health check failed.")
        return False

    backend_out = LOG_DIR / "backend.out.log"
    backend_err = LOG_DIR / "backend.err.log"
    proc = spawn_process(
        [python_bin, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
        BACKEND_DIR,
        backend_out,
        backend_err,
    )
    write_pid(LOG_DIR / "backend.pid", proc.pid)
    _print(f"Started backend (pid={proc.pid})")
    return wait_http(f"http://127.0.0.1:{BACKEND_PORT}/health", 20)


def start_frontend() -> bool:
    if http_ready(f"http://127.0.0.1:{FRONTEND_PORT}"):
        _print(f"Frontend already available at http://127.0.0.1:{FRONTEND_PORT}")
        return True
    if is_tcp_open(FRONTEND_PORT):
        _print(f"Frontend port {FRONTEND_PORT} is already in use but HTTP check failed.")
        return False

    frontend_out = LOG_DIR / "frontend.out.log"
    frontend_err = LOG_DIR / "frontend.err.log"
    proc = spawn_process(
        ["node", str(FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"), "--host", "0.0.0.0", "--port", str(FRONTEND_PORT)],
        FRONTEND_DIR,
        frontend_out,
        frontend_err,
    )
    write_pid(LOG_DIR / "frontend.pid", proc.pid)
    _print(f"Started frontend (pid={proc.pid})")
    return wait_http(f"http://127.0.0.1:{FRONTEND_PORT}", 20)


def main() -> int:
    if not BACKEND_DIR.is_dir() or not FRONTEND_DIR.is_dir():
        _print("Project layout is incomplete: backend/ and frontend/ are required.")
        return 1
    if not command_exists("node") or not command_exists("npm"):
        _print("Node.js and npm are required but were not found in PATH.")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    python_bin = find_python()

    _print("Starting data-chat-bot services ...")
    ensure_backend_deps(python_bin)
    ensure_frontend_deps()

    backend_ok = start_backend(python_bin)
    frontend_ok = start_frontend()

    _print("")
    _print("========================================")
    _print(f"Frontend: http://127.0.0.1:{FRONTEND_PORT}")
    _print(f"Backend : http://127.0.0.1:{BACKEND_PORT}")
    _print(f"Logs    : {LOG_DIR}")
    _print("========================================")

    if not backend_ok:
        _print(f"Backend failed to become healthy. See {LOG_DIR / 'backend.err.log'}")
    if not frontend_ok:
        _print(f"Frontend failed to become available. See {LOG_DIR / 'frontend.err.log'}")

    return 0 if backend_ok and frontend_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
