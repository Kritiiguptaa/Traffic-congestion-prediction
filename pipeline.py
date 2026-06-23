"""
pipeline.py

Core scoring and clustering pipeline.

Impact score formula (weights sum to 1.0):
  violation_priority  30%   (high/med/low based on traffic danger)
  vehicle_priority    22%   (large/heavy vehicles = higher congestion)
  junction_flag       22%   (at junction = high, no junction = low — binary)
  recency             13%   (recent violations weighted higher)
  day_of_week         13%   (data-driven from actual dataset volume per day)

Output: congestion_impact_score per row, cluster_stats with per-cluster
        DOW breakdown (used by predictor and frontend calendar view).
"""
import pandas as pd
import numpy as np
import ast
from sklearn.cluster import DBSCAN

from clean_data import clean_raw_violations

# ─────────────────────────────────────────────
# VIOLATION PRIORITY  (3=High, 2=Medium, 1=Low)
# ─────────────────────────────────────────────
VIOLATION_PRIORITY = {
    # HIGH — direct traffic danger / obstruction
    "AGAINST ONE WAY/NO ENTRY": 3,
    "JUMPING TRAFFIC SIGNAL": 3,
    "DOUBLE PARKING": 3,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 3,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 3,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 3,
    "PARKING IN A MAIN ROAD": 3,
    "H T V PROHIBITED": 3,
    "STOPING ON WHITE/STOP LINE": 3,
    "U TURN PROHIBITED": 3,
    "VIOLATING LANE DISIPLINE": 3,
    "WRONG PARKING": 3,

    # MEDIUM — notable but secondary impact
    "NO PARKING": 2,
    "PARKING OTHER THAN BUS STOP": 2,
    "CARRYING LENGHTY MATERIAL": 2,
    "USING BLACK FILM/OTHER MATERIALS": 2,
    "PARKING NEAR ROAD CROSSING": 2,
    "OBSTRUCTING DRIVER": 2,

    # LOW — minor / non-traffic violations
    "PARKING ON FOOTPATH": 1,
    "2W/3W - USING MOBILE PHONE": 1,
    "OTHER - USING MOBILE PHONE": 1,
    "FAIL TO USE SAFETY BELTS": 1,
    "RIDER NOT WEARING HELMET": 1,
    "DEFECTIVE NUMBER PLATE": 1,
    "WITHOUT SIDE MIRROR": 1,
    "DEMANDING EXCESS FARE": 1,
    "REFUSE TO GO FOR HIRE": 1,
}
DEFAULT_VIOLATION_PRIORITY = 2

# ─────────────────────────────────────────────
# VEHICLE PRIORITY  (3=High, 2=Medium, 1=Low)
# ─────────────────────────────────────────────
VEHICLE_PRIORITY = {
    # HIGH — large/heavy, max congestion footprint
    "BUS (BMTC/KSRTC)": 3, "FACTORY BUS": 3, "PRIVATE BUS": 3,
    "SCHOOL VEHICLE": 3, "TOURIST BUS": 3,
    "HGV": 3, "LORRY/GOODS VEHICLE": 3, "MINI LORRY": 3,
    "TANKER": 3, "TRACTOR": 3,

    # MEDIUM
    "CAR": 2, "GOODS AUTO": 2, "JEEP": 2, "LGV": 2,
    "TEMPO": 2, "VAN": 2, "MAXI-CAB": 2,

    # LOW — small footprint
    "MOPED": 1, "MOTOR CYCLE": 1, "SCOOTER": 1,
    "PASSENGER AUTO": 1, "OTHERS": 1,
}
DEFAULT_VEHICLE_PRIORITY = 2

# ─────────────────────────────────────────────
# JUNCTION FLAG  (binary: junction=1, no junction=0)
# ─────────────────────────────────────────────
# Any named junction = high priority (1), no junction = low priority (0).
# Normalisation: already 0/1, maps directly to norm_junction.
def _junction_flag(x) -> int:
    if pd.isna(x) or str(x).strip().lower() == "no junction":
        return 0   # low — no junction
    return 1       # high — any named junction


