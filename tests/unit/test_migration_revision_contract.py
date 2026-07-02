from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

MAX_ALEMBIC_VERSION_LENGTH = 32
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_all_alembic_revision_ids_fit_version_table_contract() -> None:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    oversized = {
        revision.revision: len(revision.revision)
        for revision in script.walk_revisions()
        if len(revision.revision) > MAX_ALEMBIC_VERSION_LENGTH
    }

    assert oversized == {}, (
        "Alembic revision ids must fit the standard alembic_version.version_num "
        f"VARCHAR({MAX_ALEMBIC_VERSION_LENGTH}) column: {oversized}"
    )


def test_alembic_graph_has_one_expected_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0008_outcome_path_unavailable"]
