"""Domain logic shared by the API and the worker: stretches, alert policy, versions."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Alert, Frame, Game, Localization, ModelVersion, ThresholdVersion


@dataclass
class StretchData:
    start: int
    end: int
    worst: int
    defects: list[dict[str, Any]]
    worst_frame_id: int
    region: str | None = None
    heat: dict[str, float] | None = None
    frames: list[int] = field(default_factory=list)


def max_severity(defects: list[dict[str, Any]]) -> int:
    return max((d.get("severity") or 0 for d in defects), default=0)


def stretches(
    frames: list[Frame], overlays: dict[int, Localization] | None = None, max_gap: int = 1
) -> list[StretchData]:
    """Group flagged frames (ordered by index) into runs; a gap of up to `max_gap` unflagged
    frames does not split a run. The worst frame is the highest severity, then score."""
    out: list[StretchData] = []
    cur: list[Frame] = []

    def close() -> None:
        if not cur:
            return
        worst = max(cur, key=lambda f: (max_severity(f.defects), f.issue_score))
        loc = (overlays or {}).get(worst.id)
        out.append(
            StretchData(
                start=cur[0].index,
                end=cur[-1].index,
                worst=worst.index,
                defects=[_ui_det(d) for d in worst.defects],
                worst_frame_id=worst.id,
                region=loc.location_text if loc else None,
                heat=loc.peak if loc and loc.method_status == "available" else None,
                frames=[f.index for f in cur],
            )
        )

    for f in frames:
        if not (f.quality_issue and f.defects):
            continue
        if cur and f.index - cur[-1].index > max_gap + 1:
            close()
            cur = []
        cur.append(f)
    close()
    return out


def _ui_det(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": d["type"],
        "severity": d.get("severity") or 1,
        "severity_source": d.get("severity_source"),
    }


def current_overlays(db: Session, frame_ids: list[int]) -> dict[int, Localization]:
    if not frame_ids:
        return {}
    rows = db.scalars(
        select(Localization).where(
            Localization.frame_id.in_(frame_ids), Localization.is_current.is_(True)
        )
    ).all()
    out: dict[int, Localization] = {}
    for r in rows:  # prefer an available overlay over unsupported/failed
        if r.frame_id not in out or (r.method_status == "available"):
            out[r.frame_id] = r
    return out


def game_frames(db: Session, game_id: str) -> list[Frame]:
    return list(db.scalars(select(Frame).where(Frame.game_id == game_id).order_by(Frame.index)))


def current_threshold(db: Session, settings: Settings) -> ThresholdVersion:
    t = db.scalars(select(ThresholdVersion).order_by(ThresholdVersion.id.desc()).limit(1)).first()
    if t is None:
        t = ThresholdVersion(
            severity_cutoff=settings.default_alert_threshold,
            issue_score_cutoff=settings.binary_threshold,
            created_by="system",
        )
        db.add(t)
        db.commit()
    return t


def ensure_model_version(db: Session, backend) -> ModelVersion:  # noqa: ANN001
    mv = db.get(ModelVersion, backend.model_version)
    if mv is None:
        info = getattr(backend, "provenance", lambda: {})()
        mv = ModelVersion(id=backend.model_version, backend=backend.name, **info)
        db.add(mv)
        db.commit()
    return mv


def wall_clock(game: Game, t_sec: float) -> str:
    """Match start "7:30 PM" + offset -> "8:04 PM"."""
    try:
        time, ampm = game.start_time.split(" ")
        hh, mm = (int(x) for x in time.split(":"))
    except ValueError:
        return f"+{int(t_sec // 60)}:{int(t_sec % 60):02d}"
    h24 = hh % 12 + (12 if ampm.upper() == "PM" else 0)
    minutes = (h24 * 60 + mm + int(t_sec // 60)) % (24 * 60)
    h24, m = divmod(minutes, 60)
    h12 = 12 if h24 % 12 == 0 else h24 % 12
    return f"{h12}:{m:02d} {'PM' if h24 >= 12 else 'AM'}"


def longest_run(indices: list[int]) -> int:
    """Length of the longest run of consecutive integers in a sorted list."""
    best = cur = 0
    for k, i in enumerate(indices):
        cur = cur + 1 if k and i == indices[k - 1] + 1 else 1
        best = max(best, cur)
    return best


def raise_alerts(
    db: Session, game: Game, threshold: ThresholdVersion, since_index: int = 0, min_frames: int = 1
) -> list[Alert]:
    """One alert per stretch whose worst frame clears the threshold; returns alerts that are new
    or now point at a different frame (so the caller can localize that frame).

    Incremental: only stretches that reach `since_index` (the first frame of the latest batch)
    can change, so only frames from the start of the run touching it are loaded; a 10-hour
    match does not reload every frame after every batch. An open alert follows its stretch's
    worst frame as the stretch grows (its version bumps, so a stale review gets 409); reviewed
    alerts never change. The alert id derives from the stretch start, so re-runs add nothing.
    """
    lo = run_start(db, game.id, since_index)
    frames = list(
        db.scalars(
            select(Frame).where(Frame.game_id == game.id, Frame.index >= lo).order_by(Frame.index)
        )
    )
    changed = []
    for s in stretches(frames, current_overlays(db, [f.id for f in frames if f.quality_issue])):
        if s.end < since_index:
            continue  # finished before this batch: already handled
        if longest_run(s.frames) < min_frames:
            continue  # not persistent enough (yet): stays on the timeline, no alert
        worst = next(f for f in frames if f.id == s.worst_frame_id)
        # Frames are flagged with the threshold's issue-score cutoff; severity gates alerts.
        if max_severity(worst.defects) < threshold.severity_cutoff:
            continue
        dets = [_ui_det(d) for d in worst.defects]
        alert_id = f"alr-{game.id}-{s.start}"
        a = db.get(Alert, alert_id)
        if a is None:
            a = Alert(
                id=alert_id, game_id=game.id, frame_index=worst.index, frame_id=worst.id,
                threshold_id=threshold.id, raised_at=wall_clock(game, worst.timestamp_ms / 1000),
                detections=dets, model_output=dets,
            )  # fmt: skip
            db.add(a)
            changed.append(a)
        elif a.status == "open" and a.frame_id != worst.id:
            a.frame_index, a.frame_id = worst.index, worst.id
            a.raised_at = wall_clock(game, worst.timestamp_ms / 1000)
            a.detections = a.model_output = dets
            a.version += 1
            changed.append(a)
    db.commit()
    return changed


def run_start(db: Session, game_id: str, index: int, max_gap: int = 1) -> int:
    """First index of the flagged run that reaches `index` (same gap rule as stretches)."""
    flagged = db.scalars(
        select(Frame.index)
        .where(Frame.game_id == game_id, Frame.index < index, Frame.quality_issue.is_(True))
        .order_by(Frame.index.desc())
    )
    start = index
    for i in flagged:
        if start - i > max_gap + 1:
            break
        start = i
    return start


def wake_gpu(db: Session, settings: Settings) -> bool:
    """Start the on-demand cloud GPU when work is queued and no worker is online. Best effort:
    a failure here never fails the request (PACE or a later start picks the job up)."""
    if not settings.gpu_instance_id:
        return False
    from datetime import UTC, datetime, timedelta

    from app.models import WorkerState

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    if db.get_bind().dialect.name == "sqlite":
        cutoff = cutoff.replace(tzinfo=None)
    online = db.scalar(select(WorkerState.id).where(
        WorkerState.last_seen_at >= cutoff, WorkerState.state != "stopped").limit(1))  # fmt: skip
    if online:
        return False
    try:
        import boto3

        ec2 = boto3.client("ec2", region_name=settings.gpu_region)
        state = ec2.describe_instances(InstanceIds=[settings.gpu_instance_id])[
            "Reservations"][0]["Instances"][0]["State"]["Name"]  # fmt: skip
        if state == "stopped":
            ec2.start_instances(InstanceIds=[settings.gpu_instance_id])
            return True
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("streamsense.api").warning("could not start GPU instance", exc_info=True)
    return False


def recompute_alerts(
    db: Session, game: Game, threshold: ThresholdVersion, min_frames: int
) -> tuple[int, int]:
    """Re-apply the alert rules to a game's stored frames (no re-inference). Adds alerts that
    now qualify and deletes open alerts that no longer do; reviewed alerts are kept as history.
    Returns (added, removed)."""
    before = set(db.scalars(select(Alert.id).where(Alert.game_id == game.id)))
    raise_alerts(db, game, threshold, since_index=0, min_frames=min_frames)
    frames = game_frames(db, game.id)
    keep = {
        f"alr-{game.id}-{s.start}"
        for s in stretches(frames)
        if longest_run(s.frames) >= min_frames
        and max_severity(next(f for f in frames if f.id == s.worst_frame_id).defects)
        >= threshold.severity_cutoff
    }
    removed = 0
    for a in db.scalars(select(Alert).where(Alert.game_id == game.id, Alert.status == "open")):
        if a.id not in keep:
            db.delete(a)
            removed += 1
    db.commit()
    after = set(db.scalars(select(Alert.id).where(Alert.game_id == game.id)))
    return len(after - before), removed
