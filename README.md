# Bengaluru Parking Hotspots — AI-Driven Parking Intelligence

Built for **Flipkart GRiD 2.0**, problem statement: *"Poor Visibility on Parking-Induced Congestion"* —
how can AI-driven parking intelligence detect illegal parking hotspots and quantify their impact on
traffic flow, to enable targeted enforcement?

This project turns raw Bengaluru traffic-police violation records into:
1. **Hotspot detection** — DBSCAN clustering of violation locations.
2. **Traffic-Flow Impact Model** — quantifies how much carriageway capacity each hotspot actually
   blocks, not just how many violations occurred there.
3. **Time-aware risk prediction** — forecasts how risky a location is at any future date/time.
4. **Predictive patrol planning** — turns the above into a ranked, shift-by-shift enforcement plan.

Live demo: https://huggingface.co/spaces/armaangarg3103/parking-hotspots

---

## Project structure

```
├── clean_data.py       Raw export cleaning (UTC→IST, NULL normalization, vehicle coalescing)
├── pipeline.py         Scoring, DBSCAN clustering, cluster stats, Traffic-Flow Impact Model
├── temporal_model.py   Two-layer time-aware congestion predictor (severity × activity likelihood)
├── server.py           Flask API + static file server (gunicorn-ready for deployment)
├── static/
│   ├── index.html      Hub-and-spoke dashboard + Leaflet map UI
│   └── dashboard.js     Dashboard logic: impact explainability, patrol plan, analytics, stations
├── analyze_dow.py      One-off script: data-driven day-of-week weights from the dataset
├── requirements.txt    Python dependencies (pinned for reproducible builds)
├── Dockerfile          Hugging Face Spaces (Docker SDK) deployment image
└── README.md
```

## Setup (local)

```bash
pip install -r requirements.txt
```

Place your data file in the same folder as `server.py`:
```
jan to may police violation_anonymized791b166_without_null_only_columns.xlsx
```
Or point at it via environment variable:
```bash
export VIOLATIONS_FILE=/path/to/your/file.xlsx
python server.py
```

Then open **http://localhost:5000**

## Deployment

Deployed on **Hugging Face Spaces** (Docker SDK) — chosen over serverless platforms like Vercel
because the in-memory pipeline (DBSCAN + Gradient Boosting over ~300k rows) needs ~1.5–2GB RAM and
1-2 minutes to boot, which exceeds typical serverless memory/timeout limits.

The `Dockerfile` downloads the dataset from this GitHub repo's raw URL at build time (kept out of the
Space's git history to stay lean), then serves the app via `gunicorn` with a single worker (one
in-memory model copy) and a long boot timeout.

```bash
docker build -t parking-hotspots .
docker run -p 7860:7860 parking-hotspots
```

---

## Scoring formula

Each violation row gets a `congestion_impact_score` (0–1) from 5 components:

| Component | Weight | Range | Notes |
|-----------|--------|-------|-------|
| `violation_priority` | 30% | 1–3 | High/Med/Low based on traffic danger |
| `vehicle_priority` | 22% | 1–3 | Large/heavy vehicles score higher |
| `junction_flag` | 22% | 0 or 1 | Binary: any named junction = 1, no junction = 0 |
| `recency_weight` | 13% | 1–3 | Recent violations weighted higher |
| `dow_weight` | 13% | 0–1 | Data-driven from actual dataset volume per day |

All components are normalised to [0, 1] before the weighted sum.

### Violation priority

| Priority | Violations |
|----------|-----------|
| **High (3)** | AGAINST ONE WAY/NO ENTRY, JUMPING TRAFFIC SIGNAL, DOUBLE PARKING, PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS, PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC, PARKING OPPOSITE TO ANOTHER PARKED VEHICLE, PARKING IN A MAIN ROAD, H T V PROHIBITED, STOPING ON WHITE/STOP LINE, U TURN PROHIBITED, VIOLATING LANE DISIPLINE, WRONG PARKING |
| **Medium (2)** | NO PARKING, PARKING OTHER THAN BUS STOP, CARRYING LENGHTY MATERIAL, USING BLACK FILM/OTHER MATERIALS, PARKING NEAR ROAD CROSSING, OBSTRUCTING DRIVER |
| **Low (1)** | PARKING ON FOOTPATH, 2W/3W - USING MOBILE PHONE, OTHER - USING MOBILE PHONE, FAIL TO USE SAFETY BELTS, RIDER NOT WEARING HELMET, DEFECTIVE NUMBER PLATE, WITHOUT SIDE MIRROR, DEMANDING EXCESS FARE, REFUSE TO GO FOR HIRE |

### Vehicle priority

| Priority | Vehicles |
|----------|---------|
| **High (3)** | BUS (BMTC/KSRTC), FACTORY BUS, PRIVATE BUS, SCHOOL VEHICLE, TOURIST BUS, HGV, LORRY/GOODS VEHICLE, MINI LORRY, TANKER, TRACTOR |
| **Medium (2)** | CAR, GOODS AUTO, JEEP, LGV, TEMPO, VAN, MAXI-CAB |
| **Low (1)** | MOPED, MOTOR CYCLE, SCOOTER, PASSENGER AUTO, OTHERS |

