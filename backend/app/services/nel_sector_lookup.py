"""
NEL sector/station lookup tables and bound detection.

FILE PURPOSE:
    This file contains the complete chainage-to-sector mapping for the
    North East Line (NEL). It tells the system which inter-station sector
    (e.g. "Punggol to Sengkang") or which station area (e.g. "Sengkang")
    a given chainage falls within.

    This mapping was originally derived from a VBA macro used in the legacy
    Excel-based system. The chainage numbers are the real operational
    boundaries used on the North East Line.

    KEY CONCEPTS:
    - A "chainage" is a distance marker along the track (e.g. 42915 means
      42.915 km from the start of the line).
    - A "sector" or "segment" is the running track BETWEEN two stations
      (e.g. "PGL-SKG" = Punggol to Sengkang).
    - A "station" is the track WITHIN a station area.
    - "Bound" is the direction of travel: NB = northbound, SB = southbound.

    The NEL has separate chainage ranges for northbound and southbound
    because the two tracks are physically separate.

    Station code reference:
      HBF=HarbourFront, OTP=Outram Park, CNT=Chinatown, CQY=Clarke Quay,
      DBG=Dhoby Ghaut, LTI=Little India, FRP=Farrer Park, BNK=Boon Keng,
      PTP=Potong Pasir, WLH=Woodleigh, SER=Serangoon, KVN=Kovan,
      HGN=Hougang, BGK=Buangkok, SKG=Sengkang, PGL=Punggol.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SOUTHBOUND (SB) — trains travel from Punggol towards HarbourFront
# Chainages are traversed in descending order (higher numbers first)
# ---------------------------------------------------------------------------
# Each tuple is: (lowest_chainage, highest_chainage, sector_code)
# A chainage falling within this range belongs to this sector.
SB_SEGMENTS: list[tuple[int, int, str]] = [
    (42915, 44579, "PGL-SKG"),   # Punggol to Sengkang
    (41879, 42250, "SKG-BGK"),   # Sengkang to Buangkok
    (40585, 41867, "BGK-HGN"),   # Buangkok to Hougang
    (39040, 40571, "HGN-KVN"),   # Hougang to Kovan
    (37290, 39024, "KVN-SER"),   # Kovan to Serangoon
    (36068, 37269, "SER-WLH"),   # Serangoon to Woodleigh
    (35147, 36050, "WLH-PTP"),   # Woodleigh to Potong Pasir
    (33576, 33768, "PTP-BNK"),   # Potong Pasir to Boon Keng
    (32424, 33558, "BNK-FRP"),   # Boon Keng to Farrer Park
    (31669, 32418, "FRP-LTI"),   # Farrer Park to Little India
    (30696, 31636, "LTI-DBG"),   # Little India to Dhoby Ghaut
    (29341, 29447, "DBG-CQY"),   # Dhoby Ghaut to Clarke Quay
    (28713, 29311, "CQY-CNT"),   # Clarke Quay to Chinatown
    (27838, 28006, "OTP-HBF"),   # Outram Park to HarbourFront
]

# Station areas for southbound — the track sections WITHIN each station.
# These are the gaps between the inter-station segments above.
SB_STATIONS: list[tuple[int, int, str]] = [
    (42250, 42915, "SKG"),   # Sengkang station area
    (41867, 41879, "BGK"),   # Buangkok station area
    (40571, 40585, "HGN"),   # Hougang station area
    (39024, 39040, "KVN"),   # Kovan station area
    (37269, 37290, "SER"),   # Serangoon station area
    (36050, 36068, "WLH"),   # Woodleigh station area
    (33768, 35147, "PTP"),   # Potong Pasir station area
    (33558, 33576, "BNK"),   # Boon Keng station area
    (32418, 32424, "FRP"),   # Farrer Park station area
    (31636, 31669, "LTI"),   # Little India station area
    (29447, 30696, "DBG"),   # Dhoby Ghaut station area
    (29311, 29341, "CQY"),   # Clarke Quay station area
    (28006, 28713, "CNT"),   # Chinatown station area
]

# ---------------------------------------------------------------------------
# NORTHBOUND (NB) — trains travel from HarbourFront towards Punggol
# Chainages are traversed in ascending order (lower numbers first)
# ---------------------------------------------------------------------------
NB_SEGMENTS: list[tuple[int, int, str]] = [
    (25372, 27985, "HBF-OTP"),   # HarbourFront to Outram Park
    (28709, 29303, "CNT-CQY"),   # Chinatown to Clarke Quay
    (29325, 30683, "CQY-DBG"),   # Clarke Quay to Dhoby Ghaut
    (30697, 31641, "DBG-LTI"),   # Dhoby Ghaut to Little India
    (31654, 32380, "LTI-FRP"),   # Little India to Farrer Park
    (32420, 33553, "FRP-BNK"),   # Farrer Park to Boon Keng
    (33756, 35120, "BNK-PTP"),   # Boon Keng to Potong Pasir
    (35135, 36034, "PTP-WLH"),   # Potong Pasir to Woodleigh
    (36050, 37268, "WLH-SER"),   # Woodleigh to Serangoon
    (37800, 39024, "SER-KVN"),   # Serangoon to Kovan
    (39150, 40555, "KVN-HGN"),   # Kovan to Hougang
    (40573, 41854, "HGN-BGK"),   # Hougang to Buangkok
    (41870, 42887, "BGK-SKG"),   # Buangkok to Sengkang
    (42903, 44569, "SKG-PGL"),   # Sengkang to Punggol
]

# Station areas for northbound
NB_STATIONS: list[tuple[int, int, str]] = [
    (27985, 28709, "OTP"),   # Outram Park station area
    (29303, 29325, "CQY"),   # Clarke Quay station area
    (30683, 30697, "DBG"),   # Dhoby Ghaut station area
    (31641, 31654, "LTI"),   # Little India station area
    (32380, 32420, "FRP"),   # Farrer Park station area
    (33553, 33756, "BNK"),   # Boon Keng station area
    (35120, 35135, "PTP"),   # Potong Pasir station area
    (36034, 36050, "WLH"),   # Woodleigh station area
    (37268, 37800, "SER"),   # Serangoon station area
    (39024, 39150, "KVN"),   # Kovan station area
    (40555, 40573, "HGN"),   # Hougang station area
    (41854, 41870, "BGK"),   # Buangkok station area
    (42887, 42903, "SKG"),   # Sengkang station area
]


def detect_bound(column_a_values: list) -> str:
    """
    Detect the travel direction (northbound or southbound) from the chainage
    values in the file.

    HOW IT WORKS:
    Looks at the first two numeric values in the file's chainage column:
    - If the second value is LARGER than the first, the numbers are increasing,
      which means the train is going northbound (NB).
    - If the second value is SMALLER, the numbers are decreasing, which means
      the train is going southbound (SB).

    This works because northbound chainages increase (getting further from
    HarbourFront) and southbound chainages decrease.

    Args:
        column_a_values: The raw values from column A of the Excel file.

    Returns:
        "NB" for northbound, "SB" for southbound, or "NULL" if direction
        cannot be determined (e.g. fewer than 2 numeric values).
    """
    numeric: list[float] = []
    for val in column_a_values:
        # Only consider actual numbers (skip text headers, booleans, etc.)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            numeric.append(float(val))
            # We only need the first two numbers to determine direction
            if len(numeric) == 2:
                break

    # This checks if we found at least two numbers to compare
    if len(numeric) < 2:
        return "NULL"

    # If the second chainage is bigger, trains are going northbound (ascending)
    if numeric[1] > numeric[0]:
        return "NB"
    # If the second chainage is smaller, trains are going southbound (descending)
    elif numeric[1] < numeric[0]:
        return "SB"

    # If both values are the same, we can't determine direction
    return "NULL"


def get_sector(chainage: float, bound: str) -> str:
    """
    Look up which inter-station sector or station a chainage belongs to.

    For example:
    - Chainage 43000 on SB -> "PGL-SKG" (between Punggol and Sengkang)
    - Chainage 42500 on SB -> "SKG" (within Sengkang station)

    The function first checks inter-station segments (running track between
    stations), then checks station areas (track within stations).

    Args:
        chainage: The numeric chainage value (e.g. 42915.0).
        bound: "NB" for northbound or "SB" for southbound.

    Returns:
        A sector code (e.g. "PGL-SKG"), a station code (e.g. "SKG"),
        or "NULL" if the chainage doesn't fall within any known range.
    """
    # Select the correct lookup tables based on the bound (direction)
    if bound == "SB":
        segments, stations = SB_SEGMENTS, SB_STATIONS
    elif bound == "NB":
        segments, stations = NB_SEGMENTS, NB_STATIONS
    else:
        return "NULL"

    # First, check inter-station segments (running track between stations)
    for low, high, name in segments:
        if low <= chainage <= high:
            return name

    # If not found in segments, check station areas
    for low, high, name in stations:
        if low < chainage < high:
            return name

    # If the chainage doesn't fall within any known range
    return "NULL"


def is_whole_number(value) -> bool:
    """
    Check if a numeric value is a whole number (no fractional/decimal part).

    This is used to filter out sub-metre interpolation rows in NEL equipment
    files. The equipment records measurements at fractional chainages like
    12345.25, 12345.50, 12345.75, but we only want the whole-number ones
    (e.g. 12345.0) because those are the actual measurement points.

    Args:
        value: A numeric value to check.

    Returns:
        True if the value has no fractional component (e.g. 12346.0).
        False for non-numbers or fractional values (e.g. 12345.25).
    """
    # This rejects non-numeric values and booleans (True/False are technically
    # numbers in Python, but we don't want them)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    # This checks if the decimal part is zero (e.g. 42915.0 == 42915)
    return float(value) == int(float(value))


def get_all_sectors(bound: str) -> list[str]:
    """
    Return a list of all inter-station sector names for a given direction.

    This is used to get the complete list of sectors for display purposes
    (e.g. populating a dropdown menu).

    Args:
        bound: "NB" for northbound or "SB" for southbound.

    Returns:
        A list of sector code strings (e.g. ["PGL-SKG", "SKG-BGK", ...]),
        or an empty list if the bound is not valid.
    """
    if bound == "SB":
        return [name for _, _, name in SB_SEGMENTS]
    elif bound == "NB":
        return [name for _, _, name in NB_SEGMENTS]
    return []


def validate_chainage_range(chainage: float, bound: str) -> bool:
    """
    Check if a chainage value falls within the known NEL operational range.

    This is a quick sanity check — if a chainage number is way outside
    the expected range for the NEL, it's probably an error in the data.

    The valid ranges are:
    - Northbound: 25372 to 44569
    - Southbound: 27838 to 44579

    Args:
        chainage: The numeric chainage value to check.
        bound: "NB" for northbound or "SB" for southbound.

    Returns:
        True if the chainage is within the valid range, False otherwise.
    """
    if bound == "NB":
        return 25372 <= chainage <= 44569
    elif bound == "SB":
        return 27838 <= chainage <= 44579
    return False
