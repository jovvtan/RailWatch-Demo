"""
DTL sector/station lookup tables and bound detection.

FILE PURPOSE:
    This file contains the complete chainage-to-sector mapping for the
    Downtown Line (DTL). It tells the system which inter-station sector
    a given chainage falls within.

    KEY CONCEPTS:
    - "XB" = crossbound (equivalent to southbound — descending chainages,
      trains travel from Bukit Panjang towards Expo)
    - "BB" = basebound (equivalent to northbound — ascending chainages,
      trains travel from Expo towards Bukit Panjang)

    Station code reference (DT1-DT35):
      GBD=Gali Batu Depot, BKP=Bukit Panjang, CSW=Cashew, HVW=Hillview,
      BTW=Beauty World, KAP=King Albert Park, SAV=Sixth Avenue,
      TKK=Tan Kah Kee, BTN=Botanic Gardens, STV=Stevens, NEW=Newton,
      LTI=Little India, RCR=Rochor, BGS=Bugis, PMN=Promenade,
      BFT=Bayfront, DTN=Downtown, TLA=Telok Ayer, CLA=Chinatown,
      CNT=Fort Canning, FCN=Bencoolen, BCL=Jalan Besar (?), actually:
      CNT=Chinatown, FCN=Fort Canning, BCL=Bencoolen, JLB=Jalan Besar,
      BDM=Bendemeer, GLB=Geylang Bahru, MTR=Mattar, MPS=MacPherson,
      UBI=Ubi, KKB=Kaki Bukit, BDN=Bedok North, BDR=Bedok Reservoir,
      TPW=Tampines West, TAM=Tampines, TPE=Tampines East,
      UPC=Upper Changi, XPO=Expo
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# XB BOUND — trains travel from Bukit Panjang towards Expo
# Chainages are traversed in descending order (higher numbers first)
# ---------------------------------------------------------------------------
# Each tuple is: (lowest_chainage, highest_chainage, sector_code)
XB_SEGMENTS: list[tuple[int, int, str]] = [
    (55794, 56431, "GBD-BKP"),
    (54684, 55580, "BKP-CSW"),
    (53649, 54216, "CSW-HVW"),
    (51174, 53496, "HVW-BTW"),
    (49874, 50859, "BTW-KAP"),
    (48249, 49604, "KAP-SAV"),
    (47527, 47624, "SAV-TKK"),
    (45832, 46650, "TKK-BTN"),
    (44836, 45561, "BTN-STV"),
    (43066, 44508, "STV-NEW"),
    (41660, 42911, "NEW-LTI"),
    (41180, 41497, "LTI-RCR"),
    (40316, 40952, "RCR-BGS"),
    (39468, 40021, "BGS-PMN"),
    (38194, 39223, "PMN-BFT"),
    (37242, 37767, "BFT-DTN"),
    (36792, 37053, "DTN-TLA"),
    (36029, 36452, "CLA-CNT"),
    (35068, 35856, "CNT-FCN"),
    (33996, 34791, "FCN-BCL"),
    (33037, 33632, "BCL-JLB"),
    (31903, 32206, "JLB-BDM"),
    (30590, 31642, "BDM-GLB"),
    (28773, 30138, "GLB-MTR"),
    (27934, 28473, "MTR-MPS"),
    (26837, 27690, "MPS-UBI"),
    (25658, 26571, "UBI-KKB"),
    (24757, 25406, "KKB-BDN"),
    (22698, 24234, "BDN-BDR"),
    (20917, 22449, "BDR-TPW"),
    (19609, 20734, "TPW-TAM"),
    (18383, 19426, "TAM-TPE"),
    (16090, 18032, "TPE-UPC"),
    (14696, 15160, "UPC-XPO"),
]

# ---------------------------------------------------------------------------
# BB BOUND — trains travel from Expo towards Bukit Panjang
# Chainages are traversed in ascending order (lower numbers first)
# ---------------------------------------------------------------------------
BB_SEGMENTS: list[tuple[int, int, str]] = [
    (14695, 15180, "XPO-UPC"),
    (16095, 18009, "UPC-TPE"),
    (18371, 19434, "TPE-TAM"),
    (19601, 20724, "TAM-TPW"),
    (20909, 22487, "TPW-BDR"),
    (22697, 24161, "BDR-BDN"),
    (24787, 25405, "BDN-KKB"),
    (25679, 26478, "KKB-UBI"),
    (26385, 27768, "UBI-MPS"),
    (27910, 28500, "MPS-MTR"),
    (28768, 30118, "MTR-GLB"),
    (30468, 31653, "GLB-BDM"),
    (31937, 32908, "BDM-JLB"),
    (33035, 33688, "JLB-BCL"),
    (33995, 34790, "BCL-FCN"),
    (35064, 35848, "FCN-CNT"),
    (36030, 36462, "CNT-CLA"),
    (36794, 37055, "TLA-DTN"),
    (37231, 37768, "DTN-BFT"),
    (38193, 39224, "BFT-PMN"),
    (39461, 40031, "PMN-BGS"),
    (40361, 40933, "BGS-RCR"),
    (41150, 41279, "RCR-LTI"),
    (41640, 42914, "LTI-NEW"),
    (43060, 44509, "NEW-STV"),
    (44706, 45310, "STV-BTN"),
    (45802, 46664, "BTN-TKK"),
    (47052, 47612, "TKK-SAV"),
    (48229, 49630, "SAV-KAP"),
    (49841, 50872, "KAP-BTW"),
    (51152, 53508, "BTW-HVW"),
    (53648, 54303, "HVW-CSW"),
    (54679, 55581, "CSW-BKP"),
    (56001, 56543, "BKP-GBD"),
]

# ---------------------------------------------------------------------------
# Station name mapping — converts 3-letter codes to full station names
# ---------------------------------------------------------------------------
STATION_CODE_TO_NAME: dict[str, str] = {
    "GBD": "Gali Batu Depot",
    "BKP": "Bukit Panjang",
    "CSW": "Cashew",
    "HVW": "Hillview",
    "BTW": "Beauty World",
    "KAP": "King Albert Park",
    "SAV": "Sixth Avenue",
    "TKK": "Tan Kah Kee",
    "BTN": "Botanic Gardens",
    "STV": "Stevens",
    "NEW": "Newton",
    "LTI": "Little India",
    "RCR": "Rochor",
    "BGS": "Bugis",
    "PMN": "Promenade",
    "BFT": "Bayfront",
    "DTN": "Downtown",
    "TLA": "Telok Ayer",
    "CLA": "Chinatown",
    "CNT": "Fort Canning",
    "FCN": "Bencoolen",
    "BCL": "Jalan Besar",
    "JLB": "Jalan Besar",
    "BDM": "Bendemeer",
    "GLB": "Geylang Bahru",
    "MTR": "Mattar",
    "MPS": "MacPherson",
    "UBI": "Ubi",
    "KKB": "Kaki Bukit",
    "BDN": "Bedok North",
    "BDR": "Bedok Reservoir",
    "TPW": "Tampines West",
    "TAM": "Tampines",
    "TPE": "Tampines East",
    "UPC": "Upper Changi",
    "XPO": "Expo",
}


def detect_bound(chainage: int) -> str | None:
    """Determine if a chainage belongs to XB or BB based on its range."""
    for lo, hi, _ in XB_SEGMENTS:
        if lo <= chainage <= hi:
            return "XB"
    for lo, hi, _ in BB_SEGMENTS:
        if lo <= chainage <= hi:
            return "BB"
    return None


def get_sector(chainage: int, bound: str | None = None) -> str | None:
    """
    Look up the inter-station sector for a given chainage and bound.

    Args:
        chainage: The chainage number (integer).
        bound: "XB" or "BB". If None, will try both.

    Returns:
        The sector code (e.g. "BKP-CSW") or None if not found.
    """
    # Skip non-whole-number chainages (interpolation points)
    if not isinstance(chainage, int):
        try:
            if float(chainage) != int(float(chainage)):
                return None
            chainage = int(float(chainage))
        except (ValueError, TypeError):
            return None

    segments = []
    if bound in ("XB", None):
        segments.extend(XB_SEGMENTS)
    if bound in ("BB", None):
        segments.extend(BB_SEGMENTS)

    for lo, hi, sector in segments:
        if lo <= chainage <= hi:
            return sector

    return None


def sector_to_stations(sector: str) -> tuple[str | None, str | None]:
    """
    Convert a sector code like "BKP-CSW" to full station names.

    Returns:
        (start_station_name, end_station_name) or (None, None) if unknown.
    """
    if not sector or "-" not in sector:
        return None, None
    parts = sector.split("-")
    if len(parts) != 2:
        return None, None
    start = STATION_CODE_TO_NAME.get(parts[0].strip())
    end = STATION_CODE_TO_NAME.get(parts[1].strip())
    return start, end
