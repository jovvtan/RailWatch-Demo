"""
Prediction service — orchestrates global model fitting and per-chainage prediction.

FILE PURPOSE:
    This file is the "brain" of the prediction system. It sits between the
    web API (which receives requests) and the mathematical regression layer
    (which does the actual curve fitting).

    It handles three main tasks:

    1. FITTING GLOBAL MODELS (fit_global_models):
       - Collects wear measurement data from ALL chainages in each category
       - Groups the data by category, angular position, and rail role
       - Fits one regression model (trend line) for each group
       - Saves the fitted models to the GlobalModel database table

    2. PREDICTING INDIVIDUAL CHAINAGES (predict_chainage):
       - Takes a single chainage and its latest measurement
       - Looks up the appropriate global model for that chainage's category
       - Uses the model to predict when wear will reach the maintenance threshold
       - Returns the predicted repair date and other details

    3. REFITTING AFTER DATA UPLOAD (refit_after_upload):
       - Called automatically after new measurement data is uploaded
       - Refits the global models for affected categories
       - Re-predicts all chainages in those categories
       - Saves prediction snapshots to the PredictionLog table

    The "global model" approach pools data from many chainages to build more
    reliable predictions. Instead of needing many data points at each individual
    location, the system learns the typical wear pattern for each category and
    applies it everywhere.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Set

from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.models.track import Chainage, Track
from app.models.measurement import WearMeasurement
from app.models.prediction import PredictionLog
from app.models.replacement import ReplacementLog
from app.models.global_model import GlobalModel

# Import the mathematical regression functions from the ML layer
from app.ml.regression import (
    POSITIONS,                           # List of angular positions: ["0", "22.5", "45", "67.5", "90"]
    POSITION_TO_COLUMNS,                 # Maps position to database column names
    GlobalModelResult,                   # Result container for a fitted model
    ChainagePrediction,                  # Result container for a prediction
    calculate_recency_weights,           # Calculates weights that prioritise recent data
    detect_replacements,                 # Finds rail replacement events in measurement history
    fit_single_global_model,             # Fits one regression model to pooled data
    map_rail_role,                       # Maps inner/outer rail role to left/right
    predict_chainage_from_models,        # Generates predictions using global models
    segment_measurements_by_replacement, # Splits measurement history at replacement points
)

logger = logging.getLogger(__name__)

# Human-readable names for model types, keyed by category number
CATEGORY_MODEL_TYPES = {1: "straight", 2: "curved_standard", 3: "curved_premium"}


# ---------------------------------------------------------------------------
# TASK 1: Global model fitting
# ---------------------------------------------------------------------------

def fit_global_models(
    db: Session,
    categories: Optional[Set[int]] = None,
    upload_id: Optional[int] = None,
    track_id: Optional[int] = None,
) -> Dict:
    """
    Fit (or refit) global regression models for the specified categories.

    This is the core model training function. For each category (straight,
    curved standard, curved premium), it:
    1. Gets all chainages in that category
    2. For each angular position (0, 22.5, 45, 67.5, 90 degrees):
       a. For each rail role (both/inner/outer):
          - Collects measurement data from ALL chainages
          - Pools it together into one dataset
          - Fits a regression model (trend line) to the pooled data
          - Saves the fitted model to the database

    The result is up to 25 models (see global_model.py for the breakdown).

    WHY GLOBAL MODELS?
    Individual chainages often have too few data points for a reliable
    prediction. By pooling data from all chainages in the same category,
    we get a much more robust estimate of the typical wear rate.

    Args:
        db: Database session.
        categories: Which categories to refit (e.g. {1, 2}). If None, refits all.
        upload_id: The upload that triggered this refit (for audit trail).

    Returns:
        A summary dict with: models_fitted count, details list, errors list.
    """
    # If no specific categories requested, refit all three
    if categories is None:
        categories = {1, 2, 3}

    results: List[dict] = []
    models_fitted = 0
    errors: List[str] = []

    # Process each category
    for cat in sorted(categories):
        # This determines whether the category involves curved track.
        # Curved track (categories 2 and 3) needs separate inner/outer rail models.
        is_curved = cat in (2, 3)

        # Get all chainages assigned to this category (filtered by line if specified)
        ch_q = db.query(Chainage).filter(Chainage.category == cat)
        if track_id:
            ch_q = ch_q.filter(Chainage.track_id == track_id)
        chainages = ch_q.all()
        if not chainages:
            continue  # No chainages in this category — skip

        # For curved track, we model inner and outer rails separately because
        # centripetal force causes asymmetric wear. For straight track, both
        # rails wear roughly equally, so we use a single "both" model.
        if is_curved:
            rail_roles = ["inner", "outer"]
        else:
            rail_roles = ["both"]

        # Loop through each angular position
        for pos in POSITIONS:
            # Get the database column names for this position
            # (e.g. for position "45": left_col="left_wear_45", right_col="right_wear_45")
            left_col, right_col = POSITION_TO_COLUMNS[pos]

            # Loop through each rail role
            for rail_role in rail_roles:
                # This list will hold ALL data points from ALL chainages
                # for this specific (category, position, rail_role) combination
                data_points: List[dict] = []

                # Collect data from every chainage in this category
                for ch in chainages:
                    # --- Determine which physical column to use ---
                    # For curved track, "inner" and "outer" map to left/right
                    # depending on which way the curve goes.
                    if is_curved:
                        # Skip chainages that don't have a curve direction set
                        if ch.curve_direction is None:
                            continue  # skip chainages without curve direction
                        # The "outer" rail is the one on the outside of the curve.
                        # If the curve goes RIGHT, the LEFT rail is on the outside.
                        # If the curve goes LEFT, the RIGHT rail is on the outside.
                        if rail_role == "outer":
                            col = left_col if ch.curve_direction == "right" else right_col
                        else:  # inner
                            col = right_col if ch.curve_direction == "right" else left_col
                        cols_to_use = [col]
                    else:
                        # Straight track: both left and right rails contribute
                        # to the same model
                        cols_to_use = [left_col, right_col]

                    # --- Fetch measurements for this chainage ---
                    # Exclude replacement records and baseline records (these
                    # are synthetic 0mm values, not real equipment readings)
                    meas_list = (
                        db.query(WearMeasurement)
                        .filter(
                            WearMeasurement.chainage_id == ch.id,
                            ~WearMeasurement.source_file.like("replacement_%"),
                            WearMeasurement.source_file != "NEL_opening_baseline",
                            WearMeasurement.source_file != "manual_replacement",
                        )
                        .order_by(WearMeasurement.measurement_date.asc())
                        .all()
                    )

                    # Need at least 2 measurements to fit a trend line
                    if len(meas_list) < 2:
                        continue

                    # Convert to simple dicts for the replacement detection function
                    meas_dicts = [
                        {"measurement_date": m.measurement_date, "wear_mm": m.wear_mm}
                        for m in meas_list
                    ]

                    # --- Detect rail replacements ---
                    # If a rail was replaced mid-history, we only want data
                    # AFTER the most recent replacement (the current lifecycle).
                    reps = detect_replacements(meas_dicts)

                    # Also check for manually logged replacements in the database
                    manual_reps = (
                        db.query(ReplacementLog)
                        .filter(ReplacementLog.chainage_id == ch.id)
                        .order_by(ReplacementLog.replacement_date.asc())
                        .all()
                    )

                    # Merge auto-detected and manual replacements, avoiding duplicates
                    auto_dates = {r["date"] for r in reps}
                    for mr in manual_reps:
                        if mr.replacement_date not in auto_dates:
                            # Find the measurement index closest to the replacement date
                            idx = _find_index_for_date(meas_dicts, mr.replacement_date)
                            if idx is not None:
                                reps.append({
                                    "index": idx,
                                    "date": mr.replacement_date,
                                    "prev_wear": meas_dicts[idx - 1]["wear_mm"] if idx > 0 else 0.0,
                                    "new_wear": meas_dicts[idx]["wear_mm"],
                                })
                    reps.sort(key=lambda r: r["index"])

                    # Split measurement history into segments at replacement points.
                    # We only use the LAST segment (current rail lifecycle).
                    segments = segment_measurements_by_replacement(meas_dicts, reps)
                    active = segments[-1] if segments else meas_dicts

                    # Need at least 2 measurements in the current lifecycle
                    if len(active) < 2:
                        continue

                    first_date = active[0]["measurement_date"]

                    # Get the ORM objects for the active segment (we need these
                    # to access per-position column values, not just wear_mm)
                    active_dates = {m["measurement_date"] for m in active}
                    active_orm = [m for m in meas_list if m.measurement_date in active_dates]

                    # --- Extract per-position data ---
                    for col_name in cols_to_use:
                        # Get all non-null values at this position, sorted by date
                        vals = [(m.measurement_date, getattr(m, col_name, None)) for m in active_orm]
                        vals = [(d, v) for d, v in vals if v is not None]
                        if len(vals) < 2:
                            continue
                        vals.sort()

                        # Only include chainages where wear is INCREASING.
                        # If the last value is not greater than the first, something
                        # is wrong (possible data error or recent grind).
                        first_val = abs(float(vals[0][1]))
                        last_val = abs(float(vals[-1][1]))
                        if last_val <= first_val:
                            continue  # Skip chainages with non-increasing wear

                        # Add each measurement as a data point for the model
                        for m in active_orm:
                            val = getattr(m, col_name, None)
                            if val is None:
                                continue
                            # Calculate days elapsed since the first measurement
                            elapsed = (m.measurement_date - first_date).days
                            data_points.append({
                                "elapsed_days": float(elapsed),
                                "wear_mm": abs(float(val)),
                                "date": m.measurement_date,
                                "curve_radius": float(ch.curve_radius) if ch.curve_radius else 0.0,
                                "chainage_id": ch.chainage_id,
                            })

                # --- Fit the model for this (category, position, rail_role) ---
                # Need at least 2 data points to fit a trend line
                if len(data_points) < 2:
                    continue

                try:
                    # Call the ML regression function to fit the model
                    gm_result = fit_single_global_model(data_points, cat, is_curved)
                    gm_result.position = pos
                    gm_result.rail_role = rail_role

                    # --- Save the model to the database (upsert) ---
                    # "Upsert" means: update if it exists, insert if it doesn't.
                    gm_filter = db.query(GlobalModel).filter(
                        GlobalModel.category == cat,
                        GlobalModel.position == pos,
                        GlobalModel.rail_role == rail_role,
                    )
                    if track_id:
                        gm_filter = gm_filter.filter(GlobalModel.track_id == track_id)
                    existing = gm_filter.first()

                    if existing:
                        # Update the existing model with the new coefficients
                        existing.intercept = gm_result.intercept
                        existing.slope = gm_result.slope
                        existing.curvature_coef = gm_result.curvature_coef
                        existing.r_squared = gm_result.r_squared
                        existing.wear_rate_per_month = gm_result.wear_rate_per_month
                        existing.data_points_used = gm_result.data_points_used
                        existing.chainages_contributing = gm_result.chainages_contributing
                        existing.fitted_at = datetime.now()
                        existing.upload_id = upload_id
                    else:
                        # Create a new model record
                        new_gm = GlobalModel(
                            track_id=track_id,
                            category=cat,
                            position=pos,
                            rail_role=rail_role,
                            intercept=gm_result.intercept,
                            slope=gm_result.slope,
                            curvature_coef=gm_result.curvature_coef,
                            r_squared=gm_result.r_squared,
                            wear_rate_per_month=gm_result.wear_rate_per_month,
                            data_points_used=gm_result.data_points_used,
                            chainages_contributing=gm_result.chainages_contributing,
                            upload_id=upload_id,
                        )
                        db.add(new_gm)

                    models_fitted += 1
                    results.append({
                        "category": cat, "position": pos, "rail_role": rail_role,
                        "status": gm_result.status, "r_squared": gm_result.r_squared,
                        "data_points": gm_result.data_points_used,
                        "chainages": gm_result.chainages_contributing,
                    })
                except Exception as exc:
                    logger.exception("Error fitting global model cat=%d pos=%s role=%s", cat, pos, rail_role)
                    errors.append(f"cat={cat} pos={pos} role={rail_role}: {exc}")

    # Save all model changes to the database
    db.commit()

    return {
        "models_fitted": models_fitted,
        "details": results,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# TASK 2: Per-chainage prediction using global models
# ---------------------------------------------------------------------------

def predict_chainage(chainage_id: int, db: Session) -> ChainagePrediction:
    """
    Generate per-position predictions for a single chainage using the
    global models.

    This function takes one chainage, looks up its latest measurement and
    its category, then applies the appropriate global model to predict when
    each rail position will reach the wear threshold.

    HOW IT WORKS:
    1. Look up the chainage in the database
    2. Get the most recent measurement for that chainage
    3. Extract the current wear values at each angular position
    4. Load all global models from the database
    5. Call the regression function to generate predictions

    Args:
        chainage_id: The database primary key (id) of the chainage.
        db: Database session.

    Returns:
        A ChainagePrediction object with predictions for all positions.
    """
    # Look up the chainage record
    chainage = db.query(Chainage).filter(Chainage.id == chainage_id).first()
    if chainage is None:
        return ChainagePrediction(
            chainage_id=str(chainage_id),
            status="error", message=f"Chainage id={chainage_id} not found",
        )

    # Get the most recent measurement for this chainage
    latest = (
        db.query(WearMeasurement)
        .filter(WearMeasurement.chainage_id == chainage_id)
        .order_by(WearMeasurement.measurement_date.desc())
        .first()
    )
    if latest is None:
        return ChainagePrediction(
            chainage_id=chainage.chainage_id,
            category=chainage.category,
            status="insufficient_data", message="No measurements",
        )

    # Build a dictionary of the latest wear values at each position.
    # For example: {"left_wear_45": 3.2, "right_wear_0": 1.8, ...}
    latest_meas: Dict[str, float] = {}
    for pos in POSITIONS:
        left_col, right_col = POSITION_TO_COLUMNS[pos]
        lv = getattr(latest, left_col, None)
        rv = getattr(latest, right_col, None)
        if lv is not None:
            latest_meas[left_col] = float(lv)
        if rv is not None:
            latest_meas[right_col] = float(rv)

    # Load global models for this chainage's line from the database.
    # The key is (category, position, rail_role), and the value is the model.
    gm_q = db.query(GlobalModel)
    if chainage.track_id:
        gm_q = gm_q.filter((GlobalModel.track_id == chainage.track_id) | (GlobalModel.track_id.is_(None)))
    all_gms = gm_q.all()
    gm_lookup: Dict[Tuple[int, str, str], GlobalModelResult] = {}
    for gm in all_gms:
        gmr = GlobalModelResult(
            category=gm.category,
            position=gm.position,
            rail_role=gm.rail_role,
            intercept=gm.intercept,
            slope=gm.slope,
            curvature_coef=gm.curvature_coef,
            r_squared=gm.r_squared,
            wear_rate_per_month=gm.wear_rate_per_month,
            data_points_used=gm.data_points_used or 0,
            chainages_contributing=gm.chainages_contributing or 0,
            status="ok" if gm.slope is not None else "insufficient_data",
        )
        gm_lookup[(gm.category, gm.position, gm.rail_role)] = gmr

    # Call the regression function to generate predictions using the
    # global models and the latest measurement values
    return predict_chainage_from_models(
        chainage_id=chainage.chainage_id,
        category=chainage.category,
        curve_direction=chainage.curve_direction,
        curve_radius=chainage.curve_radius,
        latest_measurements=latest_meas,
        last_date=latest.measurement_date,
        global_models=gm_lookup,
    )


# ---------------------------------------------------------------------------
# TASK 3: Refit after upload — fits global models then refreshes predictions
# ---------------------------------------------------------------------------

def refit_after_upload(
    upload_id: int,
    affected_chainage_ids: List[int],
    db: Session,
) -> Dict:
    """
    Refit global models and regenerate predictions after new data is uploaded.

    This is called automatically after every measurement upload. It ensures
    that the prediction models stay up-to-date as new data arrives.

    HOW IT WORKS:
    1. Find out which categories are affected by the new data
    2. Refit the global models for those categories (since the pooled data
       has changed)
    3. Re-predict ALL chainages in those categories (not just the ones that
       got new data, because the global model changed for everyone)
    4. Save prediction snapshots to the PredictionLog table

    Args:
        upload_id: The upload that triggered this refit (0 for deletions).
        affected_chainage_ids: Database IDs of chainages that got new data.
        db: Database session.

    Returns:
        A summary dict with: models_fitted, predictions_updated, details, errors.
    """
    # Step 1: Figure out which categories and track are affected
    affected_cats: Set[int] = set()
    affected_track_id = None
    for cid in affected_chainage_ids:
        ch = db.query(Chainage).filter(Chainage.id == cid).first()
        if ch and ch.category:
            affected_cats.add(ch.category)
            if affected_track_id is None:
                affected_track_id = ch.track_id

    # If none of the affected chainages have a category, nothing to do
    if not affected_cats:
        return {"models_fitted": 0, "predictions_updated": 0}

    # Step 2: Refit global models for the affected categories on this line
    fit_result = fit_global_models(db, categories=affected_cats, upload_id=upload_id, track_id=affected_track_id)

    # Step 3: Re-predict ALL chainages in the affected categories on this line.
    # We do all chainages (not just the uploaded ones) because the global
    # model has changed, which affects predictions for every chainage in
    # that category.
    ch_q = db.query(Chainage).filter(Chainage.category.in_(list(affected_cats)))
    if affected_track_id:
        ch_q = ch_q.filter(Chainage.track_id == affected_track_id)
    all_chainages = ch_q.all()

    predictions_updated = 0
    pred_errors: List[str] = []

    for ch in all_chainages:
        try:
            # Generate a new prediction for this chainage
            pred = predict_chainage(ch.id, db)

            # Only save predictions that produced a result
            if pred.status in ("ok", "already_exceeded"):
                # Determine the human-readable model type name
                model_type = CATEGORY_MODEL_TYPES.get(ch.category, "unknown")

                # Save a snapshot of this prediction to the PredictionLog table.
                # This creates a historical record that we can review later.
                log_entry = PredictionLog(
                    chainage_id=ch.id,
                    model_type=model_type,
                    category=ch.category,
                    slope=None,  # Global model coefficients are stored in the GlobalModel table
                    intercept=None,
                    r_squared=None,
                    wear_rate_per_month=None,
                    current_wear_mm=pred.current_wear_mm,
                    predicted_repair_date=pred.predicted_repair_date,
                    days_until_threshold=pred.days_until_threshold,
                    data_points_used=None,
                    upload_id=upload_id,
                    position=pred.earliest_position,
                    rail_role=pred.earliest_rail_role,
                    physical_side=pred.earliest_physical_side,
                )
                db.add(log_entry)
                predictions_updated += 1

        except Exception as exc:
            logger.exception("Error predicting chainage %d", ch.id)
            pred_errors.append(f"chainage_id={ch.id}: {exc}")

    # Save all prediction logs to the database
    if predictions_updated > 0:
        db.commit()

    return {
        "models_fitted": fit_result.get("models_fitted", 0),
        "predictions_updated": predictions_updated,
        "model_details": fit_result.get("details", []),
        "errors": fit_result.get("errors", []) + pred_errors,
    }


# ---------------------------------------------------------------------------
# Internal helper functions
# ---------------------------------------------------------------------------

def _find_index_for_date(measurements: List[dict], target_date: date) -> Optional[int]:
    """
    Find the index of the first measurement at or after a target date.

    This is used when merging manually logged replacements with the
    measurement history. We need to find where in the measurement list
    the replacement date falls.

    Args:
        measurements: List of measurement dicts, sorted by date.
        target_date: The date to search for.

    Returns:
        The index of the first measurement at or after the target date,
        or None if no such measurement exists.
    """
    for i, m in enumerate(measurements):
        if m["measurement_date"] >= target_date:
            return i
    return None
