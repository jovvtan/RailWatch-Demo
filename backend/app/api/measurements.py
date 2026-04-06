"""Measurement API endpoints — basic CRUD for wear measurements.

Provides a simple list endpoint that can optionally filter by chainage
database ID.  More advanced measurement access (time-series, per-chainage
detail) is handled by the chainages router.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models.measurement import WearMeasurement

router = APIRouter()


@router.get("")
def list_measurements(
    chainage_id: Optional[int] = Query(None, description="Filter by chainage DB id"),
    db: Session = Depends(get_db),
):
    """List wear measurements, optionally filtered by chainage.

    Args:
        chainage_id: If provided, only return measurements for this chainage
            (database primary key, not the string identifier).
        db: Database session (injected).

    Returns:
        A list of measurement summary dicts ordered by date ascending.
    """
    query = db.query(WearMeasurement)
    if chainage_id is not None:
        query = query.filter(WearMeasurement.chainage_id == chainage_id)
    measurements = query.order_by(WearMeasurement.measurement_date).all()
    return [
        {
            "id": m.id,
            "chainage_id": m.chainage_id,
            "measurement_date": str(m.measurement_date),
            "wear_mm": m.wear_mm,
            "source_file": m.source_file,
            "upload_id": m.upload_id,
        }
        for m in measurements
    ]
