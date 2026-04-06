"""Pydantic schemas for WearMeasurement."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class MeasurementBase(BaseModel):
    chainage_id: int
    measurement_date: date
    wear_mm: float
    source_file: Optional[str] = None


class MeasurementRead(MeasurementBase):
    id: int
    upload_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
