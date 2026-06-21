# Bengaluru Parking Hotspot Map — Real-Time + Predictive

## Project structure

```
├── clean_data.py       Raw export cleaning (UTC→IST, NULL normalization, vehicle coalescing)
├── pipeline.py         Scoring, clustering, cluster stats with DOW profile
├── temporal_model.py   Two-layer congestion impact predictor
├── server.py           Flask API + static file server
├── static/
│   └── index.html      Dark-theme map UI (sidebar, search, predict form, DOW chart)
├── analyze_dow.py      One-time script to compute data-driven DOW weights from dataset
└── README.md
```

## Setup

```bash
pip install flask pandas numpy scikit-learn openpyxl
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

### Violation priority (from your confirmed classification)

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

## Prediction

Query: `(latitude, longitude, date, time)` → `congestion_impact_score + risk_level`

```
predicted_score = severity_profile(location) × activity_likelihood(location, time)
```

**Severity** (how bad violations tend to be at this location):
- Nearest cluster within 300m → uses that cluster's real `avg_impact`
- No nearby cluster → Gradient Boosting model trained on `lat, lng, hour, dow, month`

**Activity likelihood** (how active is this location right now):
- Cluster has ≥2 records in same hour-bucket (3hr window) + same DOW → uses historical pattern, scaled by DOW weight
- Otherwise → city-wide hour/DOW activity curve, scaled by DOW weight

Response includes: `predicted_score`, `risk_level` (low/medium/high), `severity_score`, `activity_factor`, `severity_source`, `activity_source`, `dow_name`, `dow_weight`, `dow_profile` (Mon–Sun breakdown for nearest cluster).

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clusters` | All hotspot clusters with DOW profile |
| GET | `/api/predict?lat=&lng=&when=` | Congestion prediction for any point/time (`when` = ISO format e.g. `2024-06-15T09:00`) |
| GET | `/api/dow_profile?cluster_id=` | Mon–Sun avg impact for a specific cluster |
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

## UI

- **Search bar** — matches junction name, police station, or address text from data
- **Map click** — click any point to fill lat/lng and run prediction
- **Predict form** — enter lat/lng + date + time → get congestion impact score with full breakdown
- **DOW chart** — Mon–Sun bar chart of avg impact for the selected cluster
- **Cluster info panel** — violations, avg impact, cluster score, junction, police station
- **Heatmap** — cluster scores overlaid as heat (red = high, amber = medium, green = low)
- **Circle markers** — sized by cluster score, colored by avg impact
