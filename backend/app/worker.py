"""GPU worker: claims queued jobs from the database with a lease and runs inference.

Durability rules:
- A job is claimed by a conditional UPDATE (status queued -> running), so two workers never
  run the same job. The lease is renewed after every batch.
- Results are committed batch by batch; `done_frames` is the resume point. If a worker dies,
  its lease expires, the job is re-queued, and the next claim resumes from `done_frames`.
- Bad media fails immediately with a stable code; other errors retry up to `max_attempts`.

Run as its own process next to the GPU:  python -m app.worker
or embedded in the API process for development (STREAMSENSE_API_EMBEDDED_WORKER=true).
"""

import logging
import math
import os
import queue
import shutil
import socket
import threading
import time
import traceback
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import delete, select, update

from app import auth as _auth  # noqa: F401  (registers user tables)
from app import db as dbm
from app.config import Settings, get_settings
from app.defects import SPATIAL_DEFECTS
from app.inference import Backend, build_backend
from app.inference.base import FrameResult
from app.media import POSTER_SIZE, MediaStore, build_store
from app.models import Frame, Game, Job, Localization, ThresholdVersion, WorkerState
from app.scheduler import queue_order, queued_jobs, should_yield
from app.services import current_overlays, current_threshold, ensure_model_version, raise_alerts
from app.video import MediaError, frame_count, poster, probe, sample

