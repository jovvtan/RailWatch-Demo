"""Pydantic schemas for UploadLog."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class UploadLogRead(BaseModel):
    id: int
    filename: str
    uploaded_at: Optional[datetime] = None
    rows_total: int = 0
    rows_accepted: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0
    status: str = "completed"
    error_details: Optional[str] = None

    model_config = {"from_attributes": True}
