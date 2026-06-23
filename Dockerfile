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

# HF Spaces expects the app on port 7860. One worker (the model is held in
# memory once), many threads (the dashboard fires parallel requests), and a
# long timeout because the pipeline takes ~1-2 min to build on first boot.
EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "8", "--timeout", "600", "server:app"]
