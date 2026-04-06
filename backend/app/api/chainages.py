"""Chainage API endpoints — search, filters, pagination, sector summaries, and time-series data.

Provides endpoints:
- ``GET /api/chainages`` — paginated list with search, filtering, and sorting (optimised bulk queries).
- ``GET /api/chainages/sectors`` — sector summaries for sidebar navigation.
- ``GET /api/chainages/stations`` — unique station names for filter dropdowns.
- ``GET /api/chainages/{chainage_id}`` — full detail including all measurements.
- ``GET /api/chainages/{chainage_id}/measurements`` — time-series data for charts.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.track import Chainage, Track
from app.models.measurement import WearMeasurement

router = APIRouter()

CATEGORY_LABELS = {1: "Straight (Standard)", 2: "Curved (Standard)", 3: "Curved (Premium)"}
ZONE_COLORS = {"SC5": "#10b981", "SC4": "#f59e0b", "SC3": "#ef4444", "SC2": "#dc2626", "SC1": "#b91c1c"}


def classify_wear_zone(wear_mm: float | None) -> str:
    """Classify a wear reading into a service condition zone (SC1-SC5)."""
    if wear_mm is None: return "SC5"
    if wear_mm < 4.0: return "SC5"
    elif wear_mm < 6.0: return "SC4"
    elif wear_mm < 7.0: return "SC3"
    elif wear_mm < 8.0: return "SC2"
    else: return "SC1"


def _bulk_latest_measurements(db: Session):
    """Return a dict mapping chainage PK → latest WearMeasurement row.

    Simple approach: max date per chainage, then pick one row per chainage.
    If duplicates exist on the same max date, the last one wins (non-deterministic
    but acceptable for display purposes).
    """
    subq = (
        db.query(
            WearMeasurement.chainage_id,
            func.max(WearMeasurement.measurement_date).label("max_date"),
        )
        .group_by(WearMeasurement.chainage_id)
        .subquery()
    )
    rows = (
        db.query(WearMeasurement)
        .join(subq, (WearMeasurement.chainage_id == subq.c.chainage_id)
              & (WearMeasurement.measurement_date == subq.c.max_date))
        .all()
    )
    # Dict comprehension — last row wins if duplicates exist on same date
    return {m.chainage_id: m for m in rows}


def _bulk_meas_counts(db: Session):
    """Return a dict mapping chainage PK → measurement count (single query)."""
    rows = (
        db.query(WearMeasurement.chainage_id, func.count(WearMeasurement.id).label("cnt"))
        .group_by(WearMeasurement.chainage_id)
        .all()
    )
    return {cid: cnt for cid, cnt in rows}


# ---------------------------------------------------------------------------
# GET /api/chainages/sectors — sector summary for sidebar navigation
# ---------------------------------------------------------------------------
@router.get("/sectors")
def list_sectors(
    track_id: Optional[str] = Query(None),
    bound: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return sector summaries with chainage counts and worst wear zone.

    Used by the sidebar for sector-based navigation. Each sector includes
    the count of chainages, worst wear zone, and station pair names.
    """
    query = db.query(Chainage)
    if track_id:
        track = db.query(Track).filter(Track.track_id == track_id).first()
        if track:
            query = query.filter(Chainage.track_id == track.id)
    if bound:
        query = query.filter(Chainage.bound == bound)

    chainages = query.all()
    latest_map = _bulk_latest_measurements(db)

    # Group by sector
    sectors = {}
    for c in chainages:
        key = c.sector or "Unknown"
        if key not in sectors:
            sectors[key] = {
                "sector": key,
                "bound": c.bound,
                "start_station": c.start_station,
                "end_station": c.end_station,
                "chainage_count": 0,
                "worst_wear_mm": 0.0,
                "worst_zone": "SC5",
                "zone_counts": {"SC1": 0, "SC2": 0, "SC3": 0, "SC4": 0, "SC5": 0},
                "category_counts": {"straight": 0, "curved_std": 0, "curved_prem": 0},
            }
        s = sectors[key]
        s["chainage_count"] += 1
        cat_key = {1: "straight", 2: "curved_std", 3: "curved_prem"}.get(c.category)
        if cat_key:
            s["category_counts"][cat_key] += 1

        latest = latest_map.get(c.id)
        wear = latest.wear_mm if latest else None
        zone = classify_wear_zone(wear)
        s["zone_counts"][zone] += 1

        if wear is not None and wear > s["worst_wear_mm"]:
            s["worst_wear_mm"] = wear
            s["worst_zone"] = zone

    # Merge station-area sectors (no hyphen, e.g. "CQY", "BNK") into
    # an inter-station sector with the same (start_station, end_station) pair
    inter_station = {k: v for k, v in sectors.items() if "-" in k}
    station_areas = {k: v for k, v in sectors.items() if "-" not in k and k != "Unknown"}

    # Build a lookup: (start, end) -> inter-station sector key
    pair_to_key = {}
    for k, v in inter_station.items():
        pair = (v["start_station"], v["end_station"])
        pair_to_key[pair] = k

    def _merge_into(target_key, sa):
        t = sectors[target_key]
        t["chainage_count"] += sa["chainage_count"]
        for zk in sa["zone_counts"]:
            t["zone_counts"][zk] += sa["zone_counts"][zk]
        for ck in sa["category_counts"]:
            t["category_counts"][ck] += sa["category_counts"][ck]
        if sa["worst_wear_mm"] > t["worst_wear_mm"]:
            t["worst_wear_mm"] = sa["worst_wear_mm"]
            t["worst_zone"] = sa["worst_zone"]

    for sa_key, sa in list(station_areas.items()):
        pair = (sa["start_station"], sa["end_station"])
        target_key = pair_to_key.get(pair)
        if target_key and target_key in sectors:
            _merge_into(target_key, sa)
            del sectors[sa_key]
        else:
            # No matching inter-station sector — rename to proper "X-Y" format
            # e.g. CNT with (Chinatown, Outram Park) -> "CNT-OTP"
            sa["sector"] = f"{sa['start_station']} - {sa['end_station']}"

    # Sort by NEL northbound station order (Punggol end first)
    NEL_NB_ORDER = [
        "PGL-SKG", "SKG-BGK", "BGK-HGN", "HGN-KVN", "KVN-SER", "SER-WLH",
        "WLH-PTP", "PTP-BNK", "BNK-FRP", "FRP-LTI", "LTI-DBG", "DBG-CQY",
        "CQY-CNT", "OTP-HBF",
    ]
    def _sort_key(s):
        name = s["sector"]
        if name in NEL_NB_ORDER:
            return NEL_NB_ORDER.index(name)
        # Put unmatched sectors at the end, sorted by worst wear
        return 100 - (s.get("worst_wear_mm", 0) or 0) / 100

    result = sorted(sectors.values(), key=_sort_key)
    return result


