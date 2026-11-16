"""SQLAlchemy engine and session factory. SQLite in WAL mode so the GPU worker can write
partial results while the API reads them."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    else:
        # Managed Postgres (Neon) closes idle connections and may scale to zero: check each
        # pooled connection before use and recycle them well inside the idle timeout.
        kwargs = {"pool_pre_ping": True, "pool_recycle": 240, "pool_size": 5, "max_overflow": 5}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _pragmas(conn, _record):  # noqa: ANN001
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    _factory = sessionmaker(_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    add_missing_columns(_engine)
    return _engine


def session() -> Session:
    if _factory is None:
        raise RuntimeError("Database not initialised; call init_engine first")
    return _factory()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session() as s:
        yield s


def add_missing_columns(engine: Engine) -> list[str]:
    """Additive schema sync until Alembic migrations exist: ADD COLUMN for model columns that a
    table lacks, only when the column is nullable or has a scalar default. Never drops, renames
    or changes types; anything else needs a real migration."""
    from sqlalchemy import inspect, text

    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                default = (
                    col.default.arg if col.default is not None and col.default.is_scalar else None
                )
                if not col.nullable and default is None:
                    raise RuntimeError(
                        f"{table.name}.{col.name} needs a migration (NOT NULL, no default)"
                    )
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if default is not None:
                    lit = (
                        default
                        if isinstance(default, int | float)
                        else "'" + str(default).replace("'", "''") + "'"
                    )
                    ddl += f" DEFAULT {int(lit) if isinstance(lit, bool) else lit}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added
