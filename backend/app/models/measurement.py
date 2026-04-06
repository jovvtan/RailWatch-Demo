"""
WearMeasurement database table.

FILE PURPOSE:
    This file defines the database table that stores individual rail wear
    readings. Each row represents one measurement taken at one chainage
    (location) on one date.

    Rail wear is measured at up to 10 positions on the rail head:
    - 5 angular positions (0, 22.5, 45, 67.5, and 90 degrees)
    - For both the left rail and the right rail

    Think of it like this: if you look at the cross-section of a rail head,
    0 degrees is the very top, and 90 degrees is the side (gauge face).
    The angles in between (22.5, 45, 67.5) capture wear at different points
    along the rail head profile.

    Not all lines measure at all 5 angles. For example:
    - NEL (North East Line) only measures at 0 and 90 degrees (4 values total)
    - DTL (Downtown Line) measures at all 5 angles (10 values total)

    The "wear_mm" field stores the single worst (maximum) value across all
    positions, which is used for quick threshold checks — if this number
    exceeds the limit (typically 8mm), maintenance is needed.
"""

# --- Library imports ---
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Base class that all database table definitions must inherit from
from app.database import Base


class WearMeasurement(Base):
    """
    DATABASE TABLE: wear_measurements

    Stores a single wear measurement record for one chainage on one date.

    The "wear_mm" field is the maximum value across all 10 rail positions and
    is used for high-level overview displays and threshold checks (e.g. "is
    this rail close to needing replacement?").

    Individual position columns (e.g. left_wear_45) can be NULL because not
    every train line measures at all five angles.

    A unique constraint on (chainage_id, measurement_date) prevents duplicate
    entries — you cannot have two different measurement records for the same
    location on the same date.

    In simple terms: this is the "how much has the rail worn down" table.
    """

    # This tells the database to name this table "wear_measurements"
    __tablename__ = "wear_measurements"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Links this measurement to the chainage (location) where it was taken.
    # This is a foreign key referencing the "id" column in the "chainages" table.
    chainage_id = Column(Integer, ForeignKey("chainages.id"), nullable=False)

    # The date when this measurement was taken in the field
    measurement_date = Column(Date, nullable=False)

    # The worst (maximum) wear value across all 10 positions, in millimetres.
    # This is the number used for quick "is maintenance needed?" checks.
    wear_mm = Column(Float, nullable=False)           # Max of all 10 positions (overview)

    # --- Left rail wear values at each angular position (in degrees) ---
    # Each value is in millimetres. NULL means this angle was not measured.
    left_wear_0 = Column(Float, nullable=True)       # Top of rail (0 degrees)
    left_wear_22_5 = Column(Float, nullable=True)    # 22.5 degrees from top
    left_wear_45 = Column(Float, nullable=True)      # 45 degrees (diagonal)
    left_wear_67_5 = Column(Float, nullable=True)    # 67.5 degrees from top
    left_wear_90 = Column(Float, nullable=True)      # Side of rail / gauge face (90 degrees)

    # --- Right rail wear values at each angular position (in degrees) ---
    # Same angles as the left rail. NULL means this angle was not measured.
    right_wear_0 = Column(Float, nullable=True)      # Top of rail (0 degrees)
    right_wear_22_5 = Column(Float, nullable=True)   # 22.5 degrees from top
    right_wear_45 = Column(Float, nullable=True)     # 45 degrees (diagonal)
    right_wear_67_5 = Column(Float, nullable=True)   # 67.5 degrees from top
    right_wear_90 = Column(Float, nullable=True)     # Side of rail / gauge face (90 degrees)

    # The name of the file this measurement came from (for traceability)
    source_file = Column(String, nullable=True)

    # Links to the upload log entry that created this measurement (for audit trail)
    upload_id = Column(Integer, ForeignKey("upload_logs.id"), nullable=True)

    # When this record was first saved to the database
    created_at = Column(DateTime, default=func.now())

    # Link back to the Chainage record (so we can easily find which location
    # this measurement belongs to)
    chainage = relationship("Chainage", back_populates="measurements")

    # Link back to the UploadLog record (so we can see which upload created
    # this measurement)
    upload = relationship("UploadLog", back_populates="measurements")

    # This constraint prevents duplicate entries: you cannot have two
    # measurements for the same chainage on the same date. If someone tries
    # to upload the same data twice, the second upload will skip those rows.
    __table_args__ = (UniqueConstraint("chainage_id", "measurement_date"),)
