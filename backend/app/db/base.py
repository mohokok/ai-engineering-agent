"""SQLAlchemy declarative base and shared metadata conventions."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Return a lowercase UUID4 string suitable for primary keys."""
    return str(uuid4())


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
