"""
RailWatch API — the main entry point that starts the web application.

FILE PURPOSE:
    This is the file that launches the RailWatch web application. When the
    server starts, this file:

    1. Creates the FastAPI web application
    2. Sets up CORS (Cross-Origin Resource Sharing) so the frontend website
       can talk to the backend API
    3. Registers all the API routes (endpoints like /api/upload, /api/predict)
    4. Creates all database tables if they don't exist yet
    5. Runs any necessary database migrations (adding new columns)
    6. Backfills any missing station names from sector codes
    7. Optionally serves the frontend website if it's been built

    In simple terms: this is the "start here" file for the whole backend.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, Base
from app.api.router import router as api_router

# This import loads all database model definitions (Track, Chainage,
# WearMeasurement, etc.) so that SQLAlchemy knows about every table.
# Without this, some tables might not get created when the app starts.
import app.models  # noqa: F401


def _migrate_add_columns():
    """
    Add new database columns to existing tables.

    This function handles database migrations — when we add new fields to
    our models (like adding curve_direction to chainages), this function
    adds those columns to the existing database without losing any data.

    It's safe to run repeatedly — it checks if each column already exists
    before trying to add it. This only works with SQLite databases.

    If the database doesn't exist yet, this does nothing (create_all will
    handle it).
    """
    import sqlite3
    from app.config import settings

    # Extract the file path from the SQLite connection string
    # e.g. "sqlite:///C:/data/railwatch.db" -> "C:/data/railwatch.db"
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Helper function: checks if a column already exists in a table
        def has_column(table, column):
            cursor.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cursor.fetchall())

        # Add curve_direction column to chainages table (for tracking which
        # way a curve bends — needed for inner/outer rail mapping)
        if not has_column("chainages", "curve_direction"):
            cursor.execute("ALTER TABLE chainages ADD COLUMN curve_direction TEXT")

        # Add new columns to prediction_logs table (for per-position
        # prediction detail — which position and rail role was predicted)
        for col in ["position", "rail_role", "physical_side"]:
            if not has_column("prediction_logs", col):
                cursor.execute(f"ALTER TABLE prediction_logs ADD COLUMN {col} TEXT")

        # Add global_model_id to prediction_logs (links predictions to the
        # specific global model that was used)
        if not has_column("prediction_logs", "global_model_id"):
            cursor.execute("ALTER TABLE prediction_logs ADD COLUMN global_model_id INTEGER")

        # Add track_id to global_models (separates NEL and DTL models)
        if has_column("global_models", "id") and not has_column("global_models", "track_id"):
            cursor.execute("ALTER TABLE global_models ADD COLUMN track_id INTEGER")
            # Backfill existing models to NEL (track id 1)
            cursor.execute("UPDATE global_models SET track_id = (SELECT id FROM tracks WHERE track_id = 'NEL' LIMIT 1) WHERE track_id IS NULL")

        conn.commit()
        conn.close()
    except Exception:
        pass  # DB may not exist yet — create_all will handle it


def _backfill_station_names():
    """
    Fill in missing start_station and end_station names on existing Chainage
    records by looking up their sector codes.

    Some chainages were created before we started storing station names.
    This function finds those records and fills in the names from the sector
    code (e.g. sector "PGL-SKG" -> start_station="Punggol",
    end_station="Sengkang").

    This runs once at startup and only updates records that are missing
    station names.
    """
    from app.database import SessionLocal
    from app.models.track import Chainage
    from app.services.nel_raw_parser import _sector_to_stations

    db = SessionLocal()
    try:
        # Find all chainages that have a sector code but no station names
        missing = db.query(Chainage).filter(
            Chainage.sector.isnot(None),
            Chainage.start_station.is_(None),
        ).all()

        # Fill in the station names from the sector code
        for ch in missing:
            start, end = _sector_to_stations(ch.sector)
            if start:
                ch.start_station = start
                ch.end_station = end

        # Save changes if any records were updated
        if missing:
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown handler.

    This runs when the server starts up. It:
    1. Adds any new columns to existing database tables (migration)
    2. Creates all database tables that don't exist yet
    3. Backfills missing station names

    The "yield" in the middle separates startup code (before yield) from
    shutdown code (after yield). We don't have any shutdown tasks.
    """
    # Run database migrations (add new columns to existing tables)
    _migrate_add_columns()

    # Create all database tables that don't exist yet.
    # This is safe to run repeatedly — it only creates tables that are missing.
    Base.metadata.create_all(bind=engine)

    # Skip station name backfill in demo mode — data is pre-populated

    yield  # Application is now running and serving requests


# Create the FastAPI application with a title and the lifespan handler
app = FastAPI(title="RailWatch API", lifespan=lifespan)

# --- CORS (Cross-Origin Resource Sharing) ---
# This allows the frontend website (which runs on a different port during
# development) to make requests to this API. Without CORS, web browsers
# would block the frontend from talking to the backend.
# allow_origins=["*"] means "allow requests from any website" — this is
# fine for an internal tool but should be restricted for public deployments.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Allow requests from any origin
    allow_credentials=True,       # Allow cookies and auth headers
    allow_methods=["*"],          # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],          # Allow all HTTP headers
)

# --- API Routes ---
# Mount all API endpoints (upload, predict, etc.) under the /api prefix.
# For example, the upload endpoint becomes /api/upload.
app.include_router(api_router, prefix=settings.API_PREFIX)

# ---------------------------------------------------------------------------
# Static frontend serving (production mode)
# ---------------------------------------------------------------------------
# In production, the frontend React app is pre-built into static files
# (HTML, CSS, JavaScript) in the frontend/dist/ directory. If that directory
# exists, the backend serves those files directly, so you only need to run
# one server instead of two.

# Calculate the path to the frontend build directory
frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    # Mount the assets directory for JavaScript and CSS bundles.
    # These files have hashed names (e.g. main.abc123.js) for cache busting.
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        """
        Serve the frontend website from the pre-built static files.

        This is a "catch-all" route that handles any URL that isn't an API
        endpoint. It works like this:

        1. If the URL matches an actual file (e.g. /favicon.ico), serve that file
        2. Otherwise, serve index.html — the React app will handle the routing
           on the client side (this is called "SPA routing")

        IMPORTANT: This does NOT intercept /api/* routes because the API router
        was registered first and takes priority.

        Args:
            request: The incoming HTTP request.
            full_path: The URL path (e.g. "dashboard" or "assets/main.js").

        Returns:
            The requested file, or index.html as a fallback for client-side routing.
        """
        # Try to serve the exact file if it exists on disk
        file_path = frontend_dist / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        # Fall back to index.html for client-side (React) routing
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))

        # Last resort: return a simple status response
        return {"status": "ok", "app": settings.APP_NAME}

else:
    # If no frontend build exists, just serve a simple health-check endpoint
    @app.get("/")
    def root():
        """
        Simple health-check endpoint when no frontend build is available.
        Returns a JSON response confirming the API is running.
        """
        return {"status": "ok", "app": settings.APP_NAME}
