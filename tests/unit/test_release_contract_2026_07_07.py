from __future__ import annotations

from pathlib import Path

from scripts.release_integrity import verify_release_tree, write_manifest

REQUIRED_STATIC_FILES = (
    ".env.example",
    "CHANGELOG.md",
    "README.md",
    "alembic.ini",
    "app/__init__.py",
    "docs/ARCHITECTURE.md",
    "docs/CONFIGURATION.md",
    "docs/INCIDENT_RUNBOOK.md",
    "docs/MODEL_CARD.md",
    "docs/OPERATOR_MANUAL.md",
    "docs/QA_REPORT.md",
    "docs/SECURITY.md",
    "docs/SPEC_COMPLIANCE.md",
    "docs/TRACEABILITY.md",
    "manage.py",
    "pyproject.toml",
)


def _write(path: Path, content: str = "release evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _complete_release_tree(root: Path, *, version: str = "1.51.1") -> None:
    for relative in REQUIRED_STATIC_FILES:
        _write(root / relative)
    _write(root / "pyproject.toml", f'[project]\nname = "fixture"\nversion = "{version}"\n')
    _write(root / "app" / "__init__.py", f'__version__ = "{version}"\n')
    _write(root / "README.md", f"# Fixture\n\n> Версия {version}: test release.\n")
    _write(root / f"PATCH_{version}.md")
    _write(root / "docs" / "ITERATION_REPORT_2026-07-07_release-integrity.md")


def test_release_verification_rejects_self_consistent_but_incomplete_tree(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Incomplete release\n")
    _write(tmp_path / "app" / "module.py", "VALUE = 1\n")
    manifest = write_manifest(tmp_path)

    report = verify_release_tree(tmp_path, manifest_path=manifest)

    assert report.ok is False
    assert "required release file is missing: docs/QA_REPORT.md" in report.errors
    assert "required release file is missing: docs/SECURITY.md" in report.errors
    assert "required release file is missing: pyproject.toml" in report.errors


def test_release_verification_rejects_version_drift(tmp_path: Path) -> None:
    _complete_release_tree(tmp_path, version="1.51.1")
    _write(tmp_path / "app" / "__init__.py", '__version__ = "1.51.0"\n')
    manifest = write_manifest(tmp_path)

    report = verify_release_tree(tmp_path, manifest_path=manifest)

    assert report.ok is False
    assert (
        "release version mismatch: pyproject.toml=1.51.1, app/__init__.py=1.51.0, "
        "README.md=1.51.1" in report.errors
    )
