"""
CSV column mapping configuration — the SINGLE SOURCE OF TRUTH for column names.

FILE PURPOSE:
    When engineers export data from different measurement equipment or
    spreadsheets, the column headers are not always named the same way.
    For example, one file might call a column "left 45°", another might
    call it "left_45", and a third might call it "l45". They all mean
    the same thing.

    This file centralises ALL those naming variations in one place, so the
    rest of the system always knows which column means what. If the equipment
    vendor changes their column names in the future, only THIS file needs to
    be updated — all the parsers will automatically use the new mappings.

    This file defines:
    1. CSV_COLUMN_MAP — maps every known column name variation to a single
       standard internal name (e.g. "left 45°" -> "left_45")
    2. REQUIRED_COLUMNS — which columns MUST be present in every upload
    3. POSITION_COLUMNS — the full list of all 10 wear position column names
    4. NEL_POSITIONS / DTL_POSITIONS — which positions each line measures
    5. DATE_FORMATS — all the date formats we try when reading dates
    6. CATEGORY_COLUMN_MAP — column name variations for category assignment files
"""

# ---------------------------------------------------------------------------
# Measurement CSV column map
# ---------------------------------------------------------------------------
# This dictionary maps every known header variation (after lowercasing and
# removing degree symbols) to a single canonical internal field name.
#
# For example, if a CSV file has a column called "Left 45°", the parser will:
# 1. Lowercase it to "left 45°"
# 2. Remove the degree symbol to get "left 45"
# 3. Look it up in this dictionary and find it maps to "left_45"
#
# The keys (left side) are what might appear in uploaded files.
# The values (right side) are the standard names used inside the system.
CSV_COLUMN_MAP: dict[str, str] = {
    # --- Chainage identifier variants ---
    # Different files may call the chainage column by different names
    "chainage": "chainage_id",
    "chainage_id": "chainage_id",
    "chainage id": "chainage_id",

    # --- Date variants ---
    # The date column is not always present — sometimes the date comes from
    # the upload form instead of the file itself
    "date": "measurement_date",
    "measurement_date": "measurement_date",
    "measurement date": "measurement_date",

    # --- Left rail positions (degrees) ---
    # Each line maps different possible header names to the standard name.
    # "l0" is a short form that some equipment uses.
    "left 0°": "left_0", "left 0": "left_0", "left_0": "left_0", "l0": "left_0",
    "left 22.5°": "left_22_5", "left 22.5": "left_22_5", "left_22_5": "left_22_5",
    "left 45°": "left_45", "left 45": "left_45", "left_45": "left_45", "l45": "left_45",
    "left 67.5°": "left_67_5", "left 67.5": "left_67_5", "left_67_5": "left_67_5",
    "left 90°": "left_90", "left 90": "left_90", "left_90": "left_90",

    # --- Right rail positions (degrees) ---
    # Same pattern as left rail — multiple possible names for each angle
    "right 0°": "right_0", "right 0": "right_0", "right_0": "right_0", "r0": "right_0",
    "right 22.5°": "right_22_5", "right 22.5": "right_22_5", "right_22_5": "right_22_5",
    "right 45°": "right_45", "right 45": "right_45", "right_45": "right_45", "r45": "right_45",
    "right 67.5°": "right_67_5", "right 67.5": "right_67_5", "right_67_5": "right_67_5",
    "right 90°": "right_90", "right 90": "right_90", "right_90": "right_90",
}

# These columns MUST be present in every measurement upload.
# The date is not required in the file because it comes from the upload form.
REQUIRED_COLUMNS: list[str] = ["chainage_id"]  # Date comes from the upload form, not the file

# All ten possible wear position columns (left + right x 5 angles).
# This is the complete set — individual train lines may only use a subset.
POSITION_COLUMNS: list[str] = [
    "left_0", "left_22_5", "left_45", "left_67_5", "left_90",
    "right_0", "right_22_5", "right_45", "right_67_5", "right_90",
]

# NEL (North East Line) only measures at 0 and 90 degrees (4 positions total).
# The equipment on this line does not capture 22.5, 45, or 67.5 degree angles.
NEL_POSITIONS: list[str] = ["left_0", "left_90", "right_0", "right_90"]

# DTL (Downtown Line) measures at all five angles (10 positions total).
# This gives a more complete picture of the rail head profile.
DTL_POSITIONS: list[str] = POSITION_COLUMNS

# All the date formats we try when parsing date strings from CSV files.
# Different equipment and spreadsheet software export dates in different
# formats, so we try each one until one works.
# For example: "2025-03-15", "15/03/2025", "03/15/2025", "15-03-2025", etc.
DATE_FORMATS: list[str] = [
    "%Y-%m-%d",      # 2025-03-15 (ISO format)
    "%d/%m/%Y",      # 15/03/2025 (UK/SG format, day first)
    "%m/%d/%Y",      # 03/15/2025 (US format, month first)
    "%d-%m-%Y",      # 15-03-2025
    "%Y/%m/%d",      # 2025/03/15
    "%d %b %Y",      # 15 Mar 2025 (abbreviated month)
    "%d %B %Y",      # 15 March 2025 (full month name)
]

# ---------------------------------------------------------------------------
# Category CSV column map
# ---------------------------------------------------------------------------
# This is similar to CSV_COLUMN_MAP above, but for category assignment uploads.
# Category files tell the system which chainages are straight (category 1),
# curved standard (category 2), or curved premium (category 3).
CATEGORY_COLUMN_MAP: dict[str, str] = {
    # Chainage identifier — same variations as above
    "chainage": "chainage_id", "chainage_id": "chainage_id", "chainage id": "chainage_id",

    # Category number (1, 2, or 3)
    "category": "category", "cat": "category", "type": "category", "track_category": "category",

    # Curve radius in metres (optional — only relevant for curved track)
    "curve_radius": "curve_radius", "curve radius": "curve_radius", "radius": "curve_radius", "r": "curve_radius",

    # Rail type: "standard" or "premium" (optional)
    "rail_type": "rail_type", "rail type": "rail_type", "rail": "rail_type",

    # Curve direction: "left" or "right" (optional — only relevant for curved track)
    "curve_direction": "curve_direction", "curve direction": "curve_direction",
    "curve_dir": "curve_direction", "left/right/straight": "curve_direction",
}
