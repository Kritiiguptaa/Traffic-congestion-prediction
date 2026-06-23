"""
server.py
Flask backend for the hotspot map frontend.

Endpoints:
  GET  /api/clusters              -> all current hotspot clusters (for map markers/heatmap)
  GET  /api/predict?lat&lng&when  -> risk prediction for an arbitrary point/time
  GET  /api/geocode?q=            -> simple location-name search against known clusters/locations
  POST /api/refresh                -> re-run pipeline against latest data file (for "real-time" ingestion)
  GET  /                           -> serves the frontend
"""
import os
import math
import pandas as pd
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory


def clean_str(v, default=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return default
    return str(v)

from pipeline import run_pipeline
from temporal_model import HotspotPredictor

DATA_FILE = os.environ.get(
    "VIOLATIONS_FILE",
    "jan to may police violation_anonymized791b166_without_null_only_columns.xlsx"
)

app = Flask(__name__, static_folder="static", static_url_path="")

# ---- in-memory state, rebuilt on refresh ----
state = {"scored": None, "stats": None, "predictor": None, "last_loaded": None}


def load_state():
    scored, stats = run_pipeline(DATA_FILE)
    predictor = HotspotPredictor(scored, stats)
    state["scored"] = scored
    state["stats"] = stats
    state["predictor"] = predictor
    state["last_loaded"] = datetime.now().isoformat()
    print(f"[server] Loaded {len(scored)} rows, {len(stats)} clusters at {state['last_loaded']}")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/clusters")
def api_clusters():
    stats = state["stats"]
    if stats is None or stats.empty:
        return jsonify({"clusters": [], "last_loaded": state["last_loaded"]})

    when_str = request.args.get("when")
    when = None
    if when_str:
        try:
            when = datetime.fromisoformat(when_str)
        except ValueError:
            return jsonify({"error": "when must be ISO format, e.g. 2024-12-16T09:00"}), 400

    predictor = state["predictor"]

    out = []
    for cid, row in stats.iterrows():
        lat, lng = float(row["latitude"]), float(row["longitude"])
        if when is not None and predictor is not None:
            predicted_score = predictor.predict(lat, lng, when)["predicted_score"]
        else:
            predicted_score = round(float(row["cluster_score"]), 3)

        out.append({
            "cluster_id": int(row["cluster_id"]),
            "latitude": lat,
            "longitude": lng,
            "violations": int(row["violations"]),
            "avg_impact": round(float(row["avg_impact"]), 3),
            "cluster_score": round(float(row["cluster_score"]), 3),
            "predicted_score": predicted_score,
            "police_station": clean_str(row.get("police_station")),
            "junction_name": clean_str(row.get("junction_name")),
            "location": clean_str(row.get("location")),
            "peak_dow_name": clean_str(row.get("peak_dow_name"), None),
            "peak_hour": None if pd.isna(row.get("peak_hour")) else int(row.get("peak_hour")),
            "trend_pct": float(row.get("trend_pct", 0.0)),
            "trend_label": clean_str(row.get("trend_label"), "stable"),
            "quadrant": clean_str(row.get("quadrant")),
        })
    return jsonify({"clusters": out, "last_loaded": state["last_loaded"]})


@app.route("/api/predict")
def api_predict():
    try:
        lat = float(request.args.get("lat"))
        lng = float(request.args.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required and must be numeric"}), 400

    when_str = request.args.get("when")
    if when_str:
        try:
            when = datetime.fromisoformat(when_str)
        except ValueError:
            return jsonify({"error": "when must be ISO format, e.g. 2024-12-16T09:00"}), 400
    else:
        when = datetime.now()

    predictor = state["predictor"]
    if predictor is None:
        return jsonify({"error": "model not loaded yet"}), 503

    result = predictor.predict(lat, lng, when)
    result["query"] = {"lat": lat, "lng": lng, "when": when.isoformat()}
    return jsonify(result)


@app.route("/api/geocode")
def api_geocode():
    """Very lightweight search: match against known cluster locations / police stations / junctions."""
    q = (request.args.get("q") or "").strip().lower()
    stats = state["stats"]
    if not q or stats is None or stats.empty:
        return jsonify({"results": []})

    matches = []
    for cid, row in stats.iterrows():
        haystack = " ".join(str(row.get(k, "")) for k in ["location", "police_station", "junction_name"]).lower()
        if q in haystack:
            matches.append({
                "cluster_id": int(row["cluster_id"]),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "label": clean_str(row.get("location")) or clean_str(row.get("police_station")),
                "police_station": clean_str(row.get("police_station")),
                "junction_name": clean_str(row.get("junction_name")),
                "cluster_score": round(float(row["cluster_score"]), 3),
            })
    matches.sort(key=lambda m: -m["cluster_score"])
    return jsonify({"results": matches[:10]})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Re-run the pipeline against the current data file. Call this after new data lands
    (e.g. from a cron job, a file-watcher, or a webhook from your ingestion system)."""
    try:
        load_state()
        return jsonify({"status": "ok", "last_loaded": state["last_loaded"], "rows": len(state["scored"])})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/status")
def api_status():
    return jsonify({
        "last_loaded": state["last_loaded"],
        "rows": len(state["scored"]) if state["scored"] is not None else 0,
        "clusters": len(state["stats"]) if state["stats"] is not None else 0,
    })


if __name__ == "__main__":
    load_state()
    app.run(host="0.0.0.0", port=5000, debug=True)
