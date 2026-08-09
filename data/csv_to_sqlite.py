"""
Loads energy-data-pipeline/data/processed/gb_generation_mix_27col_2020_to_now.csv
into cache/grid_cache.db in the exact long-format schema that cache_db.py reads.

Run once for a full backfill (incremental=False), then incrementally on each sync.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Re-assert the last N days on every incremental sync to absorb upstream
# revisions and NaN-fill artefacts that appear after the initial load.
LOOKBACK_DAYS = 3

CSV_PATH = (
    Path(__file__).parent.parent
    / "energy-data-pipeline"
    / "data"
    / "processed"
    / "gb_generation_mix_27col_2020_to_now.csv"
)

DB_PATH = Path(__file__).parent.parent / "cache" / "grid_cache.db"

# Lowercase names match FUEL_COLORS keys in theme.py.
# GAS is kept as CCGT+OCGT combined (backward compatibility for existing charts).
# WIND is BM-metered grid-scale; WIND_EMB is embedded/distributed wind.
FUEL_MAP = {
    "GAS":        "gas",           # CCGT + OCGT combined
    "CCGT":       "ccgt",          # combined-cycle gas turbine
    "OCGT":       "ocgt",          # open-cycle gas turbine
    "COAL":       "coal",
    "BIOMASS":    "biomass",
    "WIND":       "wind_bm",       # BM-metered (grid-scale) wind only
    "WIND_EMB":   "wind_emb",      # embedded/distributed wind
    "WIND_TOTAL": "wind",          # total wind = wind_bm + wind_emb (derived)
    "NUCLEAR":    "nuclear",
    "SOLAR":      "solar",
    "NPSHYD":     "hydro",
    "PS":         "pumped storage",
    "OTHER":      "other",
    "IMPORTS":    "imports",
}

_FUEL_SOURCE = {
    # NESO-sourced fuels (embedded + distribution-connected generation)
    "solar":          "NESO",
    "biomass":        "NESO",
    "wind_bm":        "NESO",
    "wind_emb":       "NESO",
    "nuclear":        "NESO",
    "wind":           "NESO",
    # Elexon FUELHH-sourced fuels (BM-metered, transmission-connected)
    "ccgt":           "Elexon FUELHH",
    "ocgt":           "Elexon FUELHH",
    "gas":            "Elexon FUELHH",
    "coal":           "Elexon FUELHH",
    "hydro":          "Elexon FUELHH",
    "pumped storage": "Elexon FUELHH",
    "other":          "Elexon FUELHH",
    "imports":        "Elexon FUELHH",
}

CABLE_MAP = {
    "INTELEC": "Eleclink interconnector (France)",
    "INTEW":   "East-West interconnector (Ireland)",
    "INTFR":   "IFA1 interconnector (France)",
    "INTGRNL": "Greenlink interconnector (Ireland)",
    "INTIFA2": "IFA2 interconnector (France)",
    "INTIRL":  "Moyle interconnector (Northern Ireland)",
    "INTNED":  "BritNed interconnector (Netherlands)",
    "INTNEM":  "Nemo Link interconnector (Belgium)",
    "INTNSL":  "North Sea Link interconnector (Norway)",
    "INTVKL":  "Viking Link interconnector (Denmark)",
}

# CSV columns to pull from the raw DataFrame (excludes the derived WIND_TOTAL)
_CSV_FUEL_COLS = [k for k in FUEL_MAP if k != "WIND_TOTAL"]
_CABLE_COLS    = list(CABLE_MAP.keys())

# Columns that form the percent denominator — unique supply only.
# Excludes CCGT/OCGT (already in GAS) and WIND/WIND_EMB (already in WIND_TOTAL)
# to avoid double-counting.
_TOTAL_COLS = [
    "GAS", "COAL", "BIOMASS", "WIND_TOTAL", "NUCLEAR",
    "SOLAR", "NPSHYD", "PS", "OTHER", "IMPORTS",
]


def load_csv() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    return df.sort_values("startTime").reset_index(drop=True)


def csv_to_generation_mix_rows(df: pd.DataFrame) -> list[dict]:
    work = df[["startTime"] + _CSV_FUEL_COLS].copy()
    # Derive total wind before melting so it participates in the denominator
    work["WIND_TOTAL"] = work["WIND"] + work["WIND_EMB"].fillna(0)
    work["_total"] = work[_TOTAL_COLS].sum(axis=1)
    work["_ts"] = work["startTime"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    melt_cols = _CSV_FUEL_COLS + ["WIND_TOTAL"]
    melted = work.melt(
        id_vars=["_ts", "_total"],
        value_vars=melt_cols,
        var_name="csv_col",
        value_name="mw",
    )
    melted["mw"]        = melted["mw"].fillna(0.0)
    melted["percent"]   = (melted["mw"] / melted["_total"] * 100).round(2)
    melted.loc[melted["_total"] == 0, "percent"] = 0.0
    melted["fuel_type"] = melted["csv_col"].map(FUEL_MAP)
    melted["source"]    = melted["fuel_type"].map(_FUEL_SOURCE).fillna("Elexon FUELHH+NESO")

    return (
        melted[["_ts", "fuel_type", "mw", "percent", "source"]]
        .rename(columns={"_ts": "timestamp"})
        .to_dict("records")
    )


def csv_to_interconnector_rows(df: pd.DataFrame) -> list[dict]:
    work = df[["startTime"] + _CABLE_COLS].copy()
    work["_ts"] = work["startTime"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    melted = work.melt(
        id_vars=["_ts"],
        value_vars=_CABLE_COLS,
        var_name="csv_col",
        value_name="flow_mw",
    )
    melted["flow_mw"]     = melted["flow_mw"].fillna(0.0)
    melted["name"]        = melted["csv_col"].map(CABLE_MAP)
    melted["capacity_mw"] = 0.0
    melted["source"]      = "Elexon FUELHH"

    return (
        melted[["_ts", "name", "flow_mw", "capacity_mw", "source"]]
        .rename(columns={"_ts": "timestamp"})
        .to_dict("records")
    )


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def sync_csv_to_sqlite(incremental: bool = True) -> dict:
    """
    Load CSV into SQLite.

    incremental=True  — only rows newer than MAX(timestamp) in raw_generation_mix.
    incremental=False — clears both raw tables first, then loads all 113k+ rows.
    """
    df = load_csv()

    conn = _conn()

    if incremental:
        row        = conn.execute("SELECT MAX(timestamp) FROM raw_generation_mix").fetchone()
        max_ts_str = row[0] if row and row[0] else None
        conn.close()

        if max_ts_str:
            max_ts       = pd.to_datetime(max_ts_str.rstrip("Z"))
            lookback_ts  = max_ts - timedelta(days=LOOKBACK_DAYS)
            lookback_date = lookback_ts.strftime("%Y-%m-%d")
            lookback_str  = f"{lookback_date}T00:00:00"
            # Delete the lookback window so the CSV re-asserts corrected values
            conn = _conn()
            conn.execute("DELETE FROM raw_generation_mix WHERE timestamp >= ?", (lookback_str,))
            conn.execute("DELETE FROM raw_interconnector WHERE timestamp >= ?",  (lookback_str,))
            conn.commit()
            conn.close()
            # Align reload to the same day boundary used in the DELETE above.
            # Using lookback_ts (sub-day) would leave the first hours of the
            # lookback day permanently absent after each sync.
            lookback_pd = pd.Timestamp(lookback_date).tz_localize("UTC")
            df = df[df["startTime"] >= lookback_pd].reset_index(drop=True)
        else:
            lookback_date = None

        conn = _conn()
    else:
        conn.execute("DELETE FROM raw_generation_mix")
        conn.execute("DELETE FROM raw_interconnector")
        conn.commit()
        lookback_date = None

    gen_rows = csv_to_generation_mix_rows(df)
    ic_rows  = csv_to_interconnector_rows(df)

    conn.execute("PRAGMA synchronous = OFF")
    conn.executemany(
        "INSERT OR REPLACE INTO raw_generation_mix "
        "(timestamp, fuel_type, mw, percent, source) "
        "VALUES (:timestamp, :fuel_type, :mw, :percent, :source)",
        gen_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO raw_interconnector "
        "(timestamp, name, flow_mw, capacity_mw, source) "
        "VALUES (:timestamp, :name, :flow_mw, :capacity_mw, :source)",
        ic_rows,
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO sync_metadata (source, last_synced) VALUES (?, ?)",
        ("generation_mix", now),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_metadata (source, last_synced) VALUES (?, ?)",
        ("interconnector", now),
    )
    conn.commit()
    conn.close()

    from_date = lookback_date if incremental else None
    from data.cache_db import (
        _build_daily_aggregates,
        _build_monthly_aggregates,
        _build_quarterly_aggregates,
        _quarter_label,
    )
    from_quarter = _quarter_label(from_date) if from_date else None
    for src in ("generation_mix", "interconnector"):
        _build_daily_aggregates(src, from_date)
        _build_monthly_aggregates(src, from_date)
        _build_quarterly_aggregates(src, from_quarter)

    return {
        "action":              "incremental" if incremental else "full",
        "rows_added":          len(gen_rows) + len(ic_rows),
        "aggregates_rebuilt":  True,
    }
