"""
Track, Chainage, and CategoryConfig database tables.

FILE PURPOSE:
    This file defines three database tables that represent the physical railway
    infrastructure:

    1. Track — A rail line (e.g. the North East Line or Downtown Line).
    2. Chainage — A specific measurement point along a track, identified by its
       distance marker (chainage number). Each chainage stores information about
       the track at that point: whether it's curved, what type of rail is used,
       when the rail was installed, and how much wear is allowed before
       maintenance is needed.
    3. CategoryConfig — A log entry created each time someone uploads a file
       that assigns categories (straight, curved standard, curved premium) to
       chainages.

    These tables are the foundation of the system. Every wear measurement and
    every prediction is linked back to a specific chainage on a specific track.
"""

# --- Library imports ---
# These are tools from SQLAlchemy, a library that lets us define database tables
# as Python classes. Each "Column" becomes a column in the database table.
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# This imports the "Base" class that all our database tables must inherit from.
# Think of Base as the blueprint template — every table extends it.
from app.database import Base


class Track(Base):
    """
    DATABASE TABLE: tracks

    Represents a rail line (e.g. North East Line, Downtown Line).
    Each track can have many chainages (measurement points) along it.

    In simple terms: this is the "which train line" table.
    """

    # This tells the database to name this table "tracks"
    __tablename__ = "tracks"

    # "id" is the unique row number assigned automatically by the database.
    # Every table has one of these as its primary identifier.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # "track_id" is the short code used to identify the line, e.g. "NEL" for
    # North East Line. This must be unique — no two tracks can share a code.
    track_id = Column(String, unique=True, nullable=False)

    # "name" is the human-readable line name, e.g. "North East Line"
    name = Column(String, nullable=True)

    # "description" is an optional longer description of the line
    description = Column(String, nullable=True)

    # "measurement_positions" stores which angular positions (in degrees) are
    # measured on this line. The rail head is measured at different angles to
    # capture wear from different directions. The default is five standard
    # positions: 0, 22.5, 45, 67.5, and 90 degrees.
    # This is stored as a JSON list, e.g. ["0", "22.5", "45", "67.5", "90"]
    measurement_positions = Column(JSON, nullable=False, default=["0", "22.5", "45", "67.5", "90"])

    # "created_at" records when this track record was first added to the database.
    # func.now() means the database automatically fills in the current date/time.
    created_at = Column(DateTime, default=func.now())

    # This creates a link to all the Chainage records that belong to this track.
    # It lets us easily look up all measurement points on a given line.
    chainages = relationship("Chainage", back_populates="track")


