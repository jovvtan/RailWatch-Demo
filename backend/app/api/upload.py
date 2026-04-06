"""
Upload API — DEMO MODE (read-only)
All upload/delete endpoints return a friendly message instead of modifying data.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.upload import UploadLog

router = APIRouter()

DEMO_MSG = "Demo mode — uploads are disabled. This interface uses sample data only."


@router.post("/measurements")
def upload_measurements(
    file: UploadFile = File(...),
    measurement_date: str = Form(None),
    db: Session = Depends(get_db),
):
    return {
        "status": "demo",
        "message": DEMO_MSG,
        "filename": file.filename,
        "rows_accepted": 0,
        "rows_skipped": 0,
        "errors": [],
        "warnings": [DEMO_MSG],
    }


@router.post("/categories")
def upload_categories(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    return {
        "status": "demo",
        "message": DEMO_MSG,
        "filename": file.filename,
        "rows_accepted": 0,
        "errors": [],
        "warnings": [DEMO_MSG],
    }


@router.post("/replacements")
def upload_replacements(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    return {
        "status": "demo",
        "message": DEMO_MSG,
        "filename": file.filename,
        "rows_accepted": 0,
        "errors": [],
        "warnings": [DEMO_MSG],
    }


@router.get("")
def list_uploads(db: Session = Depends(get_db)):
    """Return upload history (read-only)."""
    uploads = db.query(UploadLog).order_by(UploadLog.uploaded_at.desc()).all()
    return [
        {
            "id": u.id,
            "filename": u.filename,
            "uploaded_at": str(u.uploaded_at) if u.uploaded_at else None,
            "rows_accepted": u.rows_accepted,
            "rows_total": u.rows_total,
            "status": u.status,
            "is_deleted": u.is_deleted if hasattr(u, 'is_deleted') else False,
            "deleted_at": str(u.deleted_at) if hasattr(u, 'deleted_at') and u.deleted_at else None,
            "type": "measurements",
        }
        for u in uploads
    ]


@router.delete("/{upload_id}")
def delete_upload(upload_id: int, reason: str = "", db: Session = Depends(get_db)):
    raise HTTPException(status_code=403, detail=DEMO_MSG)
