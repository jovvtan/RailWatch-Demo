"""
UploadLog database table.

FILE PURPOSE:
    This file defines the database table that keeps a record of every file
    upload. Each time someone uploads a measurement file, a replacement file,
    or any other data file, a new row is created here.

    The upload log tracks:
    - Which file was uploaded and when
    - How many rows were in the file
    - How many rows were successfully processed, skipped, or had errors
    - Whether the upload was later "deleted" (soft-deleted)

    "Soft-delete" means the upload is marked as deleted but not actually
    removed from the database. This preserves the audit trail while allowing
    users to reverse an upload that was done in error.

    In simple terms: this is the "upload history" table.
"""

# --- Library imports ---
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Base class that all database table definitions must inherit from
from app.database import Base


class UploadLog(Base):
    """
    DATABASE TABLE: upload_logs

    An audit record for a single file upload operation. One row is created
    per upload, regardless of whether the upload succeeded or failed.

    The status field tracks the overall result:
    - "completed" — all rows were processed successfully
    - "partial"   — some rows succeeded, some failed
    - "failed"    — the upload could not be processed at all
    - "deleted"   — the upload was reversed (soft-deleted) by a user

    In simple terms: this is the "what files have been uploaded" table.
    """

    # This tells the database to name this table "upload_logs"
    __tablename__ = "upload_logs"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # The name of the uploaded file (e.g. "NEL_SB_Mar2025.xlsx")
    filename = Column(String, nullable=False)

    # When the file was uploaded
    uploaded_at = Column(DateTime, default=func.now())

    # How many data rows were found in the file (not counting headers)
    rows_total = Column(Integer, default=0)

    # How many rows were successfully parsed and saved as measurements
    rows_accepted = Column(Integer, default=0)

    # How many rows were skipped because the same chainage+date already
    # existed in the database (duplicate detection)
    rows_skipped = Column(Integer, default=0)

    # How many rows failed validation or parsing (e.g. missing data,
    # unrecognised chainage)
    rows_errored = Column(Integer, default=0)

    # The overall status of the upload: "completed", "partial", "failed",
    # or "deleted" (after soft-delete)
    status = Column(String, default="completed")

    # Detailed error messages if anything went wrong (stored as a long text
    # string, can be NULL if no errors)
    error_details = Column(Text, nullable=True)

    # --- Soft-delete fields ---
    # When an upload is "deleted" (reversed), these fields are filled in.
    # The measurements from this upload are also removed from the database.

    # The date/time when the upload was soft-deleted (NULL means still active)
    deleted_at = Column(DateTime, nullable=True)

    # The reason the user gave for deleting this upload (e.g. "wrong file")
    deleted_reason = Column(String, nullable=True)

    # Link to all WearMeasurement records that were created by this upload.
    # This lets us find and remove measurements when an upload is deleted.
    measurements = relationship("WearMeasurement", back_populates="upload")
