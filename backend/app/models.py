"""ORM tables.

Follows the Detailed Design V1 ERDs (Figures 4-5) where they matter for behaviour, simplified
where the UI needs less: a MediaAsset is folded into Game (match video) or Job (clip/image);
Prediction + Defect rows are folded into Frame (defects as a JSON list, raw model output kept);
ReviewDecision is folded into Alert (immutable once written, version-checked).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SCHEMA_VERSION = "1.0"


def now() -> datetime:
    return datetime.now(UTC)


class ModelVersion(Base):
    """A fixed record of the model that produced results (provider, checkpoint, revision)."""

    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # e.g. qwen3_vl_4b@ebb281ec+run
    backend: Mapped[str]
    provider: Mapped[str] = mapped_column(default="")
    revision: Mapped[str | None] = mapped_column(default=None)
    checkpoint: Mapped[str | None] = mapped_column(default=None)
    scoring_method: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    home: Mapped[str]
    away: Mapped[str]
    sport: Mapped[str]
    league: Mapped[str] = mapped_column(default="")
    venue: Mapped[str] = mapped_column(default="")
    camera: Mapped[str] = mapped_column(default="")
    date: Mapped[str]  # ISO date
    start_time: Mapped[str] = mapped_column(default="7:00 PM")
    duration_min: Mapped[int] = mapped_column(default=60)
    # live | analyzed | processing | queued | no-video
    status: Mapped[str] = mapped_column(default="no-video")
    video_key: Mapped[str | None] = mapped_column(default=None)  # uploaded video or image
    video_sha256: Mapped[str | None] = mapped_column(default=None)
    video_duration_sec: Mapped[float | None] = mapped_column(default=None)
    poster_key: Mapped[str | None] = mapped_column(default=None)  # 640x360 JPEG
    created_at: Mapped[datetime] = mapped_column(default=now)

    frames: Mapped[list["Frame"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", passive_deletes=True
    )


class Job(Base):
    """AnalysisJob: one asset (image, clip or match), one model version, claimed by a lease."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str]
    game_id: Mapped[str | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str]  # clip | image | match
    # queued | running | done | failed | cancelled
    status: Mapped[str] = mapped_column(default="queued")
    input_key: Mapped[str | None] = mapped_column(default=None)  # media-store key of the upload
    input_sha256: Mapped[str | None] = mapped_column(default=None)
    poster_key: Mapped[str | None] = mapped_column(default=None)
    sample_interval_ms: Mapped[int] = mapped_column(default=5000)
    total_frames: Mapped[int] = mapped_column(default=0)
    done_frames: Mapped[int] = mapped_column(default=0)
    flagged_frames: Mapped[int] = mapped_column(default=0)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), default=None)
    threshold_id: Mapped[int | None] = mapped_column(
        ForeignKey("threshold_versions.id"), default=None
    )
    hardware: Mapped[str] = mapped_column(default="")
    # Throughput stats. Model latency is per frame (batch time / batch size); localization
    # (heat maps) is timed separately; frames_per_sec is end to end over the job's wall time.
    batch_size: Mapped[int | None] = mapped_column(default=None)
    mean_latency_ms: Mapped[float] = mapped_column(default=0.0)
    max_latency_ms: Mapped[float] = mapped_column(default=0.0)
    p50_latency_ms: Mapped[float | None] = mapped_column(default=None)
    p95_latency_ms: Mapped[float | None] = mapped_column(default=None)
    localize_ms_total: Mapped[float] = mapped_column(default=0.0)
    frames_per_sec: Mapped[float | None] = mapped_column(default=None)
    peak_gpu_mem_mb: Mapped[float | None] = mapped_column(default=None)
    # Lease: a worker claims a queued job until lease_expires_at; an expired lease is re-queued.
    worker_id: Mapped[str | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    attempts: Mapped[int] = mapped_column(default=0)
    # Scheduling: estimated size before decoding, when it (re-)entered the queue, pauses so far.
    est_frames: Mapped[int | None] = mapped_column(default=None)
    queued_at: Mapped[datetime | None] = mapped_column(default=None)
    preemptions: Mapped[int] = mapped_column(default=0, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(default=None)
    failure_detail: Mapped[str | None] = mapped_column(default=None)
    # What the worker is doing right now, for the UI (never used for control flow).
    stage: Mapped[str | None] = mapped_column(
        default=None
    )  # downloading|checking|analyzing|finishing
    stage_detail: Mapped[str | None] = mapped_column(default=None)  # e.g. "450 / 898 MB"
    stage_progress: Mapped[float | None] = mapped_column(default=None)  # 0..1 within the stage
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    stage_started_at: Mapped[datetime | None] = mapped_column(default=None)
    stage_start_frames: Mapped[int | None] = mapped_column(default=None)  # for the ETA
    requested_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class Frame(Base):
    """SampledFrame + its Prediction. One row per sampled timestamp per game (or clip job)."""

    __tablename__ = "frames"
    __table_args__ = (
        Index("ix_frames_game_index", "game_id", "index"),
        Index("ix_frames_job_index", "job_id", "index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[str | None] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    index: Mapped[int]
    timestamp_ms: Mapped[int]
    image_key: Mapped[str | None] = mapped_column(default=None)
    thumb_key: Mapped[str | None] = mapped_column(default=None)  # 320x180 JPEG
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    # Prediction
    schema_version: Mapped[str] = mapped_column(default=SCHEMA_VERSION)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), default=None)
    quality_issue: Mapped[bool] = mapped_column(default=False)
    issue_score: Mapped[float]  # 0..1
    # [{"type", "severity", "severity_source": "model"|"unavailable", "location_text"}]
    defects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(default=None)
    # Deferred: large and never shown in lists; loaded only when accessed.
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, deferred=True)
    latency_ms: Mapped[float | None] = mapped_column(default=None)
    localize_ms: Mapped[float | None] = mapped_column(default=None)
    parse_failed: Mapped[bool] = mapped_column(default=False)

    game: Mapped[Game | None] = relationship(back_populates="frames")
    overlays: Mapped[list["Localization"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class Localization(Base):
    """LocalizationArtifact: a heat-map overlay for one defect on one frame, with provenance.

    method_status says whether an overlay exists: available | unsupported | failed. A missing
    overlay never means the frame is clean, and global defects (lighting, weather) are
    'unsupported' rather than drawn.
    """

    __tablename__ = "localizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    defect_type: Mapped[str | None] = mapped_column(default=None)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), default=None)
    method_name: Mapped[str]  # e.g. occlusion_logodds, dummy_low_detail
    method_version: Mapped[str] = mapped_column(default="1")
    method_status: Mapped[str] = mapped_column(default="available")
    # Normalised [x0, y0, x1, y1] of the hottest region, plus the peak as a circle for the UI.
    region_bounds: Mapped[list[float] | None] = mapped_column(JSON, default=None)
    peak: Mapped[dict[str, float] | None] = mapped_column(JSON, default=None)  # {cx, cy, r}
    grid: Mapped[list[list[float]] | None] = mapped_column(JSON, default=None)
    location_text: Mapped[str | None] = mapped_column(default=None)
    object_key: Mapped[str | None] = mapped_column(default=None)  # PNG overlay
    frame_width: Mapped[int | None] = mapped_column(default=None)
    frame_height: Mapped[int | None] = mapped_column(default=None)
    is_current: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class ThresholdVersion(Base):
    """Immutable alert policy. Publishing a threshold creates a new version."""

    __tablename__ = "threshold_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), default=None)
    calibration_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_runs.id"), default=None
    )
    issue_score_cutoff: Mapped[float] = mapped_column(default=0.5)
    severity_cutoff: Mapped[int] = mapped_column(default=2)  # UI's "alert threshold" (1..5)
    created_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    frame_index: Mapped[int]
    frame_id: Mapped[int | None] = mapped_column(
        ForeignKey("frames.id", ondelete="SET NULL"), default=None
    )
    threshold_id: Mapped[int | None] = mapped_column(
        ForeignKey("threshold_versions.id"), default=None
    )
    raised_at: Mapped[str]  # wall-clock label, e.g. "8:23 PM"
    detections: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    # Original model output is preserved even after review.
    model_output: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default="open")  # open | reviewed
    version: Mapped[int] = mapped_column(default=1)  # optimistic concurrency for reviews
    decision: Mapped[str | None] = mapped_column(default=None)  # confirmed | dismissed
    reviewed_by: Mapped[str | None] = mapped_column(default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    review_note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Feedback(Base):
    """Reviewer labels on frames (correct / incorrect / missed). Never auto-added to training
    or test data; exported for an approved curation step."""

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    frame_index: Mapped[int]
    kind: Mapped[str]  # correct | incorrect | missed
    defect: Mapped[str | None] = mapped_column(default=None)
    severity: Mapped[int | None] = mapped_column(default=None)
    region: Mapped[dict[str, float] | None] = mapped_column(JSON, default=None)
    note: Mapped[str | None] = mapped_column(default=None)
    reviewer: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class ModelRun(Base):
    """EvaluationRun summary for the Model Performance page."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str]  # e.g. "E-07c"
    split: Mapped[str]  # e.g. "validation split"
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), default=None)
    precision: Mapped[float | None] = mapped_column(default=None)
    recall: Mapped[float | None] = mapped_column(default=None)
    f1: Mapped[float | None] = mapped_column(default=None)
    ap: Mapped[float | None] = mapped_column(default=None)
    published: Mapped[bool] = mapped_column(default=False)
    per_defect: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calibration: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    tradeoff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_dir: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class FineTuneRequest(Base):
    __tablename__ = "finetune_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    labels: Mapped[int]
    status: Mapped[str] = mapped_column(default="requested")
    requested_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class BenchRun(Base):
    """One inference benchmark configuration on one GPU (scripts/bench.py)."""

    __tablename__ = "bench_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str]
    hardware: Mapped[str]  # observed GPU name
    target_profile: Mapped[str | None] = mapped_column(default=None)  # e.g. "L4 (24 GB cap)"
    mem_cap_gb: Mapped[float | None] = mapped_column(default=None)
    mode: Mapped[str]  # score | predict | localize
    batch_size: Mapped[int]
    n_frames: Mapped[int]
    p50_ms: Mapped[float]  # per frame
    p95_ms: Mapped[float]
    mean_ms: Mapped[float]
    frames_per_sec: Mapped[float]
    peak_gpu_mem_mb: Mapped[float | None] = mapped_column(default=None)
    meets_target: Mapped[bool | None] = mapped_column(default=None)  # < 5 s per sampled frame
    estimate: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Upload(Base):
    """A direct browser-to-S3 multipart upload, before it becomes a game + job."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str]  # reserved id; the game row is created on completion
    key: Mapped[str]
    s3_upload_id: Mapped[str]
    filename: Mapped[str] = mapped_column(default="")
    content_type: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)  # bytes; 10 GB overflows a 32-bit INTEGER
    status: Mapped[str] = mapped_column(default="uploading")  # uploading | completed | aborted
    requested_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class WorkerState(Base):
    """A GPU worker's heartbeat: which GPU, what it runs, whether it is busy (Status page)."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # host:pid
    hardware: Mapped[str] = mapped_column(default="")
    model_id: Mapped[str | None] = mapped_column(default=None)
    state: Mapped[str] = mapped_column(default="idle")  # starting | idle | busy | stopped
    current_job_id: Mapped[str | None] = mapped_column(default=None)
    started_at: Mapped[datetime] = mapped_column(default=now)
    last_seen_at: Mapped[datetime] = mapped_column(default=now)
