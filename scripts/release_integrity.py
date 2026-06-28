from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_MANIFEST_NAME = "SHA256SUMS"
_MANIFEST_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  \./(?P<path>.+)$")

_FORBIDDEN_DIR_NAMES = {
    ".git",
    ".direnv",
    "secrets",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    ".pytype",
    ".hypothesis",
    ".tox",
    ".nox",
    ".cache",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "logs",
    "tmp",
    "temp",
}
_FORBIDDEN_FILE_NAMES = {
    ".env",
    ".envrc",
    ".coverage",
    ".DS_Store",
    "Desktop.ini",
    "Thumbs.db",
    "pytestdebug.log",
    "coverage.xml",
    "nohup.out",
}
_FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".egg",
    ".whl",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".joblib",
    ".pkl",
    ".pickle",
    ".onnx",
    ".dump",
    ".backup",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".pid",
    ".sock",
    ".zip",
    ".tgz",
    ".patch",
    ".tmp",
    ".temp",
    ".bak",
    ".orig",
    ".rej",
    ".swp",
    ".swo",
    ".tar",
    ".gz",
}
_RUNTIME_PLACEHOLDER_DIRS = {"models", "reports", "backups"}


@dataclass(frozen=True, slots=True)
class ReleaseIntegrityReport:
    ok: bool
    checked_files: int
    listed_files: int
    errors: tuple[str, ...]


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_example_env(path: Path) -> bool:
    name = path.name
    return name == ".env.example" or (name.startswith(".env.") and name.endswith(".example"))


def _is_forbidden_file(relative: PurePosixPath) -> bool:
    name = relative.name
    if name.startswith(".env") and not _is_example_env(Path(name)):
        return True
    if name in _FORBIDDEN_FILE_NAMES:
        return True
    if any(name.endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
        return True
    if name.endswith((".tar.gz", ".changed-files.txt")):
        return True
    return bool(
        relative.parts
        and relative.parts[0] in _RUNTIME_PLACEHOLDER_DIRS
        and name != ".gitkeep"
    )


def inspect_release_tree(root: Path, *, manifest_path: Path | None = None) -> tuple[list[str], list[str]]:
    root = root.resolve()
    manifest = (manifest_path or root / DEFAULT_MANIFEST_NAME).resolve()
    eligible_files: list[str] = []
    forbidden: set[str] = set()

    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory_path = current_path / directory_name
            relative = _relative_posix(root, directory_path)
            if directory_path.is_symlink():
                forbidden.add(relative)
                continue
            if directory_name in _FORBIDDEN_DIR_NAMES or directory_name.endswith(".egg-info"):
                forbidden.add(relative)
                continue
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories

        for file_name in sorted(file_names):
            file_path = current_path / file_name
            if file_path.resolve() == manifest:
                continue
            relative_text = _relative_posix(root, file_path)
            relative = PurePosixPath(relative_text)
            if file_path.is_symlink() or _is_forbidden_file(relative):
                forbidden.add(relative_text)
                continue
            if file_path.is_file():
                eligible_files.append(relative_text)

    return sorted(eligible_files), sorted(forbidden)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_manifest(manifest_path: Path) -> tuple[dict[str, str], list[str]]:
    entries: dict[str, str] = {}
    errors: list[str] = []
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, [f"manifest file is missing: {manifest_path.name}"]

    for line_number, line in enumerate(lines, start=1):
        if not line:
            errors.append(f"malformed manifest line {line_number}: empty line")
            continue
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            errors.append(f"malformed manifest line {line_number}")
            continue
        relative = match.group("path")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative.startswith("./"):
            errors.append(f"unsafe manifest path on line {line_number}: {relative}")
            continue
        if relative in entries:
            errors.append(f"duplicate manifest entry: {relative}")
            continue
        entries[relative] = match.group("digest")
    return entries, errors


def verify_release_tree(
    root: Path,
    *,
    manifest_path: Path | None = None,
) -> ReleaseIntegrityReport:
    root = root.resolve()
    manifest = (manifest_path or root / DEFAULT_MANIFEST_NAME).resolve()
    eligible_files, forbidden = inspect_release_tree(root, manifest_path=manifest)
    entries, errors = _parse_manifest(manifest)

    for relative in forbidden:
        errors.append(f"forbidden release artifact: {relative}")

    eligible_set = set(eligible_files)
    entry_set = set(entries)
    for relative in sorted(entry_set - eligible_set):
        path = root / relative
        if path.exists():
            errors.append(f"manifest entry is not an eligible release file: {relative}")
        else:
            errors.append(f"manifest entry is missing from tree: {relative}")
    for relative in sorted(eligible_set - entry_set):
        errors.append(f"release file is not listed in manifest: {relative}")
    for relative in sorted(eligible_set & entry_set):
        actual = _sha256(root / relative)
        if actual != entries[relative]:
            errors.append(f"checksum mismatch: {relative}")

    error_tuple = tuple(sorted(set(errors)))
    return ReleaseIntegrityReport(
        ok=not error_tuple,
        checked_files=len(eligible_files),
        listed_files=len(entries),
        errors=error_tuple,
    )


def write_manifest(root: Path, *, manifest_path: Path | None = None) -> Path:
    root = root.resolve()
    manifest = (manifest_path or root / DEFAULT_MANIFEST_NAME).resolve()
    eligible_files, forbidden = inspect_release_tree(root, manifest_path=manifest)
    if forbidden:
        details = ", ".join(forbidden)
        raise ValueError(f"refusing to write manifest with forbidden release artifacts: {details}")

    manifest.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{_sha256(root / relative)}  ./{relative}\n" for relative in eligible_files]
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=manifest.parent,
        prefix=f".{manifest.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        stream.writelines(lines)
        temporary = Path(stream.name)
    temporary.replace(manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Проверка fail-closed состава release tree и SHA256SUMS.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Пересоздать SHA256SUMS после проверки отсутствия запрещенных артефактов.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest.resolve() if args.manifest else root / DEFAULT_MANIFEST_NAME
    if args.write:
        try:
            write_manifest(root, manifest_path=manifest)
        except ValueError as exc:
            print(f"RELEASE MANIFEST NOT WRITTEN: {exc}")
            return 1
        print(f"SHA256 manifest written: {manifest}")

    report = verify_release_tree(root, manifest_path=manifest)
    if report.ok:
        print(
            "Release integrity PASSED: "
            f"{report.checked_files} files checked, {report.listed_files} manifest entries."
        )
        return 0
    print(
        "Release integrity FAILED: "
        f"{report.checked_files} files checked, {report.listed_files} manifest entries."
    )
    for error in report.errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
