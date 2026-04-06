"""
PredictionLog database table.

FILE PURPOSE:
    This file defines the database table that stores prediction snapshots.
    Each time the system calculates a prediction for a chainage (i.e. "when
    will this rail need maintenance?"), a row is saved here.

    Predictions are point-in-time snapshots — they capture what the system
    predicted at that moment, along with the data and model that were used.
    This is important because:

    1. Predictions change over time as new measurement data arrives.
    2. We want to track prediction accuracy — later, when the rail actually
       gets replaced, we can compare the predicted date with the actual date
       to see how accurate the model was.

    Each prediction records:
    - Which chainage the prediction is for
    - Which model was used (linear, weighted, polynomial)
    - The model coefficients (slope, intercept) — these describe the wear trend
    - The predicted repair date (when wear will reach the threshold)
    - The current wear level at the time of prediction
    - How many data points were used to make the prediction

    In simple terms: this is the "what did the system predict and when" table.
"""

# --- Library imports ---
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Base class that all database table definitions must inherit from
from app.database import Base


class PredictionLog(Base):
    """
    DATABASE TABLE: prediction_logs

    A point-in-time prediction snapshot for a single chainage. Stores the
    predicted maintenance date and the model parameters that produced it.

    Key fields for engineers:
    - predicted_repair_date: when the system expects this rail to need work
    - days_until_threshold: how many days until the wear limit is reached
    - current_wear_mm: the most recent wear measurement at prediction time
    - wear_rate_per_month: how fast the rail is wearing (mm per month)

    In simple terms: this is the "forecast history" table.
    """

    # This tells the database to name this table "prediction_logs"
    __tablename__ = "prediction_logs"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Links this prediction to the chainage it's about.
    # This is a foreign key referencing the "id" column in the "chainages" table.
    chainage_id = Column(Integer, ForeignKey("chainages.id"), nullable=False)

    # When this prediction was generated
    predicted_at = Column(DateTime, default=func.now())

    # The type of regression model used for this prediction:
    # "linear" = simple straight-line fit
    # "linear_weighted" = straight-line fit that gives more importance to recent data
    # "poly2" = curved (quadratic) fit for non-linear wear patterns
    model_type = Column(String, nullable=False)         # "linear", "linear_weighted", "poly2"

    # The track category at the time of prediction (1, 2, or 3).
    # This is saved because the category could change later, and we want
    # to know what category was used when this prediction was made.
    category = Column(Integer, nullable=True)           # 1, 2, or 3 at time of prediction

    # --- Model coefficients ---
    # These numbers describe the mathematical trend line fitted to the data.

    # "slope" is the wear rate per day — how many mm of wear per day.
    # A higher slope means faster wear.
    slope = Column(Float, nullable=True)

    # "intercept" is the baseline wear level (the y-intercept of the trend line).
    # This is the predicted wear at day zero (the start of the measurement period).
    intercept = Column(Float, nullable=True)

    # "r_squared" is a measure of how well the trend line fits the data.
    # Ranges from 0 to 1. Higher is better (1.0 = perfect fit).
    r_squared = Column(Float, nullable=True)

    # The monthly wear rate, calculated as slope * 30.44 (average days per month).
    # This is easier for engineers to understand than a daily rate.
    wear_rate_per_month = Column(Float, nullable=True)

    # --- Per-position detail (used by the global model system) ---

    # Which angular position this prediction is for: "0", "22.5", "45",
    # "67.5", or "90". NULL means this is an overall (combined) prediction.
    position = Column(String, nullable=True)          # "0", "22.5", etc. (NULL = overall min)

    # Whether this prediction is for "both" rails (straight track), the
    # "inner" rail, or the "outer" rail (curved track).
    rail_role = Column(String, nullable=True)         # "both", "inner", "outer"

    # The physical rail side: "left" or "right". This is determined by
    # combining the rail_role (inner/outer) with the curve direction.
    physical_side = Column(String, nullable=True)     # "left", "right" (mapped from rail_role + curve_dir)

    # Links to the global model that was used for this prediction (if any)
    global_model_id = Column(Integer, ForeignKey("global_models.id"), nullable=True)

    # --- Prediction outputs ---
    # These are the actual results that engineers care about.

    # The current wear level at the time of prediction (in mm)
    current_wear_mm = Column(Float, nullable=True)

    # The date when the system predicts wear will reach the maintenance
    # threshold (typically 8mm). This is the key output of the system.
    predicted_repair_date = Column(Date, nullable=True)

    # How many days from now until the threshold is reached.
    # Negative means the threshold has already been exceeded.
    days_until_threshold = Column(Integer, nullable=True)

    # Confidence interval bounds: the prediction has some uncertainty.
    # These give a range (e.g. "between 100 and 200 days until threshold").
    confidence_lower_days = Column(Integer, nullable=True)
    confidence_upper_days = Column(Integer, nullable=True)

    # --- Accuracy tracking ---
    # These fields are filled in LATER, after the rail is actually replaced.
    # They let us measure how accurate the prediction was.

    # The actual date the rail was repaired/replaced (filled in retroactively)
    actual_repair_date = Column(Date, nullable=True)

    # How many days off the prediction was (actual - predicted).
    # Positive means we predicted too early; negative means too late.
    prediction_error_days = Column(Integer, nullable=True)

    # --- Data context ---
    # Describes the measurement data that was available when this prediction
    # was generated.

    # How many measurement data points were used for the trend fitting
    data_points_used = Column(Integer, nullable=True)

    # The earliest measurement date used in the fit
    data_start_date = Column(Date, nullable=True)

    # The latest measurement date used in the fit
    data_end_date = Column(Date, nullable=True)

    # Links to the upload that triggered this prediction (for audit)
    upload_id = Column(Integer, ForeignKey("upload_logs.id"), nullable=True)

    # --- Relationships ---
    # These create convenient links to related records.

    # Link to the Chainage record this prediction is about
    chainage = relationship("Chainage")

    # Link to the upload that triggered this prediction
    upload = relationship("UploadLog")

    # Link to the global model used for this prediction
    global_model = relationship("GlobalModel")
