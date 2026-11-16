"""Thresholds (versioned), model info, evaluation runs, and private media."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import admin, viewer
from app.config import Settings
from app.db import get_db
from app.defects import CREW_TO_DEFECT, DEFECT_TYPES
from app.media import THUMB_CACHE, MediaStore
from app.models import (
    BenchRun,
    Frame,
    Game,
    Job,
    Localization,
    ModelRun,
    ModelVersion,
    ThresholdVersion,
    WorkerState,
)
from app.schemas import (
    BenchRunOut,
    ModelInfo,
    ModelRunOut,
    RunImport,
    ThresholdOut,
    ThresholdPublish,
)
from app.services import current_threshold, ensure_model_version

from .common import current_user, error, settings_dep, store_dep

router = APIRouter(tags=["meta"])
NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/health")
def health(request: Request):
    b, store = request.app.state.backend, request.app.state.store
    where = f"s3://{store.bucket}/{store.prefix}" if store.name == "s3" else str(store.root)
    return {
        "ok": True,
        "backend": b.name,
        "model": b.model_version,
        "loaded": b.loaded,
        "media": {"backend": store.name, "location": where},
    }


@router.get("/model", response_model=ModelInfo, dependencies=[Depends(viewer)])
def model_info(
    request: Request, s: Settings = Depends(settings_dep), db: Session = Depends(get_db)
):
    b = request.app.state.backend
    w = serving_worker(db, s)  # an API without its own worker reports what the workers serve
    return ModelInfo(
        direct_upload=s.media_backend == "s3",
        max_upload_mb=s.max_upload_mb,
        max_video_sec=s.max_video_sec,
        backend="worker" if w else b.name,
        model_id=w.model_id if w else b.model_version,
        device="cuda" if w else b.device,
        hardware=w.hardware if w else request.app.state.hardware,
        loaded=True if w else b.loaded,
        binary_threshold=s.binary_threshold,
        frame_interval_sec=s.frame_interval_sec,
    )


def serving_worker(db: Session, s: Settings) -> WorkerState | None:
    """The most recently seen online worker, when this API does not run its own."""
    if s.embedded_worker:
        return None
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    if db.get_bind().dialect.name == "sqlite":
        cutoff = cutoff.replace(tzinfo=None)
    return db.scalar(
        select(WorkerState)
        .where(WorkerState.last_seen_at >= cutoff, WorkerState.state != "stopped")
        .order_by(WorkerState.last_seen_at.desc())
    )


# ---- thresholds: immutable versions --------------------------------------------------------


@router.get("/thresholds/current", response_model=ThresholdOut, dependencies=[Depends(viewer)])
def threshold_current(db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    return _threshold_out(current_threshold(db, s))


@router.get("/thresholds", response_model=list[ThresholdOut], dependencies=[Depends(viewer)])
def threshold_history(db: Session = Depends(get_db)):
    rows = db.scalars(select(ThresholdVersion).order_by(ThresholdVersion.id.desc()))
    return [_threshold_out(t) for t in rows]


@router.post(
    "/thresholds", response_model=ThresholdOut, status_code=201, dependencies=[Depends(admin)]
)
def publish_threshold(
    body: ThresholdPublish,
    request: Request,
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    user: str = Depends(current_user),
):
    """Publish a new alert policy version. Applies to jobs created after this; existing
    alerts keep the version that raised them."""
    prev = current_threshold(db, s)
    if body.calibration_run_id is not None and db.get(ModelRun, body.calibration_run_id) is None:
        raise error(422, "unknown_run", "calibration_run_id does not exist")
    w = serving_worker(db, request.app.state.settings)
    model_id = (
        w.model_id if w and w.model_id else ensure_model_version(db, request.app.state.backend).id
    )
    t = ThresholdVersion(
        model_id=model_id if db.get(ModelVersion, model_id) else None,
        calibration_run_id=body.calibration_run_id,
        severity_cutoff=body.alert_threshold,
        issue_score_cutoff=body.issue_score_cutoff
        if body.issue_score_cutoff is not None
        else prev.issue_score_cutoff,
        created_by=user,
    )
    db.add(t)
    db.commit()
    return _threshold_out(t)


def _threshold_out(t: ThresholdVersion) -> ThresholdOut:
    return ThresholdOut(
        id=t.id,
        alert_threshold=t.severity_cutoff,
        issue_score_cutoff=t.issue_score_cutoff,
        model_id=t.model_id,
        calibration_run_id=t.calibration_run_id,
        created_by=t.created_by,
        created_at=t.created_at,
    )


# ---- evaluation runs -----------------------------------------------------------------------


@router.get("/runs", response_model=list[ModelRunOut], dependencies=[Depends(viewer)])
def list_runs(db: Session = Depends(get_db)):
    return list(
        db.scalars(select(ModelRun).order_by(ModelRun.published.desc(), ModelRun.created_at.desc()))
    )


@router.get("/runs/{run_id}", response_model=ModelRunOut, dependencies=[Depends(viewer)])
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(ModelRun, run_id)
    if r is None:
        raise error(404, "run_not_found", "No such run")
    return r


@router.delete("/runs/{run_id}", status_code=204, dependencies=[Depends(admin)])
def delete_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(ModelRun, run_id)
    if r is None:
        raise error(404, "run_not_found", "No such run")
    db.delete(r)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/runs/import", response_model=ModelRunOut, status_code=201, dependencies=[Depends(admin)]
)
def import_run(body: RunImport, db: Session = Depends(get_db)):
    """Import a playonsports run's metrics: a training run (eval_val/metrics.json) or an
    evaluation run such as the one-time locked test (metrics.json at the top level)."""
    run = Path(body.run_dir)
    path = run / "eval_val" / "metrics.json"
    if not path.exists():
        path = run / "metrics.json"
    try:
        record = json.loads((run / "run_record.json").read_text())
        metrics = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise error(422, "run_unreadable", "run_record.json or metrics.json missing") from None
    # An evaluation run scores another run's predictions: name it after that training run.
    src = Path(metrics.get("predictions_from") or run)
    if not src.is_absolute():  # recorded relative to the training repo: a sibling run dir
        src = run.parent / src.name
    if src != run and (src / "run_record.json").exists():
        record = {
            **json.loads((src / "run_record.json").read_text()),
            "experiment_id": record.get("experiment_id"),
        }
    r = run_from_metrics(record, metrics, str(run), body.published)
    if body.published:
        for other in db.scalars(select(ModelRun).where(ModelRun.published.is_(True))):
            other.published = False
    db.add(r)
    db.commit()
    return r


def run_from_metrics(record: dict, m: dict, source: str, published: bool) -> ModelRun:
    b = m.get("binary_at_model_decision", {})
    per: dict[str, dict] = {}
    for crew, row in (m.get("crew_classes", {}).get("per_label", {}) or {}).items():
        d = CREW_TO_DEFECT.get(crew)
        if d is None or (d in per and per[d]["support"] >= row.get("support", 0)):
            continue
        ok = row.get("metrics") != "omitted"
        per[d] = {
            "p": row.get("precision") if ok else None,
            "r": row.get("recall") if ok else None,
            "support": row.get("support", 0),
        }
    for d in DEFECT_TYPES:
        per.setdefault(d, {"p": None, "r": None, "support": 0})
    cal = [[x["confidence"], x["observed"]] for x in m.get("calibration", {}).get("bins", [])]
    tradeoff = {}
    for op in m.get("operating_points", []):
        fit = op.get("fit", {})
        if fit.get("target_precision") is not None and fit.get("precision") is not None:
            tradeoff[f"p{fit['target_precision']:.2f}"] = {
                "precision": fit["precision"],
                "recall": fit.get("recall") or 0.0,
            }
    model = (record.get("model") or {}).get("name")
    label = " · ".join(
        x
        for x in (
            record.get("experiment_id"),
            model,
            f"seed {record['seed']}" if "seed" in record else None,
        )
        if x
    )
    return ModelRun(
        run_id=label or "?",
        split=f"{m.get('split', 'val')} split",
        precision=b.get("precision"),
        recall=b.get("recall"),
        f1=b.get("f1"),
        ap=(m.get("ranking") or {}).get("average_precision"),
        published=published,
        per_defect=per,
        calibration=cal,
        tradeoff=tradeoff,
        source_dir=source,
    )


# ---- inference benchmarks -----------------------------------------------------------------


@router.get("/bench", response_model=list[BenchRunOut], dependencies=[Depends(viewer)])
def list_bench(hardware: str | None = None, mode: str | None = None, db: Session = Depends(get_db)):
    """Throughput/latency per GPU, mode and batch size (written by scripts/bench.py)."""
    stmt = select(BenchRun).order_by(BenchRun.created_at.desc())
    if hardware:
        stmt = stmt.where(BenchRun.hardware == hardware)
    if mode:
        stmt = stmt.where(BenchRun.mode == mode)
    return list(db.scalars(stmt))


# ---- private media -------------------------------------------------------------------------


@router.get("/media/frames/{frame_id}", dependencies=[Depends(viewer)])
def frame_image(
    frame_id: int, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    f = db.get(Frame, frame_id)
    if f is None or not f.image_key:
        raise error(404, "media_not_found", "Frame image unavailable")
    return store.serve(f.image_key, "image/jpeg")


@router.get("/media/overlays/{loc_id}", dependencies=[Depends(viewer)])
def overlay_image(
    loc_id: int, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    loc = db.get(Localization, loc_id)
    if loc is None or loc.method_status != "available" or not loc.object_key:
        raise error(404, "overlay_unavailable", "No heat map for this frame")
    return store.serve(loc.object_key, "image/png")


@router.get("/media/frames/{frame_id}/thumb", dependencies=[Depends(viewer)])
def frame_thumb(
    frame_id: int, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    f = db.get(Frame, frame_id)
    if f is None or not f.thumb_key:
        raise error(404, "media_not_found", "Thumbnail unavailable")
    return store.serve(f.thumb_key, "image/jpeg", THUMB_CACHE)


@router.get("/media/games/{game_id}/poster", dependencies=[Depends(viewer)])
def game_poster(
    game_id: str, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)
):
    g = db.get(Game, game_id)
    if g is None or not g.poster_key:
        raise error(404, "media_not_found", "No poster for this game")
    return store.serve(g.poster_key, "image/jpeg", THUMB_CACHE)


@router.get("/media/jobs/{job_id}/poster", dependencies=[Depends(viewer)])
def job_poster(job_id: str, db: Session = Depends(get_db), store: MediaStore = Depends(store_dep)):
    j = db.get(Job, job_id)
    if j is None or not j.poster_key:
        raise error(404, "media_not_found", "No poster for this job")
    return store.serve(j.poster_key, "image/jpeg", THUMB_CACHE)
