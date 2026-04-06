"""
Models package — imports all database table definitions in one place.

FILE PURPOSE:
    This file exists to make sure ALL database table definitions are loaded
    when the application starts up. Here is why this matters:

    The database library (SQLAlchemy) needs to "know about" every table before
    it can create them in the database. It discovers tables by looking at which
    classes have been imported and registered with the "Base" class.

    By importing every model here, we guarantee that when the application runs
    Base.metadata.create_all() (which creates all the database tables), it
    finds every table — Track, Chainage, WearMeasurement, etc.

    Without this file, some tables might not get created because their
    definitions were never loaded into memory.

    HOW TO USE:
    Other parts of the application just need to do:
        import app.models
    and all six model files are automatically loaded.
"""

# Import all model classes from their individual files.
# Each import registers the table with SQLAlchemy's metadata system.
from app.models.track import Track, Chainage, CategoryConfig       # Rail lines and measurement locations
from app.models.measurement import WearMeasurement                 # Individual wear readings
from app.models.upload import UploadLog                            # File upload history
from app.models.prediction import PredictionLog                    # Prediction snapshots
from app.models.replacement import ReplacementLog                  # Rail replacement events
from app.models.global_model import GlobalModel                    # Prediction model formulas

# This list tells Python which names are "public" when someone does
# "from app.models import *". It's a standard Python convention.
__all__ = [
    "Track", "Chainage", "CategoryConfig", "WearMeasurement",
    "UploadLog", "PredictionLog", "ReplacementLog", "GlobalModel",
]
