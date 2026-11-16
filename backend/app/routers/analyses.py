"""One-step analysis: upload a video or image with its game metadata, and analyze it."""

import datetime as dt
import math
import secrets

from fastapi import APIRouter, Depends, Form, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import reviewer, viewer
from app.config import Settings
from app.db import get_db
from app.media import POSTER_SIZE, MediaStore, TooLarge, receive
from app.models import Game, Job, Upload
from app.schemas import AnalysisOut, UploadComplete, UploadCreate, UploadOut, UploadPart
from app.services import current_threshold, wake_gpu
from app.video import MediaError, frame_count, poster, probe

from .common import current_user, error, game_out, job_out, settings_dep, store_dep

router = APIRouter(dependencies=[Depends(viewer)], tags=["analyses"])
UPLOAD_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


@router.post(
    "/analyses", response_model=AnalysisOut, status_code=202, dependencies=[Depends(reviewer)]
)
def create_analysis(
    file: UploadFile,
    home: str = Form(..., min_length=1, max_length=120),
    away: str = Form(..., min_length=1, max_length=120),
    sport: str = Form(..., min_length=1, max_length=60),
    league: str = Form("", max_length=120),
    venue: str = Form("", max_length=120),
    camera: str = Form("", max_length=60),
    date: dt.date | None = Form(None),
    start_time: str = Form("", max_length=20),
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    store: MediaStore = Depends(store_dep),
    user: str = Depends(current_user),
):
    """Create a game from an uploaded video (MP4/MOV, up to max_video_sec and max_upload_mb)
    or image (JPG/PNG), store the media and its poster, and queue the analysis. Returns 202;
    poll GET /jobs/{id} or GET /games/{id}. Nothing is stored unless the upload decodes."""
    ext = UPLOAD_TYPES.get(file.content_type or "")
    if ext is None:
        raise error(415, "unsupported_type",
                    f"Unsupported file type ({file.content_type}). Use MP4, MOV, JPG or PNG.")  # fmt: skip
    game_id = f"gam{secrets.token_hex(5)}"
    key = f"games/{game_id}/video/{secrets.token_hex(8)}{ext}"
    try:
        # Streamed to a temp file (TMPDIR) and decoded before anything is stored.
        with receive(file.file, s.max_upload_mb << 20, ext) as (tmp, _, sha):
            p = probe(tmp)
            if p.kind == "video" and p.duration_sec > s.max_video_sec + 0.5:
                raise MediaError("too_long",
                                 f"Video is {p.duration_sec / 3600:.1f} h; the limit is "
                                 f"{s.max_video_sec / 3600:.0f} h.")  # fmt: skip
            store.put_file(key, tmp, file.content_type)
            poster_key = f"games/{game_id}/poster.jpg"
            store.put_thumbnail(poster_key, poster(tmp), POSTER_SIZE)
    except TooLarge:
        raise error(413, "too_large", f"File is over {s.max_upload_mb / 1024:.0f} GB.") from None
    except MediaError as e:
        store.delete_prefix(f"games/{game_id}")
        raise error(422, e.code, e.message) from None
    game = Game(
        id=game_id, home=home.strip(), away=away.strip(), sport=sport.strip(),
        league=league.strip(), venue=venue.strip(), camera=camera.strip(),
        date=(date or dt.date.today()).isoformat(), start_time=start_time.strip() or "",
        duration_min=max(1, math.ceil(p.duration_sec / 60)), status="queued",
        video_key=key, video_sha256=sha, video_duration_sec=p.duration_sec if p.kind == "video" else None,
        poster_key=poster_key,
    )  # fmt: skip
    job = Job(
        id=f"job-{secrets.token_hex(6)}", label=f"{game.home} vs {game.away}", game_id=game_id,
        kind="match", total_frames=frame_count(p, s.frame_interval_sec),
        sample_interval_ms=s.frame_interval_sec * 1000,
        threshold_id=current_threshold(db, s).id, requested_by=user,
    )  # fmt: skip
    db.add(game)
    db.flush()
    db.add(job)
    db.commit()
    wake_gpu(db, s)
    return AnalysisOut(game=game_out(db, game, s), job=job_out(job, db))


# ---- direct browser -> S3 uploads (large files skip the API and any tunnel) ----------------


def _s3(store: MediaStore):  # noqa: ANN202
    if store.name != "s3":
        raise error(
            409,
            "direct_upload_unavailable",
            "Direct upload needs the S3 media backend; use POST /analyses",
        )
    return store


