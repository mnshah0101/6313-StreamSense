"""Job scheduling: shortest remaining processing time first (SRPT), with preemption and aging.

Why SRPT: it minimises mean turnaround time, and here job sizes are known (video length, or the
upload size as a stand-in until the worker probes it). A 30-second clip should not wait behind a
4-hour match.

Why preemption is cheap here: workers commit results batch by batch and a job resumes from its
last committed frame (the same path that survives a lost lease), so pausing a long job costs at
most one batch. The worker also keeps the paused job's video on local disk to resume quickly.

Guards against SRPT's failure modes:
  * Aging: a queued job's priority improves by `sched_aging` video-seconds per second it waits
    (about the GPU's speed, so waiting time and work are on the same scale); long matches cannot
    starve behind a stream of short clips.
  * Hysteresis: preempt only for a job under `preempt_ratio` x my remaining work, only when no
    GPU is idle, only the running job with the most work left, never a job nearly done, and at
    most `max_preemptions` times per job.

Priorities are in seconds of video still to analyze (lower runs first).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job, WorkerState

ONLINE_SEC = 60  # same window as the Status page


def _aware(t: datetime | None) -> datetime | None:
    return t if t is None or t.tzinfo else t.replace(tzinfo=UTC)


def estimate_frames(duration_sec: float | None, size_bytes: int | None, s: Settings) -> int | None:
    """Expected sampled frames before the worker has decoded the video."""
    if duration_sec:
        return max(1, int(duration_sec // s.frame_interval_sec) + 1)
    if size_bytes:
        return max(1, int(size_bytes / s.sched_bytes_per_video_sec // s.frame_interval_sec) + 1)
    return None


def remaining_frames(j: Job) -> int:
    total = j.total_frames or j.est_frames or 0
    if total <= 0:
        return 10**9  # unknown size: schedule after everything we can size
    return max(0, total - j.done_frames)


def priority(j: Job, now: datetime, s: Settings) -> float:
    """Remaining video seconds, minus credit for time spent waiting in the queue."""
    rem = remaining_frames(j) * j.sample_interval_ms / 1000
    since = _aware(j.queued_at) or _aware(j.created_at) or now
    return rem - s.sched_aging * max(0.0, (now - since).total_seconds())


def queue_order(jobs: list[Job], s: Settings, now: datetime | None = None) -> list[Job]:
    now = now or datetime.now(UTC)
    if s.sched_policy == "fifo":
        return sorted(jobs, key=lambda j: _aware(j.created_at) or now)
    return sorted(jobs, key=lambda j: (priority(j, now, s), _aware(j.created_at) or now))


def queued_jobs(db: Session, limit: int = 500) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.status == "queued").limit(limit)))


def should_yield(db: Session, job: Job, worker_id: str, s: Settings) -> Job | None:
    """The queued job this worker should switch to (pausing `job`), or None to keep going."""
    if not s.preempt or s.sched_policy != "srpt" or job.preemptions >= s.max_preemptions:
        return None
    mine = remaining_frames(job)
    if mine < s.preempt_min_frames:
        return None  # nearly done: finishing is cheaper than switching
    queued = queued_jobs(db)
    if not queued:
        return None
    now = datetime.now(UTC)
    best = queue_order(queued, s, now)[0]
    if priority(best, now, s) >= s.preempt_ratio * mine * job.sample_interval_ms / 1000:
        return None
    cutoff = (now - timedelta(seconds=ONLINE_SEC)).replace(tzinfo=None)
    idle = db.scalar(
        select(WorkerState.id).where(
            WorkerState.id != worker_id,
            WorkerState.state == "idle",
            WorkerState.last_seen_at >= cutoff,
        )
    )
    if idle:
        return None  # a free GPU will take it
    running = db.scalars(select(Job).where(Job.status == "running", Job.id != job.id))
    me = (mine, job.id)  # ties broken by id, so two equal jobs never both yield
    if any((remaining_frames(r), r.id) > me and r.preemptions < s.max_preemptions for r in running):
        return None  # a longer job should yield instead
    return best
