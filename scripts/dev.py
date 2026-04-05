from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "dashboard"


def _pythonpath(*parts: str) -> str:
    return os.pathsep.join(str(BACKEND / part) for part in parts)


def _npm_command() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def _spawn(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    print(f"[dev] starting {name}: {' '.join(command)}", flush=True)
    return subprocess.Popen(command, cwd=str(cwd), env=env)


def _terminate(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 5
    for process in processes:
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.kill()


def main() -> int:
    base_env = os.environ.copy()

    api_env = base_env.copy()
    api_env.setdefault("LOG_LEVEL", "INFO")
    api_env.setdefault("LOG_FORMAT", "pretty")
    api_env["PYTHONPATH"] = _pythonpath(
        "services/api",
        "services/orchestrator",
        "libs",
        "libs/research_rules",
        "data",
    )

    worker_env = base_env.copy()
    worker_env.setdefault("LOG_LEVEL", "INFO")
    worker_env.setdefault("LOG_FORMAT", "pretty")
    worker_env["PYTHONPATH"] = _pythonpath(
        "services/workers",
        "services/orchestrator",
        "libs",
        "libs/research_rules",
        "data",
    )

    frontend_env = base_env.copy()

    processes = [
        _spawn("api", [sys.executable, "-m", "main"], BACKEND, api_env),
        _spawn("worker", [sys.executable, "-m", "main"], BACKEND, worker_env),
        _spawn("frontend", [_npm_command(), "run", "dev"], FRONTEND, frontend_env),
    ]

    try:
        while True:
            for process, name in zip(processes, ("api", "worker", "frontend"), strict=True):
                code = process.poll()
                if code is not None:
                    print(f"[dev] {name} exited with code {code}", flush=True)
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[dev] stopping processes", flush=True)
        return 130
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
