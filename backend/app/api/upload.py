"""Upload API endpoints — measurement CSV/Excel, raw NEL files, and category uploads.

Handles three upload flows:
1. **NEL raw** — equipment Excel files exported from the NEL track inspection
   system.  Auto-detected by the presence of "milage" / "hor. wear" columns.
2. **Labelled CSV** — standard format with chainage ID + position wear columns.
3. **Category CSV** — assigns track categories to existing chainages.

Each upload is archived to ``data/uploads/`` and logged in the ``upload_logs``
table.  After measurements are stored, predictions are automatically refitted
for all affected chainages.
"""

import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.upload import UploadLog
from app.models.track import CategoryConfig
from app.services.csv_parser import parse_measurement_csv, parse_category_csv, detect_file_type
from app.services.nel_raw_parser import parse_nel_raw, parse_nel_raw_with_category
from app.services.prediction import refit_after_upload

router = APIRouter()

# Directory where raw uploaded files are archived for audit/replay
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "uploads"


def _save_uploaded_file(content: bytes, filename: str, measurement_date: date | None = None) -> str:
    """Archive a copy of the uploaded file to ``data/uploads/``.

    The saved filename is prefixed with a timestamp (and optionally the
    measurement date) to guarantee uniqueness and traceability.

    Args:
        content: Raw bytes of the uploaded file.
        filename: Original filename from the user.
        measurement_date: Optional date to include in the archived name.

    Returns:
        The full path to the saved file as a string.
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_part = f"_{measurement_date}" if measurement_date else ""
    # Sanitise the filename — keep only alphanumeric, dots, hyphens, underscores
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    archived_name = f"{ts}{date_part}_{safe_name}"
    dest = UPLOADS_DIR / archived_name
    dest.write_bytes(content)
    return str(dest)


@router.post("/measurements")
async def upload_measurements(
    file: UploadFile = File(...),
    measurement_date: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload a measurement file (CSV or Excel).

    The file format is auto-detected:
    - Raw NEL equipment exports are routed to the NEL parser.
    - All other files are treated as labelled CSVs.

    Args:
        file: The uploaded file (must be .csv, .xlsx, or .xls).
        measurement_date: ISO date string (YYYY-MM-DD) for all rows in the file.
        db: Database session (injected).

    Returns:
        A summary dict with upload status, row counts, and prediction refit results.

    Raises:
        HTTPException: 400 for missing file, bad format, invalid date, or future date.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    lower = file.filename.lower()
    if not lower.endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be .csv, .xlsx, or .xls")

    if not measurement_date:
        raise HTTPException(status_code=400, detail="Measurement date is required")

    try:
        m_date = datetime.strptime(measurement_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if m_date > date.today():
        raise HTTPException(status_code=400, detail="Date cannot be in the future")

    content = await file.read()

    # Archive the raw file for audit trail
    _save_uploaded_file(content, file.filename, m_date)

    # Auto-detect whether this is a raw NEL file or a labelled CSV
    file_type = detect_file_type(content, file.filename)

    if file_type == "nel_raw_with_category":
        return _handle_nel_raw_with_category(content, file.filename, m_date, db)
    elif file_type == "nel_raw":
        return _handle_nel_raw(content, file.filename, m_date, db)
    elif file_type in ("labelled_csv", "unknown"):
        # Try the labelled parser — it will report missing columns if unknown
        return _handle_labelled(content, file.filename, m_date, file_type, db)


def _handle_nel_raw(content: bytes, filename: str, m_date: date, db: Session) -> dict:
    """Process a raw NEL equipment file and persist measurements.

    Args:
        content: Raw file bytes.
        filename: Original filename.
        m_date: Measurement date for all rows.
        db: Database session.

    Returns:
        Upload summary dict including NEL-specific metadata (bound, sectors).
    """
    result = parse_nel_raw(content, filename, m_date, db)

    # Determine overall status from parse outcome
    if result.rows_accepted == 0 and (result.rows_with_wear > 0 or result.errors):
        status = "failed"
    elif result.rows_errored > 0:
        status = "partial"
    else:
        status = "completed"

    error_json = json.dumps(result.errors[:100]) if result.errors else None

    upload_log = UploadLog(
        filename=filename,
        rows_total=result.rows_with_wear,
        rows_accepted=result.rows_accepted,
        rows_skipped=result.rows_skipped,
        rows_errored=result.rows_errored,
        status=status,
        error_details=error_json,
    )
    db.add(upload_log)
    db.flush()

    # Link each measurement to this upload and persist
    affected_chainage_ids: set[int] = set()
    for meas in result.measurements:
        meas.upload_id = upload_log.id
        db.add(meas)
        if meas.chainage_id:
            affected_chainage_ids.add(meas.chainage_id)

    db.commit()

    # Refit prediction models for all chainages that received new data
    prediction_refit: dict = {}
    if affected_chainage_ids:
        try:
            prediction_refit = refit_after_upload(
                upload_log.id, list(affected_chainage_ids), db
            )
        except Exception:
            prediction_refit = {"error": "Prediction refit failed"}

    return {
        "status": status,
        "upload_id": upload_log.id,
        "filename": filename,
        "file_type": "nel_raw",
        "measurement_date": str(m_date),
        "summary": {
            "total_raw_rows": result.total_raw_rows,
            "whole_number_rows": result.whole_number_rows,
            "rows_with_wear": result.rows_with_wear,
            "rows_accepted": result.rows_accepted,
            "rows_skipped": result.rows_skipped,
            "rows_errored": result.rows_errored,
        },
        "nel_metadata": {
            "bound_detected": result.bound_detected,
            "chainage_range": list(result.chainage_range),
            "sectors_found": result.sectors_found,
            "new_chainages_created": result.new_chainages_created,
        },
        "prediction_refit": prediction_refit,
        "errors": result.errors[:50],
        "warnings": result.warnings[:50],
    }


def _handle_nel_raw_with_category(content: bytes, filename: str, m_date: date, db: Session) -> dict:
    """Process a raw NEL file with embedded category/curvature columns.

    Handles both wear measurements and category assignment in a single pass.

    Args:
        content: Raw file bytes.
        filename: Original filename.
        m_date: Measurement date for all rows.
        db: Database session.

    Returns:
        Upload summary dict including NEL metadata and category update counts.
    """
    result = parse_nel_raw_with_category(content, filename, m_date, db)

    if result.rows_accepted == 0 and (result.rows_with_wear > 0 or result.errors):
        status = "failed"
    elif result.rows_errored > 0:
        status = "partial"
    else:
        status = "completed"

    error_json = json.dumps(result.errors[:100]) if result.errors else None

    upload_log = UploadLog(
        filename=filename,
        rows_total=result.rows_with_wear,
        rows_accepted=result.rows_accepted,
        rows_skipped=result.rows_skipped,
        rows_errored=result.rows_errored,
        status=status,
        error_details=error_json,
    )
    db.add(upload_log)
    db.flush()

    affected_chainage_ids: set[int] = set()
    for meas in result.measurements:
        meas.upload_id = upload_log.id
        db.add(meas)
        if meas.chainage_id:
            affected_chainage_ids.add(meas.chainage_id)

    db.commit()

    prediction_refit: dict = {}
    if affected_chainage_ids:
        try:
            prediction_refit = refit_after_upload(
                upload_log.id, list(affected_chainage_ids), db
            )
        except Exception:
            prediction_refit = {"error": "Prediction refit failed"}

    return {
        "status": status,
        "upload_id": upload_log.id,
        "filename": filename,
        "file_type": "nel_raw_with_category",
        "measurement_date": str(m_date),
        "summary": {
            "total_raw_rows": result.total_raw_rows,
            "whole_number_rows": result.whole_number_rows,
            "rows_with_wear": result.rows_with_wear,
            "rows_accepted": result.rows_accepted,
            "rows_skipped": result.rows_skipped,
            "rows_errored": result.rows_errored,
        },
        "nel_metadata": {
            "bound_detected": result.bound_detected,
            "chainage_range": list(result.chainage_range),
            "sectors_found": result.sectors_found,
            "new_chainages_created": result.new_chainages_created,
        },
        "category_metadata": {
            "categories_updated": result.categories_updated,
            "category_summary": result.category_summary,
        },
        "prediction_refit": prediction_refit,
        "errors": result.errors[:50],
        "warnings": result.warnings[:50],
    }


def _handle_labelled(content: bytes, filename: str, m_date: date, file_type: str, db: Session) -> dict:
    """Process a labelled CSV/Excel measurement file and persist results.

    Args:
        content: Raw file bytes.
        filename: Original filename.
        m_date: Measurement date for all rows.
        file_type: Detected type string (for logging).
        db: Database session.

    Returns:
        Upload summary dict with row counts and prediction refit results.
    """
    result = parse_measurement_csv(content, filename, m_date, db)

    if result.rows_accepted == 0 and (result.rows_total > 0 or result.errors):
        status = "failed"
    elif result.rows_errored > 0:
        status = "partial"
    else:
        status = "completed"

    error_json = json.dumps(result.errors[:100]) if result.errors else None

    upload_log = UploadLog(
        filename=filename,
        rows_total=result.rows_total,
        rows_accepted=result.rows_accepted,
        rows_skipped=result.rows_skipped,
        rows_errored=result.rows_errored,
        status=status,
        error_details=error_json,
    )
    db.add(upload_log)
    db.flush()

    affected_chainage_ids: set[int] = set()
    for meas in result.measurements:
        meas.upload_id = upload_log.id
        db.add(meas)
        if meas.chainage_id:
            affected_chainage_ids.add(meas.chainage_id)

    db.commit()

    # Refit prediction models for affected chainages
    prediction_refit: dict = {}
    if affected_chainage_ids:
        try:
            prediction_refit = refit_after_upload(
                upload_log.id, list(affected_chainage_ids), db
            )
        except Exception:
            prediction_refit = {"error": "Prediction refit failed"}

    return {
        "status": status,
        "upload_id": upload_log.id,
        "filename": filename,
        "file_type": "labelled_csv",
        "measurement_date": str(m_date),
        "summary": {
            "rows_total": result.rows_total,
            "rows_accepted": result.rows_accepted,
            "rows_skipped": result.rows_skipped,
            "rows_errored": result.rows_errored,
        },
        "prediction_refit": prediction_refit,
        "errors": result.errors[:50],
        "warnings": result.warnings[:50],
    }


@router.post("/categories")
async def upload_categories(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a category-assignment CSV to update chainage track categories.

    Args:
        file: CSV/Excel file with chainage_id, category, and optional
            curve_radius / rail_type columns.
        db: Database session (injected).

    Returns:
        A result dict with counts of updated/not-found chainages.

    Raises:
        HTTPException: 400 if no file is provided.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    content = await file.read()
    _save_uploaded_file(content, file.filename)
    result = parse_category_csv(content, file.filename, db)
    cat_config = CategoryConfig(
        filename=file.filename,
        total_chainages=result.get("total", 0),
        updated_chainages=result.get("updated", 0),
        status=result.get("status", "completed"),
    )
    db.add(cat_config)
    db.commit()
    return result


@router.post("/replacements")
async def upload_replacements(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a rail replacement history file.

    Accepts both raw RMA files (auto-applies VBA macro logic) and
    pre-standardized files (with Standardized_Output sheet).

    Creates 0mm measurements for all chainages in each replacement range.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    lower = file.filename.lower()
    if not lower.endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(status_code=400, detail="File must be .xlsx, .xlsm, or .xls")

    content = await file.read()
    _save_uploaded_file(content, file.filename)

    from app.services.replacement_parser import parse_replacement_file, process_replacement_rows

    # Parse and standardize the file
    try:
        rows, format_detected = parse_replacement_file(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read file: {e}")

    # Create upload log
    upload_log = UploadLog(
        filename=file.filename,
        rows_total=0, rows_accepted=0, rows_skipped=0, rows_errored=0,
        status="completed",
    )
    db.add(upload_log)
    db.flush()

    # Process the standardized rows
    result = process_replacement_rows(rows, db, upload_log)

    upload_log.rows_total = result.total_rows
    upload_log.rows_accepted = result.measurements_created
    upload_log.rows_skipped = result.skipped_no_date + result.skipped_bad_bound + result.skipped_bad_chainage
    upload_log.rows_errored = result.skipped_no_match

    if result.measurements_created == 0 and result.total_rows > 0:
        upload_log.status = "failed"
    elif result.skipped_no_match > 0:
        upload_log.status = "partial"

    db.commit()

    # Refit predictions — replacement data affects wear lifecycle segmentation
    prediction_refit = {}
    if result.affected_chainage_ids:
        try:
            prediction_refit = refit_after_upload(upload_log.id, result.affected_chainage_ids, db)
        except Exception:
            prediction_refit = {"error": "Prediction refit failed"}

    return {
        "status": upload_log.status,
        "upload_id": upload_log.id,
        "filename": file.filename,
        "file_type": "replacement",
        "format_detected": format_detected,
        "summary": {
            "total_rows": result.total_rows,
            "valid_entries": result.valid_entries,
            "measurements_created": result.measurements_created,
            "skipped_no_date": result.skipped_no_date,
            "skipped_bad_bound": result.skipped_bad_bound,
            "skipped_bad_chainage": result.skipped_bad_chainage,
            "skipped_no_match": result.skipped_no_match,
        },
        "errors": result.errors[:50],
    }


@router.get("")
def list_uploads(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    """List recent uploads (measurements and category configs), newest first.

    Args:
        db: Database session (injected).
        limit: Maximum number of measurement uploads to return.

    Returns:
        A combined list of measurement and category upload records, sorted
        by upload timestamp descending.
    """
    uploads = db.query(UploadLog).order_by(UploadLog.uploaded_at.desc()).limit(limit).all()
    cat_configs = db.query(CategoryConfig).order_by(CategoryConfig.uploaded_at.desc()).all()
    results = []
    for u in uploads:
        is_deleted = u.deleted_at is not None
        results.append({
            "id": u.id, "type": "measurements", "filename": u.filename,
            "uploaded_at": str(u.uploaded_at) if u.uploaded_at else None,
            "rows_total": u.rows_total, "rows_accepted": u.rows_accepted,
            "rows_skipped": u.rows_skipped, "rows_errored": u.rows_errored,
            "status": "deleted" if is_deleted else u.status,
            "is_deleted": is_deleted,
            "deleted_at": str(u.deleted_at) if u.deleted_at else None,
            "deleted_reason": u.deleted_reason,
        })
    for c in cat_configs:
        results.append({
            "id": c.id, "type": "categories", "filename": c.filename,
            "uploaded_at": str(c.uploaded_at) if c.uploaded_at else None,
            "rows_total": c.total_chainages, "rows_accepted": c.updated_chainages,
            "rows_skipped": 0, "rows_errored": c.total_chainages - c.updated_chainages,
            "status": c.status, "is_deleted": False,
        })
    results.sort(key=lambda x: x["uploaded_at"] or "", reverse=True)
    return results


@router.get("/{upload_id}")
def get_upload(upload_id: int, db: Session = Depends(get_db)):
    """Return details for a single upload, including parsed error messages.

    Args:
        upload_id: Primary key of the upload log.
        db: Database session (injected).

    Returns:
        Upload detail dict with row counts and error list.

    Raises:
        HTTPException: 404 if the upload is not found.
    """
    upload = db.query(UploadLog).filter(UploadLog.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    errors = json.loads(upload.error_details) if upload.error_details else []
    return {
        "id": upload.id, "filename": upload.filename,
        "uploaded_at": str(upload.uploaded_at) if upload.uploaded_at else None,
        "rows_total": upload.rows_total, "rows_accepted": upload.rows_accepted,
        "rows_skipped": upload.rows_skipped, "rows_errored": upload.rows_errored,
        "status": upload.status, "errors": errors,
    }


class DeleteRequest(BaseModel):
    """Request body for the upload deletion endpoint."""
    reason: str = Field(..., min_length=1, description="Reason for deletion (required)")


@router.delete("/{upload_id}")
def delete_upload(upload_id: int, body: DeleteRequest, db: Session = Depends(get_db)):
    """Soft-delete an upload and hard-delete all its associated measurements.

    The upload record is marked as deleted (with timestamp and reason) but
    kept in the database for audit purposes.  Measurements are permanently
    removed so they no longer affect wear calculations or predictions.

    Predictions for all affected chainages are automatically refitted after
    the measurements are removed.

    Args:
        upload_id: Primary key of the upload to reverse.
        body: JSON body containing a required deletion reason.
        db: Database session (injected).

    Returns:
        Summary dict with counts of deleted measurements and affected chainages.

    Raises:
        HTTPException: 404 if not found, 400 if already deleted.
    """
    from app.models.measurement import WearMeasurement

    upload = db.query(UploadLog).filter(UploadLog.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    if upload.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Upload already deleted")

    # Identify all measurements from this upload
    measurements = db.query(WearMeasurement).filter(WearMeasurement.upload_id == upload_id).all()
    affected_chainage_ids = list({m.chainage_id for m in measurements})
    count_deleted = len(measurements)

    # Hard-delete the measurements
    db.query(WearMeasurement).filter(WearMeasurement.upload_id == upload_id).delete()

    # Soft-delete the upload log record
    upload.status = "deleted"
    upload.deleted_at = datetime.now()
    upload.deleted_reason = body.reason

    db.flush()

    # Clean up orphaned chainages — chainages with no remaining measurements
    from app.models.track import Chainage
    from sqlalchemy import func as sqlfunc

    orphaned_count = 0
    for ch_id in affected_chainage_ids:
        remaining = db.query(sqlfunc.count(WearMeasurement.id)).filter(
            WearMeasurement.chainage_id == ch_id
        ).scalar()
        if remaining == 0:
            db.query(Chainage).filter(Chainage.id == ch_id).delete()
            orphaned_count += 1

    db.commit()

    # Refit predictions for non-orphaned chainages (upload_id=0 signals a deletion)
    refit_result = {}
    surviving_ids = [ch_id for ch_id in affected_chainage_ids
                     if db.query(Chainage).filter(Chainage.id == ch_id).first() is not None]
    if surviving_ids:
        try:
            refit_result = refit_after_upload(0, surviving_ids, db)
        except Exception:
            refit_result = {"error": "Prediction refit failed"}

    return {
        "status": "ok",
        "upload_id": upload_id,
        "filename": upload.filename,
        "measurements_deleted": count_deleted,
        "chainages_affected": len(affected_chainage_ids),
        "chainages_removed": orphaned_count,
        "predictions_refitted": refit_result.get("predictions_updated", 0),
        "message": f"Upload reversed. {count_deleted:,} measurements deleted, {orphaned_count} orphaned chainages removed.",
    }
