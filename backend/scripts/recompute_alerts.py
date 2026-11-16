"""Re-apply the alert rules (threshold + min_alert_frames) to stored frames; no re-inference.

  PYTHONPATH=. python scripts/recompute_alerts.py --all            # every game with finished analysis
  PYTHONPATH=. python scripts/recompute_alerts.py GAME_ID [...]    # specific games

Uses STREAMSENSE_API_DB_URL from the environment / .env. Open alerts that no longer qualify are
deleted; reviewed alerts are kept. Games with a running job are skipped (the worker owns them).
"""

import sys

from sqlalchemy import select

from app import db as dbm
from app.config import Settings
from app.models import Game, Job
from app.services import current_threshold, recompute_alerts


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    s = Settings()
    dbm.init_engine(s.database_url)
    with dbm.session() as db:
        ids = list(db.scalars(select(Game.id))) if args == ["--all"] else args
        th = current_threshold(db, s)
        for gid in ids:
            game = db.get(Game, gid)
            if game is None:
                print(f"{gid}: not found")
                continue
            if db.scalars(
                select(Job.id).where(Job.game_id == gid, Job.status == "running")
            ).first():
                print(f"{gid}: analysis still running, skipped")
                continue
            one = len(
                list(db.scalars(select(Job.id).where(Job.game_id == gid, Job.kind == "image")))
            )
            added, removed = recompute_alerts(db, game, th, 1 if one else s.min_alert_frames)
            print(f"{gid}: +{added} -{removed} alerts")


if __name__ == "__main__":
    main()