class Chainage(Base):
    """
    DATABASE TABLE: chainages

    Represents a single measurement location along a track. A chainage is
    identified by its distance marker number (e.g. "42915" means 42.915 km
    from the start of the line).

    Each chainage stores:
    - WHERE it is (sector, stations, direction/bound)
    - WHAT the track is like at that point (curved or straight, rail type)
    - WHEN the rail was last installed or ground
    - HOW MUCH wear is allowed before maintenance is needed (threshold)

    The "category" field is especially important because it determines which
    prediction model is used to forecast when this rail will need maintenance:
        Category 1 = Straight track with standard rail
        Category 2 = Curved track with standard rail
        Category 3 = Curved track with premium (head-hardened) rail

    In simple terms: this is the "where exactly on the track" table.
    """

    # This tells the database to name this table "chainages"
    __tablename__ = "chainages"

    # Unique row number assigned automatically by the database
    id = Column(Integer, primary_key=True, autoincrement=True)

    # The chainage identifier string, e.g. "42915". This is the distance
    # marker number used by track engineers in the field.
    # Note: this is NOT unique by itself — the same chainage number can appear
    # for both northbound (NB) and southbound (SB) directions.
    chainage_id = Column(String, nullable=False)  # unique per (chainage_id, bound)

    # Links this chainage to its parent track (e.g. NEL).
    # This is a foreign key — it references the "id" column in the "tracks" table.
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False)

    # Which side of the rail is measured: "Left", "Right", or "Both"
    rail_side = Column(String, nullable=True)

    # The speed zone at this chainage (some sections have speed limits)
    speed_zone = Column(String, nullable=True)

    # Description of the curve at this point, if any
    curve = Column(String, nullable=True)

    # A free-text description of what is at this location
    location_description = Column(String, nullable=True)

    # The station before this chainage (e.g. "Punggol")
    start_station = Column(String, nullable=True)

    # The station after this chainage (e.g. "Sengkang")
    end_station = Column(String, nullable=True)

    # The travel direction at this chainage (similar to "bound" but more general)
    direction = Column(String, nullable=True)

    # The inter-station sector code, e.g. "PGL - SKG" means between
    # Punggol and Sengkang stations
    sector = Column(String, nullable=True)       # e.g. "PGL - SKG"

    # The bound (direction of travel): "NB" for northbound or "SB" for southbound.
    # On a two-track railway, the same physical location has two chainages —
    # one for each direction of travel.
    bound = Column(String, nullable=True)         # "NB" or "SB"

    # The date when the current rail was installed at this location.
    # This resets after a rail replacement.
    install_date = Column(Date, nullable=True)

    # The date when the rail was last ground (grinding smooths the rail surface
    # and can reset wear measurements)
    last_grind_date = Column(Date, nullable=True)

    # The maximum allowed wear in millimetres before maintenance is needed.
    # Default is 8.0 mm. When wear reaches this value, the rail should be
    # replaced or ground.
    wear_threshold_mm = Column(Float, default=8.0)

    # --- Category system ---
    # These fields drive which regression model is used for predictions.

    # The track category: 1 = straight standard, 2 = curved standard,
    # 3 = curved premium. This is the most important field for predictions.
    category = Column(Integer, nullable=True)       # 1=straight std, 2=curved std, 3=curved premium

    # The curve radius in metres. NULL for straight track. Tighter curves
    # (smaller radius) cause faster wear.
    curve_radius = Column(Float, nullable=True)     # Radius in metres, NULL for straight

    # The type of rail: "standard" or "premium" (head-hardened).
    # Premium rail is harder and wears more slowly, used on tight curves.
    rail_type = Column(String, nullable=True, default="standard")  # "standard" or "premium"

    # The direction the track curves: "left", "right", or NULL for straight.
    # This determines which rail (left or right) is the "outer" rail that
    # wears faster on curves.
    curve_direction = Column(String, nullable=True)  # "left", "right", or NULL for straight

    # Timestamps for when this record was created and last updated
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # This creates a link back to the parent Track record
    track = relationship("Track", back_populates="chainages")

    # This creates a link to all WearMeasurement records for this chainage.
    # It lets us easily look up all measurements at this location.
    measurements = relationship("WearMeasurement", back_populates="chainage")

    # This database constraint ensures that the combination of chainage_id and
    # bound is unique. In other words, you can't have two records for chainage
    # "42915" going northbound — but you CAN have one NB and one SB.
    __table_args__ = (
        UniqueConstraint("chainage_id", "bound", name="uq_chainage_bound"),
    )


class CategoryConfig(Base):
    """
    DATABASE TABLE: category_configs

    An audit record created each time someone uploads a category assignment
    file. This file tells the system which chainages are straight (category 1),
    curved standard (category 2), or curved premium (category 3).

    This table keeps a history of these uploads so we can track when categories
    were last updated and how many chainages were affected.

    In simple terms: this is the "category upload history" table.
    """

    # This tells the database to name this table "category_configs"
    __tablename__ = "category_configs"

    # Unique row number assigned automatically
    id = Column(Integer, primary_key=True, autoincrement=True)

    # When the category file was uploaded
    uploaded_at = Column(DateTime, default=func.now())

    # The name of the uploaded file (e.g. "NEL_categories_2025.csv")
    filename = Column(String, nullable=False)

    # How many chainages were found in the uploaded file
    total_chainages = Column(Integer, default=0)

    # How many chainages actually had their category changed
    updated_chainages = Column(Integer, default=0)

    # Whether the upload succeeded: "completed", "partial", or "failed"
    status = Column(String, default="completed")
