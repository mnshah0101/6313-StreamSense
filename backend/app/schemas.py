"""Request/response models. JSON is camelCase to match the UI's TypeScript types."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

DefectType = Literal["Blur", "Overexposure", "Low light", "Miscalibration", "Stitching", "Weather"]
GameStatus = Literal["live", "analyzed", "processing", "queued", "no-video"]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
FeedbackKind = Literal["correct", "incorrect", "missed"]


def _utc_iso(d: datetime) -> str:
    # SQLite returns naive datetimes; everything is stored in UTC, so say so explicitly.
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat().replace("+00:00", "Z")


UTCDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


class Api(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Detection(Api):
    type: DefectType
    severity: int | None = Field(None, ge=1, le=5)
    # "model" once validated against per-defect labels; "image" = copied from the image-level
    # rating; "unavailable" = no severity. The UI should not present "image" as per-defect.
    severity_source: Literal["model", "image", "unavailable"] | None = None
    location_text: str | None = None


class Heat(Api):
    cx: float
    cy: float
    r: float


class Stretch(Api):
    start: int
    end: int
    worst: int
    defects: list[Detection]
    region: str | None = None
    heat: Heat | None = None


class GameBase(Api):
    home: str
    away: str
    sport: str
    league: str = ""
    venue: str = ""
    camera: str = ""
    date: str
    start_time: str = "7:00 PM"
    duration_min: int = Field(60, ge=1, le=600)


class GameCreate(GameBase):
    id: str | None = None


class GameUpdate(Api):
    home: str | None = None
    away: str | None = None
    sport: str | None = None
    league: str | None = None
    venue: str | None = None
    camera: str | None = None
    date: str | None = None
    start_time: str | None = None
    duration_min: int | None = Field(None, ge=1, le=600)
    status: GameStatus | None = None


class GameOut(GameBase):
    id: str
    status: GameStatus
    has_video: bool
    media_kind: Literal["video", "image"] | None = None
    total_frames: int
    analyzed_frames: int
    flagged_frames: int
    open_alerts: int
    poster_url: str | None = None  # null: no video uploaded (UI keeps its placeholder art)
    stretches: list[Stretch]


class HeatmapInfo(Api):
    # available | unsupported (global defect / no spatial defect) | failed | not_requested
    status: str
    method: str | None = None
    heat: Heat | None = None
    region_bounds: list[float] | None = None
    location_text: str | None = None
    overlay_url: str | None = None


class FrameOut(Api):
    schema_version: str
    index: int
    t_sec: float
    timestamp_ms: int
    quality_issue: bool
    score: float  # issue_score, a model output in 0..1 (not a guaranteed probability)
    detections: list[Detection]
    explanation: str | None = None
    heat: Heat | None = None  # shortcut for heatmap.heat (UI field)
    heatmap: HeatmapInfo
    image_url: str | None = None
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    latency_ms: float | None = None
    localize_ms: float | None = None
    model_id: str | None = None
    parse_failed: bool = False


class AlertOut(Api):
    id: str
    game_id: str
    frame_index: int
    raised_at: str
    detections: list[Detection]
    model_output: list[Detection]
    status: Literal["open", "reviewed"]
    version: int
    threshold_id: int | None = None
    decision: Literal["confirmed", "dismissed"] | None = None
    reviewed_by: str | None = None
    reviewed_at: UTCDatetime | None = None
    created_at: UTCDatetime
    image_url: str | None = None  # the alerted frame (null for demo games without media)
    thumb_url: str | None = None


class AlertReview(Api):
    decision: Literal["confirmed", "dismissed"]
    # The alert version the reviewer loaded; a stale version gets 409 Conflict.
    expected_version: int | None = None
    note: str | None = Field(None, max_length=2000)


class Region(Api):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class FeedbackCreate(Api):
    game_id: str
    frame_index: int = Field(ge=0)
    kind: FeedbackKind
    defect: DefectType | None = None
    severity: int | None = Field(None, ge=1, le=5)
    region: Region | None = None
    note: str | None = Field(None, max_length=2000)


class FeedbackOut(FeedbackCreate):
    id: str
    reviewer: str | None = None
    created_at: UTCDatetime


class FeedbackSummary(Api):
    total: int
    correct: int
    incorrect: int
    missed: int
    observed_precision: float | None
    min_labels_for_finetune: int
    can_queue_finetune: bool


class JobCreateMatch(Api):
    game_id: str


class JobOut(Api):
    id: str
    label: str
    game_id: str | None = None
    kind: Literal["match"]
    total_frames: int
    done_frames: int
    flagged_frames: int
    status: JobStatus
    stage: str | None = None  # queued | downloading | checking | analyzing | finishing | null
    stage_detail: str | None = None
    stage_progress: float | None = None
    queue_position: int | None = None  # 1 = next to start (queued jobs only)
    eta_sec: float | None = None  # while analyzing, from the observed rate
    heartbeat_at: UTCDatetime | None = None
    poster_url: str | None = None
    failure_code: str | None = None
    error: str | None = None  # safe, user-facing failure message
    attempts: int = 0
    hardware: str
    batch_size: int | None = None
    mean_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    localize_ms_total: float = 0.0
    frames_per_sec: float | None = None
    peak_gpu_mem_mb: float | None = None
    model_id: str | None = None
    threshold_id: int | None = None
    created_at: UTCDatetime
    started_at: UTCDatetime | None = None
    finished_at: UTCDatetime | None = None


class ThresholdOut(Api):
    id: int  # the version number ("v4 published")
    alert_threshold: int  # severity cutoff, 1..5
    issue_score_cutoff: float
    model_id: str | None = None
    calibration_run_id: int | None = None
    created_by: str | None = None
    created_at: UTCDatetime


class ThresholdPublish(Api):
    alert_threshold: int = Field(ge=1, le=5)
    issue_score_cutoff: float | None = Field(None, ge=0, le=1)
    calibration_run_id: int | None = None


class DefectMetric(Api):
    p: float | None
    r: float | None
    support: int


class TradeoffPoint(Api):
    precision: float
    recall: float


class ModelRunOut(Api):
    id: int
    run_id: str
    split: str
    precision: float | None
    recall: float | None
    f1: float | None
    ap: float | None = None
    published: bool
    per_defect: dict[str, DefectMetric]
    calibration: list[list[float]]
    tradeoff: dict[str, TradeoffPoint]
    created_at: UTCDatetime


class RunImport(Api):
    run_dir: str
    published: bool = False


class ModelInfo(Api):
    direct_upload: bool = False  # browser uploads straight to S3 via /uploads
    max_upload_mb: int = 0
    max_video_sec: int = 0
    backend: str
    model_id: str
    device: str
    hardware: str
    loaded: bool
    binary_threshold: float
    frame_interval_sec: int


class BenchRunOut(Api):
    id: int
    model_id: str
    hardware: str
    target_profile: str | None
    mem_cap_gb: float | None
    mode: str
    batch_size: int
    n_frames: int
    p50_ms: float
    p95_ms: float
    mean_ms: float
    frames_per_sec: float
    peak_gpu_mem_mb: float | None
    meets_target: bool | None
    estimate: dict | None
    created_at: UTCDatetime


class AnalysisOut(Api):
    game: GameOut
    job: JobOut


class UploadCreate(Api):
    filename: str = Field(max_length=255)
    content_type: str
    size: int = Field(gt=0)


class UploadPart(Api):
    part_number: int
    url: str


class UploadOut(Api):
    upload_id: str
    part_size: int
    parts: list[UploadPart]
    expires_in_sec: int


class CompletedPart(Api):
    part_number: int = Field(ge=1, le=10000)
    etag: str


class UploadComplete(Api):
    parts: list[CompletedPart]
    home: str = Field(min_length=1, max_length=120)
    away: str = Field(min_length=1, max_length=120)
    sport: str = Field(min_length=1, max_length=60)
    league: str = Field("", max_length=120)
    venue: str = Field("", max_length=120)
    camera: str = Field("", max_length=60)
    date: str | None = None  # YYYY-MM-DD; default today
    start_time: str = Field("", max_length=20)
