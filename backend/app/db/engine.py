import logging
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

log = logging.getLogger(__name__)

connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)


# Forward-only column adds for SQLite. SQLModel.create_all only creates
# missing tables; it does NOT add columns to existing ones, so feature
# additions that touch the schema would otherwise fail with "no such
# column" until the operator wiped data.db. We keep this list small and
# self-documenting rather than pulling in Alembic for a single-table app.
_SQLITE_ADDITIVE_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL fragment)
    ("jobs", "copies", "INTEGER NOT NULL DEFAULT 1"),
]


def _apply_sqlite_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, column, ddl in _SQLITE_ADDITIVE_MIGRATIONS:
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            if column in existing:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
            )
            log.info("migrated sqlite: added %s.%s", table, column)


def init_db() -> None:
    # Importing models registers them on SQLModel.metadata.
    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _apply_sqlite_migrations()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
