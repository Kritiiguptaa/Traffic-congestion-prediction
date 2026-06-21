"""
analyze_dow.py

Calculates day-of-week distribution from the actual violations dataset.
Outputs:
  - Total violations per DOW
  - Avg congestion impact per DOW (by violation priority)
  - Violation type breakdown per DOW
Run: python analyze_dow.py
"""
import pandas as pd
import numpy as np
import ast

VIOLATION_PRIORITY = {
    # HIGH
    "AGAINST ONE WAY/NO ENTRY": 3, "JUMPING TRAFFIC SIGNAL": 3,
    "DOUBLE PARKING": 3, "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 3,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 3,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 3,
    "PARKING IN A MAIN ROAD": 3, "H T V PROHIBITED": 3,
    "STOPING ON WHITE/STOP LINE": 3, "U TURN PROHIBITED": 3,
    "VIOLATING LANE DISIPLINE": 3, "WRONG PARKING": 3,
    # MEDIUM
    "NO PARKING": 2, "PARKING OTHER THAN BUS STOP": 2,
    "CARRYING LENGHTY MATERIAL": 2, "USING BLACK FILM/OTHER MATERIALS": 2,
    "PARKING NEAR ROAD CROSSING": 2, "OBSTRUCTING DRIVER": 2,
    # LOW
    "PARKING ON FOOTPATH": 1, "2W/3W - USING MOBILE PHONE": 1,
    "OTHER - USING MOBILE PHONE": 1, "FAIL TO USE SAFETY BELTS": 1,
    "RIDER NOT WEARING HELMET": 1, "DEFECTIVE NUMBER PLATE": 1,
    "WITHOUT SIDE MIRROR": 1, "DEMANDING EXCESS FARE": 1,
    "REFUSE TO GO FOR HIRE": 1,
}
DEFAULT_PRIORITY = 2

DOW_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

DATA_FILE = "jan to may police violation_anonymized791b166_without_null_only_columns.xlsx"


def get_max_priority(v):
    try:
        vals = ast.literal_eval(v) if isinstance(v, str) and v.startswith("[") else [v]
        return max(VIOLATION_PRIORITY.get(str(x).strip().upper(), DEFAULT_PRIORITY) for x in vals)
    except Exception:
        return DEFAULT_PRIORITY


def main():
    print(f"Loading: {DATA_FILE}")
    df = pd.read_excel(DATA_FILE, na_values=[], keep_default_na=False)
    df = df.replace("", np.nan)

    # parse timestamp UTC -> IST
    df["created_datetime_ist"] = pd.to_datetime(
        df["created_datetime"], errors="coerce", utc=True
    ).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    df = df.dropna(subset=["created_datetime_ist", "violation_type"])
    df["dow"]      = df["created_datetime_ist"].dt.dayofweek
    df["dow_name"] = df["dow"].map(DOW_NAMES)
    df["priority"] = df["violation_type"].apply(get_max_priority)

    print(f"\nTotal rows with valid timestamp + violation_type: {len(df)}\n")

    # ── 1. Total violations per DOW ──
    total_per_dow = df.groupby(["dow", "dow_name"]).size().reset_index(name="total_violations")
    total_per_dow = total_per_dow.sort_values("dow")
    print("=" * 55)
    print("TOTAL VIOLATIONS PER DAY OF WEEK")
    print("=" * 55)
    print(f"{'Day':<10} {'Count':>10} {'% of total':>12}")
    print("-" * 35)
    grand = total_per_dow["total_violations"].sum()
    for _, row in total_per_dow.iterrows():
        pct = row["total_violations"] / grand * 100
        print(f"{row['dow_name']:<10} {row['total_violations']:>10,} {pct:>11.1f}%")
    print(f"{'TOTAL':<10} {grand:>10,} {'100.0%':>12}")

    # ── 2. Violations by priority per DOW ──
    print("\n" + "=" * 65)
    print("VIOLATIONS BY PRIORITY PER DAY OF WEEK")
    print("=" * 65)
    piv = df.groupby(["dow_name", "dow", "priority"]).size().unstack(fill_value=0).reset_index()
    piv = piv.sort_values("dow")
    piv.columns.name = None
    print(f"{'Day':<10} {'High(3)':>10} {'Med(2)':>10} {'Low(1)':>10} {'Total':>10} {'Avg Priority':>14}")
    print("-" * 60)
    for _, row in piv.iterrows():
        h = row.get(3, 0); m = row.get(2, 0); l = row.get(1, 0)
        tot = h + m + l
        avg = (3*h + 2*m + 1*l) / tot if tot else 0
        print(f"{row['dow_name']:<10} {h:>10,} {m:>10,} {l:>10,} {tot:>10,} {avg:>14.3f}")

    # ── 3. Avg priority score per DOW (usable as DOW weight) ──
    print("\n" + "=" * 55)
    print("AVG VIOLATION PRIORITY PER DOW  (use as DOW weight)")
    print("=" * 55)
    avg_priority = (
        df.groupby(["dow", "dow_name"])["priority"]
        .mean().reset_index().sort_values("dow")
    )
    max_avg = avg_priority["priority"].max()
    print(f"{'Day':<10} {'Avg Priority':>14} {'Normalised (0-1)':>18}")
    print("-" * 45)
    for _, row in avg_priority.iterrows():
        norm = (row["priority"] - 1) / (max_avg - 1) if max_avg > 1 else 1.0
        print(f"{row['dow_name']:<10} {row['priority']:>14.4f} {norm:>18.4f}")

    # ── 4. Top violation types per DOW ──
    print("\n" + "=" * 65)
    print("TOP 3 VIOLATION TYPES PER DAY OF WEEK")
    print("=" * 65)
    for dow in range(7):
        day_df = df[df["dow"] == dow]
        if day_df.empty:
            continue
        # explode list-format violation_type
        def extract_types(v):
            try:
                return ast.literal_eval(v) if isinstance(v, str) and v.startswith("[") else [str(v)]
            except:
                return [str(v)]
        types = day_df["violation_type"].apply(extract_types).explode()
        top3 = types.value_counts().head(3)
        print(f"\n{DOW_NAMES[dow]}:")
        for vtype, cnt in top3.items():
            pri = VIOLATION_PRIORITY.get(str(vtype).strip().upper(), DEFAULT_PRIORITY)
            label = {3: "HIGH", 2: "MED", 1: "LOW"}[pri]
            print(f"  [{label}] {vtype:<55} {cnt:>6,}")

    print("\n" + "=" * 55)
    print("Done. Use 'Avg Priority' values above to set DOW_WEIGHT in pipeline.py")
    print("=" * 55)


if __name__ == "__main__":
    main()