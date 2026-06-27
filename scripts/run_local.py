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
    parser = argparse.ArgumentParser(description="Нативный запуск API, inference worker и trainer")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--worker-only", action="store_true")
    parser.add_argument("--trainer-only", action="store_true")
    parser.add_argument("--no-trainer", action="store_true")
    args = parser.parse_args()
    selected_only = sum((args.api_only, args.worker_only, args.trainer_only))
    if selected_only > 1:
        raise SystemExit("Можно выбрать только один режим: --api-only, --worker-only или --trainer-only.")
    if args.trainer_only and args.no_trainer:
        raise SystemExit("Нельзя одновременно указать --trainer-only и --no-trainer.")

    settings = get_settings()
    commands: list[tuple[str, list[str]]] = []
    if args.trainer_only:
        commands.append(("trainer", [sys.executable, "-m", "app.workers.trainer"]))
    else:
        if not args.worker_only:
            commands.append(("api", [sys.executable, "-m", "app.main"]))
        if not args.api_only:
            commands.append(("worker", [sys.executable, "-m", "app.workers.runner"]))
            if settings.auto_train_enabled and not args.no_trainer:
                commands.append(("trainer", [sys.executable, "-m", "app.workers.trainer"]))

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for name, command in commands:
            print(f"Запуск {name}: {' '.join(command)}")
            process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy())
            processes.append(process)
            if name == "api" and len(commands) > 1:
                time.sleep(1)
        if any(name == "api" for name, _ in commands):
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
