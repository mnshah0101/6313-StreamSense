"""One-time copy of a StreamSense SQLite database into Postgres (e.g. Neon).

  python scripts/sqlite_to_postgres.py SQLITE_FILE POSTGRES_URL

Copies every table in dependency order, then moves each serial id sequence past the copied
rows. Refuses to write into a database that already has rows (no merging, no duplicates).
Stop every process using the SQLite file first.
"""

import sys

from sqlalchemy import create_engine, func, inspect, select, text

from app import auth  # noqa: F401  (registers user tables)
from app import db as dbm
from app.config import Settings


def main() -> None:
    src_path, dst_url = sys.argv[1], sys.argv[2]
    src = create_engine(f"sqlite:///{src_path}")
    dst_url = Settings(_env_file=None, db_url=dst_url).database_url
    dst = dbm.init_engine(dst_url)  # creates the schema if needed
    tables = dbm.Base.metadata.sorted_tables
    have = set(inspect(src).get_table_names())
    with dst.connect() as c:
        busy = [t.name for t in tables if c.execute(select(func.count()).select_from(t)).scalar()]
    if busy:
        sys.exit(f"target already has rows in {busy}; refusing to merge")
    counts = {}
    with src.connect() as s, dst.begin() as d:
        for t in tables:
            if t.name not in have:
                continue
            src_cols = {c["name"] for c in inspect(src).get_columns(t.name)}
            cols = [c for c in t.columns if c.name in src_cols]
            rows = [dict(r._mapping) for r in s.execute(select(*[t.c[c.name] for c in cols]))]
            if rows:
                d.execute(t.insert(), rows)
            counts[t.name] = len(rows)
        # Serial ids continue after the copied rows.
        for t in tables:
            pk = list(t.primary_key.columns)
            if len(pk) == 1 and pk[0].autoincrement is True and counts.get(t.name):
                d.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                    f"(SELECT MAX({pk[0].name}) FROM {t.name}))"
                ))  # fmt: skip
    with dst.connect() as c:
        for name, n in counts.items():
            got = c.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            assert got == n, (name, got, n)
    print({k: v for k, v in counts.items() if v})


if __name__ == "__main__":
    main()