log = logging.getLogger("streamsense.worker")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(t: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; everything is stored in UTC.
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def hardware_label(settings: Settings, backend: Backend) -> str:
    if settings.hardware_label:
        return settings.hardware_label
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except ImportError:
        pass
    return "cpu"


class Worker:
    def __init__(
        self, settings: Settings, backend: Backend, store: MediaStore, worker_id: str | None = None
    ) -> None:
        self.s = settings
        self.backend = backend
        self.store = store
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.hardware = hardware_label(settings, backend)
        # Media writes (frames, thumbnails) run concurrently; S3 PUTs are latency-bound.
        self.io = ThreadPoolExecutor(
            max_workers=settings.media_io_threads, thread_name_prefix="media"
        )

    # ---- queue -------------------------------------------------------------------------

    def requeue_expired(self) -> int:
        with dbm.session() as db:
            res = db.execute(
                update(Job)
                .where(Job.status == "running", Job.lease_expires_at < utcnow())
                .values(status="queued", worker_id=None, lease_expires_at=None, queued_at=utcnow())
            )
            db.commit()
            return res.rowcount or 0

    def claim(self) -> str | None:
        with dbm.session() as db:
            # Shortest remaining work first, with aging (app/scheduler.py); try a few in order
            # in case another worker wins the race for the first.
            order = [j.id for j in queue_order(queued_jobs(db), self.s)][:5]
            for job_id in order:
                res = db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "queued")
                    .values(
                        status="running",
                        worker_id=self.id,
                        attempts=Job.attempts + 1,
                        lease_expires_at=utcnow() + timedelta(seconds=self.s.lease_sec),
                    )
                )
                db.commit()
                if res.rowcount == 1:
                    return job_id
        return None

    def run_once(self) -> bool:
        """Claim and run one job. Returns False when the queue is empty."""
        self.requeue_expired()
        job_id = self.claim()
        if job_id is None:
            return False
        self.process(job_id)
        return True

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        log.info(
            "worker %s up: backend=%s model=%s hardware=%s",
            self.id,
            self.backend.name,
            self.backend.model_version,
            self.hardware,
        )
        self._beat("starting", force=True)
        self.backend.load()
        last_work = time.monotonic()
        while not stop.is_set():
            try:
                self._beat("idle")
                if self.run_once():
                    last_work = time.monotonic()
                else:
                    idle = self.s.idle_shutdown_sec
                    if idle is not None and time.monotonic() - last_work > idle:
                        log.info("idle for %ss: stopping this machine", idle)
                        self._beat("stopped", force=True)
                        os.system(self.s.idle_shutdown_cmd)  # noqa: S605 - fixed, configured command
                        return
                    stop.wait(self.s.poll_sec)
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("worker loop error")
                stop.wait(self.s.poll_sec)

    # ---- one job -----------------------------------------------------------------------

    def process(self, job_id: str) -> None:
        self._beat("busy", job_id, force=True)
        try:
            self._run(job_id)
        except MediaError as e:
            self._finish(job_id, "failed", e.code, e.message)
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
            with dbm.session() as db:
                job = db.get(Job, job_id)
                retry = job is not None and job.attempts < self.s.max_attempts
            if retry:
                with dbm.session() as db:
                    db.execute(
                        update(Job)
                        .where(Job.id == job_id)
                        .values(
                            status="queued",
                            worker_id=None,
                            lease_expires_at=None,
                            queued_at=utcnow(),
                        )
                    )
                    db.commit()
            else:
                self._finish(
                    job_id,
                    "failed",
                    "internal_error",
                    "Analysis failed after retries. The job can be re-run.",
                )

    def _run(self, job_id: str) -> None:
        with dbm.session() as db:
            job = db.get(Job, job_id)
            game = db.get(Game, job.game_id) if job.game_id else None
            if game is None or not game.video_key:
                raise MediaError("media_missing", "This game has no uploaded media to analyze")
            mv = ensure_model_version(db, self.backend)
            threshold = (
                db.get(ThresholdVersion, job.threshold_id)
                if job.threshold_id
                else current_threshold(db, self.s)
            )
            if job.started_at is None:
                job.started_at = utcnow()
            job.model_id, job.threshold_id, job.hardware = mv.id, threshold.id, self.hardware
            job.batch_size = self.s.batch_size
            _reset_peak_memory()
            if job.done_frames == 0:  # fresh (re-)run: replace earlier results
                db.execute(delete(Frame).where(Frame.game_id == game.id))
            game.status = "processing"
            db.commit()
            start, game_id, key = job.done_frames, game.id, game.video_key
            interval_ms = job.sample_interval_ms

        with ExitStack() as stack:
            if self.store.name == "s3":
                self._stage(job_id, "downloading", "Downloading video", 0.0, force=True)
            progress = self._throttled(
                job_id,
                "downloading",
                lambda d, t: (f"{d / 2**20:.0f} / {t / 2**20:.0f} MB", d / max(t, 1)),
            )
            cached = self._resume_file(job_id, key)
            try:  # S3: downloaded to a temp file (kept if this job is paused, to resume fast)
                if self.store.name == "s3" and cached.is_file():
                    path = cached
                    log.info("job %s: resuming from the local copy", job_id)
                else:
                    path = stack.enter_context(self.store.local_copy(key, on_progress=progress))
            except FileNotFoundError:
                raise MediaError(
                    "media_missing", "The uploaded media is no longer available"
                ) from None
            total = self._validate_media(job_id, game_id, path)
            # Short media gets a heat map on every flagged spatial frame; long matches only on
            # the frames alerts point to (occlusion costs ~25 forward passes per frame).
            localize_all = total <= self.s.localize_all_max_frames
            with dbm.session() as db:
                job = db.get(Job, job_id)
                job.stage, job.stage_detail, job.stage_progress = "analyzing", None, None
                job.stage_started_at, job.stage_start_frames = utcnow(), job.done_frames
                job.heartbeat_at = utcnow()
                db.commit()
            for batch in self._media_batches(path, interval_ms / 1000, start, threshold):
                if not self._still_mine(job_id):
                    log.info("job %s cancelled or lease lost; stopping", job_id)
                    return
                self._save_batch(job_id, game_id, batch, mv.id, threshold, localize_all, total)
                self._beat("busy", job_id)  # throttled to every 10 s; keeps Status "online"
                if self._yield_to_shorter(job_id, path, cached):
                    return
        cached.unlink(missing_ok=True)
        self._stage(job_id, "finishing", "Finishing up", None, force=True)
        with dbm.session() as db:  # the decoder is the truth if the container over-reported
            job = db.get(Job, job_id)
            if job.done_frames < job.total_frames:
                job.total_frames = job.done_frames
                db.commit()
        self._finish(job_id, "done")

    def _validate_media(self, job_id: str, game_id: str, path) -> int:
        """Direct-to-S3 uploads were never seen by the API: decode-check them here (format,
        length limit), make the poster and set the frame count. Returns total frames."""
        with dbm.session() as db:
            job, game = db.get(Job, job_id), db.get(Game, game_id)
            if game.poster_key and job.total_frames:
                return job.total_frames
            job.stage, job.stage_detail, job.stage_progress = "checking", "Checking video", None
            job.heartbeat_at = utcnow()
            db.commit()
            p = probe(path)  # raises MediaError on undecodable/unsupported media
            if p.kind == "video" and p.duration_sec > self.s.max_video_sec + 0.5:
                raise MediaError(
                    "too_long",
                    f"Video is {p.duration_sec / 3600:.1f} h; the limit is "
                    f"{self.s.max_video_sec / 3600:.0f} h.",
                )
            poster_key = f"games/{game_id}/poster.jpg"
            self.store.put_thumbnail(poster_key, poster(path), POSTER_SIZE)
            game.poster_key = job.poster_key = poster_key
            game.video_duration_sec = p.duration_sec if p.kind == "video" else None
            game.duration_min = max(1, math.ceil(p.duration_sec / 60))
            job.total_frames = frame_count(p, self.s.frame_interval_sec)
            db.commit()
            return job.total_frames

    def _media_batches(
        self, path, interval_sec: float, start: int, threshold: ThresholdVersion
    ) -> Iterator[list]:
        """Score every frame (one forward pass); generate defects + explanation only for frames
        at or above the issue-score cutoff (generate="flagged"), or for all (generate="all").
        Decoding runs one batch ahead in a background thread, overlapping the GPU."""
        for chunk in prefetch(chunks(sample(path, interval_sec, start), self.s.batch_size)):
            ims = [im for _, _, im in chunk]
            t0 = time.perf_counter()
            scores = self.backend.score(ims)
            score_ms = 1000 * (time.perf_counter() - t0) / len(ims)
            results = [FrameResult(score=s, latency_ms=score_ms) for s in scores]
            todo = [
                i
                for i, s in enumerate(scores)
                if self.s.generate == "all" or s >= threshold.issue_score_cutoff
            ]
            if todo:
                t1 = time.perf_counter()
                described = self.backend.describe([ims[i] for i in todo])
                gen_ms = 1000 * (time.perf_counter() - t1) / len(todo)
                for i, r in zip(todo, described, strict=True):
                    r.score, r.latency_ms = scores[i], score_ms + gen_ms
                    results[i] = r
            yield [(i, t, im, r) for (i, t, im), r in zip(chunk, results, strict=True)]

    def _save_batch(
        self,
        job_id: str,
        game_id: str,
        batch: list[tuple[int, int, Image.Image, FrameResult]],
        model_id: str,
        threshold: ThresholdVersion,
        localize_all: bool,
        total: int = 2,
    ) -> None:
        owner = f"games/{game_id}/runs/{job_id}"
        writes: list = []
        with dbm.session() as db:
            job = db.get(Job, job_id)
            lat = []
            for idx, t_ms, im, r in batch:
                flagged = bool(r.detections) or r.score >= threshold.issue_score_cutoff
                defects = [{**d, "severity_source": r.severity_source} for d in r.detections]
                f = Frame(
                    game_id=game_id,
                    job_id=job_id,
                    index=idx,
                    timestamp_ms=t_ms,
                    model_id=model_id,
                    quality_issue=flagged,
                    issue_score=float(r.score),
                    defects=defects,
                    explanation=r.explanation,
                    raw_output=r.raw_output,
                    latency_ms=r.latency_ms,
                    parse_failed=r.parse_failed,
                    image_key=f"{owner}/{idx:06d}.jpg",
                    thumb_key=f"{owner}/{idx:06d}_thumb.jpg",
                    width=im.width,
                    height=im.height,
                )
                writes += [
                    self.io.submit(self.store.put_image, f.image_key, im),
                    self.io.submit(self.store.put_thumbnail, f.thumb_key, im),
                ]
                db.add(f)
                db.flush()
                if flagged and localize_all:
                    self._localize(db, f, im, model_id, owner)
                job.flagged_frames += int(flagged)
                job.localize_ms_total += f.localize_ms or 0.0
                if r.latency_ms is not None:
                    lat.append(r.latency_ms)
            n_before = job.done_frames
            job.done_frames = n_before + len(batch)
            if lat:
                job.mean_latency_ms = (job.mean_latency_ms * n_before + sum(lat)) / job.done_frames
                job.max_latency_ms = max(job.max_latency_ms, max(lat))
            job.lease_expires_at = utcnow() + timedelta(seconds=self.s.lease_sec)
            job.heartbeat_at = utcnow()
            # Rows are committed only once their images are stored (a row never points at a
            # missing object); .result() re-raises a failed write, so the batch is retried.
            for w in writes:
                w.result()
            db.commit()
            game = db.get(Game, game_id)
            min_frames = 1 if total <= 1 else self.s.min_alert_frames  # an image is one frame
            new_alerts = raise_alerts(
                db, game, threshold, since_index=batch[0][0], min_frames=min_frames
            )
            if not localize_all:
                # Every alert gets its heat map: localize the frame it points to (read back
                # from the store; the worst frame may be from an earlier batch).
                for a in new_alerts:
                    f = db.get(Frame, a.frame_id)
                    if f is None or current_overlays(db, [f.id]):
                        continue
                    with self.store.local_copy(f.image_key) as p, Image.open(p) as im:
                        self._localize(db, f, im.convert("RGB"), model_id, owner)
                    job.localize_ms_total += f.localize_ms or 0.0
                db.commit()

    def _localize(self, db, frame: Frame, im: Image.Image, model_id: str, owner: str) -> None:
        """Heat map for one flagged frame, recorded as a Localization row whatever happens."""
        spatial = [d["type"] for d in frame.defects if d["type"] in SPATIAL_DEFECTS]
        defect = spatial[0] if spatial else (frame.defects[0]["type"] if frame.defects else None)
        base = dict(
            frame_id=frame.id,
            defect_type=defect,
            model_id=model_id,
            frame_width=frame.width,
            frame_height=frame.height,
        )
        if not spatial or not self.s.localize:
            # Global defects (lighting, weather) have no region to highlight.
            db.add(Localization(**base, method_name="none", method_status="unsupported"))
            return
        t0 = time.perf_counter()
        try:
            loc = self.backend.localize(im)
        except Exception as e:  # noqa: BLE001 - an overlay failure never fails the job
            log.warning("localization failed for frame %s: %s", frame.id, e)
            loc, status = None, "failed"
        else:
            status = "available" if loc else "unsupported"
        frame.localize_ms = 1000 * (time.perf_counter() - t0)
        if loc is None:
            db.add(Localization(**base, method_name="none", method_status=status))
            return
        key = f"{owner}/{frame.index:06d}_heat.png"
        self.store.put_image(key, overlay_png(np.array(loc.grid), im.size), "PNG")
        db.add(
            Localization(
                **base,
                method_name=loc.method,
                method_version=loc.method_version,
                region_bounds=loc.region_bounds,
                peak=loc.peak,
                grid=loc.grid,
                object_key=key,
            )
        )

    def _beat(self, state: str, job_id: str | None = None, force: bool = False) -> None:
        """Worker heartbeat for the Status page (at most every 10 s unless the state changes)."""
        now_ = time.monotonic()
        if (
            not force
            and state == getattr(self, "_last_state", None)
            and now_ - getattr(self, "_last_beat", 0) < 10
        ):
            return
        self._last_state, self._last_beat = state, now_
        try:
            with dbm.session() as db:
                w = db.get(WorkerState, self.id) or WorkerState(id=self.id, started_at=utcnow())
                w.hardware, w.model_id = self.hardware, self.backend.model_version
                w.state, w.current_job_id, w.last_seen_at = state, job_id, utcnow()
                db.merge(w)
                db.commit()
        except Exception:  # noqa: BLE001 - status reporting must never stop the worker
            log.debug("heartbeat failed", exc_info=True)

    def _stage(self, job_id: str, stage: str, detail: str | None, progress: float | None,
               force: bool = False) -> None:  # fmt: skip
        """Record what the job is doing (and a heartbeat) for the UI. Display only."""
        with dbm.session() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "running":
                return
            job.stage, job.stage_detail, job.stage_progress = stage, detail, progress
            job.heartbeat_at = utcnow()
            db.commit()

    def _throttled(self, job_id: str, stage: str, fmt, every_sec: float = 2.0):  # noqa: ANN001, ANN202
        """A progress callback that writes at most every `every_sec` (S3 calls it per chunk)."""
        last = [0.0]

        def cb(done: int, total: int) -> None:
            now = time.monotonic()
            if now - last[0] < every_sec and done < total:
                return
            last[0] = now
            detail, frac = fmt(done, total)
            try:
                self._stage(job_id, stage, f"Downloading video · {detail}", round(frac, 3))
            except Exception:  # noqa: BLE001 - progress display must never break the job
                log.debug("stage update failed", exc_info=True)

        return cb

    def _still_mine(self, job_id: str) -> bool:
        with dbm.session() as db:
            job = db.get(Job, job_id)
            return job is not None and job.status == "running" and job.worker_id == self.id

    # ---- scheduling ----------------------------------------------------------------------

    def _resume_file(self, job_id: str, key: str) -> Path:
        return Path(self.s.data_dir) / "resume" / f"{job_id}{Path(key).suffix}"

    def _yield_to_shorter(self, job_id: str, path: Path, cached: Path) -> bool:
        """Between batches: pause this job if a much shorter one is waiting (SRPT preemption).
        Progress is already committed, so the job resumes from its next frame later."""
        now_ = time.monotonic()
        if now_ - getattr(self, "_last_sched", 0.0) < self.s.sched_check_sec:
            return False
        self._last_sched = now_
        with dbm.session() as db:
            job = db.get(Job, job_id)
            shorter = should_yield(db, job, self.id, self.s) if job else None
            if shorter is None:
                return False
            res = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.worker_id == self.id, Job.status == "running")
                .values(
                    status="queued", worker_id=None, lease_expires_at=None, queued_at=utcnow(),
                    preemptions=Job.preemptions + 1, attempts=Job.attempts - 1,  # not a failure
                    stage="paused", stage_detail="Paused for a shorter video", stage_progress=None,
                )
            )  # fmt: skip
            if job.game_id and res.rowcount:
                db.get(Game, job.game_id).status = "queued"
            db.commit()
            if not res.rowcount:
                return False
            log.info(
                "job %s paused at frame %s for shorter job %s", job_id, job.done_frames, shorter.id
            )
        if (
            self.store.name == "s3" and path != cached
        ):  # keep the video to resume without re-download
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                for old in sorted(cached.parent.glob("*"), key=lambda p: p.stat().st_mtime)[:-1]:
                    old.unlink(missing_ok=True)  # keep at most two paused videos on disk
                shutil.move(str(path), cached)
            except OSError:
                log.warning("could not keep the video of paused job %s", job_id, exc_info=True)
        return True

    def _finish(
        self, job_id: str, status: str, code: str | None = None, detail: str | None = None
    ) -> None:
        for f in (Path(self.s.data_dir) / "resume").glob(f"{job_id}.*"):
            f.unlink(missing_ok=True)  # a paused job's kept video
        with dbm.session() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status, job.failure_code, job.failure_detail = status, code, detail
            job.stage = job.stage_detail = job.stage_progress = None
            job.finished_at, job.lease_expires_at = utcnow(), None
            if status == "done":
                _throughput(db, job)
            if job.game_id:
                game = db.get(Game, job.game_id)
                if game is not None:
                    game.status = (
                        "analyzed"
                        if status == "done"
                        else ("analyzed" if job.done_frames else "queued")
                    )
            db.commit()


