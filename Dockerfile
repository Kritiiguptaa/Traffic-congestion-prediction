# Hugging Face Spaces (Docker SDK) — Bengaluru Parking Hotspots
FROM python:3.11-slim

WORKDIR /app

# Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (the dataset is .dockerignored — it is fetched below instead)
COPY . .

# Fetch the 41 MB dataset from the public GitHub repo at build time, so the
# image/Space stays lean and we avoid Git LFS. server.py reads the path from
# the VIOLATIONS_FILE env var.
ENV VIOLATIONS_FILE=violations.xlsx
RUN python -c "import urllib.request, urllib.parse; \
name='jan to may police violation_anonymized791b166_without_null_only_columns.xlsx'; \
url='https://raw.githubusercontent.com/Kritiiguptaa/Traffic-congestion-prediction/main/' + urllib.parse.quote(name); \
print('downloading', url); \
urllib.request.urlretrieve(url, 'violations.xlsx'); \
import os; print('dataset bytes:', os.path.getsize('violations.xlsx'))"

# Run the pipeline once at build time and pickle the result (scored df,
# cluster stats, fitted predictor incl. trained GradientBoosting model) so
# every container boot loads this cache (~1-2s) instead of re-running
# Excel parsing + scoring + DBSCAN + model training (~1-2 min) on restart.
RUN python -c "from pipeline import run_pipeline; from temporal_model import HotspotPredictor; import pickle; \
scored, stats = run_pipeline('violations.xlsx'); \
predictor = HotspotPredictor(scored, stats); \
pickle.dump((scored, stats, predictor), open('pipeline_cache.pkl', 'wb')); \
print('cached', len(scored), 'rows,', len(stats), 'clusters')"

# HF Spaces expects the app on port 7860. One worker (the model is held in
# memory once), many threads (the dashboard fires parallel requests), and a
# long timeout because the pipeline takes ~1-2 min to build on first boot.
EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "8", "--timeout", "600", "server:app"]
