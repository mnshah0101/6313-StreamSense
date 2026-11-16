"""System status: live GPUs and queue, plus aggregated model speed over time (all users).

Everything here is aggregated over jobs (never per user). Per finished job:
  wall      = finished - started            (seconds of GPU work, incl. download/decoding)
  speed     = video seconds / wall          ("x real time": 12x = an hour of video in 5 min)
  fps       = frames / wall
  queue     = started - created             (waiting for a GPU)
  latency   = the job's per-frame model latency p50 / p95
Summaries take the median across jobs, so one odd job does not swing them.
"""

from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import viewer
from app.config import Settings
from app.db import get_db
from app.models import Job, WorkerState
from app.schemas import Api, UTCDatetime

from .common import settings_dep

router = APIRouter(tags=["status"], dependencies=[Depends(viewer)])

RANGES = {"24h": (timedelta(hours=24), timedelta(hours=1)),
          "7d": (timedelta(days=7), timedelta(hours=6)),
          "30d": (timedelta(days=30), timedelta(days=1))}  # fmt: skip
ONLINE_SEC = 60


class GpuLive(Api):
    id: str
    hardware: str
    model_id: str | None
    state: str  # starting | idle | busy
    job_id: str | None = None
    job_label: str | None = None
    job_progress: float | None = None
    last_seen_at: UTCDatetime


class Live(Api):
    gpus: list[GpuLive]
    queued: int
    running: int
    oldest_wait_sec: float | None


class Summary(Api):
    jobs_done: int
    jobs_failed: int
    success_rate: float | None
    frames: int
    video_hours: float
    speed_x: float | None  # median "x real time"
    fps: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    queue_wait_p50_sec: float | None
    queue_wait_p95_sec: float | None
    turnaround_per_video_hour_min: float | None  # minutes from upload to results per video hour
    peak_gpu_mem_gb: float | None


class GpuStats(Api):
    hardware: str
    jobs: int
    frames: int
    video_hours: float
    speed_x: float | None
    fps: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    peak_gpu_mem_gb: float | None
    busy_pct: float | None  # share of the window this GPU type spent on jobs (per worker)


class Point(Api):
    t: UTCDatetime  # bucket start
    jobs: int
    failed: int
    frames: int
    video_hours: float
    speed_x: float | None
    fps: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    queue_wait_sec: float | None


class Status(Api):
    range: str
    bucket_sec: int
    generated_at: UTCDatetime
    live: Live
    summary: Summary
    by_gpu: list[GpuStats]
    series: list[Point]


def _aware(t: datetime | None) -> datetime | None:
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def _med(xs: list[float]) -> float | None:
    return round(median(xs), 3) if xs else None


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 3)


def _job_metrics(j: Job) -> dict | None:
    start, end, created = _aware(j.started_at), _aware(j.finished_at), _aware(j.created_at)
    if not (start and end) or end <= start or not j.done_frames:
        return None
    wall = (end - start).total_seconds()
    video_sec = j.done_frames * j.sample_interval_ms / 1000 if j.done_frames > 1 else 0.0
    return {
        "wall": wall,
        "frames": j.done_frames,
        "video_sec": video_sec,
        "speed": video_sec / wall if video_sec else None,
        "fps": j.done_frames / wall,
        "p50": j.p50_latency_ms,
        "p95": j.p95_latency_ms,
        "queue": (start - created).total_seconds() if created else None,
        "turnaround": (end - created).total_seconds() if created else None,
        "mem": j.peak_gpu_mem_mb,
        "worker": j.worker_id,
        "hardware": j.hardware or "unknown",
        "end": end,
    }


def _agg(ms: list[dict]) -> dict:
    vals = lambda k: [m[k] for m in ms if m[k] is not None]  # noqa: E731
    video_sec = sum(m["video_sec"] for m in ms)
    turn = [m["turnaround"] / (m["video_sec"] / 3600) / 60 for m in ms
            if m["turnaround"] is not None and m["video_sec"] >= 60]  # fmt: skip
    mem = vals("mem")
    return {
        "frames": sum(m["frames"] for m in ms),
        "video_hours": round(video_sec / 3600, 4),
        "speed_x": _med(vals("speed")),
        "fps": _med(vals("fps")),
        "latency_p50_ms": _med(vals("p50")),
        "latency_p95_ms": _med(vals("p95")),
        "queue_p50": _med(vals("queue")),
        "queue_p95": _pct(vals("queue"), 0.95),
        "turnaround": _med(turn),
        "peak_mem_gb": round(max(mem) / 1024, 2) if mem else None,
    }