def _reset_peak_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass


def _peak_memory_mb() -> float | None:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 2**20
    except ImportError:
        pass
    return None


def _throughput(db, job: Job) -> None:
    lat = sorted(
        x
        for x in db.scalars(select(Frame.latency_ms).where(Frame.job_id == job.id))
        if x is not None
    )
    if lat:
        job.p50_latency_ms = float(np.percentile(lat, 50))
        job.p95_latency_ms = float(np.percentile(lat, 95))
    started = _aware(job.started_at)
    if started and job.done_frames:
        wall = (_aware(job.finished_at) - started).total_seconds()
        job.frames_per_sec = job.done_frames / wall if wall > 0 else None
    job.peak_gpu_mem_mb = _peak_memory_mb()


def overlay_png(grid: np.ndarray, size: tuple[int, int]) -> Image.Image:
    """RGBA overlay with the frame's exact dimensions: red, alpha = normalised signal."""
    g = grid.astype(np.float32)
    g = (g - g.min()) / max(float(g.max() - g.min()), 1e-6)
    alpha = Image.fromarray((g * 170).astype(np.uint8), "L").resize(size, Image.BICUBIC)
    rgba = Image.new("RGBA", size, (230, 40, 40, 0))
    rgba.putalpha(alpha)
    return rgba


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    settings.check_persistent()
    dbm.init_engine(settings.database_url)
    worker = Worker(settings, build_backend(settings), build_store(settings))
    stop = threading.Event()
    try:
        worker.run_forever(stop)
    except KeyboardInterrupt:
        stop.set()


_DONE = object()


def chunks(it: Iterator, n: int) -> Iterator[list]:
    """Consecutive lists of up to n items."""
    while chunk := list(islice(it, n)):
        yield chunk


def prefetch(items: Iterator, depth: int = 2) -> Iterator:
    """Run an iterator in a background thread, `depth` items ahead (decode overlaps the GPU).
    Exceptions are re-raised in the consumer."""
    q: queue.Queue = queue.Queue(maxsize=depth)

    def run() -> None:
        try:
            for x in items:
                q.put(x)
        except BaseException as e:  # noqa: BLE001
            q.put(e)
        finally:
            q.put(_DONE)

    threading.Thread(target=run, daemon=True, name="decode-prefetch").start()
    while (x := q.get()) is not _DONE:
        if isinstance(x, BaseException):
            raise x
        yield x


if __name__ == "__main__":
    main()
