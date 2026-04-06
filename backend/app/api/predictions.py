"""Prediction API endpoints — wear prediction retrieval and replacement logging.

Provides endpoints to:
- Retrieve the current wear prediction for a chainage.
- Record a rail replacement event (which resets the wear lifecycle).
- List historical replacement events for a chainage.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.track import Chainage
from app.models.measurement import WearMeasurement
from app.models.replacement import ReplacementLog
from app.services.prediction import predict_chainage

router = APIRouter()


class ReplacementRequest(BaseModel):
    """Request body for recording a rail replacement event."""
    replacement_date: str = Field(..., description="ISO date string YYYY-MM-DD")
    notes: Optional[str] = None


def _get_chainage(chainage_id: str, db: Session, bound: str = None) -> Chainage:
    """Look up a chainage by its string ID (and optional bound) or raise 404."""
    query = db.query(Chainage).filter(Chainage.chainage_id == chainage_id)
    if bound:
        query = query.filter(Chainage.bound == bound)
    ch = query.first()
    if ch is None:
        raise HTTPException(status_code=404, detail="Chainage not found")
    return ch


def _pred_to_dict(pred) -> dict:
    """Convert a ChainagePrediction dataclass to a JSON-serialisable dict.

    Date fields are converted to ISO-format strings so FastAPI can
    serialise them without a custom encoder.
    """
    result = asdict(pred)
    # Convert date objects to ISO strings throughout
    for key in ("predicted_repair_date",):
        val = result.get(key)
        if isinstance(val, date):
            result[key] = val.isoformat()
    # Also convert dates inside position_predictions
    for pp in result.get("position_predictions", []):
        if isinstance(pp.get("predicted_repair_date"), date):
            pp["predicted_repair_date"] = pp["predicted_repair_date"].isoformat()
    return result


@router.get("/{chainage_id}/prediction")
def get_prediction(chainage_id: str, bound: Optional[str] = None, db: Session = Depends(get_db)) -> dict:
    """Return per-position wear predictions for a chainage.

    Uses globally-fitted models (per category/position/rail-role) applied
    to this chainage's latest measurements to predict when each position
    hits the 7mm threshold.

    Args:
        chainage_id: External chainage identifier.
        db: Database session (injected).

    Returns:
        Dict with overall prediction (earliest position to hit threshold)
        and per-position breakdowns.
    """
    ch = _get_chainage(chainage_id, db, bound=bound)
    pred = predict_chainage(ch.id, db)
    result = _pred_to_dict(pred)
    result["curve_radius"] = ch.curve_radius
    result["bound"] = ch.bound
    return result


@router.post("/{chainage_id}/replacement")
def record_replacement(chainage_id: str, body: ReplacementRequest, db: Session = Depends(get_db)) -> dict:
    """Record a rail replacement event and reset the wear lifecycle.

    This endpoint:
    1. Inserts (or updates) a 0 mm measurement at the replacement date.
    2. Creates a ``ReplacementLog`` record for audit.
    3. Updates the chainage's install and last-grind dates.
    4. Refits the prediction model using the new (post-replacement) data.

    Args:
        chainage_id: External chainage identifier.
        body: Replacement details (date and optional notes).
        db: Database session (injected).

    Returns:
        Confirmation dict with the pre-replacement wear and updated prediction.

    Raises:
        HTTPException: 400 for invalid or future dates, 404 if chainage not found.
    """
    ch = _get_chainage(chainage_id, db)

    try:
        rep_date = datetime.strptime(body.replacement_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if rep_date > date.today():
        raise HTTPException(status_code=400, detail="Date cannot be in the future")

    # Capture the pre-replacement wear reading for the audit log
    last_meas = (
        db.query(WearMeasurement)
        .filter(WearMeasurement.chainage_id == ch.id, WearMeasurement.measurement_date <= rep_date)
        .order_by(WearMeasurement.measurement_date.desc())
        .first()
    )
    pre_wear = last_meas.wear_mm if last_meas else None

    # Insert or update a 0 mm measurement on the replacement date.
    # The unique constraint (chainage_id, measurement_date) means we must
    # check for an existing row first.
    existing_meas = (
        db.query(WearMeasurement)
        .filter(WearMeasurement.chainage_id == ch.id, WearMeasurement.measurement_date == rep_date)
        .first()
    )
    if existing_meas:
        # Overwrite the existing measurement with zero wear
        existing_meas.wear_mm = 0.0
        existing_meas.left_wear_0 = 0.0
        existing_meas.left_wear_22_5 = 0.0
        existing_meas.left_wear_45 = 0.0
        existing_meas.left_wear_67_5 = 0.0
        existing_meas.left_wear_90 = 0.0
        existing_meas.right_wear_0 = 0.0
        existing_meas.right_wear_22_5 = 0.0
        existing_meas.right_wear_45 = 0.0
        existing_meas.right_wear_67_5 = 0.0
        existing_meas.right_wear_90 = 0.0
        existing_meas.source_file = "manual_replacement"
        zero_meas = existing_meas
    else:
        zero_meas = WearMeasurement(
            chainage_id=ch.id, measurement_date=rep_date, wear_mm=0.0,
            left_wear_0=0.0, left_wear_22_5=0.0, left_wear_45=0.0, left_wear_67_5=0.0, left_wear_90=0.0,
            right_wear_0=0.0, right_wear_22_5=0.0, right_wear_45=0.0, right_wear_67_5=0.0, right_wear_90=0.0,
            source_file="manual_replacement",
        )
        db.add(zero_meas)
    db.flush()

    # Create the replacement audit log entry
    rep_log = ReplacementLog(
        chainage_id=ch.id, replacement_date=rep_date,
        pre_replacement_wear_mm=pre_wear, notes=body.notes,
        measurement_id=zero_meas.id,
    )
    db.add(rep_log)

    # Update the chainage lifecycle dates to start from the replacement
    ch.install_date = rep_date
    ch.last_grind_date = rep_date
    db.commit()

    # Refit the prediction model using the new post-replacement segment
    pred = predict_chainage(ch.id, db)

    return {
        "status": "ok",
        "message": f"Rail replacement logged for {chainage_id} on {rep_date}",
        "replacement_id": rep_log.id,
        "pre_replacement_wear_mm": pre_wear,
        "prediction_updated": True,
        "new_prediction": {
            "predicted_repair_date": pred.predicted_repair_date.isoformat() if pred.predicted_repair_date else None,
            "days_until_threshold": pred.days_until_threshold,
            "message": pred.message,
        },
    }


@router.get("/{chainage_id}/replacements")
def list_replacements(chainage_id: str, db: Session = Depends(get_db)) -> list:
    """List all recorded replacement events for a chainage, newest first.

    Args:
        chainage_id: External chainage identifier.
        db: Database session (injected).

    Returns:
        A list of replacement dicts with date, pre-replacement wear, and notes.
    """
    ch = _get_chainage(chainage_id, db)
    reps = (
        db.query(ReplacementLog)
        .filter(ReplacementLog.chainage_id == ch.id)
        .order_by(ReplacementLog.replacement_date.desc())
        .all()
    )
    return [
        {
            "id": r.id, "replacement_date": r.replacement_date.isoformat() if r.replacement_date else None,
            "logged_at": str(r.logged_at) if r.logged_at else None,
            "pre_replacement_wear_mm": r.pre_replacement_wear_mm, "notes": r.notes,
        }
        for r in reps
    ]
