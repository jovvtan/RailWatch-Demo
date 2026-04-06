"""Maintenance dashboard API — aggregated predictions, wear status, and repair schedule.

Provides a single comprehensive endpoint that combines real-time predictions
with measurement data to produce a prioritised list of upcoming repairs,
broken down by track, category, and sector.
"""

from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.track import Track, Chainage
from app.models.measurement import WearMeasurement
from app.models.upload import UploadLog
from app.models.replacement import ReplacementLog
from app.models.prediction import PredictionLog
from app.services.prediction import predict_chainage
from app.api.chainages import classify_wear_zone

router = APIRouter()

CATEGORY_LABELS = {1: "Straight Standard", 2: "Curved Standard", 3: "Curved Premium"}


def _get_latest_prediction(chainage_id: int, db: Session) -> Optional[PredictionLog]:
    """Return the most recent cached PredictionLog entry for a chainage.

    Args:
        chainage_id: Database primary key of the chainage.
        db: Database session.

    Returns:
        The latest PredictionLog row, or ``None`` if no predictions exist.
    """
    return (
        db.query(PredictionLog)
        .filter(PredictionLog.chainage_id == chainage_id)
        .order_by(PredictionLog.predicted_at.desc())
        .first()
    )


def _prediction_to_dict(pred) -> dict:
    """Normalise a PredictionLog or ChainagePrediction into a flat dict.

    Args:
        pred: Either a ``PredictionLog`` ORM instance or a ``ChainagePrediction``
            dataclass returned by the prediction service.

    Returns:
        A dict with standardised keys for the maintenance dashboard.
    """
    if isinstance(pred, PredictionLog):
        return {
            "wear_rate_per_month": pred.wear_rate_per_month,
            "predicted_repair_date": str(pred.predicted_repair_date) if pred.predicted_repair_date else None,
            "days_until_threshold": pred.days_until_threshold,
            "confidence_lower_days": pred.confidence_lower_days,
            "confidence_upper_days": pred.confidence_upper_days,
            "r_squared": pred.r_squared,
            "model_type": pred.model_type,
            "current_wear_mm": pred.current_wear_mm,
            "earliest_position": pred.position,
            "earliest_physical_side": pred.physical_side,
            "status": "ok",
        }
    # ChainagePrediction dataclass (from live prediction)
    return {
        "wear_rate_per_month": None,
        "predicted_repair_date": str(pred.predicted_repair_date) if pred.predicted_repair_date else None,
        "days_until_threshold": pred.days_until_threshold,
        "confidence_lower_days": None,
        "confidence_upper_days": None,
        "r_squared": None,
        "model_type": None,
        "current_wear_mm": pred.current_wear_mm,
        "earliest_position": pred.earliest_position,
        "earliest_physical_side": pred.earliest_physical_side,
        "status": pred.status,
    }


def _status_label(days: Optional[int], wear_mm: Optional[float]) -> str:
    """Classify a chainage into a maintenance urgency tier.

    Args:
        days: Predicted days until the wear threshold is reached.
        wear_mm: Current wear reading in millimetres.

    Returns:
        One of ``"overdue"``, ``"critical_60d"``, ``"warning_180d"``, or
        ``"healthy"``.
    """
    if wear_mm is not None and wear_mm >= 7.0:
        return "overdue"
    if days is not None and days <= 60:
        return "critical_60d"
    if days is not None and days <= 180:
        return "warning_180d"
    return "healthy"