### Day-of-week weights (data-driven from 298,445 violations)

| Day | Violations | Weight |
|-----|-----------|--------|
| Sunday | 50,160 (16.8%) | **1.000** |
| Saturday | 44,523 (14.9%) | 0.887 |
| Thursday | 43,547 (14.6%) | 0.868 |
| Tuesday | 42,697 (14.3%) | 0.851 |
| Wednesday | 41,974 (14.1%) | 0.836 |
| Friday | 40,864 (13.7%) | 0.814 |
| Monday | 34,680 (11.6%) | **0.691** |

Note: avg violation priority was nearly identical across all days (2.57–2.59), so weight is derived from volume (higher volume = higher congestion likelihood), not violation type.

---

## Clustering

DBSCAN over lat/lng coordinates:
- `eps_m = 100` (100m radius)
- `min_samples = 20` (minimum 20 violations to form a cluster)
- Noise points (cluster_id = -1) are excluded from cluster stats
- `cluster_score = avg_impact × log(1 + violations)` — balances severity with density

If clustering returns very few hotspots, increase `eps_m` in `pipeline.run_pipeline()`.

---

## Traffic-Flow Impact Model

This is the piece that directly answers the problem statement's "quantify their impact on traffic
flow" requirement — a hotspot with few but severe violations can matter more than one with many
trivial ones.

For every violation row:

```
obstruction_intensity = (lane_block_weight × vehicle_footprint × junction_multiplier) / max_possible
```

- **`lane_block_weight`** — how much of a lane a violation type physically occupies (e.g. Double
  Parking = 1.00, Parking On Footpath = 0.15, non-parking violations like helmet/seatbelt = 0.0).
- **`vehicle_footprint`** — heavier/larger vehicles (buses, lorries) occupy more carriageway width
  than two-wheelers.
- **`junction_multiplier`** — violations at junctions amplify impact (1.5×) because they block
  turning movement and queue spillback, not just one lane.

Per cluster, these aggregate into:

| Field | Meaning |
|-------|---------|
| `tfi_index` | 0–100 normalized Traffic-Flow Impact score — ranks hotspots by actual congestion caused, not just violation count |
| `pct_lane_capacity_cut` | Estimated % of lane capacity removed at peak |
| `veh_affected_peak` | Estimated vehicles/hour affected, using a standard lane-flow baseline scaled by capacity cut and violation persistence |
| `junction_share`, `mean_footprint`, `block_reason` | Explainability fields — surfaced in the dashboard so the score isn't a black box |

---

## Time-aware prediction

Query: `(latitude, longitude, date, time)` → `predicted_score + risk_level`

```
predicted_score = severity_profile(location) × activity_likelihood(location, time)
```

**Severity** (how bad violations tend to be at this location):
- Nearest cluster within 300m → uses that cluster's real `avg_impact`
- No nearby cluster → Gradient Boosting model trained on `lat, lng, hour, dow, month`

**Activity likelihood** (how active is this location right now):
- Cluster has ≥2 records in same hour-bucket (3hr window) + same DOW → uses historical pattern, scaled by DOW weight
- Otherwise → city-wide hour/DOW activity curve, scaled by DOW weight

Response includes: `predicted_score`, `risk_level` (low/medium/high), `severity_score`, `activity_factor`, `severity_source`, `activity_source`, `dow_name`, `dow_weight`.

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clusters?when=` | All hotspot clusters — violation stats, Traffic-Flow Impact fields, and (if `when` given) time-aware predicted score |
| GET | `/api/predict?lat=&lng=&when=` | Congestion prediction for any point/time (`when` = ISO format e.g. `2024-06-15T09:00`) |
| GET | `/api/geocode?q=` | Search clusters by location/junction/police station name |
| POST | `/api/refresh` | Re-run full pipeline against current data file |
| GET | `/api/status` | Loaded row/cluster counts + last load time |

### Refresh for real-time ingestion

Once new violation rows are appended to the data file:
```bash
curl -X POST http://localhost:5000/api/refresh
```
Hook this into a cron job, file-watcher, or webhook from your ingestion pipeline.

---

## Dashboard

A hub-and-spoke layout — a landing page with headline stats and time filters, leading into four
focused sections (back button returns to the hub):

- **Traffic-Flow Impact** — ranked chokepoints with full score explainability (obstruction
  intensity, junction share, footprint, volume) and assumptions disclosed.
- **Predictive Patrol Plan** — per-shift (morning peak / midday / evening peak / night) ranked
  enforcement zones for today or tomorrow, downloadable as a patrol report.
- **Analytics** — top areas, risk breakdown, trend sparklines, quadrant view.
- **Stations** — busiest police-station jurisdictions, searchable by station/location.

## Map

- **Search bar** — matches junction name, police station, or address text from data
- **Metric toggle** — color hotspots by Traffic-Flow Impact, violation volume, or time-aware
  predicted risk, without refetching data
- **Map click / circle markers** — sized and colored by the selected metric
- **Popup** — violations, avg impact, cluster score, junction, police station, and the
  Traffic-Flow Impact breakdown (TFI index, lane capacity cut, vehicles affected, top blocking
  violation)
