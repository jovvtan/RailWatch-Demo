"""
Database connection setup — engine, session factory, and base class.

FILE PURPOSE:
    This file sets up the connection to the database. It provides three things
    that the rest of the application uses:

    1. engine — The database "engine" that manages the actual connection to
       the SQLite database file. Think of it as the pipeline between the
       application and the database.

    2. SessionLocal — A "session factory" that creates database sessions.
       A session is like a conversation with the database — you can read data,
       make changes, and then save (commit) those changes. Each web request
       gets its own session.

    3. Base — The base class that all database table definitions inherit from.
       When you see "class Track(Base):" in the model files, this is the Base
       they're referring to.

    4. get_db() — A helper function used by the web API to get a database
       session for each incoming request, and automatically close it when
       the request is done.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# Create the database engine.
# This establishes the connection to the SQLite database file specified in
# the settings (e.g. "sqlite:///C:/SBS Transit Interface/data/railwatch.db").
#
# "check_same_thread=False" is required for SQLite when used with multiple
# threads (which happens in a web server). Without this, SQLite would throw
# errors when different web requests try to access the database at the same time.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite with threads
)

# Create the session factory.
# A "session" is like a single conversation with the database. Each web
# request gets its own session so that changes from one request don't
# interfere with another.
#
# autocommit=False means changes are NOT saved automatically — you must
# explicitly call db.commit() to save changes.
#
# autoflush=False means the session does NOT automatically send pending
# changes to the database before queries — we control when that happens.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create the declarative base class.
# All database table definitions (Track, Chainage, WearMeasurement, etc.)
# inherit from this class. It provides the magic that connects Python classes
# to database tables.
Base = declarative_base()


def get_db():
    """
    Provide a database session for a single web request.

    This is a "dependency" used by FastAPI — it runs automatically for each
    incoming API request that needs database access. It:

    1. Creates a new database session
    2. Hands it to the request handler (via "yield")
    3. Automatically closes the session when the request is done
       (even if an error occurred)

    This ensures that database connections are always properly cleaned up
    and not left open accidentally.

    Yields:
        A SQLAlchemy Session instance that can be used to read from and
        write to the database.
    """
    # Create a new database session for this request
    db = SessionLocal()
    try:
        # Hand the session to the request handler
        yield db
    finally:
        # Always close the session when done (even if an error occurred).
        # This releases the database connection back to the pool.
        db.close()
