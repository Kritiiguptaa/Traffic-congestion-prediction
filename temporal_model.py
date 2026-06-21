"""
temporal_model.py

Predicts congestion impact at (latitude, longitude, datetime).

Two-layer system:
─────────────────
Layer 1 — Historical lookup (per cluster):
  Builds an hour-bucket x DOW activity profile from actual past violations.
  Fast and grounded in real history for known hotspots.

Layer 2 — Learned severity model (GradientBoosting):
  Trained on lat, lng, hour, dow, month to predict expected congestion impact.
  Generalises to locations/times with sparse or no cluster history.

Final score:
  predicted_score = severity_profile(location) x activity_likelihood(location, time)

  severity_profile  — avg_impact of nearest cluster (if close), else GB model
  activity_likelihood — cluster's historical hour/DOW activity factor (if enough
                        samples), else city-wide curve, scaled by DOW weight
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

from pipeline import DOW_WEIGHT, DOW_MIN, DOW_MAX, DOW_NAMES

EARTH_R_M = 6371000


def haversine_m(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_R_M * atan2(sqrt(a), sqrt(1 - a))


class HotspotPredictor:
    def __init__(self, scored_df: pd.DataFrame, cluster_stats: pd.DataFrame):
        self.cluster_stats = (
            cluster_stats.set_index("cluster_id") if len(cluster_stats) else cluster_stats
        )
        self.df = scored_df[scored_df["cluster_id"] != -1].copy()
        self.df = self.df.dropna(subset=["event_time"])
        self.df["hour"] = self.df["event_time"].dt.hour
        self.df["dow"]  = self.df["event_time"].dt.dayofweek

        self._build_pattern_table()
        self._build_global_time_curve()
        self._train_global_model()

    # ── Layer 1: per-cluster hour x DOW activity profile ──────────────────────
    def _build_pattern_table(self):
        if self.df.empty:
            self.pattern = pd.DataFrame(
                columns=["cluster_id", "dow", "hour_bucket", "mean_impact", "count", "activity_factor"]
            )
            return

        self.df["hour_bucket"] = (self.df["hour"] // 3) * 3

        self.pattern = (
            self.df.groupby(["cluster_id", "dow", "hour_bucket"])
            .agg(mean_impact=("congestion_impact_score", "mean"),
                 count=("congestion_impact_score", "count"))
            .reset_index()
        )
        # activity_factor: relative volume within each cluster [0.4, 1.0]
        max_count = self.pattern.groupby("cluster_id")["count"].transform("max")
        self.pattern["activity_factor"] = 0.4 + 0.6 * (self.pattern["count"] / max_count)

    def _lookup_pattern(self, cluster_id, when: datetime):
        if self.pattern.empty:
            return None
        hour_bucket = (when.hour // 3) * 3
        dow = when.weekday()
        row = self.pattern[
            (self.pattern["cluster_id"] == cluster_id)
            & (self.pattern["dow"] == dow)
            & (self.pattern["hour_bucket"] == hour_bucket)
        ]
        if row.empty:
            return None
        return {
            "mean_impact":     float(row["mean_impact"].iloc[0]),
            "count":           int(row["count"].iloc[0]),
            "activity_factor": float(row["activity_factor"].iloc[0]),
        }

    # ── City-wide hour x DOW curve (fallback) ─────────────────────────────────
    def _build_global_time_curve(self):
        if self.df.empty:
            self.global_curve = {}
            return
        g = (
            self.df.groupby(["dow", "hour_bucket"]).size().reset_index(name="count")
            if "hour_bucket" in self.df.columns
            else self.df.assign(hour_bucket=(self.df["hour"] // 3) * 3)
                         .groupby(["dow", "hour_bucket"]).size().reset_index(name="count")
        )
        max_count = g["count"].max()
        g["activity_factor"] = 0.3 + 0.7 * (g["count"] / max_count)
        self.global_curve = {
            (int(r["dow"]), int(r["hour_bucket"])): float(r["activity_factor"])
            for _, r in g.iterrows()
        }

    def _global_activity_factor(self, when: datetime) -> float:
        hour_bucket = (when.hour // 3) * 3
        dow = when.weekday()
        base = self.global_curve.get((dow, hour_bucket), 0.5)
        # scale by data-driven DOW weight (Sun=1.0 highest, Mon=0.691 lowest)
        dow_scale = (DOW_WEIGHT.get(dow, 0.845) - DOW_MIN) / (DOW_MAX - DOW_MIN)  # 0..1
        return float(np.clip(base * (0.7 + 0.3 * dow_scale), 0.1, 1.0))

    # ── Layer 2: learned severity model ───────────────────────────────────────
    def _train_global_model(self):
        if len(self.df) < 30:
            self.model = None
            return

        feat = pd.DataFrame({
            "lat":   self.df["latitude"],
            "lng":   self.df["longitude"],
            "hour":  self.df["hour"].fillna(12),
            "dow":   self.df["dow"].fillna(0),
            "month": self.df["event_time"].dt.month.fillna(1),
        })
        target = self.df["congestion_impact_score"]

        self.model = GradientBoostingRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.08, random_state=42
        )
        self.model.fit(feat, target)

    def _predict_severity(self, lat, lng, when: datetime) -> float:
        if self.model is None:
            return float(self.df["congestion_impact_score"].mean()) if not self.df.empty else 0.3
        feat = pd.DataFrame([{
            "lat":   lat,
            "lng":   lng,
            "hour":  when.hour,
            "dow":   when.weekday(),
            "month": when.month,
        }])
        return float(np.clip(self.model.predict(feat)[0], 0, 1))

    # ── Nearest cluster lookup ─────────────────────────────────────────────────
    def _nearest_cluster(self, lat, lng, max_dist_m=300):
        if self.cluster_stats is None or len(self.cluster_stats) == 0:
            return None, None
        dists = self.cluster_stats.apply(
            lambda r: haversine_m(lat, lng, r["latitude"], r["longitude"]), axis=1
        )
        nearest_id   = dists.idxmin()
        nearest_dist = dists.min()
        return (nearest_id, nearest_dist) if nearest_dist <= max_dist_m else (None, nearest_dist)

    # ── DOW impact profile for a cluster (for calendar chart) ─────────────────
    def dow_profile_for_cluster(self, cluster_id) -> dict:
        """Returns {dow_name: avg_impact} for all 7 days, using real history
        where available and the global curve as fallback."""
        profile = {}
        for dow in range(7):
            # try real cluster history for this DOW (any hour)
            rows = self.pattern[
                (self.pattern["cluster_id"] == cluster_id)
                & (self.pattern["dow"] == dow)
            ] if not self.pattern.empty else pd.DataFrame()

            if not rows.empty:
                val = float(rows["mean_impact"].mean())
            else:
                # fallback: global average for this DOW
                dow_rows = [v for (d, _), v in self.global_curve.items() if d == dow]
                val = float(np.mean(dow_rows)) if dow_rows else 0.3

            profile[DOW_NAMES[dow]] = round(val, 3)
        return profile

    # ── Public API ─────────────────────────────────────────────────────────────
    def predict(self, lat: float, lng: float, when: datetime) -> dict:
        """
        Returns predicted congestion impact + breakdown at (lat, lng, when).

        Fields:
          predicted_score        — final 0..1 congestion impact
          risk_level             — low / medium / high
          severity_score         — location-based severity component
          activity_factor        — time-based activity component
          severity_source        — 'cluster_history' or 'model'
          activity_source        — 'cluster_history' or 'city_average'
          nearest_cluster_id     — closest cluster (if within 300m)
          nearest_cluster_dist_m
          historical_sample_size — violations in that cluster/hour/dow bucket
          dow_name               — day name for the queried datetime
          dow_weight             — the DOW weight applied (0.3..1.0)
          dow_profile            — {Mon..Sun: avg_impact} for nearest cluster
        """
        cluster_id, dist_m = self._nearest_cluster(lat, lng)
        dow = when.weekday()
        dow_w = DOW_WEIGHT.get(dow, 0.65)

        result = {
            "nearest_cluster_id":       None,
            "nearest_cluster_dist_m":   None,
            "historical_sample_size":   0,
            "severity_source":          "model",
            "activity_source":          "city_average",
            "dow_name":                 DOW_NAMES[dow],
            "dow_weight":               round(dow_w, 2),
            "dow_profile":              {},
        }

        # severity
        if cluster_id is not None and cluster_id in self.cluster_stats.index:
            severity = float(self.cluster_stats.loc[cluster_id, "avg_impact"])
            result["severity_source"] = "cluster_history"
            result["dow_profile"] = self.dow_profile_for_cluster(cluster_id)
        else:
            severity = self._predict_severity(lat, lng, when)

        # activity likelihood
        activity_factor = self._global_activity_factor(when)
        if cluster_id is not None:
            pattern_hit = self._lookup_pattern(cluster_id, when)
            if pattern_hit is not None and pattern_hit["count"] >= 2:
                # blend cluster's historical activity with data-driven DOW weight
                raw_activity = pattern_hit["activity_factor"]
                dow_scale = (dow_w - DOW_MIN) / (DOW_MAX - DOW_MIN)  # 0..1, Sun=1 Mon=0
                activity_factor = float(np.clip(raw_activity * (0.7 + 0.3 * dow_scale), 0.1, 1.0))
                result["activity_source"]        = "cluster_history"
                result["historical_sample_size"] = pattern_hit["count"]

        if cluster_id is not None:
            result["nearest_cluster_id"]     = int(cluster_id)
            result["nearest_cluster_dist_m"] = round(float(dist_m), 1)

        predicted_score = float(np.clip(severity * activity_factor, 0, 1))
        result["severity_score"]  = round(severity, 3)
        result["activity_factor"] = round(activity_factor, 3)
        result["predicted_score"] = round(predicted_score, 3)
        result["risk_level"]      = self._risk_label(predicted_score)
        return result

    @staticmethod
    def _risk_label(score: float) -> str:
        if score >= 0.45:
            return "high"
        elif score >= 0.25:
            return "medium"
        return "low"