# ─────────────────────────────────────────────
# DAY-OF-WEEK WEIGHT  — data-driven from actual dataset
# Derived from violation volume per day (298,445 total rows):
#   Sun 50,160 (16.8%) → 1.000  Mon 34,680 (11.6%) → 0.691
# Higher volume = higher congestion likelihood on that day.
# ─────────────────────────────────────────────
DOW_WEIGHT = {
    0: 0.691,  # Monday    — 34,680 violations (lowest)
    1: 0.851,  # Tuesday   — 42,697
    2: 0.836,  # Wednesday — 41,974
    3: 0.868,  # Thursday  — 43,547
    4: 0.814,  # Friday    — 40,864
    5: 0.887,  # Saturday  — 44,523
    6: 1.000,  # Sunday    — 50,160 violations (highest)
}
DOW_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
DOW_MIN, DOW_MAX = 0.691, 1.000

# ─────────────────────────────────────────────
# SCORING WEIGHTS  (must sum to 1.0)
# ─────────────────────────────────────────────
W_VIOLATION = 0.30
W_VEHICLE   = 0.22
W_JUNCTION  = 0.22
W_RECENCY   = 0.13
W_DOW       = 0.13

# ─────────────────────────────────────────────
# CARRIAGEWAY IMPACT MODEL  — "quantify impact on traffic flow"
# ─────────────────────────────────────────────
# Unlike the generic priority score above, this models how much a violation
# physically OBSTRUCTS the carriageway (moving lanes). This is the key
# distinction for parking-induced congestion: a double-parked car blocks a
# lane; a rider without a helmet blocks nothing.
#
# LANE_BLOCK_WEIGHT ∈ [0,1]:  1.0 = fully blocks a moving lane,
#                             0.0 = no carriageway obstruction at all.
LANE_BLOCK_WEIGHT = {
    # SEVERE — directly blocks a moving/through lane
    "DOUBLE PARKING": 1.00,
    "PARKING IN A MAIN ROAD": 0.90,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 0.85,  # creates a chokepoint
    "AGAINST ONE WAY/NO ENTRY": 0.80,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 0.80,
    "H T V PROHIBITED": 0.75,

    # HIGH — blocks flow at a critical point / partial lane
    "VIOLATING LANE DISIPLINE": 0.65,
    "STOPING ON WHITE/STOP LINE": 0.60,
    "WRONG PARKING": 0.60,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 0.60,
    "U TURN PROHIBITED": 0.55,

    # MEDIUM — narrows the carriageway / kerb-side obstruction
    "NO PARKING": 0.50,
    "PARKING NEAR ROAD CROSSING": 0.50,
    "PARKING OTHER THAN BUS STOP": 0.45,
    "CARRYING LENGHTY MATERIAL": 0.40,
    "OBSTRUCTING DRIVER": 0.40,
    "JUMPING TRAFFIC SIGNAL": 0.30,  # transient, not a standing blockage

    # LOW — pushes obstruction onto footpath, not the carriageway
    "PARKING ON FOOTPATH": 0.15,

    # NONE — moving / paperwork / safety violations, zero carriageway impact
    "2W/3W - USING MOBILE PHONE": 0.0,
    "OTHER - USING MOBILE PHONE": 0.0,
    "FAIL TO USE SAFETY BELTS": 0.0,
    "RIDER NOT WEARING HELMET": 0.0,
    "DEFECTIVE NUMBER PLATE": 0.0,
    "WITHOUT SIDE MIRROR": 0.0,
    "USING BLACK FILM/OTHER MATERIALS": 0.0,
    "DEMANDING EXCESS FARE": 0.0,
    "REFUSE TO GO FOR HIRE": 0.0,
}
DEFAULT_LANE_BLOCK = 0.40  # unknown type → assume moderate obstruction

# Vehicle footprint = relative carriageway area a stopped vehicle occupies.
# Derived from the existing vehicle priority tiers (1=2W/auto, 2=car, 3=bus/truck).
VEHICLE_FOOTPRINT = {1: 0.40, 2: 1.00, 3: 2.20}

# Junction amplification: a vehicle obstructing at/near a junction backs up
# far more traffic (queue spillback) than one mid-block.
JUNCTION_AMPLIFY = 1.50

# Max possible per-incident obstruction (worst weight × worst footprint × junction),
# used to normalise obstruction intensity to [0,1].
MAX_ROW_BLOCK = 1.00 * 2.20 * JUNCTION_AMPLIFY  # = 3.30