@router.get("/dashboard")
def maintenance_dashboard(db: Session = Depends(get_db)):
    """Return the full maintenance dashboard payload.

    This is the most data-intensive endpoint: it iterates every chainage,
    fetches or computes its prediction, and builds aggregated breakdowns.

    The response includes:
    - ``summary`` — total counts by urgency tier.
    - ``upcoming_repairs`` — per-chainage list sorted by urgency.
    - ``by_track`` / ``by_category`` / ``by_sector`` — grouping breakdowns.
    - ``recent_activity`` — timestamps of latest upload, replacement, and
      prediction run.

    Args:
        db: Database session (injected).

    Returns:
        A comprehensive maintenance dashboard dict.
    """
    now = datetime.utcnow()

    # ---- Fetch all chainages with their latest measurement (using bulk helpers) ----
    from app.api.chainages import _bulk_latest_measurements
    chainages = db.query(Chainage).all()
    latest_meas_map = _bulk_latest_measurements(db)
    tracks = {t.id: t for t in db.query(Track).all()}

    # Bulk-fetch latest prediction per chainage (one query instead of 34k)
    pred_subq = (
        db.query(
            PredictionLog.chainage_id,
            func.max(PredictionLog.predicted_at).label("max_at"),
        )
        .group_by(PredictionLog.chainage_id)
        .subquery()
    )
    pred_rows = (
        db.query(PredictionLog)
        .join(pred_subq, (PredictionLog.chainage_id == pred_subq.c.chainage_id)
              & (PredictionLog.predicted_at == pred_subq.c.max_at))
        .all()
    )
    pred_map = {p.chainage_id: p for p in pred_rows}

    # ---- Build per-chainage prediction data ----
    upcoming_repairs = []
    summary_counts = {
        "total_chainages": len(chainages),
        "with_predictions": 0,
        "without_predictions": 0,
        "overdue": 0,
        "critical_60d": 0,
        "warning_180d": 0,
        "healthy": 0,
    }

    by_track: dict = {}
    by_category = {
        "straight_standard": {"total": 0, "critical": 0},
        "curved_standard": {"total": 0, "critical": 0},
        "curved_premium": {"total": 0, "critical": 0},
        "uncategorised": {"total": 0, "critical": 0},
    }
    sector_data: dict = {}  # key: (sector, bound)

    for c in chainages:
        track = tracks.get(c.track_id)
        track_code = track.track_id if track else "UNKNOWN"
        latest_m = latest_meas_map.get(c.id)
        current_wear = latest_m.wear_mm if latest_m else None
        last_meas_date = str(latest_m.measurement_date) if latest_m else None

        # Use bulk-fetched cached PredictionLog
        pred_log = pred_map.get(c.id)
        if pred_log is not None:
            pred_dict = _prediction_to_dict(pred_log)
        else:
            pred_dict = {
                "wear_rate_per_month": None, "predicted_repair_date": None,
                "days_until_threshold": None, "confidence_lower_days": None,
                "confidence_upper_days": None, "r_squared": None,
                "model_type": None, "current_wear_mm": current_wear,
                "earliest_position": None, "earliest_physical_side": None,
                "status": "no_prediction",
            }

        has_prediction = pred_dict["status"] in ("ok", "already_exceeded", "wear_decreasing")
        days_until = pred_dict["days_until_threshold"]
        wear_for_status = current_wear if current_wear is not None else pred_dict.get("current_wear_mm")
        status = _status_label(days_until, wear_for_status)

        # Update summary counters
        if has_prediction:
            summary_counts["with_predictions"] += 1
        else:
            summary_counts["without_predictions"] += 1
        summary_counts[status] += 1

        # Aggregate by track
        if track_code not in by_track:
            by_track[track_code] = {"total": 0, "overdue": 0, "critical_60d": 0, "warning_180d": 0, "healthy": 0}
        by_track[track_code]["total"] += 1
        by_track[track_code][status] += 1

        # Aggregate by category
        cat_key = {1: "straight_standard", 2: "curved_standard", 3: "curved_premium"}.get(c.category, "uncategorised")
        by_category[cat_key]["total"] += 1
        if status in ("overdue", "critical_60d"):
            by_category[cat_key]["critical"] += 1

        # Aggregate by sector — track the worst wear and critical count
        sector_key = (c.sector or "Unknown", c.bound or "")
        if sector_key not in sector_data:
            sector_data[sector_key] = {"sector": c.sector or "Unknown", "bound": c.bound or "", "worst_wear_mm": 0.0, "critical_count": 0}
        if wear_for_status is not None and wear_for_status > sector_data[sector_key]["worst_wear_mm"]:
            sector_data[sector_key]["worst_wear_mm"] = wear_for_status
        if status in ("overdue", "critical_60d"):
            sector_data[sector_key]["critical_count"] += 1

        # Build the per-chainage repair entry
        entry = {
            "chainage_id": c.chainage_id,
            "track": track_code,
            "sector": c.sector,
            "bound": c.bound,
            "category": c.category,
            "category_label": CATEGORY_LABELS.get(c.category, "Uncategorised"),
            "curve_radius": c.curve_radius,
            "current_wear_mm": current_wear,
            "wear_zone": classify_wear_zone(current_wear),
            "wear_rate_per_month": pred_dict["wear_rate_per_month"],
            "predicted_repair_date": pred_dict["predicted_repair_date"],
            "days_until_threshold": days_until,
            "confidence_lower_days": pred_dict["confidence_lower_days"],
            "confidence_upper_days": pred_dict["confidence_upper_days"],
            "r_squared": pred_dict["r_squared"],
            "model_type": pred_dict["model_type"],
            "last_measurement_date": last_meas_date,
            "status": status,
        }
        upcoming_repairs.append(entry)

    # Sort repairs by urgency: overdue first, then ascending days_until
    def _sort_key(r):
        d = r["days_until_threshold"]
        return 999999 if d is None else d

    upcoming_repairs.sort(key=_sort_key)
    # Only return non-healthy chainages in the repair list (cap at 500)
    upcoming_repairs = [r for r in upcoming_repairs if r["status"] != "healthy"][:500]

    # Sort sectors by worst wear descending for the heatmap
    by_sector = sorted(sector_data.values(), key=lambda s: -s["worst_wear_mm"])

    # ---- Recent activity timestamps ----
    last_upload_row = db.query(UploadLog).order_by(UploadLog.uploaded_at.desc()).first()
    last_replacement_row = db.query(ReplacementLog).order_by(ReplacementLog.logged_at.desc()).first()
    last_prediction_row = db.query(PredictionLog).order_by(PredictionLog.predicted_at.desc()).first()

    recent_activity = {
        "last_upload": str(last_upload_row.uploaded_at) if last_upload_row else None,
        "last_replacement": str(last_replacement_row.logged_at) if last_replacement_row else None,
        "predictions_last_updated": str(last_prediction_row.predicted_at) if last_prediction_row else None,
    }

    return {
        "generated_at": now.isoformat(),
        "summary": summary_counts,
        "upcoming_repairs": upcoming_repairs,
        "by_track": by_track,
        "by_category": by_category,
        "by_sector": by_sector,
        "recent_activity": recent_activity,
    }
