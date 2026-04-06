"""
overview.py — Fleet-Wide Dashboard Summary
============================================
This file provides a single endpoint that returns a high-level summary of the
entire rail fleet's health.

HOW IT WORKS (plain English):
- It looks at every chainage (track section) in the system.
- For each one, it finds the most recent wear measurement.
- It classifies each chainage into a wear zone (SC1 through SC5), where
  SC1 is the most critical (needs urgent attention) and SC5 is acceptable.
- It then counts how many chainages fall into each zone, each track category,
  and each rail line.
- It also identifies the top 5 most worn chainages and lists the 3 most
  recent data uploads.
- All of this is returned in one response so the dashboard can display it
  without making many separate requests.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.track import Chainage, Track
from app.models.measurement import WearMeasurement
from app.models.upload import UploadLog
from app.api.chainages import classify_wear_zone, _bulk_latest_measurements

router = APIRouter()


# ── GET /api/overview ──────────────────────────────────────────────────────
# This is the main dashboard endpoint. It gathers fleet-wide statistics
# and returns everything the overview screen needs in a single response.
@router.get("")
def fleet_overview(line: str = None, db: Session = Depends(get_db)):
    """Return a dashboard summary, optionally filtered by rail line."""

    # ── Step 1: Load chainages, filtered by line if specified ─────────────
    q = db.query(Chainage)
    if line:
        track = db.query(Track).filter(Track.track_id == line.upper()).first()
        if track:
            q = q.filter(Chainage.track_id == track.id)
    chainages = q.all()
    total = len(chainages)  # Total number of track sections in the system

    # ── Step 2: Get the latest wear measurement for every chainage ─────────
    # This uses a single efficient database query instead of querying each
    # chainage one at a time (which would be very slow with thousands of sections).
    # The result is a dictionary: chainage ID -> its latest measurement record.
    latest_map = _bulk_latest_measurements(db)

    # ── Step 3: Build a lookup of tracks by ID for quick access ────────────
    # This lets us find a track's name/code without querying the database
    # again for each chainage.
    tracks = {t.id: t for t in db.query(Track).all()}

    # ── Step 4: Prepare counters for the summary statistics ────────────────

    # Count of chainages in each wear zone (SC5 = healthy, SC1 = critical)
    by_zone = {"SC5": 0, "SC4": 0, "SC3": 0, "SC2": 0, "SC1": 0}

    # Count of chainages by track category:
    #   1 = Straight track with standard rail
    #   2 = Curved track with standard rail
    #   3 = Curved track with premium (harder) rail
    cat_counts = {1: 0, 2: 0, 3: 0}

    # Count of chainages per rail line (e.g. "NEL", "DTL"), with a sub-count
    # of how many are in a critical wear zone (SC1, SC2, or SC3).
    by_track = {}

    # Detailed list of every chainage's wear data — used to find the top 5 worst
    wear_data = []

    # ── Step 5: Loop through every chainage and classify it ────────────────
    for c in chainages:
        # Look up the most recent wear measurement for this chainage.
        # If no measurement exists yet, wear_val will be None.
        latest = latest_map.get(c.id)
        wear_val = latest.wear_mm if latest else None

        # Classify the wear value into a zone (SC1–SC5).
        # For example: 3 mm -> SC5 (acceptable), 7.5 mm -> SC2 (urgent).
        zone = classify_wear_zone(wear_val)

        # Find which track/line this chainage belongs to (e.g. "NEL", "DTL").
        track = tracks.get(c.track_id)
        tc = track.track_id if track else "Unknown"

        # Increment the counter for this wear zone
        by_zone[zone] = by_zone.get(zone, 0) + 1

        # Increment the counter for this chainage's category (straight/curved/premium)
        if c.category in cat_counts:
            cat_counts[c.category] += 1

        # Increment the per-track counters (total and critical)
        if tc not in by_track:
            by_track[tc] = {"total": 0, "critical": 0}
        by_track[tc]["total"] += 1

        # SC1, SC2, and SC3 are all considered "critical" — they need maintenance action
        if zone in ("SC1", "SC2", "SC3"):
            by_track[tc]["critical"] += 1

        # Store the full detail for this chainage (used later to find top 5 worst)
        wear_data.append({
            "chainage_id": c.chainage_id,
            "track_code": tc,
            "wear_mm": wear_val,
            "wear_zone": zone,
            "category": c.category,
            "sector": c.sector,
            "bound": c.bound,
            "start_station": c.start_station,
            "end_station": c.end_station,
        })

    # ── Step 6: Find the top 5 most critical chainages ─────────────────────
    # Sort all chainages by wear (highest first) and take the top 5.
    # The "or 0" handles chainages with no measurement (None), treating them as 0.
    top_critical = sorted(wear_data, key=lambda x: -(x["wear_mm"] or 0))[:5]

    # ── Step 7: Get the 3 most recent data uploads ─────────────────────────
    # This shows engineers when data was last uploaded and how many rows were accepted.
    recent = db.query(UploadLog).order_by(UploadLog.uploaded_at.desc()).limit(3).all()
    recent_uploads = [
        {"filename": u.filename, "date": str(u.uploaded_at)[:10] if u.uploaded_at else None, "rows_accepted": u.rows_accepted}
        for u in recent
    ]

    # ── Step 8: Return everything the dashboard needs ──────────────────────
    return {
        # Total number of track sections in the entire system
        "total_chainages": total,

        # How many chainages fall into each wear severity zone
        "by_wear_zone": by_zone,

        # How many chainages are in each track category
        "by_category": {
            "straight_standard": cat_counts.get(1, 0),   # Straight track, standard rail
            "curved_standard": cat_counts.get(2, 0),     # Curved track, standard rail
            "curved_premium": cat_counts.get(3, 0),      # Curved track, premium (harder) rail
        },

        # Per-track/line breakdown (total and critical counts)
        "by_track": by_track,

        # The 5 track sections with the worst (highest) wear
        "top_critical": top_critical,

        # The 3 most recent data file uploads
        "recent_uploads": recent_uploads,
    }
