"""Shared dependencies, errors and serializers for the routers."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import authenticate
from app.config import Settings
from app.media import MediaStore
from app.models import Alert, Frame, Game, Job, Localization
from app.schemas import AlertOut, FrameOut, GameOut, HeatmapInfo, JobOut, Stretch
from app.services import current_overlays, game_frames, stretches


def error(status: int, code: str, message: str) -> HTTPException:
    """Errors carry a stable code and a safe message, never paths or stack traces."""
    return HTTPException(status, detail={"code": code, "message": message})


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def store_dep(request: Request) -> MediaStore:
    return request.app.state.store


def current_user(user=Depends(authenticate)) -> str:  # noqa: ANN001
    """Who is acting, from the signed-in session (never from a header or body field)."""
    return user.name


def total_frames(game: Game, s: Settings) -> int:
    if game.video_duration_sec:  # the real video length, not the scheduled duration
        from app.video import Probe, frame_count

        return frame_count(Probe("video", game.video_duration_sec, 0, 0), s.frame_interval_sec)
    return max(1, round(game.duration_min * 60 / s.frame_interval_sec))


def game_out(db: Session, game: Game, s: Settings) -> GameOut:
    frames = game_frames(db, game.id)
    overlays = current_overlays(db, [f.id for f in frames if f.quality_issue])
    open_alerts = db.scalar(
        select(func.count())
        .select_from(Alert)
        .where(Alert.game_id == game.id, Alert.status == "open")
    )
    return GameOut(
        id=game.id,
        home=game.home,
        away=game.away,
        sport=game.sport,
        league=game.league,
        venue=game.venue,
        camera=game.camera,
        date=game.date,
        start_time=game.start_time,
        duration_min=game.duration_min,
        status=game.status,
        has_video=bool(game.video_key),
        media_kind=_media_kind(game.video_key),
        total_frames=total_frames(game, s),
        analyzed_frames=len(frames),
        flagged_frames=sum(f.quality_issue for f in frames),
        open_alerts=open_alerts or 0,
        poster_url=f"/media/games/{game.id}/poster" if game.poster_key else None,
        stretches=[
            Stretch(
                start=x.start,
                end=x.end,
                worst=x.worst,
                defects=x.defects,
                region=x.region,
                heat=x.heat,
            )
            for x in stretches(frames, overlays)
        ],
    )


def heatmap_info(f: Frame, loc: Localization | None) -> HeatmapInfo:
    if loc is None:
        # No overlay row: not computed (clean frame, or a long match where only alerted
        # frames are localized). Never implies the frame is clean.
        return HeatmapInfo(status="not_requested")
    return HeatmapInfo(
        status=loc.method_status,
        method=loc.method_name,
        heat=loc.peak if loc.method_status == "available" else None,
        region_bounds=loc.region_bounds,
        location_text=loc.location_text,
        overlay_url=f"/media/overlays/{loc.id}" if loc.object_key else None,
    )


def frame_out(f: Frame, loc: Localization | None) -> FrameOut:
    hm = heatmap_info(f, loc)
    return FrameOut(
        schema_version=f.schema_version,
        index=f.index,
        t_sec=f.timestamp_ms / 1000,
        timestamp_ms=f.timestamp_ms,
        quality_issue=f.quality_issue,
        score=f.issue_score,
        detections=f.defects,
        explanation=f.explanation,
        heat=hm.heat,
        heatmap=hm,
        image_url=f"/media/frames/{f.id}" if f.image_key else None,
        thumb_url=f"/media/frames/{f.id}/thumb" if f.thumb_key else None,
        width=f.width,
        height=f.height,
        latency_ms=f.latency_ms,
        localize_ms=f.localize_ms,
        model_id=f.model_id,
        parse_failed=f.parse_failed,
    )


def job_out(j: Job, db: Session | None = None) -> JobOut:
    return JobOut(
        stage="queued" if j.status == "queued" else (j.stage if j.status == "running" else None),
        stage_detail=j.stage_detail if j.status == "running" else None,
        stage_progress=j.stage_progress if j.status == "running" else None,
        queue_position=_queue_position(db, j),
        eta_sec=_eta(j),
        heartbeat_at=j.heartbeat_at,
        id=j.id,
        label=j.label,
        game_id=j.game_id,
        kind=j.kind,
        total_frames=j.total_frames,
        done_frames=j.done_frames,
        flagged_frames=j.flagged_frames,
        status=j.status,
        poster_url=f"/media/jobs/{j.id}/poster" if j.poster_key else None,
        failure_code=j.failure_code,
        error=j.failure_detail,
        attempts=j.attempts,
        hardware=j.hardware,
        batch_size=j.batch_size,
        mean_latency_ms=round(j.mean_latency_ms, 1),
        max_latency_ms=round(j.max_latency_ms, 1),
        p50_latency_ms=j.p50_latency_ms,
        p95_latency_ms=j.p95_latency_ms,
        localize_ms_total=round(j.localize_ms_total, 1),
        frames_per_sec=j.frames_per_sec,
        peak_gpu_mem_mb=j.peak_gpu_mem_mb,
        model_id=j.model_id,
        threshold_id=j.threshold_id,
        created_at=j.created_at,
        started_at=j.started_at,
        finished_at=j.finished_at,
    )


def alert_out(db: Session, a: Alert) -> AlertOut:
    out = AlertOut.model_validate(a)
    f = db.get(Frame, a.frame_id) if a.frame_id else None
    if f is not None:
        out.image_url = f"/media/frames/{f.id}" if f.image_key else None
        out.thumb_url = f"/media/frames/{f.id}/thumb" if f.thumb_key else None
    return out


def _media_kind(key: str | None) -> str | None:
    if not key:
        return None
    return "image" if key.rsplit(".", 1)[-1].lower() in ("jpg", "jpeg", "png") else "video"


def _queue_position(db: Session | None, j: Job) -> int | None:
    if db is None or j.status != "queued":
        return None
    ahead = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == "queued", Job.created_at < j.created_at)
    )
    return (ahead or 0) + 1


def _eta(j: Job) -> float | None:
    """Seconds left while analyzing, from this attempt's observed frame rate."""
    if j.status != "running" or j.stage != "analyzing" or not j.stage_started_at:
        return None
    from datetime import UTC, datetime

    started = (
        j.stage_started_at if j.stage_started_at.tzinfo else j.stage_started_at.replace(tzinfo=UTC)
    )
    done = j.done_frames - (j.stage_start_frames or 0)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    if done < 1 or elapsed <= 0 or j.total_frames <= j.done_frames:
        return None
    return round((j.total_frames - j.done_frames) * elapsed / done, 1)
