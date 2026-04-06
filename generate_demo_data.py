"""
Generate fake demo data for RailWatch demo interface.
Uses the ORM models directly so the schema always matches.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import random
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)

DB_PATH = Path(__file__).parent / "data" / "demo.db"

# Delete old DB before importing (engine grabs the file on import)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    try:
        DB_PATH.unlink()
    except PermissionError:
        # If locked, use a temp name and swap later
        DB_PATH = DB_PATH.parent / "demo_new.db"

# Overwrite config to use demo.db before importing anything else
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from app.database import engine, Base, SessionLocal
from app.models.track import Track, Chainage
from app.models.measurement import WearMeasurement
from app.models.upload import UploadLog
from app.models.replacement import ReplacementLog
from app.models.prediction import PredictionLog
from app.models.global_model import GlobalModel

# ---------------------------------------------------------------------------
# Sector definitions
# ---------------------------------------------------------------------------
NEL_SB_SECTORS = [
    ("PGL-SKG", 42915, 44579, "Punggol", "Sengkang"),
    ("SKG-BGK", 41879, 42250, "Sengkang", "Buangkok"),
    ("BGK-HGN", 40585, 41867, "Buangkok", "Hougang"),
    ("HGN-KVN", 39040, 40571, "Hougang", "Kovan"),
    ("KVN-SER", 37290, 39024, "Kovan", "Serangoon"),
    ("SER-WLH", 36068, 37269, "Serangoon", "Woodleigh"),
    ("WLH-PTP", 35147, 36050, "Woodleigh", "Potong Pasir"),
    ("PTP-BNK", 33576, 33768, "Potong Pasir", "Boon Keng"),
    ("BNK-FRP", 32424, 33558, "Boon Keng", "Farrer Park"),
    ("FRP-LTI", 31669, 32418, "Farrer Park", "Little India"),
    ("LTI-DBG", 30696, 31636, "Little India", "Dhoby Ghaut"),
    ("DBG-CQY", 29341, 29447, "Dhoby Ghaut", "Clarke Quay"),
    ("CQY-CNT", 28713, 29311, "Clarke Quay", "Chinatown"),
    ("OTP-HBF", 27838, 28006, "Outram Park", "HarbourFront"),
]
NEL_NB_SECTORS = [
    ("HBF-OTP", 27993, 28175, "HarbourFront", "Outram Park"),
    ("CNT-CQY", 28895, 29476, "Chinatown", "Clarke Quay"),
    ("CQY-DBG", 29505, 29724, "Clarke Quay", "Dhoby Ghaut"),
    ("DBG-LTI", 30727, 31723, "Dhoby Ghaut", "Little India"),
    ("LTI-FRP", 31762, 32538, "Little India", "Farrer Park"),
    ("FRP-BNK", 32578, 33659, "Farrer Park", "Boon Keng"),
    ("BNK-PTP", 33728, 33884, "Boon Keng", "Potong Pasir"),
    ("PTP-WLH", 35220, 36125, "Potong Pasir", "Woodleigh"),
    ("WLH-SER", 36181, 37408, "Woodleigh", "Serangoon"),
    ("SER-KVN", 37420, 39115, "Serangoon", "Kovan"),
    ("KVN-HGN", 39145, 40650, "Kovan", "Hougang"),
    ("HGN-BGK", 40690, 41960, "Hougang", "Buangkok"),
    ("BGK-SKG", 41985, 42350, "Buangkok", "Sengkang"),
    ("SKG-PGL", 42915, 44680, "Sengkang", "Punggol"),
]
DTL_XB_SECTORS = [
    ("GBD-BKP", 55794, 56431, "Gali Batu Depot", "Bukit Panjang"),
    ("BKP-CSW", 54684, 55580, "Bukit Panjang", "Cashew"),
    ("CSW-HVW", 53649, 54216, "Cashew", "Hillview"),
    ("HVW-BTW", 51174, 53496, "Hillview", "Beauty World"),
    ("BTW-KAP", 49874, 50859, "Beauty World", "King Albert Park"),
    ("KAP-SAV", 48249, 49604, "King Albert Park", "Sixth Avenue"),
    ("SAV-TKK", 47527, 47624, "Sixth Avenue", "Tan Kah Kee"),
    ("TKK-BTN", 45832, 46650, "Tan Kah Kee", "Botanic Gardens"),
    ("BTN-STV", 44836, 45561, "Botanic Gardens", "Stevens"),
    ("STV-NEW", 43066, 44508, "Stevens", "Newton"),
    ("NEW-LTI", 41660, 42911, "Newton", "Little India"),
    ("LTI-RCR", 41180, 41497, "Little India", "Rochor"),
    ("RCR-BGS", 40316, 40952, "Rochor", "Bugis"),
    ("BGS-PMN", 39468, 40021, "Bugis", "Promenade"),
    ("PMN-BFT", 38194, 39223, "Promenade", "Bayfront"),
    ("BFT-DTN", 37242, 37767, "Bayfront", "Downtown"),
    ("DTN-TLA", 36792, 37053, "Downtown", "Telok Ayer"),
    ("CLA-CNT", 36029, 36452, "Chinatown", "Fort Canning"),
    ("CNT-FCN", 35068, 35856, "Fort Canning", "Bencoolen"),
    ("FCN-BCL", 33996, 34791, "Bencoolen", "Jalan Besar"),
    ("BCL-JLB", 33037, 33632, "Jalan Besar", "Jalan Besar"),
    ("JLB-BDM", 31903, 32206, "Jalan Besar", "Bendemeer"),
    ("BDM-GLB", 30590, 31642, "Bendemeer", "Geylang Bahru"),
    ("GLB-MTR", 28773, 30138, "Geylang Bahru", "Mattar"),
    ("MTR-MPS", 27934, 28473, "Mattar", "MacPherson"),
    ("MPS-UBI", 26837, 27690, "MacPherson", "Ubi"),
    ("UBI-KKB", 25658, 26571, "Ubi", "Kaki Bukit"),
    ("KKB-BDN", 24757, 25406, "Kaki Bukit", "Bedok North"),
    ("BDN-BDR", 22698, 24234, "Bedok North", "Bedok Reservoir"),
    ("BDR-TPW", 20917, 22449, "Bedok Reservoir", "Tampines West"),
    ("TPW-TAM", 19609, 20734, "Tampines West", "Tampines"),
    ("TAM-TPE", 18383, 19426, "Tampines", "Tampines East"),
    ("TPE-UPC", 16090, 18032, "Tampines East", "Upper Changi"),
    ("UPC-XPO", 14696, 15160, "Upper Changi", "Expo"),
]
DTL_BB_SECTORS = [
    ("XPO-UPC", 14695, 15180, "Expo", "Upper Changi"),
    ("UPC-TPE", 16095, 18009, "Upper Changi", "Tampines East"),
    ("TPE-TAM", 18371, 19434, "Tampines East", "Tampines"),
    ("TAM-TPW", 19601, 20724, "Tampines", "Tampines West"),
    ("TPW-BDR", 20909, 22487, "Tampines West", "Bedok Reservoir"),
    ("BDR-BDN", 22697, 24161, "Bedok Reservoir", "Bedok North"),
    ("BDN-KKB", 24787, 25405, "Bedok North", "Kaki Bukit"),
    ("KKB-UBI", 25679, 26478, "Kaki Bukit", "Ubi"),
    ("UBI-MPS", 26385, 27768, "Ubi", "MacPherson"),
    ("MPS-MTR", 27910, 28500, "MacPherson", "Mattar"),
    ("MTR-GLB", 28768, 30118, "Mattar", "Geylang Bahru"),
    ("GLB-BDM", 30468, 31653, "Geylang Bahru", "Bendemeer"),
    ("BDM-JLB", 31937, 32908, "Bendemeer", "Jalan Besar"),
    ("JLB-BCL", 33035, 33688, "Jalan Besar", "Jalan Besar"),
    ("BCL-FCN", 33995, 34790, "Jalan Besar", "Bencoolen"),
    ("FCN-CNT", 35064, 35848, "Bencoolen", "Fort Canning"),
    ("CNT-CLA", 36030, 36462, "Fort Canning", "Chinatown"),
    ("TLA-DTN", 36794, 37055, "Telok Ayer", "Downtown"),
    ("DTN-BFT", 37231, 37768, "Downtown", "Bayfront"),
    ("BFT-PMN", 38193, 39224, "Bayfront", "Promenade"),
    ("PMN-BGS", 39461, 40031, "Promenade", "Bugis"),
    ("BGS-RCR", 40361, 40933, "Bugis", "Rochor"),
    ("RCR-LTI", 41150, 41279, "Rochor", "Little India"),
    ("LTI-NEW", 41640, 42914, "Little India", "Newton"),
    ("NEW-STV", 43060, 44509, "Newton", "Stevens"),
    ("STV-BTN", 44706, 45310, "Stevens", "Botanic Gardens"),
    ("BTN-TKK", 45802, 46664, "Botanic Gardens", "Tan Kah Kee"),
    ("TKK-SAV", 47052, 47612, "Tan Kah Kee", "Sixth Avenue"),
    ("SAV-KAP", 48229, 49630, "Sixth Avenue", "King Albert Park"),
    ("KAP-BTW", 49841, 50872, "King Albert Park", "Beauty World"),
    ("BTW-HVW", 51152, 53508, "Beauty World", "Hillview"),
    ("HVW-CSW", 53648, 54303, "Hillview", "Cashew"),
    ("CSW-BKP", 54679, 55581, "Cashew", "Bukit Panjang"),
    ("BKP-GBD", 56001, 56543, "Bukit Panjang", "Gali Batu Depot"),
]


def pick_chainages(sectors, count_per_sector=2):
    result = []
    for sector, lo, hi, start_stn, end_stn in sectors:
        span = hi - lo
        if span < count_per_sector:
            picks = [lo]
        else:
            step = span // (count_per_sector + 1)
            picks = [lo + step * (i + 1) for i in range(count_per_sector)]
        for ch in picks:
            result.append((str(ch), sector, start_stn, end_stn))
    return result


def assign_category(chainage_id):
    v = int(chainage_id) % 10
    if v < 5:
        return 1, None, "standard", None
    elif v < 8:
        return 2, random.choice([300, 400, 500, 600, 800]), "standard", random.choice(["left", "right"])
    else:
        return 3, random.choice([250, 350, 450]), "premium", random.choice(["left", "right"])


def main():
    # Create all tables from ORM models
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # Create tracks
    nel = Track(track_id="NEL", name="North East Line", measurement_positions=["0", "90"])
    dtl = Track(track_id="DTL", name="Downtown Line", measurement_positions=["0", "22.5", "45", "67.5", "90"])
    db.add_all([nel, dtl])
    db.flush()

    # Upload logs
    run_dates = [date(2024, 6, 15), date(2024, 12, 10), date(2025, 6, 20)]
    for i, rd in enumerate(run_dates):
        db.add(UploadLog(filename=f"Demo_Run_{i+1}.xlsx", uploaded_at=datetime.combine(rd, datetime.min.time()),
                         rows_total=200, rows_accepted=200, status="completed"))
    db.flush()

    # Create chainages
    all_chainages = []  # (Chainage obj, category, radius)

    for sectors, track, bound in [
        (NEL_SB_SECTORS, nel, "SB"), (NEL_NB_SECTORS, nel, "NB"),
        (DTL_XB_SECTORS, dtl, "XB"), (DTL_BB_SECTORS, dtl, "BB"),
    ]:
        count = 4 if track == nel else 2
        for ch_id, sector, start_stn, end_stn in pick_chainages(sectors, count):
            cat, radius, rail_type, curve_dir = assign_category(ch_id)
            ch = Chainage(
                chainage_id=ch_id, track_id=track.id, bound=bound,
                sector=sector, start_station=start_stn, end_station=end_stn,
                category=cat, curve_radius=radius, rail_type=rail_type,
                curve_direction=curve_dir,
            )
            db.add(ch)
            db.flush()
            all_chainages.append((ch, cat, radius))

    # Generate measurements — mix of healthy, moderate, and critical wear
    for idx, (ch, cat, radius) in enumerate(all_chainages):
        # Create a realistic spread: ~40% healthy (SC5), ~30% moderate (SC4),
        # ~15% warning (SC3), ~15% critical (SC2/SC1)
        wear_tier = random.random()
        if wear_tier < 0.40:
            # Healthy — low wear rate, recent install
            base_rate = random.uniform(0.001, 0.003)
            days_base = random.randint(150, 300)
        elif wear_tier < 0.70:
            # Moderate — mid wear
            base_rate = random.uniform(0.003, 0.006)
            days_base = random.randint(250, 400)
        elif wear_tier < 0.85:
            # Warning — higher wear
            base_rate = random.uniform(0.005, 0.009)
            days_base = random.randint(350, 500)
        else:
            # Critical — high wear
            base_rate = random.uniform(0.008, 0.015)
            days_base = random.randint(400, 600)

        rate = base_rate * random.uniform(0.8, 1.2)

        for run_idx, run_date in enumerate(run_dates):
            days_worn = days_base + run_idx * 180 + random.randint(-20, 20)
            bw = rate * days_worn
            vals = {}
            for prefix in ["left", "right"]:
                mult = random.uniform(0.9, 1.1) if prefix == "left" else random.uniform(0.85, 1.05)
                vals[f"{prefix}_wear_0"] = round(max(0, bw * mult + random.uniform(-0.3, 0.3)), 2)
                vals[f"{prefix}_wear_22_5"] = round(max(0, bw * mult * 0.9 + random.uniform(-0.2, 0.2)), 2)
                vals[f"{prefix}_wear_45"] = round(max(0, bw * mult * 0.85 + random.uniform(-0.2, 0.2)), 2)
                vals[f"{prefix}_wear_67_5"] = round(max(0, bw * mult * 0.8 + random.uniform(-0.2, 0.2)), 2)
                vals[f"{prefix}_wear_90"] = round(max(0, bw * mult * 1.1 + random.uniform(-0.3, 0.3)), 2)

            wear_mm = max(vals.values())
            db.add(WearMeasurement(
                chainage_id=ch.id, measurement_date=run_date, wear_mm=round(wear_mm, 2),
                source_file=f"demo_run_{run_idx+1}", **vals,
            ))

    # Replacements (10 random)
    for ch, cat, radius in random.sample(all_chainages, 10):
        rep_date = date(2024, 1, 1) + timedelta(days=random.randint(0, 180))
        db.add(ReplacementLog(chainage_id=ch.id, replacement_date=rep_date, notes="Scheduled replacement"))
        db.add(WearMeasurement(
            chainage_id=ch.id, measurement_date=rep_date, wear_mm=0.0,
            left_wear_0=0.0, left_wear_22_5=0.0, left_wear_45=0.0, left_wear_67_5=0.0, left_wear_90=0.0,
            right_wear_0=0.0, right_wear_22_5=0.0, right_wear_45=0.0, right_wear_67_5=0.0, right_wear_90=0.0,
            source_file="replacement_upload",
        ))

    db.flush()

    # Global models
    for track, positions in [(nel, ["0", "90"]), (dtl, ["0", "22.5", "45", "67.5", "90"])]:
        for cat in [1, 2, 3]:
            roles = ["inner", "outer"] if cat in (2, 3) else ["both"]
            for pos in positions:
                for role in roles:
                    slope = random.uniform(0.003, 0.010)
                    db.add(GlobalModel(
                        track_id=track.id, category=cat, position=pos, rail_role=role,
                        intercept=round(random.uniform(-0.5, 0.5), 4),
                        slope=round(slope, 6),
                        curvature_coef=round(random.uniform(0.5, 2.0), 4) if cat in (2, 3) else None,
                        r_squared=round(random.uniform(0.55, 0.92), 4),
                        wear_rate_per_month=round(slope * 30.44, 4),
                        data_points_used=random.randint(24, 120),
                        chainages_contributing=random.randint(8, 40),
                        fitted_at=datetime.now(),
                    ))
    db.flush()

    # Predictions — build lookup of global models
    gm_lookup = {}
    for gm in db.query(GlobalModel).all():
        gm_lookup[(gm.track_id, gm.category, gm.position, gm.rail_role)] = gm

    # For each chainage, get latest measurement and generate predictions
    from sqlalchemy import func
    for ch, cat, radius in all_chainages:
        latest = db.query(WearMeasurement).filter(
            WearMeasurement.chainage_id == ch.id
        ).order_by(WearMeasurement.measurement_date.desc()).first()

        if not latest:
            continue

        track = nel if ch.track_id == nel.id else dtl
        positions = ["0", "90"] if track == nel else ["0", "22.5", "45", "67.5", "90"]
        roles = ["inner", "outer"] if cat in (2, 3) else ["both"]

        for pos in positions:
            for role in roles:
                gm = gm_lookup.get((track.id, cat, pos, role))
                if not gm:
                    continue

                eff_slope = gm.slope
                if cat in (2, 3) and gm.curvature_coef and radius and radius > 0:
                    eff_slope = gm.slope + gm.curvature_coef / radius
                if eff_slope <= 0:
                    eff_slope = 0.001

                days_to = max(0, (7.0 - latest.wear_mm) / eff_slope)
                thr_date = latest.measurement_date + timedelta(days=int(days_to))

                physical_side = "both"
                if role == "outer":
                    physical_side = "left" if ch.curve_direction == "right" else "right"
                elif role == "inner":
                    physical_side = "right" if ch.curve_direction == "right" else "left"

                db.add(PredictionLog(
                    chainage_id=ch.id,
                    model_type="global_model",
                    category=cat,
                    slope=round(gm.slope, 6),
                    intercept=round(gm.intercept, 4),
                    r_squared=round(random.uniform(0.55, 0.92), 4),
                    wear_rate_per_month=round(eff_slope * 30.44, 4),
                    position=pos,
                    rail_role=role,
                    physical_side=physical_side,
                    global_model_id=gm.id,
                    current_wear_mm=round(latest.wear_mm, 2),
                    predicted_repair_date=thr_date,
                    days_until_threshold=int(days_to),
                    confidence_lower_days=max(0, int(days_to * 0.7)),
                    confidence_upper_days=int(days_to * 1.3),
                    data_points_used=3,
                    data_start_date=run_dates[0],
                    data_end_date=run_dates[-1],
                ))

    db.commit()

    # Summary
    nel_count = db.query(Chainage).filter(Chainage.track_id == nel.id).count()
    dtl_count = db.query(Chainage).filter(Chainage.track_id == dtl.id).count()
    meas_count = db.query(WearMeasurement).count()
    gm_count = db.query(GlobalModel).count()
    pred_count = db.query(PredictionLog).count()
    rep_count = db.query(ReplacementLog).count()

    print(f"Demo database created at: {DB_PATH}")
    print(f"  NEL chainages: {nel_count}")
    print(f"  DTL chainages: {dtl_count}")
    print(f"  Measurements: {meas_count}")
    print(f"  Global models: {gm_count}")
    print(f"  Predictions: {pred_count}")
    print(f"  Replacements: {rep_count}")

    db.close()


if __name__ == "__main__":
    main()
