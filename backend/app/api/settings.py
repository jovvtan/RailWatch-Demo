"""
settings.py — Model Coefficients and System Configuration
==========================================================
This file provides endpoints that return information about the mathematical
models used to predict rail wear, as well as general system configuration.

HOW IT WORKS (plain English):
- The RailWatch system uses regression models to predict how quickly rail
  sections will wear down over time.
- There are 3 categories of track, each with its own model:
    Category 1: Straight track with standard rail (simple linear model)
    Category 2: Curved track with standard rail (includes curvature effect)
    Category 3: Curved track with premium/harder rail (same formula as Cat 2
                 but with different coefficients because premium rail wears slower)
- The "GET /models" endpoint returns the current model coefficients (the numbers
  that define each prediction formula), so engineers can see what the system
  is using behind the scenes.
- The "GET /config" endpoint returns fixed system settings like wear zone
  thresholds (e.g., "above 7mm is urgent") and prediction parameters.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.track import Track, Chainage
from app.models.prediction import PredictionLog
from app.models.global_model import GlobalModel

router = APIRouter()

# ---------------------------------------------------------------------------
# Category metadata — describes the mathematical model for each category
# ---------------------------------------------------------------------------
# This dictionary holds human-readable descriptions of each track category's
# prediction model. It explains the formula, what each variable means, and
# why the model is shaped the way it is. This metadata is sent to the frontend
# so it can display explanatory text alongside the numbers.
CATEGORY_META = {
    # ── Category 1: Straight Track (Standard Rail) ─────────────────────────
    # Uses a simple straight-line formula: wear increases at a constant rate.
    # No curvature factor because the track is straight.
    1: {
        "name": "Straight Track (Standard Rail)",
        "formula": "wear(t) = β₀ + β₁t",
        "description": (
            "Linear regression model for straight-track standard-rail chainages. "
            "Wear is modelled as a function of elapsed time only."
        ),
        "variables": {
            "β₀": "Intercept — baseline wear (mm) at t=0",
            "β₁": "Slope — wear rate per day",
            "t": "Elapsed time in days since installation / last grind",
        },
    },
    # ── Category 2: Curved Track (Standard Rail) ──────────────────────────
    # Adds a curvature term: tighter curves (smaller radius R) cause faster
    # wear because trains push harder against the outer rail on sharp bends.
    2: {
        "name": "Curved Track (Standard Rail)",
        "formula": "wear(t) = β₀ + β₁t + β₂(t/R)",
        "description": (
            "Curvature-adjusted model for standard rail on curved track. "
            "Tighter curves (smaller R) cause faster wear due to increased lateral force on the gauge face. "
            "The effective slope incorporates the curvature effect."
        ),
        "variables": {
            "β₀": "Intercept — baseline wear (mm) at t=0",
            "β₁": "Base wear rate (mm per day)",
            "β₂": "Curvature wear coefficient — amplifies wear for tighter curves",
            "R": "Curve radius (metres)",
            "t": "Elapsed time in days since installation / last grind",
        },
    },
    # ── Category 3: Curved Track (Premium Rail) ───────────────────────────
    # Same formula as Category 2, but trained on premium (head-hardened) rail
    # data. Premium rail is harder and wears more slowly on curves, so the
    # curvature coefficient (β₂) is typically smaller than Category 2.
    3: {
        "name": "Curved Track (Premium Rail)",
        "formula": "wear(t) = β₀ + β₁t + β₂(t/R)",
        "description": (
            "Same curvature-adjusted model as Category 2, but fitted separately on premium "
            "(head-hardened) rail data. Premium rail produces a lower β₂ coefficient, "
            "meaning slower lateral wear on curves compared to standard rail."
        ),
        "variables": {
            "β₀": "Intercept — baseline wear (mm) at t=0",
            "β₁": "Base wear rate (mm per day)",
            "β₂": "Curvature wear coefficient — lower than Category 2 due to harder rail",
            "R": "Curve radius (metres)",
            "t": "Elapsed time in days since installation / last grind",
        },
    },
}


# ---------------------------------------------------------------------------
# GET /api/settings/models
# ---------------------------------------------------------------------------
# This endpoint returns the actual numbers (coefficients) that the prediction
# models are currently using, along with metadata about each model.
# Engineers can use this to understand what the system "thinks" the wear rate
# is for each type of track.
@router.get("/models")
def get_model_settings(line: str = "NEL", db: Session = Depends(get_db)):
    """Return the 25 globally-fitted model coefficients, grouped by category.

    Each category contains models for each angular position (0, 22.5, 45,
    67.5, 90) and for curved categories, separate inner/outer rail models.

    Returns:
        A dict with ``last_updated``, threshold, recency weights, and a
        ``categories`` list with nested ``models`` arrays.
    """

    # ── Step 1: Resolve the track for the requested line ────────────────────
    # Look up the track record for the requested line (e.g. "NEL" or "DTL").
    track = db.query(Track).filter(Track.track_id == line.upper()).first()
    track_db_id = track.id if track else None

    # ── Step 2: Load global models for this line from the database ────────
    # Global models are the system-wide prediction formulas. There is one model
    # per combination of (track, category, measurement position, rail role).
    # They are sorted so the output is always in a predictable order.
    q = db.query(GlobalModel).order_by(
        GlobalModel.category, GlobalModel.position, GlobalModel.rail_role
    )
    if track_db_id:
        q = q.filter((GlobalModel.track_id == track_db_id) | (GlobalModel.track_id.is_(None)))
    all_gms = q.all()

    # ── Step 3: Group the models by category (1, 2, or 3) ─────────────────
    # Also track the most recent "fitted_at" date across all models,
    # so we can report when the models were last updated.
    by_cat: dict[int, list[GlobalModel]] = {}
    last_fitted = None  # Will hold the date the models were last recalculated
    for gm in all_gms:
        # Add this model to its category's list
        by_cat.setdefault(gm.category, []).append(gm)
        # Keep track of the newest fitted_at date across all models
        if gm.fitted_at and (last_fitted is None or gm.fitted_at > last_fitted):
            last_fitted = gm.fitted_at

    # ── Step 4: Count how many chainages exist in each category ────────────
    # This tells engineers how many track sections each model covers.
    # Filtered by the selected line so counts match the models shown.
    total_by_cat: dict[int, int] = {}
    ch_q = db.query(Chainage.category, func.count(Chainage.id)).group_by(Chainage.category)
    if track_db_id:
        ch_q = ch_q.filter(Chainage.track_id == track_db_id)
    for row in ch_q.all():
        # row[0] = category number, row[1] = count of chainages in that category
        # Default to category 1 if a chainage has no category set
        cat = row[0] or 1
        total_by_cat[cat] = total_by_cat.get(cat, 0) + row[1]

    # ── Step 5: Build the response for each category ───────────────────────
    categories = []
    for cat_id in sorted(CATEGORY_META.keys()):  # Loop through categories 1, 2, 3
        meta = CATEGORY_META[cat_id]  # Get the human-readable metadata
        gms = by_cat.get(cat_id, [])  # Get the models for this category

        # Build a list of model details for this category
        models_list = []
        for gm in gms:
            models_list.append({
                # The angular position on the rail head (0°, 22.5°, 45°, 67.5°, or 90°)
                "position": gm.position,
                # Whether this model is for the inner or outer rail (for curved tracks)
                "rail_role": gm.rail_role,
                # β₀ — the starting wear value when time = 0
                "beta_0": gm.intercept,
                # β₁ — how many mm of wear per day
                "beta_1": gm.slope,
                # β₂ — the curvature effect (only meaningful for curved tracks, categories 2 & 3)
                "beta_2": gm.curvature_coef,
                # The wear rate converted to mm per month (easier for engineers to interpret)
                "beta_1_per_month": gm.wear_rate_per_month,
                # R² — how well the model fits the data (1.0 = perfect, 0.0 = no fit)
                "r_squared": gm.r_squared,
                # How many individual measurement data points were used to train this model
                "data_points": gm.data_points_used,
                # How many different chainages contributed data to this model
                "chainages_contributing": gm.chainages_contributing,
                # When this particular model was last recalculated
                "last_fitted": str(gm.fitted_at)[:10] if gm.fitted_at else None,
            })

        # Combine the metadata and model data for this category
        categories.append({
            "category": cat_id,
            "name": meta["name"],            # e.g. "Straight Track (Standard Rail)"
            "formula": meta["formula"],       # e.g. "wear(t) = β₀ + β₁t"
            "description": meta["description"],
            "variables": meta["variables"],   # Explanation of each variable
            "total_chainages": total_by_cat.get(cat_id, 0),  # How many sections use this model
            "models_count": len(gms),         # How many sub-models (positions x rail roles)
            "models": models_list,            # The actual coefficient data
        })

    # ── Step 6: Return the complete response ───────────────────────────────
    return {
        # When the models were last recalculated (date only, no time)
        "last_updated": str(last_fitted)[:10] if last_fitted else None,

        # Recency weights control how much importance is given to older data.
        # Recent measurements (0–6 months old) get full weight (1.0).
        # Older data is down-weighted so predictions rely more on fresh readings.
        "recency_weights": {
            "0_to_6_months": 1.0,    # Full weight for recent data
            "6_to_12_months": 0.8,   # Slightly reduced
            "12_to_24_months": 0.5,  # Half weight
            "over_24_months": 0.3,   # Low weight for very old data
        },

        # The wear threshold in millimetres — above this value, a rail section
        # is considered to need maintenance (maps to SC2/SC1 zones).
        "threshold_mm": 7.0,

        # Total number of global models across all categories
        "total_global_models": len(all_gms),

        # The per-category breakdown with all model coefficients
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# GET /api/settings/config
# ---------------------------------------------------------------------------
# This endpoint returns the fixed system configuration — the rules and
# thresholds that the application uses. These values don't change at runtime;
# they are built into the system.
@router.get("/config")
def get_config():
    """Return static application configuration values.

    Returns:
        A dict containing wear zone definitions, prediction parameters,
        maintenance thresholds, and application metadata.
    """
    return {
        # The wear value (in mm) above which a rail is flagged for maintenance
        "wear_threshold_mm": 7.0,

        # Wear zone definitions — these map wear values to severity levels.
        # Each zone has a label, a min/max range (in mm), and a display colour.
        # SC5 is the healthiest; SC1 is the most critical.
        "wear_zones": {
            "SC5": {"label": "SC5 - Acceptable", "min": 0, "max": 4, "color": "green"},      # 0–4 mm: no action needed
            "SC4": {"label": "SC4 - Monitor", "min": 4, "max": 6, "color": "orange"},         # 4–6 mm: keep an eye on it
            "SC3": {"label": "SC3 - Plan Repair", "min": 6, "max": 7, "color": "red"},        # 6–7 mm: schedule maintenance
            "SC2": {"label": "SC2 - Urgent", "min": 7, "max": 8, "color": "red"},             # 7–8 mm: urgent action required
            "SC1": {"label": "SC1 - Critical", "min": 8, "max": None, "color": "darkred"},    # 8+ mm: immediate action
        },

        # Settings that control how wear predictions are calculated
        "prediction_settings": {
            "max_projection_years": 10,       # Don't predict more than 10 years into the future
            "confidence_level": 0.95,         # 95% confidence interval on predictions
            "minimum_data_points": 2,         # Need at least 2 measurements to make a prediction
            # Recency weights — same as in the /models endpoint (see above for explanation)
            "recency_weights": {
                "0_to_6_months": 1.0,
                "6_to_12_months": 0.8,
                "12_to_24_months": 0.5,
                "over_24_months": 0.3,
            },
        },

        # Thresholds for flagging upcoming maintenance needs
        "maintenance_thresholds": {
            "critical_days": 60,   # If a rail will hit the wear limit within 60 days, it's critical
            "warning_days": 180,   # If within 180 days (6 months), show a warning
        },

        # Basic information about the application itself
        "app_info": {
            "version": "1.0.0",
            "name": "RailWatch",
            "description": "Rail Wear Monitoring & Prediction System",
        },
    }


# ---------------------------------------------------------------------------
# PUT /api/settings/config
# ---------------------------------------------------------------------------
# This endpoint is a placeholder for a future feature that would allow
# updating the configuration through the web interface.
# Right now it just returns a "not implemented" response.
@router.put("/config")
def update_config():
    """Stub — config updates not yet implemented.

    Returns:
        A 501 response indicating the feature is planned but not available.
    """
    # Return HTTP 501 (Not Implemented) to indicate this feature is not ready yet
    return Response(
        content='{"detail": "Config updates not yet implemented"}',
        status_code=501,
        media_type="application/json",
    )
