"""
router.py — Central Route Registry
====================================
This file is the "switchboard" that connects all parts of the RailWatch web API together.

HOW IT WORKS (plain English):
- The RailWatch backend is split into separate modules, each handling a specific job
  (e.g., chainages, measurements, uploads, predictions, etc.).
- This file imports each module and registers it under a URL prefix.
- For example, the chainage module is mounted at "/chainages", so any request
  to /api/chainages/... is handled by the chainages module.
- This file also defines two simple endpoints of its own: a health check and
  a track listing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# ── Import all the feature modules ────────────────────────────────────────
# Each of these modules handles a specific area of the application.
from app.api.chainages import router as chainages_router       # Track section (chainage) data
from app.api.measurements import router as measurements_router # Wear measurement readings
from app.api.upload import router as upload_router             # CSV / data file uploads
from app.api.overview import router as overview_router         # Fleet-wide dashboard summary
from app.api.predictions import router as predictions_router   # Wear predictions & forecasts
from app.api.maintenance import router as maintenance_router   # Maintenance scheduling
from app.api.settings import router as settings_router         # System configuration & model info
from app.api.auth import router as auth_router                 # Login / logout / session management
from app.database import get_db        # Helper that provides a database connection
from app.models.track import Track     # Database model representing a rail track/line

# Create the main router — all sub-routers will be attached to this one.
router = APIRouter()

# ── Mount each feature module under its own URL prefix ─────────────────────
# "prefix" sets the URL path, e.g. prefix="/chainages" means all endpoints
# in that module are reached at /api/chainages/...
# "tags" groups them in the auto-generated API documentation.

# Chainage endpoints — view and manage individual track sections
router.include_router(chainages_router, prefix="/chainages", tags=["chainages"])

# Measurement endpoints — view wear measurement data for track sections
router.include_router(measurements_router, prefix="/measurements", tags=["measurements"])

# Upload endpoints — upload new measurement data from CSV files
router.include_router(upload_router, prefix="/upload", tags=["upload"])

# Overview endpoint — provides the fleet-wide dashboard summary
router.include_router(overview_router, prefix="/overview", tags=["overview"])

# Prediction endpoints — get wear forecasts for track sections
# Note: these are mounted under "/chainages" because predictions relate to chainages
router.include_router(predictions_router, prefix="/chainages", tags=["predictions"])

# Maintenance endpoints — manage and view maintenance schedules
router.include_router(maintenance_router, prefix="/maintenance", tags=["maintenance"])

# Settings endpoints — view model coefficients and system configuration
router.include_router(settings_router, prefix="/settings", tags=["settings"])

# Auth endpoints — handle login, logout, and session checks
router.include_router(auth_router, prefix="/auth", tags=["auth"])


# ── GET /api/health ────────────────────────────────────────────────────────
# A simple "heartbeat" endpoint used by monitoring tools to check whether
# the server is running. If this returns "ok", the server is alive.
@router.get("/health")
def health_check():
    """Return a simple health-check response for uptime monitoring."""
    return {"status": "ok"}


# ── GET /api/tracks ────────────────────────────────────────────────────────
# This returns a list of all rail tracks (lines) registered in the system,
# along with their measurement position configurations.
# For example, this would list "NEL" (North-East Line), "DTL" (Downtown Line), etc.
@router.get("/tracks")
def list_tracks(db: Session = Depends(get_db)):
    """Return all registered tracks with their measurement position configs.

    Args:
        db: Database session (injected by FastAPI).

    Returns:
        A list of track dicts containing id, track_id, name, description,
        and measurement_positions.
    """
    # Query the database for every track record
    tracks = db.query(Track).all()

    # Build and return a list of dictionaries, one per track.
    # Each dictionary contains the track's ID, human-readable name,
    # description, and the list of angular positions where wear is measured
    # (e.g., 0°, 22.5°, 45°, 67.5°, 90° around the rail head).
    return [
        {
            "id": t.id, "track_id": t.track_id, "name": t.name,
            "description": t.description, "measurement_positions": t.measurement_positions,
        }
        for t in tracks
    ]
