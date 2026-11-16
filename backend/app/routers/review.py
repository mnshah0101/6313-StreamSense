"""Human review: the alert queue and reviewer feedback labels."""

import csv
import io
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import admin, reviewer, viewer
from app.config import Settings
from app.db import get_db
from app.models import Alert, Feedback, FineTuneRequest, Game
from app.schemas import AlertOut, AlertReview, FeedbackCreate, FeedbackOut, FeedbackSummary

from .common import alert_out, current_user, error, settings_dep

router = APIRouter(dependencies=[Depends(viewer)], tags=["review"])


# ---- alerts --------------------------------------------------------------------------------


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    status: str | None = None, game_id: str | None = None, db: Session = Depends(get_db)
):
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if status:
        stmt = stmt.where(Alert.status == status)
    if game_id:
        stmt = stmt.where(Alert.game_id == game_id)
    alerts = list(db.scalars(stmt))
    # Worst first within the open queue, like the UI's seed ordering.
    alerts.sort(key=lambda a: -max((d.get("severity") or 0) for d in a.detections or [{}]))
    return [alert_out(db, a) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None:
        raise error(404, "alert_not_found", f"No alert with id {alert_id!r}")
    return alert_out(db, a)


@router.post("/alerts/{alert_id}/review", response_model=AlertOut, dependencies=[Depends(reviewer)])
def review_alert(
    alert_id: str,
    body: AlertReview,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    """Confirm or dismiss. Decisions are final; the version check stops two reviewers from
    silently overwriting each other (409). The model's output is never modified."""
    a = db.get(Alert, alert_id)
    if a is None:
        raise error(404, "alert_not_found", f"No alert with id {alert_id!r}")
    if a.status == "reviewed":
        raise error(
            409,
            "already_reviewed",
            f"Already {a.decision} by {a.reviewed_by}. Reload to see the decision.",
        )
    version = body.expected_version if body.expected_version is not None else a.version
    res = db.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.version == version, Alert.status == "open")
        .values(
            status="reviewed",
            decision=body.decision,
            reviewed_by=user,
            reviewed_at=datetime.now(UTC),
            review_note=body.note,
            version=version + 1,
        )
    )
    if res.rowcount != 1:
        db.rollback()
        raise error(409, "version_conflict", "This alert changed since it was loaded. Reload it.")
    db.commit()
    db.refresh(a)
    return alert_out(db, a)


# ---- feedback ------------------------------------------------------------------------------


@router.get("/feedback", response_model=list[FeedbackOut])
def list_feedback(game_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Feedback).order_by(Feedback.created_at.desc())
    if game_id:
        stmt = stmt.where(Feedback.game_id == game_id)
    return list(db.scalars(stmt))


@router.post(
    "/feedback", response_model=FeedbackOut, status_code=201, dependencies=[Depends(reviewer)]
)
def add_feedback(
    body: FeedbackCreate, db: Session = Depends(get_db), user: str = Depends(current_user)
):
    if db.get(Game, body.game_id) is None:
        raise error(404, "game_not_found", f"No game with id {body.game_id!r}")
    if body.kind == "missed" and body.defect is None:
        raise error(422, "defect_required", "A missed issue needs a defect type")
    fb = Feedback(
        id=f"fb-{secrets.token_hex(6)}",
        reviewer=user,
        **body.model_dump(exclude={"region"}),
        region=body.region.model_dump() if body.region else None,
    )
    db.add(fb)
    db.commit()
    return fb


@router.delete("/feedback/{feedback_id}", status_code=204, dependencies=[Depends(reviewer)])
def delete_feedback(feedback_id: str, db: Session = Depends(get_db)):
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise error(404, "feedback_not_found", "No such label")
    db.delete(fb)
    db.commit()
    return Response(status_code=204)


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    kinds = [k for (k,) in db.execute(select(Feedback.kind))]
    c, i, m = kinds.count("correct"), kinds.count("incorrect"), kinds.count("missed")
    return FeedbackSummary(
        total=len(kinds),
        correct=c,
        incorrect=i,
        missed=m,
        observed_precision=round(c / (c + i), 3) if c + i else None,
        min_labels_for_finetune=s.min_labels_for_finetune,
        can_queue_finetune=len(kinds) >= s.min_labels_for_finetune,
    )


@router.get("/feedback/export.csv", dependencies=[Depends(reviewer)])
def export_feedback(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "game_id",
            "frame_index",
            "kind",
            "defect",
            "severity",
            "region_x",
            "region_y",
            "note",
            "reviewer",
            "created_at",
        ]
    )
    for f in db.scalars(select(Feedback).order_by(Feedback.created_at)):
        r = f.region or {}
        w.writerow(
            [
                f.id,
                f.game_id,
                f.frame_index,
                f.kind,
                f.defect or "",
                f.severity or "",
                r.get("x", ""),
                r.get("y", ""),
                f.note or "",
                f.reviewer or "",
                f.created_at.isoformat(),
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedback.csv"},
    )


@router.post("/feedback/fine-tune", status_code=202, dependencies=[Depends(admin)])
def queue_finetune(
    db: Session = Depends(get_db),
    s: Settings = Depends(settings_dep),
    user: str = Depends(current_user),
):
    """Record a request for a fine-tune run. Labels still pass a curation step before any
    training; they are never added to the locked test set."""
    n = len(db.scalars(select(Feedback.id)).all())
    if n < s.min_labels_for_finetune:
        raise error(
            409,
            "not_enough_labels",
            f"{s.min_labels_for_finetune - n} more labels needed to queue a run",
        )
    req = FineTuneRequest(labels=n, requested_by=user)
    db.add(req)
    db.commit()
    return {"id": req.id, "labels": n, "status": req.status}
