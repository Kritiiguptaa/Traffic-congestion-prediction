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