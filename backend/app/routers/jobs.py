"""Analysis jobs. Creating one returns 202 at once; the GPU worker does the work."""

import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import reviewer, viewer
from app.config import Settings
from app.db import get_db
from app.models import Frame, Game, Job
from app.schemas import FrameOut, JobCreateMatch, JobOut
from app.services import current_overlays, current_threshold, wake_gpu
from app.video import Probe, frame_count

from .common import current_user, error, frame_out, job_out, settings_dep, total_frames

router = APIRouter(dependencies=[Depends(viewer)], prefix="/jobs", tags=["jobs"])
ACTIVE = ("queued", "running")


def _get(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise error(404, "job_not_found", f"No job with id {job_id!r}")
    return job


@router.post("/match", response_model=JobOut, status_code=202, dependencies=[Depends(reviewer)])
def run_match(
    body: JobCreateMatch,
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    user: str = Depends(current_user),
):
    """Analyze every sampled frame of a game's recorded match (re-run replaces results)."""
    game = db.get(Game, body.game_id)
    if game is None:
        raise error(404, "game_not_found", f"No game with id {body.game_id!r}")
    if game.status == "live":
        raise error(409, "game_live", "Live games are analyzed as frames arrive")
    if not game.video_key:
        raise error(409, "no_video", "No video available for this match. Upload it first.")
    existing = db.scalar(select(Job).where(Job.game_id == game.id, Job.status.in_(ACTIVE)))
    if existing:  # a double click returns the job already running
        return job_out(existing, db)
    n = total_frames(game, s)
    if game.video_key and game.video_duration_sec:
        n = frame_count(Probe("video", game.video_duration_sec, 0, 0), s.frame_interval_sec)
    job = Job(
        id=f"job-{secrets.token_hex(6)}",
        label=f"{game.id} · {game.home} vs {game.away}",
        game_id=game.id,
        kind="match",
        total_frames=n,
        sample_interval_ms=s.frame_interval_sec * 1000,
        threshold_id=current_threshold(db, s).id,
        requested_by=user,
    )
    game.status = "queued"
    db.add(job)
    db.commit()
    wake_gpu(db, s)
    return job_out(job, db)


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = None,
    game_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Job.status == status)
    if game_id:
        stmt = stmt.where(Job.game_id == game_id)
    return [job_out(j, db) for j in db.scalars(stmt)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return job_out(_get(db, job_id), db)


@router.get("/{job_id}/frames", response_model=list[FrameOut])
def job_frames(job_id: str, db: Session = Depends(get_db)):
    _get(db, job_id)
    frames = list(db.scalars(select(Frame).where(Frame.job_id == job_id).order_by(Frame.index)))
    locs = current_overlays(db, [f.id for f in frames if f.quality_issue])
    return [frame_out(f, locs.get(f.id)) for f in frames]


@router.post("/{job_id}/cancel", response_model=JobOut, dependencies=[Depends(reviewer)])
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    if job.status in ACTIVE:
        job.status = "cancelled"  # the worker checks this after every batch
        job.lease_expires_at = None
        if job.game_id and (game := db.get(Game, job.game_id)):
            game.status = "analyzed" if job.done_frames else "queued"
        db.commit()
    return job_out(job, db)
