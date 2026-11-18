"""Alembic migration environment supporting SQLite and PostgreSQL."""

from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import create_db_engine

config = context.config

if config.attributes.get("configure_logger", True) and config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve database URL from attributes, alembic options, or app Settings."""
    url = config.attributes.get("database_url") or config.get_main_option("sqlalchemy.url")
    if url and url.strip():
        return url.strip()
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without creating a DBAPI connection."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the configured SQLAlchemy engine."""
    url = get_database_url()
    connectable = create_db_engine(url)
    try:
        is_sqlite = url.startswith("sqlite")
        with connectable.connect() as connection:
            if is_sqlite:
                # Commit the implicit begin and disable SQLite FK enforcement during
                # batch table rebuilds so parent tables with existing rows can migrate cleanly.
                connection.commit()
                autocommit_conn = connection.execution_options(isolation_level="AUTOCOMMIT")
                autocommit_conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=is_sqlite,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()

            if is_sqlite:
                connection.commit()
                autocommit_conn = connection.execution_options(isolation_level="AUTOCOMMIT")
                autocommit_conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                fk_errors = autocommit_conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if fk_errors:
                    raise RuntimeError(f"Foreign key violations after migration: {fk_errors}")
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
