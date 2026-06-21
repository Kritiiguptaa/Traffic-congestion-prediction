"""
clean_data.py

Cleans the raw export (e.g. "jan to may police violation_anonymized..." file) into
the shape pipeline.py expects.

Handles the specifics of this export:
  - created_datetime / modified_datetime are UTC with a "+00" offset suffix and no
    precomputed _ist column -> we parse as UTC and derive created_datetime_ist ourselves.
  - "NULL" sometimes appears as a literal string (not an empty cell) in object columns
    like updated_vehicle_type, updated_vehicle_number, data_sent_to_scita_timestamp,
    validation_status -- these are normalized to real NaN before any fallback logic runs.
  - updated_vehicle_type / updated_vehicle_number are the source of truth when present;
    when missing (NaN or literal "NULL"), we fall back to vehicle_type / vehicle_number.
"""
import pandas as pd
import numpy as np

# Columns where the literal string "NULL" (case-insensitive) should be treated as missing
NULL_STRING_COLUMNS = [
    "updated_vehicle_number", "updated_vehicle_type", "data_sent_to_scita_timestamp",
    "validation_status", "validation_timestamp", "vehicle_type", "vehicle_number",
    "junction_name", "police_station", "location", "violation_type", "offence_code",
]


def _normalize_null_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Replace the literal string 'NULL' (any case, with surrounding whitespace) with real NaN."""
    df = df.copy()
    for col in NULL_STRING_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: np.nan if isinstance(v, str) and v.strip().upper() == "NULL" else v
            )
    return df


def _parse_utc_to_ist(series: pd.Series) -> pd.Series:
    """Parse a UTC timestamp column (possibly with a '+00' offset suffix, possibly without)
    and return it converted to IST (Asia/Kolkata, UTC+5:30), tz-naive for downstream use."""
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    ist = parsed.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return ist


def clean_raw_violations(filepath: str) -> pd.DataFrame:
    """
    Load the raw export and produce a cleaned dataframe with the columns
    pipeline.py expects:
      - latitude, longitude, location, police_station, junction_name
      - violation_type, offence_code
      - vehicle_type / updated_vehicle_type  (coalesced -- updated wins, falls back to original)
      - vehicle_number / updated_vehicle_number (coalesced the same way)
      - created_datetime_ist (derived from UTC created_datetime)
      - validation_status
    """
    if filepath.endswith((".xlsx", ".xls")):
        # keep_default_na=False so pandas doesn't silently treat "NULL"/"NA"/etc as NaN
        # before our explicit normalization below runs -- we want full control over what
        # counts as missing, since this export uses the literal string "NULL" deliberately
        # alongside genuinely empty cells.
        df = pd.read_excel(filepath, na_values=[], keep_default_na=False)
    else:
        df = pd.read_csv(filepath, na_values=[], keep_default_na=False)

    # truly empty cells still need to become NaN (pandas reads them as "" with the above settings)
    df = df.replace("", np.nan)

    df = _normalize_null_strings(df)

    # ---- required geo fields ----
    df = df.dropna(subset=["latitude", "longitude"]).copy()

    # ---- timestamps: UTC -> IST ----
    if "created_datetime" in df.columns:
        df["created_datetime_ist"] = _parse_utc_to_ist(df["created_datetime"])
    else:
        df["created_datetime_ist"] = pd.NaT

    if "modified_datetime" in df.columns:
        df["modified_datetime_ist"] = _parse_utc_to_ist(df["modified_datetime"])

    # ---- vehicle type: updated wins, falls back to original ----
    if "updated_vehicle_type" in df.columns and "vehicle_type" in df.columns:
        df["vehicle_type_final"] = df["updated_vehicle_type"].fillna(df["vehicle_type"])
    elif "updated_vehicle_type" in df.columns:
        df["vehicle_type_final"] = df["updated_vehicle_type"]
    else:
        df["vehicle_type_final"] = df.get("vehicle_type")

    # ---- vehicle number: updated wins, falls back to original ----
    if "updated_vehicle_number" in df.columns and "vehicle_number" in df.columns:
        df["vehicle_number_final"] = df["updated_vehicle_number"].fillna(df["vehicle_number"])
    elif "updated_vehicle_number" in df.columns:
        df["vehicle_number_final"] = df["updated_vehicle_number"]
    else:
        df["vehicle_number_final"] = df.get("vehicle_number")

    # ---- junction_name: missing -> treat as "No Junction" ----
    if "junction_name" in df.columns:
        df["junction_name"] = df["junction_name"].fillna("No Junction")
    else:
        df["junction_name"] = "No Junction"

    # ---- drop rows with no violation_type at all (can't be scored) ----
    if "violation_type" in df.columns:
        df = df.dropna(subset=["violation_type"]).copy()

    return df


if __name__ == "__main__":
    cleaned = clean_raw_violations("raw_violations_new_schema.csv")
    print(f"Cleaned rows: {len(cleaned)}")
    print(cleaned[[
        "created_datetime", "created_datetime_ist",
        "vehicle_type", "updated_vehicle_type", "vehicle_type_final",
        "vehicle_number", "updated_vehicle_number", "vehicle_number_final",
    ]].head(12).to_string())
