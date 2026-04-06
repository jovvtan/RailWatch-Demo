"""
CSV/Excel parsing and validation for measurement and category uploads.

FILE PURPOSE:
    This file handles reading uploaded files (CSV or Excel), figuring out what
    type of data they contain, and converting them into database records.

    It contains three main functions:

    1. detect_file_type() — looks at the column headers in an uploaded file and
       figures out what kind of file it is:
       - "nel_raw" = raw equipment data from the North East Line
       - "nel_raw_with_category" = NEL raw data that also has category columns
       - "labelled_csv" = a standard measurement file with named columns
       - "category" = a category assignment file
       - "unknown" = can't figure out what it is

    2. parse_measurement_csv() — reads a standard measurement file and creates
       WearMeasurement database records. It handles:
       - Column name mapping (translating varied headers to standard names)
       - Chainage validation (checking each location exists in the database)
       - Duplicate detection (skipping rows already in the database)
       - Error reporting (tracking which rows failed and why)

    3. parse_category_csv() — reads a category assignment file and updates
       existing Chainage records with their category, curve radius, and rail type.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, date

import pandas as pd
from sqlalchemy.orm import Session

from app.models.track import Chainage, Track
from app.models.measurement import WearMeasurement
from app.services.csv_config import (
    CSV_COLUMN_MAP, REQUIRED_COLUMNS, POSITION_COLUMNS,
    CATEGORY_COLUMN_MAP,
)


def detect_file_type(file_content: bytes, filename: str) -> str:
    """
    Detect what type of data an uploaded file contains by looking at its
    column headers.

    This is the first step when a user uploads a file — the system needs to
    know what kind of file it is so it can use the right parser.

    HOW IT WORKS:
    1. Try to read the file as a spreadsheet
    2. Look at the column headers
    3. Check for distinctive column names that identify each file type

    For example:
    - If it has columns like "milage" and "hor. wear", it's an NEL raw file
    - If it has "chainage" and "category" columns, it's a category file
    - If it has "chainage" and position columns like "left 45", it's a
      standard measurement file

    Args:
        file_content: The raw bytes of the uploaded file.
        filename: The original filename (used to determine CSV vs Excel).

    Returns:
        One of: "nel_raw", "nel_raw_with_category", "labelled_csv",
        "category", or "unknown".
    """
    try:
        # Try to read the file into a table format
        df = _read_file(file_content, filename)
    except Exception:
        # If we can't even read the file, it's unknown
        return "unknown"

    # If the file has no data at all, we can't determine its type
    if df.empty:
        return "unknown"

    # Convert all column headers to lowercase for easier comparison
    headers_lower = [str(c).lower().strip() for c in df.columns]

    # --- Check for NEL raw equipment file ---
    # NEL raw files have distinctive columns like "milage" (note the spelling)
    # or "hor. wear" (horizontal wear)
    has_milage = any("milage" in h or "mileage" in h for h in headers_lower)
    has_wear = any("hor. wear" in h or "vert. wear" in h for h in headers_lower)
    has_radius = any("radius" in h for h in headers_lower)
    has_tracktype = any("tracktype" in h.replace(" ", "") for h in headers_lower)

    # This checks if it's an NEL raw file WITH category/curvature data
    # (it has the Radius and/or TrackType columns in addition to the standard ones)
    if has_milage and (has_radius or has_tracktype):
        return "nel_raw_with_category"

    # This checks if it's a standard NEL raw file (without category columns)
    if has_milage or has_wear:
        return "nel_raw"

    # --- Check for labelled CSV or category file ---
    # Map the column headers to our internal names to see what data is present
    mapped = set()
    for h in headers_lower:
        # Remove degree symbols before looking up (e.g. "left 45°" -> "left 45")
        normalised = h.replace("°", "").strip()
        if normalised in CSV_COLUMN_MAP:
            mapped.add(CSV_COLUMN_MAP[normalised])

    # This checks if it's a category assignment file (has chainage + category columns)
    if "chainage_id" in mapped and "category" in mapped:
        return "category"

    # This checks if it's a standard measurement file (has chainage + at least
    # one wear position column like "left_45" or "right_0")
    if "chainage_id" in mapped and any(p in mapped for p in POSITION_COLUMNS):
        return "labelled_csv"

    # If none of the above patterns matched, we don't know what this file is
    return "unknown"


@dataclass
class CSVParseResult:
    """
    A container that holds the results of parsing a measurement CSV file.

    After parsing, this object tells you:
    - How many rows were in the file (rows_total)
    - How many were successfully processed (rows_accepted)
    - How many were duplicates and skipped (rows_skipped)
    - How many had errors (rows_errored)
    - What the specific errors were (errors list)
    - The actual measurement objects ready to save (measurements list)
    """
    rows_total: int = 0
    rows_accepted: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    measurements: list[WearMeasurement] = field(default_factory=list)


def _read_file(file_content: bytes, filename: str) -> pd.DataFrame:
    """
    Read a CSV or Excel file and return it as a table (DataFrame).

    This function handles the fact that different equipment exports files in
    different character encodings. It tries multiple encodings until one works.

    For Excel files (.xlsx, .xls), it uses the openpyxl engine.
    For CSV files, it tries these encodings in order:
    1. utf-8-sig (UTF-8 with BOM marker — common from Windows Excel exports)
    2. utf-8 (standard UTF-8)
    3. latin-1 (Western European)
    4. cp1252 (Windows Western European)

    Args:
        file_content: The raw bytes of the file.
        filename: Used to determine whether it's CSV or Excel.

    Returns:
        A pandas DataFrame (basically a table with rows and columns).

    Raises:
        ValueError: If none of the supported encodings can read the file.
    """
    lower = filename.lower()

    # This checks if the file is an Excel file based on its extension
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_content), engine="openpyxl")

    # For CSV files, try multiple character encodings until one works
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(file_content), encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            # This encoding didn't work — try the next one
            continue

    # If none of the encodings worked, raise an error
    raise ValueError("Unable to decode CSV file with any supported encoding")


def _normalise_header(col: str) -> str:
    """
    Clean up a column header name by lowercasing it, removing whitespace,
    and stripping degree symbols.

    For example: "Left 45°" -> "left 45"

    This normalisation makes it possible to match column names regardless of
    how they were formatted in the original file.
    """
    return str(col).lower().strip().replace("°", "").strip()


def _map_columns(df: pd.DataFrame, col_map: dict[str, str]) -> dict[str, str]:
    """
    Map the column names from an uploaded file to our standard internal names.

    For example, if a file has a column called "Left 45°", this function will
    map it to our internal name "left_45".

    Args:
        df: The uploaded data table.
        col_map: The mapping dictionary (e.g. CSV_COLUMN_MAP).

    Returns:
        A dictionary where keys are the original column names from the file
        and values are our standard internal names.
    """
    mapping: dict[str, str] = {}
    for raw_col in df.columns:
        # Normalise the column name (lowercase, strip, remove degrees)
        normalised = _normalise_header(raw_col)
        # Look it up in the mapping dictionary
        if normalised in col_map:
            mapping[raw_col] = col_map[normalised]
    return mapping


def _parse_float(value) -> float | None:
    """
    Safely convert a cell value to a decimal number (float).

    Returns None if the value is missing, empty, or not a valid number.
    This handles all the weird values that can appear in real-world data:
    - pandas NA/NaN (missing data marker)
    - Empty strings
    - Placeholder text like "N/A", "-", "null", "none"
    - Infinity values

    Args:
        value: The raw cell value from the spreadsheet.

    Returns:
        A finite float number, or None if the value can't be parsed.
    """
    # This checks if the value is a pandas "missing data" marker
    if pd.isna(value):
        return None

    # Convert to string and check for common placeholder values
    s = str(value).strip().lower()
    if s in ("", "n/a", "-", "na", "null", "none"):
        return None

    try:
        v = float(s)
        # This rejects infinity values (which can appear from division by zero)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def parse_measurement_csv(
    file_content: bytes,
    filename: str,
    measurement_date: date,
    db: Session,
) -> CSVParseResult:
    """
    Parse a standard measurement CSV or Excel file and create WearMeasurement
    database records.

    This is the main function for processing labelled measurement uploads.
    The measurement date is provided by the user on the upload form (not
    extracted from the file), so every row gets the same date.

    HOW IT WORKS:
    1. Read the file into a table
    2. Map column names to our standard internal names
    3. Check that required columns (at least chainage_id) are present
    4. For each row:
       a. Look up the chainage in the database
       b. Skip if this chainage+date combination already exists (duplicate)
       c. Parse all wear values at each angular position
       d. Calculate the overall maximum wear
       e. Create a WearMeasurement record

    Args:
        file_content: Raw bytes of the uploaded file.
        filename: Original filename.
        measurement_date: The date to assign to every measurement row.
        db: Database session for looking up chainages and checking duplicates.

    Returns:
        A CSVParseResult with the validated measurements and any errors.
    """
    result = CSVParseResult()

    # Step 1: Try to read the file
    try:
        df = _read_file(file_content, filename)
    except Exception as e:
        result.errors.append({"row": 0, "error": f"Cannot read file: {e}"})
        return result

    # This checks if the file is empty (no data rows)
    if df.empty:
        result.errors.append({"row": 0, "error": "File is empty"})
        return result

    # Step 2: Map the file's column names to our standard internal names
    col_mapping = _map_columns(df, CSV_COLUMN_MAP)
    mapped_fields = set(col_mapping.values())

    # Step 3: Check that required columns are present
    for req in REQUIRED_COLUMNS:
        if req not in mapped_fields:
            result.errors.append({"row": 0, "error": f"Missing required column: {req}"})
            return result

    # This checks that at least one wear position column was found
    # (otherwise there's no actual measurement data in the file)
    pos_cols_found = [c for c in POSITION_COLUMNS if c in mapped_fields]
    if not pos_cols_found:
        result.errors.append({"row": 0, "error": "No measurement position columns found"})
        return result

    # Build a reverse lookup: internal field name -> original column name.
    # This lets us find the right column in each row when we read the data.
    field_to_raw: dict[str, str] = {}
    for raw_col, internal in col_mapping.items():
        field_to_raw[internal] = raw_col

    # Create a cache for chainage lookups to avoid hitting the database
    # repeatedly for the same chainage ID
    chainage_cache: dict[str, Chainage | None] = {}

    # Pre-load ALL existing (chainage, date) pairs from the database.
    # This is used for duplicate detection — if a measurement already exists
    # for a given chainage and date, we skip it rather than creating a duplicate.
    existing_pairs: set[tuple[int, date]] = set()
    all_existing = db.query(WearMeasurement.chainage_id, WearMeasurement.measurement_date).all()
    for cid, mdate in all_existing:
        existing_pairs.add((cid, mdate))

    result.rows_total = len(df)

    # Step 4: Process each row in the file
    for idx, row in df.iterrows():
        # Calculate the "human-readable" row number (+2 because: 0-indexed + header row)
        row_num = int(idx) + 2  # +2 accounts for 0-indexing and header row

        # --- Extract and validate the chainage ID ---
        raw_chainage = str(row.get(field_to_raw.get("chainage_id", ""), "")).strip()
        if not raw_chainage or raw_chainage == "nan":
            result.rows_errored += 1
            result.errors.append({"row": row_num, "error": "Missing chainage ID"})
            continue

        # --- Look up the chainage in the database ---
        # Uses a cache so we only query the database once per unique chainage ID
        if raw_chainage not in chainage_cache:
            chainage_cache[raw_chainage] = db.query(Chainage).filter(
                Chainage.chainage_id == raw_chainage
            ).first()

        chainage_obj = chainage_cache[raw_chainage]
        # This checks if the chainage exists in the database — if not, we
        # can't store a measurement for it
        if chainage_obj is None:
            result.rows_errored += 1
            result.warnings.append({"row": row_num, "warning": f"Unknown chainage: {raw_chainage}"})
            continue

        # Use the date provided by the user on the upload form
        m_date = measurement_date

        # --- Duplicate detection ---
        # This checks if we already have a measurement for this chainage on
        # this date. If so, skip it to avoid duplicates.
        if (chainage_obj.id, m_date) in existing_pairs:
            result.rows_skipped += 1
            continue

        # --- Parse wear values at each angular position ---
        pos_values: dict[str, float | None] = {}
        for pos_col in POSITION_COLUMNS:
            raw_col = field_to_raw.get(pos_col)
            if raw_col is not None:
                # This converts the cell value to a number (or None if invalid)
                pos_values[pos_col] = _parse_float(row.get(raw_col))
            else:
                pos_values[pos_col] = None

        # This checks if ALL position values are empty — if so, there's no
        # actual measurement data in this row
        non_null = [v for v in pos_values.values() if v is not None]
        if not non_null:
            result.rows_errored += 1
            result.errors.append({"row": row_num, "error": "All position values are empty"})
            continue

        # The overall wear value is the MAXIMUM across all measured positions.
        # This is the single number used for threshold checks.
        wear_mm = max(non_null)

        # Create the WearMeasurement database record
        meas = WearMeasurement(
            chainage_id=chainage_obj.id,
            measurement_date=m_date,
            wear_mm=wear_mm,
            left_wear_0=pos_values.get("left_0"),
            left_wear_22_5=pos_values.get("left_22_5"),
            left_wear_45=pos_values.get("left_45"),
            left_wear_67_5=pos_values.get("left_67_5"),
            left_wear_90=pos_values.get("left_90"),
            right_wear_0=pos_values.get("right_0"),
            right_wear_22_5=pos_values.get("right_22_5"),
            right_wear_45=pos_values.get("right_45"),
            right_wear_67_5=pos_values.get("right_67_5"),
            right_wear_90=pos_values.get("right_90"),
            source_file=filename,
        )
        result.measurements.append(meas)

        # Add to the existing pairs set so we don't create duplicates within
        # the same file (if two rows have the same chainage)
        existing_pairs.add((chainage_obj.id, m_date))
        result.rows_accepted += 1

    return result


def parse_category_csv(file_content: bytes, filename: str, db: Session) -> dict:
    """
    Parse a category assignment CSV file and update Chainage records in the
    database.

    This function is used when someone uploads a file that assigns categories
    to chainages. Each row should specify a chainage ID and its category
    (1 = straight, 2 = curved standard, 3 = curved premium).

    Optional columns for curve_radius, rail_type, and curve_direction are
    also applied if present. Business rules are enforced:
    - Category 3 automatically sets rail_type to "premium"
    - Category 1 automatically clears curve_direction (straight track)

    HOW IT WORKS:
    1. Read the file
    2. Map column names to standard internal names
    3. For each row:
       a. Look up the chainage in the database
       b. Validate the category value (must be 1, 2, or 3)
       c. Update the chainage's category, curve_radius, rail_type, etc.
       d. Apply business rules

    Args:
        file_content: Raw bytes of the uploaded file.
        filename: Original filename.
        db: Database session for looking up and updating chainages.

    Returns:
        A dictionary with: status, updated count, not_found list, errors list,
        and total row count.
    """
    # Try to read the file
    try:
        df = _read_file(file_content, filename)
    except Exception as e:
        return {"status": "failed", "updated": 0, "not_found": [], "errors": [str(e)]}

    if df.empty:
        return {"status": "failed", "updated": 0, "not_found": [], "errors": ["File is empty"]}

    # Map column names from the file to our standard internal names
    col_mapping = _map_columns(df, CATEGORY_COLUMN_MAP)
    mapped_fields = set(col_mapping.values())

    # Validate that required columns are present
    if "chainage_id" not in mapped_fields:
        return {"status": "failed", "updated": 0, "not_found": [], "errors": ["Missing chainage column"]}
    if "category" not in mapped_fields:
        return {"status": "failed", "updated": 0, "not_found": [], "errors": ["Missing category column"]}

    # Build a reverse lookup: internal field name -> original column name
    field_to_raw: dict[str, str] = {}
    for raw_col, internal in col_mapping.items():
        field_to_raw[internal] = raw_col

    updated = 0
    not_found: list[str] = []
    errors: list[str] = []

    # Process each row in the file
    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # Human-readable row number

        # Extract the chainage ID from this row
        raw_cid = str(row.get(field_to_raw.get("chainage_id", ""), "")).strip()
        if not raw_cid or raw_cid == "nan":
            errors.append(f"Row {row_num}: Missing chainage ID")
            continue

        # Look up the chainage in the database
        chainage = db.query(Chainage).filter(Chainage.chainage_id == raw_cid).first()
        if not chainage:
            # This chainage doesn't exist in the database — record it
            not_found.append(raw_cid)
            continue

        # Parse and validate the category value (must be 1, 2, or 3)
        raw_cat = _parse_float(row.get(field_to_raw.get("category", ""), None))
        if raw_cat is None or int(raw_cat) not in (1, 2, 3):
            errors.append(f"Row {row_num}: Invalid category for {raw_cid} (must be 1, 2, or 3)")
            continue

        # Set the category on the chainage record
        cat = int(raw_cat)
        chainage.category = cat

        # Optionally update curve radius if the column is present in the file
        if "curve_radius" in field_to_raw:
            radius = _parse_float(row.get(field_to_raw["curve_radius"], None))
            chainage.curve_radius = radius

        # Optionally update rail type if the column is present in the file
        if "rail_type" in field_to_raw:
            rt = str(row.get(field_to_raw["rail_type"], "")).strip().lower()
            if rt in ("standard", "premium"):
                chainage.rail_type = rt

        # Optionally update curve direction if the column is present
        if "curve_direction" in field_to_raw:
            cd = str(row.get(field_to_raw["curve_direction"], "")).strip().lower()
            # Normalise various formats: "l" -> "left", "r" -> "right"
            if cd in ("left", "right", "l", "r"):
                chainage.curve_direction = "left" if cd in ("left", "l") else "right"
            elif cd in ("straight", "s", ""):
                chainage.curve_direction = None  # Straight track has no curve direction
            elif cd not in ("nan", "none"):
                chainage.curve_direction = cd  # store as-is if unrecognised

        # --- Enforce business rules ---
        # Category 3 = premium curve — rail type MUST be "premium"
        if cat == 3:
            chainage.rail_type = "premium"
        # Categories 1 and 2 default to "standard" rail if not already set
        elif cat in (1, 2) and not chainage.rail_type:
            chainage.rail_type = "standard"
        # Category 1 = straight track — must NOT have a curve direction
        if cat == 1:
            chainage.curve_direction = None  # straight track has no curve direction

        updated += 1

    # Save all the changes to the database
    db.commit()

    # Return "completed" if no issues, "partial" if some rows had problems
    status = "completed" if not errors and not not_found else "partial"
    return {
        "status": status,
        "updated": updated,
        "not_found": not_found,
        "errors": errors,
        "total": len(df),
    }