# ---------------------------------------------------------------------------
# GET /api/chainages — optimised paginated list
# ---------------------------------------------------------------------------
@router.get("")
def list_chainages(
    search: Optional[str] = Query(None),
    track_id: Optional[str] = Query(None),
    wear_zone: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    bound: Optional[str] = Query(None),
    sort: Optional[str] = Query("criticality"),
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List chainages with optional filtering, searching, and sorting.

    Optimised with bulk queries — no N+1 problem regardless of chainage count.
    """
    query = db.query(Chainage)

    if track_id:
        track = db.query(Track).filter(Track.track_id == track_id).first()
        if track:
            query = query.filter(Chainage.track_id == track.id)

    if category:
        cats = [int(c.strip()) for c in category.split(",") if c.strip().isdigit()]
        if cats:
            query = query.filter(Chainage.category.in_(cats))

    if sector:
        query = query.filter(Chainage.sector == sector)

    if bound:
        query = query.filter(Chainage.bound == bound)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            Chainage.chainage_id.ilike(pattern)
            | Chainage.location_description.ilike(pattern)
            | Chainage.start_station.ilike(pattern)
            | Chainage.end_station.ilike(pattern)
            | Chainage.sector.ilike(pattern)
        )

    chainages = query.order_by(Chainage.chainage_id).all()

    # Bulk fetch latest measurements and counts (2 queries total instead of 2N)
    latest_map = _bulk_latest_measurements(db)
    count_map = _bulk_meas_counts(db)
    tracks = {t.id: t for t in db.query(Track).all()}

    results = []
    for c in chainages:
        latest = latest_map.get(c.id)
        track_obj = tracks.get(c.track_id)
        wear_val = latest.wear_mm if latest else None
        zone = classify_wear_zone(wear_val)

        results.append({
            "id": c.id,
            "chainage_id": c.chainage_id,
            "track_id": c.track_id,
            "track_code": track_obj.track_id if track_obj else None,
            "track_name": track_obj.name if track_obj else None,
            "start_station": c.start_station,
            "end_station": c.end_station,
            "last_recorded_date": str(latest.measurement_date) if latest else None,
            "wear_threshold_mm": c.wear_threshold_mm,
            "latest_wear_mm": wear_val,
            "wear_zone": zone,
            "wear_zone_color": ZONE_COLORS.get(zone, "#10b981"),
            "category": c.category,
            "category_label": CATEGORY_LABELS.get(c.category, "Uncategorised"),
            "curve_radius": c.curve_radius,
            "curve_direction": c.curve_direction,
            "rail_type": c.rail_type,
            "sector": c.sector,
            "bound": c.bound,
            "measurement_count": count_map.get(c.id, 0),
            "measurement_positions": track_obj.measurement_positions if track_obj else None,
        })

    # Post-query wear zone filter (zone is computed, not stored)
    if wear_zone:
        zones = [z.strip() for z in wear_zone.split(",")]
        results = [r for r in results if r["wear_zone"] in zones]

    # Sort
    if sort == "criticality":
        results.sort(key=lambda r: -(r["latest_wear_mm"] or 0))
    elif sort == "chainage":
        results.sort(key=lambda r: r["chainage_id"])
    elif sort == "wear_asc":
        results.sort(key=lambda r: (r["latest_wear_mm"] or 0))
    elif sort == "wear_desc":
        results.sort(key=lambda r: -(r["latest_wear_mm"] or 0))
    elif sort == "category":
        results.sort(key=lambda r: (r["category"] or 0, r["chainage_id"]))

    total = len(results)
    results = results[offset:offset + limit]
    return results


# ---------------------------------------------------------------------------
# GET /api/chainages/stations
# ---------------------------------------------------------------------------
@router.get("/stations")
def list_stations(track_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Return a sorted list of unique station names."""
    query = db.query(Chainage)
    if track_id:
        track = db.query(Track).filter(Track.track_id == track_id).first()
        if track:
            query = query.filter(Chainage.track_id == track.id)
    stations = set()
    for c in query.all():
        if c.start_station: stations.add(c.start_station)
        if c.end_station: stations.add(c.end_station)
    return sorted(stations)


# ---------------------------------------------------------------------------
# GET /api/chainages/{chainage_id}/measurements
# ---------------------------------------------------------------------------
@router.get("/{chainage_id}/measurements")
def get_chainage_measurements(
    chainage_id: str,
    bound: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return time-series measurement data for a chainage, formatted for charts."""
    query = db.query(Chainage).filter(Chainage.chainage_id == chainage_id)
    if bound:
        query = query.filter(Chainage.bound == bound)
    chainage = query.first()
    if not chainage:
        raise HTTPException(status_code=404, detail="Chainage not found")

    track = db.query(Track).filter(Track.id == chainage.track_id).first()
    positions = track.measurement_positions if track else ["0", "45"]

    query = (
        db.query(WearMeasurement)
        .filter(WearMeasurement.chainage_id == chainage.id)
        .order_by(WearMeasurement.measurement_date)
    )
    if start_date:
        try:
            query = query.filter(WearMeasurement.measurement_date >= date.fromisoformat(start_date))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(WearMeasurement.measurement_date <= date.fromisoformat(end_date))
        except ValueError:
            pass

    measurements = query.all()

    pos_fields = []
    for side in ("left", "right"):
        for angle in positions:
            suffix = angle.replace(".", "_")
            pos_fields.append((f"{side}_{suffix}", f"{side}_wear_{suffix}"))

    meas_list = []
    for m in measurements:
        entry = {"date": str(m.measurement_date), "wear_mm": m.wear_mm}
        for label, attr in pos_fields:
            val = getattr(m, attr, None)
            if val is not None:
                entry[label] = val
        meas_list.append(entry)

    latest = measurements[-1] if measurements else None
    current_wear = latest.wear_mm if latest else None
    dates_list = [str(m.measurement_date) for m in measurements]

    return {
        "chainage_id": chainage.chainage_id,
        "track": track.track_id if track else None,
        "measurement_positions": positions,
        "measurements": meas_list,
        "metadata": {
            "total_points": len(measurements),
            "date_range": [dates_list[0], dates_list[-1]] if dates_list else [],
            "current_wear": current_wear,
            "wear_zone": classify_wear_zone(current_wear),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/chainages/{chainage_id}
# ---------------------------------------------------------------------------
@router.get("/{chainage_id}")
def get_chainage(chainage_id: str, bound: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Return full chainage detail including all historical measurements."""
    query = db.query(Chainage).filter(Chainage.chainage_id == chainage_id)
    if bound:
        query = query.filter(Chainage.bound == bound)
    chainage = query.first()
    if not chainage:
        raise HTTPException(status_code=404, detail="Chainage not found")

    track = db.query(Track).filter(Track.id == chainage.track_id).first()

    measurements = (
        db.query(WearMeasurement)
        .filter(WearMeasurement.chainage_id == chainage.id)
        .order_by(WearMeasurement.measurement_date)
        .all()
    )

    latest = measurements[-1] if measurements else None
    wear_val = latest.wear_mm if latest else None

    def _meas_dict(m):
        return {
            "id": m.id, "measurement_date": str(m.measurement_date), "wear_mm": m.wear_mm,
            "left_wear_0": m.left_wear_0, "left_wear_22_5": m.left_wear_22_5,
            "left_wear_45": m.left_wear_45, "left_wear_67_5": m.left_wear_67_5,
            "left_wear_90": m.left_wear_90, "right_wear_0": m.right_wear_0,
            "right_wear_22_5": m.right_wear_22_5, "right_wear_45": m.right_wear_45,
            "right_wear_67_5": m.right_wear_67_5, "right_wear_90": m.right_wear_90,
            "source_file": m.source_file,
        }

    return {
        "id": chainage.id, "chainage_id": chainage.chainage_id,
        "track_id": chainage.track_id,
        "track_code": track.track_id if track else None,
        "track_name": track.name if track else None,
        "start_station": chainage.start_station, "end_station": chainage.end_station,
        "direction": chainage.direction,
        "install_date": str(chainage.install_date) if chainage.install_date else None,
        "last_recorded_date": str(latest.measurement_date) if latest else None,
        "wear_threshold_mm": chainage.wear_threshold_mm,
        "latest_wear_mm": wear_val,
        "wear_zone": classify_wear_zone(wear_val),
        "category": chainage.category,
        "category_label": CATEGORY_LABELS.get(chainage.category, "Uncategorised"),
        "curve_radius": chainage.curve_radius,
        "curve_direction": chainage.curve_direction,
        "rail_type": chainage.rail_type,
        "sector": chainage.sector, "bound": chainage.bound,
        "measurements": [_meas_dict(m) for m in measurements],
        "track": {
            "id": track.id, "track_id": track.track_id, "name": track.name,
            "description": track.description,
            "measurement_positions": track.measurement_positions,
        } if track else None,
    }