@router.post(
    "/uploads", response_model=UploadOut, status_code=201, dependencies=[Depends(reviewer)]
)
def start_upload(
    body: UploadCreate,
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    store: MediaStore = Depends(store_dep),
    user: str = Depends(current_user),
):
    """Start a multipart upload: returns one presigned PUT URL per part. The browser PUTs the
    parts (in parallel), keeps each response's ETag, then calls /uploads/{id}/complete."""
    s3 = _s3(store)
    ext = UPLOAD_TYPES.get(body.content_type)
    if ext is None:
        raise error(
            415,
            "unsupported_type",
            f"Unsupported file type ({body.content_type}). Use MP4, MOV, JPG or PNG.",
        )
    if body.size > s.max_upload_mb << 20:
        raise error(413, "too_large", f"File is over {s.max_upload_mb / 1024:.0f} GB.")
    part = max(s.multipart_part_mb << 20, math.ceil(body.size / 10_000))  # S3: <= 10,000 parts
    n_parts = max(1, math.ceil(body.size / part))
    game_id = f"gam{secrets.token_hex(5)}"
    key = f"games/{game_id}/video/{secrets.token_hex(8)}{ext}"
    upload_id = s3.create_multipart(key, body.content_type)
    ttl = 6 * 3600  # long enough for a 10 GB upload on a slow link
    up = Upload(
        id=f"upl-{secrets.token_hex(8)}", game_id=game_id, key=key, s3_upload_id=upload_id,
        filename=body.filename, content_type=body.content_type, size=body.size, requested_by=user,
    )  # fmt: skip
    db.add(up)
    db.commit()
    parts = [
        UploadPart(part_number=i, url=s3.presign_part(key, upload_id, i, ttl))
        for i in range(1, n_parts + 1)
    ]
    return UploadOut(upload_id=up.id, part_size=part, parts=parts, expires_in_sec=ttl)


def _open_upload(db: Session, upload_id: str) -> Upload:
    up = db.get(Upload, upload_id)
    if up is None or up.status != "uploading":
        raise error(404, "upload_not_found", "No upload in progress with that id")
    return up


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=AnalysisOut,
    status_code=202,
    dependencies=[Depends(reviewer)],
)
def complete_upload(
    upload_id: str,
    body: UploadComplete,
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    store: MediaStore = Depends(store_dep),
    user: str = Depends(current_user),
):
    """Assemble the parts, check the stored size, create the game and queue the analysis. The
    worker decode-checks the file (format, length limit) and makes the poster before analyzing."""
    s3 = _s3(store)
    up = _open_upload(db, upload_id)
    parts = sorted(body.parts, key=lambda p: p.part_number)
    try:
        s3.complete_multipart(
            up.key, up.s3_upload_id, [{"PartNumber": p.part_number, "ETag": p.etag} for p in parts]
        )
        size = s3.size(up.key)
    except Exception:  # noqa: BLE001 - missing/bad parts: the client can retry the parts
        raise error(
            422, "upload_incomplete", "Upload parts are missing or invalid; retry the upload"
        ) from None
    if size != up.size or size > s.max_upload_mb << 20:
        store.delete_prefix(f"games/{up.game_id}")
        up.status = "aborted"
        db.commit()
        raise error(422, "size_mismatch", "Uploaded size does not match the declared size")
    meta = body.model_dump(exclude={"parts"})
    date = meta.pop("date") or dt.date.today().isoformat()
    game, job = _create_game_and_job(db, s, up.game_id, up.key, None, user, date=date, **meta)
    game.status = "queued"
    up.status = "completed"
    db.commit()
    wake_gpu(db, s)
    return AnalysisOut(game=game_out(db, game, s), job=job_out(job, db))


@router.post("/uploads/{upload_id}/abort", status_code=204, dependencies=[Depends(reviewer)])
def abort_upload(
    upload_id: str, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    s3 = _s3(store)
    up = _open_upload(db, upload_id)
    try:
        s3.abort_multipart(up.key, up.s3_upload_id)
    finally:
        up.status = "aborted"
        db.commit()
    return Response(status_code=204)


def _create_game_and_job(
    db: Session, s: Settings, game_id: str, key: str, sha: str | None, user: str, **meta
) -> tuple[Game, Job]:
    """Game + queued match job. Frame count and poster are set by the worker after decoding."""
    game = Game(
        id=game_id, home=meta["home"].strip(), away=meta["away"].strip(), sport=meta["sport"].strip(),
        league=meta.get("league", "").strip(), venue=meta.get("venue", "").strip(),
        camera=meta.get("camera", "").strip(), date=meta["date"], start_time=meta.get("start_time", "").strip(),
        duration_min=1, status="queued", video_key=key, video_sha256=sha,
    )  # fmt: skip
    job = Job(
        id=f"job-{secrets.token_hex(6)}", label=f"{game.home} vs {game.away}", game_id=game_id,
        kind="match", total_frames=0, sample_interval_ms=s.frame_interval_sec * 1000,
        threshold_id=current_threshold(db, s).id, requested_by=user,
    )  # fmt: skip
    db.add(game)
    db.flush()
    db.add(job)
    return game, job
