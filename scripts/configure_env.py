from __future__ import annotations

import argparse
import getpass
import secrets
import shutil
from pathlib import Path

from scripts.postgres_utils import project_root


def encode_env_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise SystemExit("Значения .env не могут содержать перевод строки.")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env(path: Path, values: dict[str, str]) -> None:
    encoded = {key: encode_env_value(value) for key, value in values.items()}
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in encoded:
                updated.append(f"{key}={encoded[key]}")
                seen.add(key)
                continue
        updated.append(line)
    for key, value in encoded.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Безопасная первичная настройка .env")
    parser.add_argument("--password", help="Пароль оператора; безопаснее не передавать в командной строке")
    parser.add_argument("--keep-secret", action="store_true", help="Не заменять SECRET_KEY")
    args = parser.parse_args()

    root = project_root()
    env_path = root / ".env"
    if not env_path.exists():
        shutil.copy2(root / ".env.example", env_path)

    password = args.password
    if password is None:
        first = getpass.getpass("Новый пароль оператора (минимум 12 символов): ")
        second = getpass.getpass("Повторите пароль: ")
        if first != second:
            raise SystemExit("Пароли не совпадают.")
        password = first
    if len(password) < 12:
        raise SystemExit("Пароль должен содержать не менее 12 символов.")

    values = {"OPERATOR_PASSWORD": password}
    if not args.keep_secret:
        values["SECRET_KEY"] = secrets.token_urlsafe(48)
    update_env(env_path, values)
    print(f"Файл {env_path.name} обновлен. Секреты не выводились в консоль.")


if __name__ == "__main__":
    main()
