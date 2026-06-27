from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from scripts.postgres_utils import pg_environment, project_root, require_tool


def main() -> None:
    parser = argparse.ArgumentParser(description="Резервная копия PostgreSQL через pg_dump")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    output = args.output
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = project_root() / "backups" / f"cost_momentum-{stamp}.dump"
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        require_tool("pg_dump"),
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output),
    ]
    subprocess.run(command, env=pg_environment(settings.database_url), check=True)
    print(f"Резервная копия создана: {output}")


if __name__ == "__main__":
    main()