# Illustrative traffic assumptions (clearly-labelled estimates, shown in the UI):
#   LANE_FLOW  — typical urban-arterial throughput per lane at peak (veh/hr).
#                Conservative vs the ~1800 pcphpl textbook saturation flow.
#   MAX_CAP_CUT — worst-case share of one lane's capacity a chronic hotspot cuts.
LANE_FLOW = 1500
MAX_CAP_CUT = 0.50

TIMESTAMP_CANDIDATES = [
    "created_datetime_ist", "created_datetime",
    "modified_datetime_ist", "modified_datetime",
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _violation_score(v):
    """Max priority among all violation types in a row (stored as a list string)."""
    try:
        vals = ast.literal_eval(v) if isinstance(v, str) else v
        scores = [
            VIOLATION_PRIORITY.get(str(x).strip().upper(), DEFAULT_VIOLATION_PRIORITY)
            for x in vals
        ]
        return max(scores)
    except Exception:
        return VIOLATION_PRIORITY.get(str(v).strip().upper(), DEFAULT_VIOLATION_PRIORITY)


def _parse_violation_list(v):
    """Normalise a row's violation_type (list-string or scalar) to an UPPER list."""
    try:
        vals = ast.literal_eval(v) if isinstance(v, str) else v
        return [str(x).strip().upper() for x in vals]
    except Exception:
        return [str(v).strip().upper()]


def _lane_block_score(v):
    """Worst carriageway-obstruction weight among a row's violation types [0,1]."""
    vals = _parse_violation_list(v)
    return max((LANE_BLOCK_WEIGHT.get(x, DEFAULT_LANE_BLOCK) for x in vals), default=DEFAULT_LANE_BLOCK)


def _top_block_violation(v):
    """The single violation type in a row that contributes the most obstruction —
    used to explain *why* a hotspot is congested (the dominant blocking cause)."""
    vals = _parse_violation_list(v)
    if not vals:
        return ""
    return max(vals, key=lambda x: LANE_BLOCK_WEIGHT.get(x, DEFAULT_LANE_BLOCK))


# ─────────────────────────────────────────────
# LOAD + SCORE
# ─────────────────────────────────────────────
def load_and_score(filepath: str) -> pd.DataFrame:
    df = clean_raw_violations(filepath)

    # ── timestamp ──
    ts_col = next((c for c in TIMESTAMP_CANDIDATES if c in df.columns), None)
    if ts_col is not None:
        df["event_time"] = df[ts_col]
        latest = df[ts_col].max()
        if pd.notna(latest):
            days_old = (latest - df[ts_col]).dt.days.fillna(0)
            max_days = max(days_old.max(), 1)
            df["recency_weight"] = 1 + 2 * (1 - days_old / max_days)   # [1, 3]
        else:
            df["recency_weight"] = 2.0
    else:
        df["event_time"] = pd.NaT
        df["recency_weight"] = 2.0

    # ── day of week ──
    if ts_col is not None and pd.api.types.is_datetime64_any_dtype(df["event_time"]):
        df["dow"] = df["event_time"].dt.dayofweek          # 0=Mon … 6=Sun
        df["dow_name"] = df["dow"].map(DOW_NAMES)
        df["dow_raw"] = df["dow"].map(DOW_WEIGHT).fillna(0.65)
    else:
        df["dow"] = np.nan
        df["dow_name"] = "Unknown"
        df["dow_raw"] = 0.65   # mid-range fallback

    # ── hour of day (for temporal model) ──
    if ts_col is not None and pd.api.types.is_datetime64_any_dtype(df["event_time"]):
        df["hour"] = df["event_time"].dt.hour
    else:
        df["hour"] = np.nan

    # ── violation priority ──
    df["violation_priority"] = df["violation_type"].apply(_violation_score)   # [1, 3]

    # ── vehicle priority ──
    df["vehicle_priority"] = (
        df["vehicle_type_final"].astype(str).str.strip().str.upper()
        .map(VEHICLE_PRIORITY).fillna(DEFAULT_VEHICLE_PRIORITY)
    )   # [1, 3]

    # ── junction flag ──
    df["junction_flag"] = df["junction_name"].apply(_junction_flag)   # 0 or 1

    # ── carriageway obstruction (traffic-flow impact model) ──
    df["lane_block"] = df["violation_type"].apply(_lane_block_score)        # [0, 1]
    df["top_block_violation"] = df["violation_type"].apply(_top_block_violation)
    df["vehicle_footprint"] = df["vehicle_priority"].map(VEHICLE_FOOTPRINT).fillna(1.0)
    junction_mult = np.where(df["junction_flag"] == 1, JUNCTION_AMPLIFY, 1.0)
    # per-incident obstruction, normalised to [0, 1] against the worst possible case
    df["obstruction_intensity"] = (
        df["lane_block"] * df["vehicle_footprint"] * junction_mult / MAX_ROW_BLOCK
    ).clip(0, 1)

    # ── normalise all components to [0, 1] ──
    norm_violation = (df["violation_priority"] - 1) / 2    # 1..3 -> 0..1
    norm_vehicle   = (df["vehicle_priority"]   - 1) / 2    # 1..3 -> 0..1
    norm_junction  = df["junction_flag"]                    # already 0..1
    norm_recency   = (df["recency_weight"]     - 1) / 2    # 1..3 -> 0..1
    norm_dow       = (df["dow_raw"] - DOW_MIN) / (DOW_MAX - DOW_MIN)   # 0..1

    df["congestion_impact_score"] = (
        W_VIOLATION * norm_violation
        + W_VEHICLE  * norm_vehicle
        + W_JUNCTION * norm_junction
        + W_RECENCY  * norm_recency
        + W_DOW      * norm_dow
    )

    return df


# ─────────────────────────────────────────────
# CLUSTERING
# ─────────────────────────────────────────────
def cluster_hotspots(df: pd.DataFrame, eps_m: float = 200, min_samples: int = 20) -> pd.DataFrame:
    coords = np.radians(df[["latitude", "longitude"]])
    db = DBSCAN(eps=eps_m / 6371000, min_samples=min_samples, metric="haversine", n_jobs=-1)
    df = df.copy()
    df["cluster_id"] = db.fit_predict(coords)
    return df


# ─────────────────────────────────────────────
# CLUSTER STATS  (with per-DOW breakdown)
# ─────────────────────────────────────────────
def build_cluster_stats(df: pd.DataFrame) -> pd.DataFrame:
    hotspots = df[df["cluster_id"] != -1].copy()
    if hotspots.empty:
        return pd.DataFrame(columns=[
            "cluster_id", "violations", "latitude", "longitude",
            "avg_impact", "police_station", "junction_name", "location",
            "cluster_score", "dow_profile",
        ])

    agg = {
        "violations":     ("cluster_id", "count"),
        "latitude":       ("latitude", "mean"),
        "longitude":      ("longitude", "mean"),
        "avg_impact":     ("congestion_impact_score", "mean"),
        "police_station": ("police_station", lambda x: x.mode().iloc[0] if not x.mode().empty else ""),
        "location":       ("location", lambda x: x.iloc[0]),
    }
    if "junction_name" in hotspots.columns:
        agg["junction_name"] = ("junction_name", lambda x: x.mode().iloc[0] if not x.mode().empty else "")

    cluster_stats = hotspots.groupby("cluster_id").agg(**agg).reset_index()
    cluster_stats["cluster_score"] = (
        cluster_stats["avg_impact"] * np.log1p(cluster_stats["violations"])
    )
    cluster_stats = cluster_stats.sort_values("cluster_score", ascending=False).reset_index(drop=True)

    # ── per-DOW breakdown: avg congestion impact by day for each cluster ──
    # Used by predictor and by the frontend DOW chart.
    if "dow" in hotspots.columns and hotspots["dow"].notna().any():
        dow_profile = (
            hotspots.groupby(["cluster_id", "dow"])["congestion_impact_score"]
            .mean()
            .reset_index()
            .rename(columns={"congestion_impact_score": "avg_impact"})
        )
        dow_profile["dow_name"] = dow_profile["dow"].map(DOW_NAMES)

        # Pivot to wide dict per cluster: {0: 0.45, 1: 0.52, ...}
        dow_dict = (
            dow_profile.groupby("cluster_id")
            .apply(lambda g: dict(zip(g["dow"].astype(int), g["avg_impact"].round(3))), include_groups=False)
            .to_dict()
        )
        cluster_stats["dow_profile"] = cluster_stats["cluster_id"].map(dow_dict).apply(
            lambda d: d if isinstance(d, dict) else {}
        )
    else:
        cluster_stats["dow_profile"] = [{}] * len(cluster_stats)

    # ── peak day/hour: busiest dow+hour combo per cluster, by volume ──
    if "dow" in hotspots.columns and "hour" in hotspots.columns and hotspots["dow"].notna().any():
        peak = (
            hotspots.dropna(subset=["dow", "hour"])
            .groupby(["cluster_id", "dow", "hour"])
            .size()
            .reset_index(name="cnt")
        )
        if not peak.empty:
            top_idx = peak.groupby("cluster_id")["cnt"].idxmax()
            peak_rows = peak.loc[top_idx].set_index("cluster_id")
            cluster_stats["peak_dow_name"] = cluster_stats["cluster_id"].map(
                peak_rows["dow"].astype(int).map(DOW_NAMES)
            )
            cluster_stats["peak_hour"] = cluster_stats["cluster_id"].map(
                peak_rows["hour"].astype(int)
            )
    if "peak_dow_name" not in cluster_stats.columns:
        cluster_stats["peak_dow_name"] = None
        cluster_stats["peak_hour"] = None

    # ── trend: is violation volume rising or falling within the data window? ──
    cluster_stats["trend_pct"] = 0.0
    cluster_stats["trend_label"] = "stable"
    if "event_time" in hotspots.columns:
        trend_map = (
            hotspots.groupby("cluster_id")
            .apply(_cluster_trend, include_groups=False)
            .to_dict()
        )
        cluster_stats["trend_pct"] = cluster_stats["cluster_id"].map(
            lambda cid: trend_map.get(cid, (0.0, "stable"))[0]
        )
        cluster_stats["trend_label"] = cluster_stats["cluster_id"].map(
            lambda cid: trend_map.get(cid, (0.0, "stable"))[1]
        )

    # ── quadrant: frequency (violation volume) x severity (avg impact), split on the
    # median across all clusters -- tells police whether an area needs steady patrolling
    # (frequent) vs a one-off severe-incident watch (rare & severe), etc. ──
    med_violations = cluster_stats["violations"].median()
    med_impact = cluster_stats["avg_impact"].median()
    cluster_stats["quadrant"] = cluster_stats.apply(
        lambda r: ("Frequent" if r["violations"] >= med_violations else "Rare")
        + " & "
        + ("Severe" if r["avg_impact"] >= med_impact else "Mild"),
        axis=1,
    )

    # ── traffic-flow impact: quantify how much each hotspot chokes the carriageway ──
    cluster_stats = _add_traffic_flow_impact(cluster_stats, hotspots)

    return cluster_stats


def _add_traffic_flow_impact(cluster_stats: pd.DataFrame, hotspots: pd.DataFrame) -> pd.DataFrame:
    """Quantify each hotspot's impact on traffic flow and attach explainable
    components. Produces:
      tfi_index            — Traffic-Flow Impact, 0..100 (headline ranking metric)
      obstruction_intensity— mean per-incident carriageway obstruction, 0..1
      pct_lane_capacity_cut— est. % of one lane's capacity lost (illustrative)
      veh_affected_peak    — est. vehicles delayed per peak hour (illustrative)
      junction_share       — fraction of incidents at/near a junction
      mean_footprint       — mean vehicle footprint (lane area occupied)
      volume_factor        — 0..1, how sustained/repeated the blockage is
      block_reason         — dominant blocking violation type (plain-English cause)
    """
    if not {"obstruction_intensity", "lane_block"}.issubset(hotspots.columns):
        # impact columns missing (older data path) — fill neutral defaults
        for col, val in [("tfi_index", 0), ("obstruction_intensity", 0.0),
                         ("pct_lane_capacity_cut", 0.0), ("veh_affected_peak", 0),
                         ("junction_share", 0.0), ("mean_footprint", 1.0),
                         ("volume_factor", 0.0), ("block_reason", "")]:
            cluster_stats[col] = val
        return cluster_stats

    imp = hotspots.groupby("cluster_id").agg(
        obstruction_intensity=("obstruction_intensity", "mean"),
        mean_footprint=("vehicle_footprint", "mean"),
        junction_share=("junction_flag", "mean"),
        block_reason=("top_block_violation",
                      lambda x: x.mode().iloc[0] if not x.mode().empty else ""),
    ).reset_index()
    cluster_stats = cluster_stats.merge(imp, on="cluster_id", how="left")

    # volume/persistence: a hotspot blocking the road repeatedly matters more than
    # a one-off. Log-scaled so a handful of huge clusters don't flatten everything.
    max_v = max(cluster_stats["violations"].max(), 1)
    cluster_stats["volume_factor"] = (
        np.log1p(cluster_stats["violations"]) / np.log1p(max_v)
    ).round(3)

    # Traffic-Flow Impact: obstruction severity dominates, modulated by how
    # sustained the blockage is. Scaled to 0..100 across all hotspots for ranking.
    tfi_raw = cluster_stats["obstruction_intensity"] * (0.5 + 0.5 * cluster_stats["volume_factor"])
    tfi_max = max(tfi_raw.max(), 1e-9)
    cluster_stats["tfi_index"] = (tfi_raw / tfi_max * 100).round().astype(int)

    # Tangible, clearly-labelled estimates of the flow impact.
    cluster_stats["pct_lane_capacity_cut"] = (
        cluster_stats["obstruction_intensity"] * MAX_CAP_CUT * 100
    ).round(1)
    med_v = max(cluster_stats["violations"].median(), 1)
    persistence = (cluster_stats["violations"] / med_v).clip(0.2, 1.5)
    cluster_stats["veh_affected_peak"] = (
        cluster_stats["obstruction_intensity"] * MAX_CAP_CUT * LANE_FLOW * persistence
    ).round().astype(int)

    # tidy up the explainability fields
    cluster_stats["obstruction_intensity"] = cluster_stats["obstruction_intensity"].round(3)
    cluster_stats["mean_footprint"] = cluster_stats["mean_footprint"].round(2)
    cluster_stats["junction_share"] = cluster_stats["junction_share"].round(3)
    cluster_stats["block_reason"] = (
        cluster_stats["block_reason"].fillna("").astype(str).str.title()
    )
    return cluster_stats


def _cluster_trend(g: pd.DataFrame, min_rows: int = 10):
    """Compare violation rate (per day) in the first vs second half of a cluster's
    history. Returns (trend_pct, trend_label) where label is rising/falling/stable
    using a +-15% threshold."""
    g = g.dropna(subset=["event_time"]).sort_values("event_time")
    if len(g) < min_rows:
        return 0.0, "stable"

    median_time = g["event_time"].median()
    first = g[g["event_time"] <= median_time]
    second = g[g["event_time"] > median_time]
    if first.empty or second.empty:
        return 0.0, "stable"

    span_first = max((first["event_time"].max() - first["event_time"].min()).days, 1)
    span_second = max((second["event_time"].max() - second["event_time"].min()).days, 1)
    rate_first = len(first) / span_first
    rate_second = len(second) / span_second

    if rate_first == 0:
        pct = 100.0 if rate_second > 0 else 0.0
    else:
        pct = (rate_second - rate_first) / rate_first * 100

    if pct >= 15:
        label = "rising"
    elif pct <= -15:
        label = "falling"
    else:
        label = "stable"
    return round(pct, 1), label


# ─────────────────────────────────────────────
# FULL PIPELINE
# ─────────────────────────────────────────────
def run_pipeline(filepath: str, eps_m: float = 200, min_samples: int = 20):
    """Load -> score -> cluster -> aggregate. Returns (scored_df, cluster_stats)."""
    df = load_and_score(filepath)
    df = cluster_hotspots(df, eps_m=eps_m, min_samples=min_samples)
    stats = build_cluster_stats(df)
    return df, stats


if __name__ == "__main__":
    scored, stats = run_pipeline(
        "jan to may police violation_anonymized791b166_without_null_only_columns.xlsx"
    )
    print(f"Rows scored : {len(scored)}")
    print(f"Clusters    : {len(stats)}")
    print(stats[["cluster_id", "violations", "avg_impact", "cluster_score", "dow_profile"]].head(10).to_string())
    stats.to_csv("hotspots.csv", index=False)