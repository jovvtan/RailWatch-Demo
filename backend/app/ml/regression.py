"""Global regression models for rail wear prediction.

Fits 25 global models across all chainages:
- Standard Straight (cat 1): 5 models (one per position, rail_role="both")
- Standard Curve (cat 2): 10 models (5 positions × inner/outer rail)
- Premium Curve (cat 3): 10 models (5 positions × inner/outer rail)

Each model pools data from ALL chainages of that category.  For curved track,
the curve direction (left/right) determines which physical rail is inner vs
outer.  The global coefficients are then applied to each individual chainage
and position to predict when that position hits the 7mm threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Dict, Tuple

import numpy as np
from sklearn.linear_model import LinearRegression

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPAIR_THRESHOLD_MM: float = 7.0
MAX_PREDICTION_DAYS: int = 3650  # 10-year cap

POSITIONS: List[str] = ["0", "22.5", "45", "67.5", "90"]

# Maps position string to WearMeasurement column names
POSITION_TO_COLUMNS: Dict[str, Tuple[str, str]] = {
    "0":    ("left_wear_0",    "right_wear_0"),
    "22.5": ("left_wear_22_5", "right_wear_22_5"),
    "45":   ("left_wear_45",   "right_wear_45"),
    "67.5": ("left_wear_67_5", "right_wear_67_5"),
    "90":   ("left_wear_90",   "right_wear_90"),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class GlobalModelResult:
    """Result of fitting a single global model."""
    category: int
    position: str
    rail_role: str  # "both", "inner", "outer"
    intercept: Optional[float] = None
    slope: Optional[float] = None
    curvature_coef: Optional[float] = None
    r_squared: Optional[float] = None
    wear_rate_per_month: Optional[float] = None
    data_points_used: int = 0
    chainages_contributing: int = 0
    status: str = "ok"
    message: str = ""


@dataclass
class PositionPrediction:
    """Prediction for a single position on a single chainage."""
    position: str           # "0", "22.5", "45", "67.5", "90"
    rail_role: str          # "both", "inner", "outer"
    physical_side: str      # "left" or "right"
    current_wear_mm: Optional[float] = None
    wear_rate_per_month: Optional[float] = None
    days_until_threshold: Optional[int] = None
    predicted_repair_date: Optional[date] = None
    r_squared: Optional[float] = None
    status: str = "ok"
    message: str = ""
    projection_data: List[dict] = field(default_factory=list)
    confidence_band: List[dict] = field(default_factory=list)


@dataclass
class ChainagePrediction:
    """Complete prediction for a chainage across all positions."""
    chainage_id: str
    category: Optional[int] = None
    curve_direction: Optional[str] = None
    curve_radius: Optional[float] = None
    position_predictions: List[PositionPrediction] = field(default_factory=list)
    earliest_position: Optional[str] = None
    earliest_rail_role: Optional[str] = None
    earliest_physical_side: Optional[str] = None
    days_until_threshold: Optional[int] = None
    predicted_repair_date: Optional[date] = None
    current_wear_mm: Optional[float] = None
    status: str = "ok"
    message: str = ""


# ---------------------------------------------------------------------------
# Recency weighting (unchanged)
# ---------------------------------------------------------------------------
def calculate_recency_weights(
    dates: List[date], reference_date: date
) -> np.ndarray:
    """Calculate sample weights giving more importance to recent measurements.

    Tiers: 0-6mo=1.0, 6-12mo=0.8, 12-24mo=0.5, >24mo=0.3.
    """
    weights: List[float] = []
    for d in dates:
        age_months = (reference_date - d).days / 30.44
        if age_months <= 6:
            weights.append(1.0)
        elif age_months <= 12:
            weights.append(0.8)
        elif age_months <= 24:
            weights.append(0.5)
        else:
            weights.append(0.3)
    return np.array(weights, dtype=float)


# ---------------------------------------------------------------------------
# Replacement detection (unchanged)
# ---------------------------------------------------------------------------
def detect_replacements(measurements: List[dict]) -> List[dict]:
    """Detect replacement events from sudden wear drops."""
    replacements: List[dict] = []
    for i in range(1, len(measurements)):
        prev_wear = measurements[i - 1]["wear_mm"]
        cur_wear = measurements[i]["wear_mm"]
        if cur_wear == 0 or (prev_wear - cur_wear) > 2.0:
            replacements.append({
                "index": i,
                "date": measurements[i]["measurement_date"],
                "prev_wear": prev_wear,
                "new_wear": cur_wear,
            })
    return replacements


def segment_measurements_by_replacement(
    measurements: List[dict], replacements: List[dict]
) -> List[List[dict]]:
    """Split measurements at replacement points, return list of segments."""
    if not replacements:
        return [measurements]
    segments: List[List[dict]] = []
    prev_idx = 0
    for rep in replacements:
        idx = rep["index"]
        if prev_idx < idx:
            segments.append(measurements[prev_idx:idx])
        prev_idx = idx
    if prev_idx < len(measurements):
        segments.append(measurements[prev_idx:])
    return segments


# ---------------------------------------------------------------------------
# Inner/outer rail mapping
# ---------------------------------------------------------------------------
def map_rail_role(physical_side: str, curve_direction: Optional[str]) -> str:
    """Map a physical rail side to its role given the curve direction.

    Args:
        physical_side: "left" or "right".
        curve_direction: "left", "right", or None (straight).

    Returns:
        "both" for straight, "inner" or "outer" for curved.
    """
    if not curve_direction:
        return "both"
    if curve_direction == "right":
        return "outer" if physical_side == "left" else "inner"
    else:  # curve_direction == "left"
        return "outer" if physical_side == "right" else "inner"


def map_role_to_physical(rail_role: str, curve_direction: Optional[str]) -> str:
    """Reverse map: given a rail role and curve direction, return physical side.

    For straight track (rail_role="both"), returns "left" by convention.
    """
    if rail_role == "both" or not curve_direction:
        return "left"  # convention for straight
    if curve_direction == "right":
        return "left" if rail_role == "outer" else "right"
    else:
        return "right" if rail_role == "outer" else "left"


# ---------------------------------------------------------------------------
# Global model fitting
# ---------------------------------------------------------------------------
def fit_single_global_model(
    data_points: List[dict],
    category: int,
    is_curved: bool,
) -> GlobalModelResult:
    """Fit a single global regression model from pooled data points.

    Each data point is a dict with keys:
        - "elapsed_days": float (days since that chainage's first measurement)
        - "wear_mm": float (absolute wear value)
        - "date": date (measurement date)
        - "curve_radius": float (only used for curved models)

    For straight (cat 1): wear(t) = β₀ + β₁t
    For curved (cat 2/3): wear(t) = β₀ + β₁t + β₂(t/R)
    """
    result = GlobalModelResult(
        category=category,
        position="",  # set by caller
        rail_role="",  # set by caller
    )

    if len(data_points) < 2:
        result.status = "insufficient_data"
        result.message = f"Need ≥2 data points, got {len(data_points)}"
        result.data_points_used = len(data_points)
        return result

    t = np.array([dp["elapsed_days"] for dp in data_points], dtype=float)
    y = np.array([dp["wear_mm"] for dp in data_points], dtype=float)
    dates = [dp["date"] for dp in data_points]
    ref_date = max(dates)
    weights = calculate_recency_weights(dates, ref_date)

    if is_curved:
        radii = np.array([dp["curve_radius"] for dp in data_points], dtype=float)
        # Filter out invalid radii (zero, negative, NaN, inf)
        valid = np.isfinite(radii) & (radii > 0)
        if valid.sum() < 2:
            result.status = "insufficient_data"
            result.message = "Not enough data points with valid curve radius"
            return result
        t, y, weights, radii = t[valid], y[valid], weights[valid], radii[valid]
        X = np.column_stack([t, t / radii])
    else:
        X = t.reshape(-1, 1)

    model = LinearRegression()
    model.fit(X, y, sample_weight=weights)
    r2 = float(model.score(X, y, sample_weight=weights))

    coefs = model.coef_
    slope_val = float(coefs[0]) if len(coefs) >= 1 else 0.0
    curv_val = float(coefs[1]) if len(coefs) >= 2 else None

    # If curved model produces a negative slope, fall back to simple linear (no curvature term)
    # This happens when there's insufficient data for the curvature term to be stable
    if is_curved and slope_val <= 0:
        X_simple = t.reshape(-1, 1)
        model_simple = LinearRegression()
        model_simple.fit(X_simple, y, sample_weight=weights)
        r2 = float(model_simple.score(X_simple, y, sample_weight=weights))
        slope_val = float(model_simple.coef_[0])
        curv_val = None  # no curvature term
        result.intercept = float(model_simple.intercept_)
        result.message = "Fallback to linear (curvature term unstable)"
    else:
        result.intercept = float(model.intercept_)

    result.slope = slope_val
    result.curvature_coef = curv_val
    result.r_squared = r2
    result.wear_rate_per_month = result.slope * 30.44
    result.data_points_used = len(t)
    result.chainages_contributing = len(set(dp.get("chainage_id", "") for dp in data_points))
    result.status = "ok"
    return result


# ---------------------------------------------------------------------------
# Per-chainage prediction using global model coefficients
# ---------------------------------------------------------------------------
def predict_position(
    current_wear: float,
    last_date: date,
    model: GlobalModelResult,
    curve_radius: Optional[float] = None,
) -> PositionPrediction:
    """Apply a global model to a single chainage position to predict threshold crossing.

    Args:
        current_wear: Latest measured wear (mm) at this position.
        last_date: Date of the latest measurement.
        model: The global model for this (category, position, rail_role).
        curve_radius: The chainage's curve radius (for curved models).

    Returns:
        A PositionPrediction with days to threshold and projection data.
    """
    pred = PositionPrediction(
        position=model.position,
        rail_role=model.rail_role,
        physical_side="",  # set by caller
        current_wear_mm=current_wear,
        r_squared=model.r_squared,
    )

    if model.status != "ok" or model.slope is None:
        pred.status = "no_model"
        pred.message = "No fitted model available for this category/position"
        return pred

    # Calculate effective slope
    if model.curvature_coef is not None and curve_radius and curve_radius > 0:
        effective_slope = model.slope + model.curvature_coef / curve_radius
    else:
        effective_slope = model.slope

    pred.wear_rate_per_month = effective_slope * 30.44

    if current_wear >= REPAIR_THRESHOLD_MM:
        pred.status = "already_exceeded"
        pred.message = f"Current wear {current_wear:.2f}mm exceeds threshold"
        pred.days_until_threshold = 0
        pred.predicted_repair_date = last_date
        return pred

    if effective_slope <= 0:
        pred.status = "wear_decreasing"
        pred.message = "Wear rate is non-positive"
        # Still build projection so the chart has something to show
        proj_end = 2 * 365  # project 2 years out
        t_vals = np.linspace(0, proj_end, 20)
        pred.projection_data = [{
            "date": (last_date + timedelta(days=int(round(tv)))).isoformat(),
            "days": int(round(tv)),
            "predicted_wear_mm": round(current_wear + effective_slope * tv, 3),
        } for tv in t_vals]
        return pred

    # days = (threshold - current_wear) / rate (effective_slope guaranteed > 0 here)
    if effective_slope <= 0:
        effective_slope = 0.0001  # safety net — should never reach here
    days_remaining = (REPAIR_THRESHOLD_MM - current_wear) / effective_slope
    capped = days_remaining > float(MAX_PREDICTION_DAYS)
    days_remaining = min(days_remaining, float(MAX_PREDICTION_DAYS))
    days_remaining = max(days_remaining, 0.0)
    days_int = int(round(days_remaining))

    pred.days_until_threshold = days_int
    pred.predicted_repair_date = last_date + timedelta(days=days_int)
    if capped:
        pred.message = f">{MAX_PREDICTION_DAYS} days (beyond prediction horizon)"

    # Build projection data (~20 points from now to threshold + buffer)
    proj_end = max(days_int, 365)
    proj_end = min(proj_end, 5 * 365)
    t_vals = np.linspace(0, proj_end, 20)
    projection = []
    for tv in t_vals:
        d = last_date + timedelta(days=int(round(tv)))
        projected_wear = current_wear + effective_slope * tv
        projection.append({
            "date": d.isoformat(),
            "days": int(round(tv)),
            "predicted_wear_mm": round(projected_wear, 3),
        })
    pred.projection_data = projection

    # Confidence band (±30% heuristic or SE-based if we had residuals)
    ci_days = max(int(round(days_remaining * 0.3)), 30) if days_remaining > 0 else 30
    band = []
    for pt in projection:
        wear = pt["predicted_wear_mm"]
        frac = pt["days"] / proj_end if proj_end > 0 else 0
        delta = ci_days * effective_slope * frac
        band.append({
            "date": pt["date"],
            "days": pt["days"],
            "lower_mm": round(wear - delta, 3),
            "upper_mm": round(wear + delta, 3),
        })
    pred.confidence_band = band

    pred.status = "ok"
    pred.message = f"Threshold in {days_int} days ({pred.predicted_repair_date})"
    return pred


def predict_chainage_from_models(
    chainage_id: str,
    category: Optional[int],
    curve_direction: Optional[str],
    curve_radius: Optional[float],
    latest_measurements: Dict[str, float],
    last_date: date,
    global_models: Dict[Tuple[int, str, str], GlobalModelResult],
) -> ChainagePrediction:
    """Apply global models to predict all positions for a single chainage.

    Args:
        chainage_id: The chainage string ID.
        category: Track category (1, 2, 3).
        curve_direction: "left", "right", or None.
        curve_radius: Curve radius in metres.
        latest_measurements: Dict mapping column names (e.g. "left_wear_90")
            to their latest wear values.
        last_date: Date of the latest measurement.
        global_models: Dict keyed by (category, position, rail_role) → GlobalModelResult.

    Returns:
        A ChainagePrediction with per-position predictions.
    """
    pred = ChainagePrediction(
        chainage_id=chainage_id,
        category=category,
        curve_direction=curve_direction,
        curve_radius=curve_radius,
    )

    if category is None:
        pred.status = "no_category"
        pred.message = "Chainage has no category assigned"
        return pred

    is_straight = (category == 1)
    position_preds: List[PositionPrediction] = []

    for pos in POSITIONS:
        left_col, right_col = POSITION_TO_COLUMNS[pos]

        # For each physical side (left, right), determine rail role and get wear
        for phys_side, col_name in [("left", left_col), ("right", right_col)]:
            wear_val = latest_measurements.get(col_name)
            if wear_val is None:
                continue  # No data for this position/side

            wear_val = abs(wear_val)
            rail_role = map_rail_role(phys_side, curve_direction) if not is_straight else "both"

            # Look up the global model
            model_key = (category, pos, rail_role)
            gm = global_models.get(model_key)

            if gm is None:
                pp = PositionPrediction(
                    position=pos, rail_role=rail_role, physical_side=phys_side,
                    current_wear_mm=wear_val,
                    status="no_model",
                    message=f"No global model for cat={category}, pos={pos}, role={rail_role}",
                )
                position_preds.append(pp)
                continue

            pp = predict_position(wear_val, last_date, gm, curve_radius)
            pp.physical_side = phys_side
            position_preds.append(pp)

    pred.position_predictions = position_preds

    # Find the overall max current wear
    non_null_wears = [pp.current_wear_mm for pp in position_preds if pp.current_wear_mm is not None]
    pred.current_wear_mm = max(non_null_wears) if non_null_wears else None

    # Find earliest position to hit threshold
    ok_preds = [pp for pp in position_preds if pp.status == "ok" and pp.days_until_threshold is not None]
    exceeded = [pp for pp in position_preds if pp.status == "already_exceeded"]

    if exceeded:
        worst = min(exceeded, key=lambda p: p.current_wear_mm or 0, default=None)
        if worst:
            pred.earliest_position = worst.position
            pred.earliest_rail_role = worst.rail_role
            pred.earliest_physical_side = worst.physical_side
            pred.days_until_threshold = 0
            pred.predicted_repair_date = last_date
            pred.status = "already_exceeded"
            pred.message = f"Position {worst.position} ({worst.physical_side}) already at {worst.current_wear_mm:.2f}mm"
    elif ok_preds:
        earliest = min(ok_preds, key=lambda p: p.days_until_threshold)
        pred.earliest_position = earliest.position
        pred.earliest_rail_role = earliest.rail_role
        pred.earliest_physical_side = earliest.physical_side
        pred.days_until_threshold = earliest.days_until_threshold
        pred.predicted_repair_date = earliest.predicted_repair_date
        pred.status = "ok"
        pred.message = (
            f"Position {earliest.position} ({earliest.physical_side}) "
            f"hits threshold in {earliest.days_until_threshold} days"
        )
    else:
        decreasing = [pp for pp in position_preds if pp.status == "wear_decreasing"]
        no_model = [pp for pp in position_preds if pp.status == "no_model"]
        if decreasing:
            pred.status = "wear_decreasing"
            pred.message = "All positions show stable or decreasing wear"
        elif no_model and len(no_model) == len(position_preds):
            pred.status = "no_model"
            pred.message = "No global models available for this category"
        else:
            pred.status = "insufficient_data"
            pred.message = "No positions with valid predictions"

    return pred
