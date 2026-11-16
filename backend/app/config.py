"""Service settings, read from STREAMSENSE_API_* environment variables (or a .env file)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STREAMSENSE_API_", env_file=".env", extra="ignore"
    )

    # Storage: SQLite file + a media directory for uploads and sampled frame JPEGs.
    # Persistent state: SQLite DB (unless db_url) and, with the local media backend, every
    # upload, sampled frame and heat-map overlay. Must survive restarts; resolved to an
    # absolute path at startup. Production: media_backend=s3 (+ Postgres via db_url).
    data_dir: Path = Path("var")
    db_url: str | None = None  # default: sqlite:///<data_dir>/streamsense.db
    # Refuse to keep media in temp/node-local dirs (/tmp, /dev/shm, $TMPDIR) unless set.
    allow_ephemeral_media: bool = False

    # Media: "local" (data_dir/media) or "s3". S3 credentials come from the standard AWS chain
    # (env vars, profile, instance/task role). s3_endpoint_url targets MinIO / R2.
    media_backend: Literal["local", "s3"] = "local"
    s3_bucket: str | None = None
    s3_prefix: str = "streamsense/"
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    presign_ttl_sec: int = 300

    # Inference backend. "dummy" needs no GPU; "streamsense" loads a playonsports run dir.
    backend: Literal["dummy", "streamsense"] = "dummy"
    run_dir: Path | None = None  # playonsports outputs/<exp>/<run> (has run_record.json, adapter/)
    streamsense_repo: Path | None = None  # playonsports checkout, put on sys.path
    device: str | None = None  # e.g. "cuda:0"; None = the run's own setting
    batch_size: int = 8  # frames per inference call
    binary_threshold: float = 0.5  # P(issue) at or above which a frame is flagged
    # Generated JSON on val: median 64 tokens on flagged frames, max 96. Generation stops at the
    # end of the JSON, so this only bounds a runaway output (training config uses 256).
    max_new_tokens: int = 128

    # Worker. embedded_worker runs it inside the API process (dev); in production run
    # `python -m app.worker` on the GPU host against the same database and media store.
    embedded_worker: bool = True
    lease_sec: int = 120  # renewed after every batch; an expired lease re-queues the job
    poll_sec: float = 1.0
    max_attempts: int = 3
    # Cloud GPU on demand: the API starts this EC2 instance when a job is queued and no worker
    # has checked in for a minute; the worker there stops its machine after idle_shutdown_sec.
    gpu_instance_id: str | None = None
    gpu_region: str = "us-east-2"
    idle_shutdown_sec: int | None = None
    idle_shutdown_cmd: str = "sudo /usr/sbin/shutdown -h now"
    localize: bool = True  # heat maps (occlusion) for spatial defects
    # Videos up to this many sampled frames (5 min) get a heat map on every flagged spatial
    # frame; longer ones only on the frame each alert points to.
    localize_all_max_frames: int = 60
    # "flagged": every frame is scored, defects/explanation are generated only for frames at or
    # above the issue-score cutoff (fast enough for L4-class GPUs). "all": generate for every frame.
    generate: Literal["flagged", "all"] = "flagged"

    # Sampling: production analyzes one frame every 5 seconds.
    frame_interval_sec: int = 5
    max_upload_mb: int = 10240  # 10 GB per upload (streamed / multipart, never held in memory)
    max_video_sec: int = 36000  # 10 hours, checked by decoding the upload
    media_io_threads: int = 16  # concurrent media writes (S3 PUTs) in the worker
    multipart_part_mb: int = 64  # direct-to-S3 upload part size (10 GB = 160 parts)

    default_alert_threshold: int = 2
    min_labels_for_finetune: int = 50

    # Sign-in. "session": accounts + HttpOnly session cookie (default). "off": everyone is a
    # built-in admin (tests and local scripts only; logged loudly at startup).
    auth_mode: Literal["session", "off"] = "session"
    session_ttl_hours: int = 72
    cookie_secure: bool = False  # True behind HTTPS (production)

    # Shared access token (dev/staging gate until OIDC): when set, every route except /health
    # needs "Authorization: Bearer <token>" (the UI dev-server proxy adds it server-side).
    token: str | None = None  # env: STREAMSENSE_API_TOKEN

    cors_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]
    cors_origin_regex: str | None = r"https://.*\.vercel\.app"

    hardware_label: str | None = None  # shown on jobs; default: detected GPU name or "cpu"

    @property
    def database_url(self) -> str:
        url = self.db_url or f"sqlite:///{(self.data_dir / 'streamsense.db').resolve()}"
        # Provider URLs (Neon, RDS) say postgresql://; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def media_dir(self) -> Path:
        return self.data_dir.resolve() / "media"

    def check_persistent(self) -> None:
        """Fail fast if sampled frames would land somewhere that does not survive a restart."""
        if self.media_backend != "local" or self.allow_ephemeral_media:
            return
        import os
        import tempfile

        media = self.media_dir
        volatile = {Path("/tmp"), Path("/dev/shm"), Path("/var/tmp"), Path(tempfile.gettempdir())}
        if os.environ.get("TMPDIR"):
            volatile.add(Path(os.environ["TMPDIR"]))
        for v in volatile:
            v = v.resolve()
            if media == v or v in media.parents:
                raise ValueError(
                    f"Media dir {media} is under {v}, which is not persistent. Set "
                    "STREAMSENSE_API_DATA_DIR to persistent storage, use MEDIA_BACKEND=s3, or "
                    "STREAMSENSE_API_ALLOW_EPHEMERAL_MEDIA=true for throwaway runs."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
