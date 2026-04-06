"""
Application configuration settings.

FILE PURPOSE:
    This file defines all the configurable settings for the RailWatch backend.
    Settings can be changed using environment variables or a .env file,
    without modifying the code.

    Default values are provided for local development, so the application
    starts without any extra configuration.

    The settings include:
    - APP_NAME: The display name of the application ("RailWatch")
    - API_PREFIX: The URL prefix for all API routes ("/api")
    - DATABASE_URL: Where the database file is located
    - WEAR_THRESHOLD_DEFAULT: The default wear limit in mm (8.0mm)

    HOW TO OVERRIDE SETTINGS:
    You can override any setting by:
    1. Setting an environment variable with the same name
       (e.g. set WEAR_THRESHOLD_DEFAULT=10.0)
    2. Creating a .env file in the project root with key=value pairs
       (e.g. WEAR_THRESHOLD_DEFAULT=10.0)
"""

from pathlib import Path

# pydantic-settings is a library that automatically loads configuration from
# environment variables and .env files
from pydantic_settings import BaseSettings

# Calculate the project root directory.
# This file is at: backend/app/config.py
# So parent.parent.parent goes up to: C:\SBS Transit Interface
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Central configuration for the RailWatch backend.

    All settings have default values, so the application works out of the
    box for local development. In production, settings can be overridden
    using environment variables or a .env file.
    """

    # The display name of the application (shown in API responses)
    APP_NAME: str = "RailWatch"

    # The URL prefix for all API routes. All API endpoints will start with
    # this prefix (e.g. /api/upload, /api/predict, /api/chainages)
    API_PREFIX: str = "/api"

    # The database connection string. By default, this uses an SQLite database
    # file stored in the project's data/ directory.
    # For example: "sqlite:///C:/SBS Transit Interface/data/railwatch.db"
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'demo.db'}"

    # The default wear threshold in millimetres. When rail wear reaches this
    # value, maintenance (replacement or grinding) is needed.
    # The standard threshold for SBS Transit is 8.0mm.
    WEAR_THRESHOLD_DEFAULT: float = 8.0  # mm — maintenance trigger threshold

    class Config:
        # This tells pydantic-settings to look for a .env file in the current
        # working directory for any setting overrides
        env_file = ".env"


# Create a single global instance of the settings.
# Other files import this instance: from app.config import settings
settings = Settings()
