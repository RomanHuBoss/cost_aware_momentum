from __future__ import annotations

from pathlib import Path

from scripts.release_integrity import REQUIRED_RELEASE_FILES, verify_release_tree, write_manifest


def _write(path: Path, content: str = "release evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_release_contract(root: Path, version: str = "1.51.1") -> None:
    for relative in REQUIRED_RELEASE_FILES:
        _write(root / relative)
    _write(root / "pyproject.toml", f'[project]\nname = "fixture"\nversion = "{version}"\n')
    _write(root / "app" / "__init__.py", f'__version__ = "{version}"\n')
    _write(root / "README.md", f"# Fixture\n\n> Версия {version}: test release.\n")
    _write(root / f"PATCH_{version}.md")
    _write(root / "docs" / "ITERATION_REPORT_2026-07-07_release-integrity.md")


def test_release_manifest_round_trip_and_detects_missing_file(tmp_path: Path) -> None:
    _write_release_contract(tmp_path)
    _write(tmp_path / "app" / "module.py", "VALUE = 1\n")

    manifest_path = write_manifest(tmp_path)
    clean = verify_release_tree(tmp_path, manifest_path=manifest_path)
    assert clean.ok is True
    assert clean.checked_files == len(REQUIRED_RELEASE_FILES) + 3
    assert clean.errors == ()

    (tmp_path / "app" / "module.py").unlink()
    broken = verify_release_tree(tmp_path, manifest_path=manifest_path)
    assert broken.ok is False
    assert "manifest entry is missing from tree: app/module.py" in broken.errors


def test_release_manifest_detects_unlisted_and_modified_files(tmp_path: Path) -> None:
    _write_release_contract(tmp_path)
    manifest_path = write_manifest(tmp_path)

    _write(tmp_path / "README.md", "changed\n")
    _write(tmp_path / "docs" / "extra.md", "not listed\n")

    report = verify_release_tree(tmp_path, manifest_path=manifest_path)
    assert report.ok is False
    assert "checksum mismatch: README.md" in report.errors
    assert "release file is not listed in manifest: docs/extra.md" in report.errors


def test_release_manifest_rejects_forbidden_artifacts(tmp_path: Path) -> None:
    _write_release_contract(tmp_path)
    manifest_path = write_manifest(tmp_path)
    _write(tmp_path / ".env", "SECRET_KEY=real-secret\n")
    _write(tmp_path / "app" / "__pycache__" / "module.pyc", "bytecode\n")

    report = verify_release_tree(tmp_path, manifest_path=manifest_path)
    assert report.ok is False
    assert "forbidden release artifact: .env" in report.errors
    assert "forbidden release artifact: app/__pycache__" in report.errors
