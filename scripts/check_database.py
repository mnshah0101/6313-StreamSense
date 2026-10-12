"""Check development connectivity without creating application tables or migrations."""

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("FAIL: set DATABASE_URL to a disposable PostgreSQL 17 database.")
        return 1
    engine = None
    try:
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
        if engine.dialect.name != "postgresql":
            print("FAIL: this check requires PostgreSQL 17, not another database.")
            return 1
        with engine.connect() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")))
            if version // 10000 != 17:
                print("FAIL: expected PostgreSQL major version 17.")
                return 1
            value = connection.scalar(
                text("SELECT CAST(:value AS jsonb)"), {"value": '{"ok":true}'}
            )
            now = connection.scalar(text("SELECT CURRENT_TIMESTAMP"))
            if value != {"ok": True} or now.tzinfo is None:
                print("FAIL: JSON or timezone-aware timestamp round trip failed.")
                return 1
        print("PASS: PostgreSQL 17 connection, JSONB and timezone-aware timestamps.")
        print("No application tables or migrations were created or tested.")
        return 0
    except (SQLAlchemyError, ValueError, TypeError, ImportError):
        # Database errors can include credentials/hosts. Keep the public diagnostic safe.
        print("FAIL: database check could not finish; check URL, driver, service and credentials.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
