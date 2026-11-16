"""Games (one stream = one match): CRUD, match video upload, sampled frame results."""

import secrets

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import admin, reviewer, viewer
from app.config import Settings
from app.db import get_db
from app.media import MediaStore
from app.models import Frame, Game, Job
from app.schemas import FrameOut, GameCreate, GameOut, GameUpdate
from app.services import current_overlays

from .common import error, frame_out, game_out, settings_dep, store_dep

router = APIRouter(dependencies=[Depends(viewer)], prefix="/games", tags=["games"])


def _get(db: Session, game_id: str) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise error(404, "game_not_found", f"No game with id {game_id!r}")
    return game


@router.get("", response_model=list[GameOut])
def list_games(
    q: str | None = None,
    sport: str | None = None,
    status: str | None = None,
    camera: str | None = None,
    defect: str | None = Query(None, description="games with a stretch of this defect"),
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
):
    stmt = select(Game).order_by(Game.date.desc(), Game.id)
    if sport:
        stmt = stmt.where(Game.sport == sport)
    if status:
        stmt = stmt.where(Game.status == status)
    if camera:
        stmt = stmt.where(Game.camera == camera)
    out = [game_out(db, g, s) for g in db.scalars(stmt)]
    if q:
        ql = q.lower()
        out = [
            g
            for g in out
            if ql in f"{g.id} {g.home} {g.away} {g.venue} {g.league} {g.sport} {g.camera}".lower()
        ]
    if defect:
        out = [g for g in out if any(d.type == defect for st in g.stretches for d in st.defects)]
    return out


@router.post("", response_model=GameOut, status_code=201, dependencies=[Depends(reviewer)])
def create_game(
    body: GameCreate, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)
):
    game_id = body.id or f"gam{secrets.token_hex(4)}"
    if db.get(Game, game_id):
        raise error(409, "game_exists", f"Game {game_id!r} already exists")
    game = Game(id=game_id, status="no-video", **body.model_dump(exclude={"id"}))
    db.add(game)
    db.commit()
    return game_out(db, game, s)


@router.get("/{game_id}", response_model=GameOut)
def get_game(game_id: str, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    return game_out(db, _get(db, game_id), s)


@router.patch("/{game_id}", response_model=GameOut, dependencies=[Depends(reviewer)])
def update_game(
    game_id: str,
    body: GameUpdate,
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
):
    game = _get(db, game_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(game, k, v)
    db.commit()
    return game_out(db, game, s)


@router.delete("/{game_id}", status_code=204, dependencies=[Depends(admin)])
def delete_game(
    game_id: str, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    game = _get(db, game_id)
    running = db.scalar(
        select(Job.id).where(Job.game_id == game_id, Job.status.in_(("queued", "running")))
    )
    if running:
        raise error(409, "job_in_progress", "Cancel the running analysis before deleting")
    db.delete(game)
    db.commit()
    # Media goes with the record: footage, sampled frames and overlays.
    store.delete_prefix(f"games/{game_id}")
    return Response(status_code=204)


@router.get("/{game_id}/frames", response_model=list[FrameOut])
def list_frames(
    game_id: str,
    start: int = Query(0, ge=0),
    end: int | None = Query(None, ge=0),
    flagged: bool = False,
    db: Session = Depends(get_db),
):
    """Sampled frames with results, ordered by time. Partial while a job is running."""
    _get(db, game_id)
    stmt = select(Frame).where(Frame.game_id == game_id, Frame.index >= start)
    if end is not None:
        stmt = stmt.where(Frame.index <= end)
    if flagged:
        stmt = stmt.where(Frame.quality_issue.is_(True))
    frames = list(db.scalars(stmt.order_by(Frame.index)))
    locs = current_overlays(db, [f.id for f in frames if f.quality_issue])
    return [frame_out(f, locs.get(f.id)) for f in frames]


@router.get("/{game_id}/frames/{index}", response_model=FrameOut)
def get_frame(game_id: str, index: int, db: Session = Depends(get_db)):
    f = db.scalar(select(Frame).where(Frame.game_id == game_id, Frame.index == index))
    if f is None:
        raise error(404, "frame_not_found", "No analyzed frame at that index")
    return frame_out(f, current_overlays(db, [f.id]).get(f.id))
