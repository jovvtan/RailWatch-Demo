"""
ReplacementLog database table.

FILE PURPOSE:
    This file defines the database table that records rail replacement events.
    When a section of rail is physically replaced in the field, this table
    keeps a record of it.

    When a replacement is logged, two things happen:
    1. A zero-wear measurement (0.0 mm) is inserted for the replacement date,
       because the new rail has no wear.
    2. The chainage's install date and/or last grind date are updated.

    This effectively "resets the clock" on the wear lifecycle — all future
    predictions will be based on measurements taken after the replacement,
    not before.

    In simple terms: this is the "when was the rail replaced" table.
"""

# --- Library imports ---
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Base class that all database table definitions must inherit from
from app.database import Base


class ReplacementLog(Base):
    """
    DATABASE TABLE: replacement_logs

    A record of a rail replacement or grind-reset event at one chainage.

    Each row represents one replacement event at one location. The
    pre_replacement_wear_mm field captures how worn the rail was just before
    it was replaced — this is useful for historical analysis (e.g. "we
    typically replace rails when they reach 7.5mm of wear").

    In simple terms: this is the "rail replacement history" table.
    """

    # This tells the database to name this table "replacement_logs"
    __tablename__ = "replacement_logs"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Links this replacement to the chainage where it happened.
    # This is a foreign key referencing the "id" column in the "chainages" table.
    chainage_id = Column(Integer, ForeignKey("chainages.id"), nullable=False)

    # The date when the rail was physically replaced in the field
    replacement_date = Column(Date, nullable=False)

    # When this replacement was logged in the system (may differ from the
    # actual replacement date if entered later)
    logged_at = Column(DateTime, default=func.now())

    # Who logged this replacement (username or staff ID, optional)
    logged_by = Column(String, nullable=True)

    # The wear reading (in mm) just before the replacement happened.
    # This is captured for historical analysis — helps understand at what
    # wear level replacements typically occur.
    pre_replacement_wear_mm = Column(Float, nullable=True)

    # Free-text notes about the replacement (e.g. "emergency replacement
    # due to crack detected during inspection")
    notes = Column(Text, nullable=True)

    # Links to the zero-wear WearMeasurement record that was created to
    # mark the reset point. When a rail is replaced, a 0.0mm measurement
    # is inserted to show the fresh start.
    measurement_id = Column(Integer, ForeignKey("wear_measurements.id"), nullable=True)

    # Link to the Chainage record where this replacement happened
    chainage = relationship("Chainage")
