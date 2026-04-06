"""
GlobalModel database table.

FILE PURPOSE:
    This file defines the database table that stores the globally-fitted
    regression models used for predicting rail wear.

    Instead of fitting a separate model for every single chainage (which would
    need lots of data at each location), the system groups chainages by
    category and fits ONE shared model per group. This is called a "global
    model" because it pools data from many chainages together.

    There are up to 25 global models in total:
    - Category 1 (Straight Standard): 5 models
      (one per angular position: 0, 22.5, 45, 67.5, 90 degrees)
      Rail role = "both" because straight track wears both rails equally.

    - Category 2 (Standard Curve): 10 models
      (5 positions x 2 rail roles: "inner" and "outer")
      Inner and outer rails are modelled separately because centripetal force
      causes the outer rail to wear faster on curves.

    - Category 3 (Premium Curve): 10 models
      (same as Category 2, but for premium/head-hardened rail)

    Each model stores its fitted coefficients (slope and intercept), which
    describe the mathematical trend line of wear over time.

    In simple terms: this is the "prediction formulas" table.
"""

# --- Library imports ---
from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Base class that all database table definitions must inherit from
from app.database import Base


class GlobalModel(Base):
    """
    DATABASE TABLE: global_models

    A single globally-fitted regression model. All chainages sharing the same
    category contribute their measurement data to the same model.

    For curved tracks (categories 2 and 3), inner and outer rails are modelled
    separately because centripetal force pushes the train against the outer
    rail, causing it to wear faster.

    The key outputs are:
    - slope: how fast wear increases per day (the wear rate)
    - intercept: the baseline wear level at day zero
    - wear_rate_per_month: the monthly wear rate (easier to understand)

    In simple terms: each row is a mathematical formula that predicts how
    fast a certain type of rail wears down.
    """

    # This tells the database to name this table "global_models"
    __tablename__ = "global_models"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Which rail line this model belongs to (foreign key to tracks.id).
    # NEL and DTL have separate models because their data is independent.
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)

    # The track category this model belongs to:
    # 1 = Straight standard, 2 = Curved standard, 3 = Curved premium
    category = Column(Integer, nullable=False)        # 1, 2, 3

    # The angular measurement position this model is for:
    # "0", "22.5", "45", "67.5", or "90" (degrees on the rail head)
    position = Column(String, nullable=False)         # "0", "22.5", "45", "67.5", "90"

    # The rail role:
    # "both" = straight track (both rails wear equally)
    # "inner" = the rail on the inside of a curve
    # "outer" = the rail on the outside of a curve (wears faster)
    rail_role = Column(String, nullable=False)        # "both", "inner", "outer"

    # --- Fitted coefficients ---
    # These are the numbers that make up the prediction formula.
    # The formula is: predicted_wear = intercept + (slope x days_elapsed)

    # The baseline wear in mm at day zero (the y-intercept of the trend line)
    intercept = Column(Float, nullable=True)          # B0 (beta-zero)

    # The wear rate per day in mm (the slope of the trend line).
    # For example, 0.005 means the rail wears 0.005mm per day.
    slope = Column(Float, nullable=True)              # B1 (beta-one, per day)

    # An additional coefficient that accounts for the effect of curve tightness
    # on wear rate. Only used for curved track (categories 2 and 3).
    # NULL for straight track (category 1).
    curvature_coef = Column(Float, nullable=True)     # B2 (NULL for cat 1)

    # How well the model fits the data. Ranges from 0 to 1.
    # 1.0 = perfect fit, 0.0 = the model explains nothing.
    # Higher values mean more reliable predictions.
    r_squared = Column(Float, nullable=True)

    # The monthly wear rate, calculated as slope * 30.44 (average days per
    # month). This is easier for engineers to understand than a daily rate.
    # For example, 0.15 means the rail wears 0.15mm per month.
    wear_rate_per_month = Column(Float, nullable=True)  # slope * 30.44

    # --- Fit metadata ---
    # Information about the data that was used to create this model.

    # How many individual measurement data points were used to fit this model.
    # More data points generally means a more reliable model.
    data_points_used = Column(Integer, default=0)

    # How many different chainages contributed data to this model.
    # More chainages means the model is based on a wider sample.
    chainages_contributing = Column(Integer, default=0)

    # When this model was last fitted (recalculated)
    fitted_at = Column(DateTime, default=func.now())

    # Links to the upload that triggered the last refit of this model
    upload_id = Column(Integer, ForeignKey("upload_logs.id"), nullable=True)

    # Link to the UploadLog record
    upload = relationship("UploadLog")

    # This constraint ensures that there is only ONE model per combination of
    # (category, position, rail_role). For example, there can only be one model
    # for "category 2, position 45, outer rail". If the model is refitted,
    # the existing row is updated rather than creating a new one.
    # Link to the Track record (e.g. NEL or DTL)
    track = relationship("Track")

    __table_args__ = (
        UniqueConstraint("track_id", "category", "position", "rail_role", name="uq_global_model_track"),
    )
