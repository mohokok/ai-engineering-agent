"""CLI entrypoint for Step 20 verified workspace + database backup and restore (--dry-run supported)."""

import argparse
import json
from pathlib import Path
import sys

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.services.backup import (
    BackupNotFoundError,
    BackupValidationError,
    create_workspace_backup,
    verify_and_restore_backup,
)


def main(argv: list[str] | None = None) -> int:
    """Execute backup or verify/restore CLI subcommands and print structured JSON result."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli_backup",
        description="Local backup & verified restore for workspace files + SQLite DB (keyring excluded).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_bak = sub.add_parser("backup", help="Create timestamped zip backup with SHA-256 manifest.")
    p_bak.add_argument("--workspaces-dir", default="", help="Override WORKSPACES_DIR")
    p_bak.add_argument("--db-url", default="", help="Override DATABASE_URL")
    p_bak.add_argument("--label", default="", help="Optional short archive tag")

    p_res = sub.add_parser("restore", help="Verify and optionally restore from a backup archive.")
    p_res.add_argument("--archive", required=True, help="Path to backup_*.zip file")
    p_res.add_argument("--workspaces-dir", default="", help="Target WORKSPACES_DIR")
    p_res.add_argument("--db-url", default="", help="Target DATABASE_URL")
    p_res.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify archive paths & SHA-256 manifest without modifying target files or database.",
    )

    args = parser.parse_args(argv)
    settings_kwargs: dict[str, object] = {}
    if args.workspaces_dir:
        settings_kwargs["workspaces_dir"] = args.workspaces_dir
    if args.db_url:
        settings_kwargs["database_url"] = args.db_url
    settings = Settings(**settings_kwargs)

    if args.command == "backup":
        engine = create_db_engine(settings.database_url)
        sf = create_session_factory(engine)
        try:
            with sf() as db:
                out = create_workspace_backup(db, settings, label=args.label)
        finally:
            engine.dispose()
        print(json.dumps(out.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0

    try:
        out = verify_and_restore_backup(
            archive_path=Path(args.archive),
            target_workspaces_dir=settings.workspaces_dir,
            target_database_url=settings.database_url,
            dry_run=bool(args.dry_run),
        )
    except (BackupNotFoundError, BackupValidationError) as exc:
        print(json.dumps({"valid": False, "restored": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(out.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if out.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
