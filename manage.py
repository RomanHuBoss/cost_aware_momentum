from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(command: list[str], *, check: bool = True) -> int:
    completed = subprocess.run(command, cwd=ROOT, check=check)
    return completed.returncode


def ensure_supported_python() -> None:
    if (sys.version_info.major, sys.version_info.minor) < (3, 12):
        raise SystemExit("Требуется Python 3.12 или новее.")


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        raise SystemExit("Виртуальная среда не найдена. Сначала выполните: python manage.py setup")
    return python


def command_setup(_: argparse.Namespace, extras: list[str]) -> int:
    ensure_supported_python()
    if extras:
        raise SystemExit("Команда setup не принимает дополнительные аргументы.")
    if not VENV.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    python = ensure_venv()
    run([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([str(python), "-m", "pip", "install", "-e", ".[dev]"])
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy2(ROOT / ".env.example", env_file)
        print("Создан файл .env. Перед запуском задайте SECRET_KEY и OPERATOR_PASSWORD.")
    print("Среда Python подготовлена: .venv")
    print("Следующий шаг: python manage.py configure")
    return 0


def command_module(module: str, extras: list[str]) -> int:
    python = ensure_venv()
    return run([str(python), "-m", module, *extras])


def command_tool(args: argparse.Namespace, extras: list[str]) -> int:
    mapping = {
        "configure": "scripts.configure_env",
        "db-init": "scripts.db_init",
        "doctor": "scripts.doctor",
        "run": "scripts.run_local",
        "api": "app.main",
        "worker": "app.workers.runner",
        "trainer": "app.workers.trainer",
        "test": "scripts.test_runner",
        "backup": "scripts.backup",
        "restore-check": "scripts.restore_check",
        "report": "scripts.daily_report",
        "selection-report": "scripts.selection_report",
        "drift-report": "scripts.drift_report",
        "experiment-report": "scripts.experiment_report",
        "train": "scripts.train",
        "backtest": "scripts.backtest",
        "replay": "scripts.replay",
        "model-registry": "scripts.model_registry",
    }
    if args.command == "migrate":
        python = ensure_venv()
        return run([str(python), "-m", "alembic", "upgrade", "head", *extras])
    if args.command == "lint":
        python = ensure_venv()
        return run([str(python), "-m", "ruff", "check", "app", "scripts", "tests", "migrations", "manage.py", *extras])
    if args.command == "release-check":
        return run([sys.executable, "-B", "-m", "scripts.release_integrity", *extras])
    return command_module(mapping[args.command], extras)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Нативное управление Cost-aware hourly ML momentum без контейнеров."
    )
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "configure",
            "db-init",
            "migrate",
            "doctor",
            "run",
            "api",
            "worker",
            "trainer",
            "test",
            "lint",
            "backup",
            "restore-check",
            "report",
            "selection-report",
            "drift-report",
            "experiment-report",
            "train",
            "backtest",
            "replay",
            "model-registry",
            "release-check",
        ],
    )
    return parser


def main() -> int:
    parser = build_parser()
    args, extras = parser.parse_known_args()
    if args.command == "setup":
        return command_setup(args, extras)
    return command_tool(args, extras)


if __name__ == "__main__":
    raise SystemExit(main())
