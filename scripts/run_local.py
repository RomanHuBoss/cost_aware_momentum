from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Нативный запуск API и worker")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--worker-only", action="store_true")
    args = parser.parse_args()
    if args.api_only and args.worker_only:
        raise SystemExit("Нельзя одновременно указать --api-only и --worker-only.")

    settings = get_settings()
    commands: list[tuple[str, list[str]]] = []
    if not args.worker_only:
        commands.append(("api", [sys.executable, "-m", "app.main"]))
    if not args.api_only:
        commands.append(("worker", [sys.executable, "-m", "app.workers.runner"]))

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for name, command in commands:
            print(f"Запуск {name}: {' '.join(command)}")
            process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy())
            processes.append(process)
            if name == "api" and len(commands) > 1:
                time.sleep(1)
        if not args.worker_only:
            print(f"Интерфейс: http://{settings.app_host}:{settings.app_port}")
        print("Для остановки нажмите Ctrl+C.")
        while True:
            for process, (name, _) in zip(processes, commands, strict=True):
                code = process.poll()
                if code is not None:
                    raise SystemExit(f"Процесс {name} завершился с кодом {code}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Остановка процессов...")
    finally:
        terminate(processes)


if __name__ == "__main__":
    main()
