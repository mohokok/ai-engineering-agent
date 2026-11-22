"""Database engine creation, SQLite pragmas, and FastAPI session dependency."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import record_audit_log_event


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine configured for SQLite or PostgreSQL."""
    parsed = make_url(database_url)
    if parsed.drivername.startswith("sqlite"):
        db_name = parsed.database
        if db_name and db_name != ":memory:" and not db_name.startswith("file:"):
            Path(db_name).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

        return engine

    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured sessionmaker bound to the supplied engine."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @event.listens_for(factory, "before_commit")
    def _capture_audit_logs(session: Session) -> None:
        from app.db.models import AuditLog

        pending: list[dict[str, Any]] = []
        for obj in session.new:
            if isinstance(obj, AuditLog):
                pending.append(
                    {
                        "action": obj.action,
                        "entity_type": obj.entity_type,
                        "entity_id": obj.entity_id,
                        "project_id": obj.project_id,
                        "actor": obj.actor,
                        "details": dict(obj.details_json or {}),
                    }
                )
        if pending:
            session.info.setdefault("_pending_audit_logs", []).extend(pending)

    @event.listens_for(factory, "after_commit")
    def _emit_audit_logs(session: Session) -> None:
        items = session.info.pop("_pending_audit_logs", [])
        for item in items:
            record_audit_log_event(
                action=str(item["action"]),
                entity_type=str(item["entity_type"]),
                entity_id=item.get("entity_id"),
                project_id=item.get("project_id"),
                actor=str(item.get("actor") or "owner"),
                details=item.get("details"),
            )

    @event.listens_for(factory, "after_rollback")
    def _discard_audit_logs(session: Session) -> None:
        session.info.pop("_pending_audit_logs", None)

    return factory


def get_db(request: Request) -> Iterator[Session]:
    """Yield a scoped SQLAlchemy session attached to the active FastAPI app."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
