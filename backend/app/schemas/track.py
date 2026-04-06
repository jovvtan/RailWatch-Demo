"""Pydantic schemas for Track and Chainage."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


# --- Track ---

class TrackBase(BaseModel):
    track_id: str
    name: Optional[str] = None
    description: Optional[str] = None


class TrackRead(TrackBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Chainage ---

class ChainageBase(BaseModel):
    chainage_id: str
    track_id: int
    rail_side: Optional[str] = None
    speed_zone: Optional[str] = None
    curve: Optional[str] = None
    location_description: Optional[str] = None
    install_date: Optional[date] = None
    last_grind_date: Optional[date] = None
    wear_threshold_mm: float = 8.0


class ChainageRead(ChainageBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    latest_wear_mm: Optional[float] = None
    track_name: Optional[str] = None

    model_config = {"from_attributes": True}


class ChainageDetail(ChainageRead):
    """Extended schema returned by the detail endpoint."""
    track: Optional[TrackRead] = None

    model_config = {"from_attributes": True}