@router.get("/status", response_model=Status)
def status(window: Literal["24h", "7d", "30d"] = Query("24h", alias="range"), db: Session = Depends(get_db),
           s: Settings = Depends(settings_dep)):  # fmt: skip
    span, step = RANGES[window]
    now = datetime.now(UTC)
    since = now - span

    # Live: workers seen in the last minute, and the queue.
    gpus = []
    for w in db.scalars(select(WorkerState).order_by(WorkerState.id)):
        seen = _aware(w.last_seen_at)
        if w.state == "stopped" or (now - seen).total_seconds() > ONLINE_SEC:
            continue
        job = db.get(Job, w.current_job_id) if w.current_job_id and w.state == "busy" else None
        gpus.append(GpuLive(
            id=w.id, hardware=w.hardware, model_id=w.model_id, state=w.state,
            job_id=job.id if job else None, job_label=job.label if job else None,
            job_progress=round(job.done_frames / job.total_frames, 3) if job and job.total_frames else None,
            last_seen_at=seen,
        ))  # fmt: skip
    queued = db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")) or 0
    running = db.scalar(select(func.count()).select_from(Job).where(Job.status == "running")) or 0
    oldest = db.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
    live = Live(gpus=gpus, queued=queued, running=running,
                oldest_wait_sec=round((now - _aware(oldest)).total_seconds(), 1) if oldest else None)  # fmt: skip

    # Finished jobs in the window.
    # SQLite stores naive UTC; compare in the database's own representation.
    since_db = since.replace(tzinfo=None) if db.get_bind().dialect.name == "sqlite" else since
    jobs = list(db.scalars(select(Job).where(Job.finished_at >= since_db)))
    done = [m for j in jobs if j.status == "done" and (m := _job_metrics(j))]
    failed = [j for j in jobs if j.status == "failed"]
    a = _agg(done)
    n_done, n_failed = len(done), len(failed)
    summary = Summary(
        jobs_done=n_done, jobs_failed=n_failed,
        success_rate=round(n_done / (n_done + n_failed), 4) if n_done + n_failed else None,
        frames=a["frames"], video_hours=a["video_hours"], speed_x=a["speed_x"], fps=a["fps"],
        latency_p50_ms=a["latency_p50_ms"], latency_p95_ms=a["latency_p95_ms"],
        queue_wait_p50_sec=a["queue_p50"], queue_wait_p95_sec=a["queue_p95"],
        turnaround_per_video_hour_min=a["turnaround"], peak_gpu_mem_gb=a["peak_mem_gb"],
    )  # fmt: skip

    # Per GPU type (busy %: GPU-seconds on jobs / (window x workers of that type)).
    by_gpu = []
    for hw in sorted({m["hardware"] for m in done}):
        ms = [m for m in done if m["hardware"] == hw]
        g = _agg(ms)
        workers = len({m["worker"] for m in ms if m["worker"]}) or 1
        busy = sum(m["wall"] for m in ms) / (span.total_seconds() * workers)
        by_gpu.append(GpuStats(
            hardware=hw, jobs=len(ms), frames=g["frames"], video_hours=g["video_hours"],
            speed_x=g["speed_x"], fps=g["fps"], latency_p50_ms=g["latency_p50_ms"],
            latency_p95_ms=g["latency_p95_ms"], peak_gpu_mem_gb=g["peak_mem_gb"],
            busy_pct=round(min(1.0, busy) * 100, 1),
        ))  # fmt: skip

    # Time series by job finish time; empty buckets are kept (gaps, not zeros, in charts).
    n_buckets = int(span / step)
    start = now - step * n_buckets
    buckets: list[list[dict]] = [[] for _ in range(n_buckets)]
    fails = [0] * n_buckets
    for m in done:
        i = int((m["end"] - start) / step)
        if 0 <= i < n_buckets:
            buckets[i].append(m)
    for j in failed:
        i = int((_aware(j.finished_at) - start) / step)
        if 0 <= i < n_buckets:
            fails[i] += 1
    series = []
    for i, ms in enumerate(buckets):
        g = _agg(ms)
        series.append(Point(
            t=start + step * i, jobs=len(ms), failed=fails[i], frames=g["frames"],
            video_hours=g["video_hours"], speed_x=g["speed_x"], fps=g["fps"],
            latency_p50_ms=g["latency_p50_ms"], latency_p95_ms=g["latency_p95_ms"],
            queue_wait_sec=g["queue_p50"],
        ))  # fmt: skip
    return Status(range=window, bucket_sec=int(step.total_seconds()), generated_at=now,
                  live=live, summary=summary, by_gpu=by_gpu, series=series)  # fmt: skip
