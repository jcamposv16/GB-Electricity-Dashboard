"""
Self-contained SQLite cache layer for GB Electricity Dashboard.

Reads and writes  cache/grid_cache.db  relative to the project root.
All three upstream APIs are public — no API key required:
  - NESO CKAN datastore  (generation mix)
  - carbonintensity.org.uk  (carbon intensity)
  - Elexon BMRS  (interconnector flows)

Ported from GB-Grid-Agent/cache_db.py + tools.py but has NO dependency
on that project — no sys.path tricks, no shared venv, no shared .env.
"""

import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "cache" / "grid_cache.db"

# On Linux (HF), grid_cache.db is served from the Space's Xet-backed repo
# checkout, which fetches content in 64KB chunks over the network on access
# and can intermittently raise "disk I/O error" when a query seeks into a
# chunk that hasn't been fetched yet. Copying the file once to /tmp — real
# local container disk — before any query runs removes that dependency.
# Windows is unaffected: resolve_db_path() returns DB_PATH unchanged there.
_LOCAL_DB_PATH = Path("/tmp/grid_cache.db")
_db_path_lock = threading.Lock()
_resolved_db_path: Path | None = None
_startup_logged = False

# ── Diagnostic logging (temporary — added to trace the disk I/O error) ─────────
_logged_conn_sources: set[str] = set()
_logged_conn_lock = threading.Lock()


def log_conn_open(source: str, path) -> None:
    """Print the exact path a connection is opened against, once per
    (source, path) pair, so repeated reruns don't flood stderr."""
    key = f"{source}:{path}"
    if key in _logged_conn_sources:
        return
    with _logged_conn_lock:
        if key in _logged_conn_sources:
            return
        _logged_conn_sources.add(key)
        import sys
        print(f"[cache_db] CONN OPEN source={source} path={path}", file=sys.stderr)


def resolve_db_path() -> Path:
    """Runtime path every connection should open. Memoized per container;
    safe under concurrent Streamlit reruns via double-checked locking."""
    global _resolved_db_path, _startup_logged
    import sys
    if sys.platform.startswith("win"):
        if not _startup_logged:
            _startup_logged = True
            print(
                f"[cache_db] STARTUP platform=win source_db={DB_PATH} "
                f"resolved_path={DB_PATH} tmp_copy_attempted=False",
                file=sys.stderr,
            )
        return DB_PATH
    if _resolved_db_path is not None:
        return _resolved_db_path
    with _db_path_lock:
        if _resolved_db_path is not None:
            return _resolved_db_path
        src_size = DB_PATH.stat().st_size
        needs_copy = not _LOCAL_DB_PATH.exists() or _LOCAL_DB_PATH.stat().st_size != src_size
        print(
            f"[cache_db] STARTUP platform=linux source_db={DB_PATH} "
            f"source_size_bytes={src_size} tmp_path={_LOCAL_DB_PATH} "
            f"tmp_copy_needed={needs_copy}",
            file=sys.stderr,
        )
        if needs_copy:
            start = time.monotonic()
            tmp = _LOCAL_DB_PATH.with_suffix(".db.tmp")
            shutil.copyfile(DB_PATH, tmp)
            tmp.replace(_LOCAL_DB_PATH)  # atomic rename, same filesystem
            elapsed = time.monotonic() - start
            copied_size = _LOCAL_DB_PATH.stat().st_size
            print(
                f"[cache_db] Copied grid_cache.db to {_LOCAL_DB_PATH} "
                f"in {elapsed:.2f}s ({copied_size / 1e6:.1f} MB)",
                file=sys.stderr,
            )
        else:
            print(
                f"[cache_db] {_LOCAL_DB_PATH} already present and matches "
                f"source size ({src_size} bytes) — skipping copy",
                file=sys.stderr,
            )
        _resolved_db_path = _LOCAL_DB_PATH
        print(
            f"[cache_db] STARTUP RESOLVED final_path={_resolved_db_path}",
            file=sys.stderr,
        )
        try:
            import importlib.metadata as _ilm
            _versions = {}
            for _pkg in ("streamlit", "pandas", "pyarrow", "plotly", "numpy"):
                try:
                    _versions[_pkg] = _ilm.version(_pkg)
                except _ilm.PackageNotFoundError:
                    _versions[_pkg] = "not installed"
            print(
                "[cache_db] STARTUP versions "
                + " ".join(f"{k}={v}" for k, v in _versions.items()),
                file=sys.stderr,
            )
        except Exception as _e:
            print(
                f"[cache_db] STARTUP version logging failed: "
                f"{type(_e).__name__}: {_e}",
                file=sys.stderr,
            )
        return _resolved_db_path

# ── API endpoints (all public, key-less) ───────────────────────────────────────
_CI_URL     = "https://api.carbonintensity.org.uk/intensity"
_NESO_URL   = "https://api.neso.energy/api/3/action/datastore_search_sql"
_NESO_RES   = "f93d1835-75bc-43e5-84ad-12472b180a98"
_NESO_FUELS = ["GAS", "COAL", "BIOMASS", "OTHER", "NUCLEAR", "SOLAR", "HYDRO", "IMPORTS", "STORAGE"]
_ELEXON_URL = "https://data.elexon.co.uk/bmrs/api/v1/generation/outturn/interconnectors"
_IC_CABLES  = [
    "Belgium (Nemolink)", "Denmark (Viking link)", "Eleclink (INTELEC)",
    "France(IFA)", "IFA2 (INTIFA2)", "Northern Ireland(Moyle)",
    "Ireland(East-West)", "Ireland (Greenlink)", "Netherlands(BritNed)",
    "North Sea Link (INTNSL)",
]

_build_lock = threading.Lock()


# ── DB connection ──────────────────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    import sys
    if sys.platform.startswith("win"):
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        log_conn_open("cache_db._conn[win]", DB_PATH)
    else:
        # Linux/HF: open read-only, no WAL, against the local /tmp copy (see
        # resolve_db_path()) rather than the Xet-backed repo path. The
        # deployed app never writes to this database (every write path is
        # unreachable behind the platform guard in fetcher.py), and the
        # shipped file no longer carries a persistent WAL flag — see
        # sync_to_hf.py's journal_mode=DELETE step.
        path = resolve_db_path()
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        log_conn_open("cache_db._conn[linux]", path)
    return conn


def _init_schema() -> None:
    """Create tables and indexes if they don't already exist."""
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_carbon_intensity (
            timestamp   TEXT NOT NULL,
            intensity   REAL NOT NULL,
            index_label TEXT NOT NULL,
            source      TEXT NOT NULL,
            PRIMARY KEY (timestamp, source)
        );
        CREATE TABLE IF NOT EXISTS raw_generation_mix (
            timestamp TEXT NOT NULL,
            fuel_type TEXT NOT NULL,
            mw        REAL NOT NULL,
            percent   REAL NOT NULL,
            source    TEXT NOT NULL,
            PRIMARY KEY (timestamp, fuel_type)
        );
        CREATE TABLE IF NOT EXISTS raw_interconnector (
            timestamp   TEXT NOT NULL,
            name        TEXT NOT NULL,
            flow_mw     REAL NOT NULL,
            capacity_mw REAL NOT NULL,
            source      TEXT NOT NULL,
            PRIMARY KEY (timestamp, name)
        );
        CREATE TABLE IF NOT EXISTS sync_metadata (
            source      TEXT PRIMARY KEY,
            last_synced TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raw_electricity_price (
            timestamp         TEXT PRIMARY KEY,
            settlement_date   TEXT,
            settlement_period INTEGER,
            price             REAL,
            volume            REAL,
            source            TEXT DEFAULT 'Elexon MID APXMIDP'
        );
        CREATE TABLE IF NOT EXISTS agg_price_daily (
            date          TEXT PRIMARY KEY,
            avg_price     REAL,
            min_price     REAL,
            max_price     REAL,
            p25_price     REAL,
            p75_price     REAL,
            total_volume  REAL,
            peak_price    REAL,
            offpeak_price REAL,
            neg_count     INTEGER,
            spike_count   INTEGER
        );
        CREATE TABLE IF NOT EXISTS agg_price_monthly (
            month         TEXT PRIMARY KEY,
            avg_price     REAL,
            min_price     REAL,
            max_price     REAL,
            p25_price     REAL,
            p75_price     REAL,
            total_volume  REAL,
            peak_price    REAL,
            offpeak_price REAL,
            neg_count     INTEGER,
            spike_count   INTEGER
        );
        CREATE TABLE IF NOT EXISTS agg_price_quarterly (
            quarter       TEXT PRIMARY KEY,
            avg_price     REAL,
            min_price     REAL,
            max_price     REAL,
            p25_price     REAL,
            p75_price     REAL,
            total_volume  REAL,
            peak_price    REAL,
            offpeak_price REAL,
            neg_count     INTEGER,
            spike_count   INTEGER
        );
        CREATE TABLE IF NOT EXISTS agg_price_settlement_profile (
            settlement_period INTEGER,
            year              INTEGER,
            avg_price         REAL,
            PRIMARY KEY (settlement_period, year)
        );
        CREATE TABLE IF NOT EXISTS regional_carbon_intensity (
            date            TEXT    NOT NULL,
            region_id       INTEGER NOT NULL,
            short_name      TEXT,
            dno_region      TEXT,
            avg_intensity   REAL,
            min_intensity   REAL,
            max_intensity   REAL,
            avg_wind_pct    REAL,
            avg_solar_pct   REAL,
            avg_gas_pct     REAL,
            avg_nuclear_pct REAL,
            avg_imports_pct REAL,
            avg_biomass_pct REAL,
            avg_hydro_pct   REAL,
            avg_other_pct   REAL,
            period_count    INTEGER,
            PRIMARY KEY (date, region_id)
        );
        CREATE INDEX IF NOT EXISTS idx_gen_ts
            ON raw_generation_mix (timestamp);
        CREATE INDEX IF NOT EXISTS idx_ci_ts
            ON raw_carbon_intensity (timestamp, source);
        CREATE INDEX IF NOT EXISTS idx_ic_ts
            ON raw_interconnector (timestamp, name);
        CREATE INDEX IF NOT EXISTS idx_price_ts
            ON raw_electricity_price (timestamp);
        CREATE INDEX IF NOT EXISTS idx_price_date
            ON raw_electricity_price (settlement_date);
        CREATE INDEX IF NOT EXISTS idx_rci_date
            ON regional_carbon_intensity (date);
        CREATE INDEX IF NOT EXISTS idx_rci_region
            ON regional_carbon_intensity (region_id);
    """)
    conn.commit()
    conn.close()


# ── READ (called by data/fetcher.py) ──────────────────────────────────────────
def query_latest(source: str, limit: int = 1, include_subcomponents: bool = False) -> list[sqlite3.Row]:
    table_map = {
        "carbon_intensity": ("raw_carbon_intensity", "timestamp"),
        "generation_mix":   ("raw_generation_mix",   "timestamp"),
        "interconnector":   ("raw_interconnector",    "timestamp"),
    }
    if source not in table_map:
        raise ValueError(f"Unknown source: {source}")
    table, order_col = table_map[source]
    conn = _conn()
    if source == "generation_mix" and not include_subcomponents:
        rows = conn.execute(
            f"SELECT * FROM {table}"
            " WHERE fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')"
            f" ORDER BY {order_col} DESC LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return rows


def query_aggregated(source: str, granularity: str, limit: int = 30) -> list[sqlite3.Row]:
    table = f"agg_{source}_{granularity}"
    if granularity == "daily":
        order_col = "date"
    elif granularity == "quarterly":
        order_col = "quarter"
    else:
        order_col = "month"
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        raise ValueError(f"Aggregate table '{table}' does not exist — run sync first.")
    conn.close()
    return rows


def query_raw_range(
    source: str,
    from_ts: str,
    to_ts: str,
    include_subcomponents: bool = False,
) -> list[sqlite3.Row]:
    table_map = {
        "carbon_intensity": "raw_carbon_intensity",
        "generation_mix":   "raw_generation_mix",
        "interconnector":   "raw_interconnector",
    }
    if source not in table_map:
        raise ValueError(f"Unknown source: {source}")
    table = table_map[source]
    conn = _conn()
    if source == "generation_mix" and not include_subcomponents:
        rows = conn.execute(
            f"SELECT * FROM {table}"
            " WHERE fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')"
            " AND timestamp >= ? AND timestamp <= ?"
            " ORDER BY timestamp",
            (from_ts, to_ts),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM {table}"
            " WHERE timestamp >= ? AND timestamp <= ?"
            " ORDER BY timestamp",
            (from_ts, to_ts),
        ).fetchall()
    conn.close()
    return rows


def query_agg_range(
    source: str,
    granularity: str,
    from_key: str,
    to_key: str,
) -> list[sqlite3.Row]:
    if granularity == "daily":
        table = f"agg_{source}_daily"
        col   = "date"
    elif granularity == "monthly":
        table = f"agg_{source}_monthly"
        col   = "month"
    else:
        raise ValueError(f"Unsupported granularity for range query: {granularity}")
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {col} BETWEEN ? AND ? ORDER BY {col}",
            (from_key, to_key),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        raise ValueError(f"Aggregate table '{table}' does not exist — run sync first.")
    conn.close()
    return rows


def get_last_synced(source: str) -> str | None:
    conn = _conn()
    row = conn.execute(
        "SELECT last_synced FROM sync_metadata WHERE source = ?", (source,)
    ).fetchone()
    conn.close()
    return row["last_synced"] if row else None


def get_latest_timestamp(source: str) -> datetime | None:
    """MAX(timestamp) actually present in the raw table for source, as a
    timezone-aware UTC datetime. None if the table is empty."""
    table_map = {
        "generation_mix": "raw_generation_mix",
        "interconnector":  "raw_interconnector",
    }
    if source not in table_map:
        raise ValueError(f"Unknown source: {source}")
    table = table_map[source]
    conn = _conn()
    row = conn.execute(f"SELECT MAX(timestamp) FROM {table}").fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)


def query_price_range(from_ts: str, to_ts: str) -> list[dict]:
    """Fetch raw_electricity_price rows between two ISO timestamps (inclusive)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM raw_electricity_price"
        " WHERE timestamp >= ? AND timestamp <= ?"
        " ORDER BY timestamp",
        (from_ts, to_ts),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_price_agg(granularity: str, from_key: str, to_key: str) -> list[dict]:
    """
    Fetch price aggregates for a key range.

    granularity : 'daily' (key = YYYY-MM-DD) | 'monthly' (YYYY-MM) |
                  'quarterly' (YYYY-Qn)
    """
    if granularity == "settlement_profile":
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM agg_price_settlement_profile ORDER BY year, settlement_period",
            ).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            raise ValueError("Table 'agg_price_settlement_profile' does not exist — run sync first.")
        conn.close()
        return [dict(r) for r in rows]

    table_col = {
        "daily":     ("agg_price_daily",     "date"),
        "monthly":   ("agg_price_monthly",   "month"),
        "quarterly": ("agg_price_quarterly", "quarter"),
    }
    if granularity not in table_col:
        raise ValueError(f"Unsupported granularity: {granularity}")
    table, col = table_col[granularity]
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {col} BETWEEN ? AND ? ORDER BY {col}",
            (from_key, to_key),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        raise ValueError(f"Table '{table}' does not exist — run sync first.")
    conn.close()
    return [dict(r) for r in rows]


def query_nordpool_range(from_ts: str, to_ts: str) -> list[dict]:
    """Fetch raw_nordpool_n2ex rows between two ISO timestamps (inclusive)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM raw_nordpool_n2ex"
        " WHERE timestamp >= ? AND timestamp <= ?"
        " ORDER BY timestamp",
        (from_ts, to_ts),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_nordpool_agg(granularity: str, from_key: str, to_key: str) -> list[dict]:
    """
    Fetch Nord Pool N2EX aggregates for a key range.

    granularity : 'daily' (key = YYYY-MM-DD) | 'monthly' (YYYY-MM)
    """
    table_col = {
        "daily":   ("agg_nordpool_daily",   "date"),
        "monthly": ("agg_nordpool_monthly", "month"),
    }
    if granularity not in table_col:
        raise ValueError(f"Unsupported granularity for nordpool query: {granularity}")
    table, col = table_col[granularity]
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {col} BETWEEN ? AND ? ORDER BY {col}",
            (from_key, to_key),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        raise ValueError(f"Table '{table}' does not exist — run load_nordpool_excel first.")
    conn.close()
    return [dict(r) for r in rows]


def query_quarterly_summary(from_q: str, to_q: str) -> list[dict]:
    """Return rows from agg_generation_mix_quarterly for quarters in [from_q, to_q]."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT quarter, fuel_type, total_mwh, avg_mw, total_percent
            FROM   agg_generation_mix_quarterly
            WHERE  quarter >= ? AND quarter <= ?
            ORDER  BY quarter, fuel_type
            """,
            (from_q, to_q),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        raise ValueError("agg_generation_mix_quarterly does not exist — run sync first.")
    conn.close()
    return [dict(r) for r in rows]


def check_data_quality(source: str = "generation_mix", days: int = 30) -> dict:
    import datetime as _dt
    conn = _conn()
    try:
        utcnow     = _dt.datetime.utcnow()
        start_date = (utcnow - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        end_date   = (utcnow - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        table = {
            "generation_mix":   "raw_generation_mix",
            "carbon_intensity": "raw_carbon_intensity",
            "interconnector":   "raw_interconnector",
        }.get(source, "raw_generation_mix")
        rows = conn.execute(
            f"""
            SELECT substr(timestamp, 1, 10) AS day,
                   COUNT(DISTINCT substr(timestamp, 1, 16)) AS periods
            FROM   {table}
            WHERE  substr(timestamp, 1, 10) >= ?
               AND substr(timestamp, 1, 10) <= ?
            GROUP  BY day
            ORDER  BY day DESC
            """,
            (start_date, end_date),
        ).fetchall()
        if not rows:
            return {"total_gaps": days * 48, "incomplete_days": days,
                    "worst_day": "", "coverage_pct": 0.0, "checked_days": 0, "source": source}
        total_gaps = 0
        incomplete_days = 0
        worst_day  = ""
        worst_gaps = 0
        for row in rows:
            day, periods = row[0], row[1]
            gaps = max(0, 48 - periods)
            total_gaps += gaps
            if periods < 40:
                incomplete_days += 1
                if gaps > worst_gaps:
                    worst_gaps = gaps
                    worst_day  = day
        checked  = len(rows)
        actual   = sum(r[1] for r in rows)
        expected = checked * 48
        coverage = round(actual / expected * 100, 1) if expected else 0.0
        return {"total_gaps": total_gaps, "incomplete_days": incomplete_days,
                "worst_day": worst_day, "coverage_pct": coverage,
                "checked_days": checked, "source": source}
    except Exception:
        return {"total_gaps": 0, "incomplete_days": 0, "worst_day": "",
                "coverage_pct": 100.0, "checked_days": 0, "source": source}
    finally:
        conn.close()


# ── WRITE helpers ──────────────────────────────────────────────────────────────
def _set_last_synced(source: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO sync_metadata (source, last_synced) VALUES (?, ?)",
        (source, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _insert_generation_mix_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    conn = _conn()
    conn.executemany(
        "INSERT OR REPLACE INTO raw_generation_mix "
        "(timestamp, fuel_type, mw, percent, source) "
        "VALUES (:timestamp, :fuel_type, :mw, :percent, :source)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def _insert_carbon_intensity_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    conn = _conn()
    conn.executemany(
        "INSERT OR REPLACE INTO raw_carbon_intensity "
        "(timestamp, intensity, index_label, source) "
        "VALUES (:timestamp, :intensity, :index_label, :source)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def _insert_interconnector_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    conn = _conn()
    conn.executemany(
        "INSERT OR REPLACE INTO raw_interconnector "
        "(timestamp, name, flow_mw, capacity_mw, source) "
        "VALUES (:timestamp, :name, :flow_mw, :capacity_mw, :source)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def _build_daily_aggregates(source: str, from_date: str = None) -> int:
    with _build_lock:
        conn = _conn()
        if from_date is None:
            if source == "carbon_intensity":
                conn.execute("DROP TABLE IF EXISTS agg_carbon_intensity_daily")
                conn.execute("""
                    CREATE TABLE agg_carbon_intensity_daily AS
                    SELECT substr(timestamp,1,10) AS date, source,
                           AVG(intensity) AS avg_intensity,
                           MIN(intensity) AS min_intensity,
                           MAX(intensity) AS max_intensity,
                           COUNT(*)       AS sample_count
                    FROM   raw_carbon_intensity
                    GROUP  BY date, source
                """)
            elif source == "generation_mix":
                conn.execute("DROP TABLE IF EXISTS agg_generation_mix_daily")
                conn.execute("""
                    CREATE TABLE agg_generation_mix_daily AS
                    WITH daily_totals AS (
                        SELECT substr(timestamp,1,10) AS date,
                               SUM(mw) * 0.5          AS day_total_mwh
                        FROM   raw_generation_mix
                        WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY date
                    )
                    SELECT r.date, r.fuel_type, r.source,
                           AVG(r.mw)                                           AS avg_mw,
                           AVG(r.percent)                                      AS avg_percent,
                           COUNT(*)                                            AS sample_count,
                           SUM(r.mw) * 0.5                                    AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / d.day_total_mwh * 100, 2) AS total_percent
                    FROM   (SELECT substr(timestamp,1,10) AS date,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   daily_totals d ON r.date = d.date
                    GROUP  BY r.date, r.fuel_type, r.source
                """)
            elif source == "interconnector":
                conn.execute("DROP TABLE IF EXISTS agg_interconnector_daily")
                conn.execute("""
                    CREATE TABLE agg_interconnector_daily AS
                    WITH daily_totals AS (
                        SELECT substr(timestamp,1,10)  AS date,
                               SUM(ABS(flow_mw)) * 0.5 AS day_total_abs_mwh
                        FROM   raw_interconnector
                        GROUP  BY date
                    )
                    SELECT r.date, r.name, r.source,
                           AVG(r.flow_mw)                                                    AS avg_flow_mw,
                           COUNT(*)                                                          AS sample_count,
                           SUM(r.flow_mw) * 0.5                                             AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / d.day_total_abs_mwh * 100, 2) AS total_percent
                    FROM   (SELECT substr(timestamp,1,10) AS date, name, source, flow_mw
                            FROM   raw_interconnector) r
                    JOIN   daily_totals d ON r.date = d.date
                    GROUP  BY r.date, r.name, r.source
                """)
        else:
            # Incremental: delete and re-aggregate only affected dates.
            # WHERE timestamp >= from_date uses idx_gen_ts / idx_ic_ts indexes.
            if source == "carbon_intensity":
                conn.execute("DELETE FROM agg_carbon_intensity_daily WHERE date >= ?", (from_date,))
                conn.execute("""
                    INSERT INTO agg_carbon_intensity_daily
                    SELECT substr(timestamp,1,10) AS date, source,
                           AVG(intensity) AS avg_intensity,
                           MIN(intensity) AS min_intensity,
                           MAX(intensity) AS max_intensity,
                           COUNT(*)       AS sample_count
                    FROM   raw_carbon_intensity
                    WHERE  timestamp >= ?
                    GROUP  BY date, source
                """, (from_date,))
            elif source == "generation_mix":
                conn.execute("DELETE FROM agg_generation_mix_daily WHERE date >= ?", (from_date,))
                conn.execute("""
                    INSERT INTO agg_generation_mix_daily
                    WITH daily_totals AS (
                        SELECT substr(timestamp,1,10) AS date,
                               SUM(mw) * 0.5          AS day_total_mwh
                        FROM   raw_generation_mix
                        WHERE  timestamp >= ?
                          AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY date
                    )
                    SELECT r.date, r.fuel_type, r.source,
                           AVG(r.mw)                                           AS avg_mw,
                           AVG(r.percent)                                      AS avg_percent,
                           COUNT(*)                                            AS sample_count,
                           SUM(r.mw) * 0.5                                    AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / d.day_total_mwh * 100, 2) AS total_percent
                    FROM   (SELECT substr(timestamp,1,10) AS date,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  timestamp >= ?
                              AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   daily_totals d ON r.date = d.date
                    GROUP  BY r.date, r.fuel_type, r.source
                """, (from_date, from_date))
            elif source == "interconnector":
                conn.execute("DELETE FROM agg_interconnector_daily WHERE date >= ?", (from_date,))
                conn.execute("""
                    INSERT INTO agg_interconnector_daily
                    WITH daily_totals AS (
                        SELECT substr(timestamp,1,10)  AS date,
                               SUM(ABS(flow_mw)) * 0.5 AS day_total_abs_mwh
                        FROM   raw_interconnector
                        WHERE  timestamp >= ?
                        GROUP  BY date
                    )
                    SELECT r.date, r.name, r.source,
                           AVG(r.flow_mw)                                                    AS avg_flow_mw,
                           COUNT(*)                                                          AS sample_count,
                           SUM(r.flow_mw) * 0.5                                             AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / d.day_total_abs_mwh * 100, 2) AS total_percent
                    FROM   (SELECT substr(timestamp,1,10) AS date, name, source, flow_mw
                            FROM   raw_interconnector
                            WHERE  timestamp >= ?) r
                    JOIN   daily_totals d ON r.date = d.date
                    GROUP  BY r.date, r.name, r.source
                """, (from_date, from_date))
        n = conn.execute(f"SELECT COUNT(*) FROM agg_{source}_daily").fetchone()[0]
        conn.commit()
        conn.close()
        return n


def _build_monthly_aggregates(source: str, from_month: str = None) -> int:
    with _build_lock:
        conn = _conn()
        # Normalise: accept either "2026-07" or "2026-07-02" — take first 7 chars.
        fm = from_month[:7] if from_month else None
        if fm is None:
            if source == "carbon_intensity":
                conn.execute("DROP TABLE IF EXISTS agg_carbon_intensity_monthly")
                conn.execute("""
                    CREATE TABLE agg_carbon_intensity_monthly AS
                    SELECT substr(timestamp,1,7) AS month, source,
                           AVG(intensity) AS avg_intensity,
                           MIN(intensity) AS min_intensity,
                           MAX(intensity) AS max_intensity,
                           COUNT(*)       AS sample_count
                    FROM   raw_carbon_intensity
                    GROUP  BY month, source
                """)
            elif source == "generation_mix":
                conn.execute("DROP TABLE IF EXISTS agg_generation_mix_monthly")
                conn.execute("""
                    CREATE TABLE agg_generation_mix_monthly AS
                    WITH monthly_totals AS (
                        SELECT substr(timestamp,1,7) AS month,
                               SUM(mw) * 0.5          AS month_total_mwh
                        FROM   raw_generation_mix
                        WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY month
                    )
                    SELECT r.month, r.fuel_type, r.source,
                           AVG(r.mw)                                              AS avg_mw,
                           AVG(r.percent)                                         AS avg_percent,
                           COUNT(*)                                               AS sample_count,
                           SUM(r.mw) * 0.5                                       AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / m.month_total_mwh * 100, 2)  AS total_percent
                    FROM   (SELECT substr(timestamp,1,7) AS month,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   monthly_totals m ON r.month = m.month
                    GROUP  BY r.month, r.fuel_type, r.source
                """)
            elif source == "interconnector":
                conn.execute("DROP TABLE IF EXISTS agg_interconnector_monthly")
                conn.execute("""
                    CREATE TABLE agg_interconnector_monthly AS
                    WITH monthly_totals AS (
                        SELECT substr(timestamp,1,7)   AS month,
                               SUM(ABS(flow_mw)) * 0.5 AS month_total_abs_mwh
                        FROM   raw_interconnector
                        GROUP  BY month
                    )
                    SELECT r.month, r.name, r.source,
                           AVG(r.flow_mw)                                                       AS avg_flow_mw,
                           COUNT(*)                                                             AS sample_count,
                           SUM(r.flow_mw) * 0.5                                                AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / m.month_total_abs_mwh * 100, 2)  AS total_percent
                    FROM   (SELECT substr(timestamp,1,7) AS month, name, source, flow_mw
                            FROM   raw_interconnector) r
                    JOIN   monthly_totals m ON r.month = m.month
                    GROUP  BY r.month, r.name, r.source
                """)
        else:
            month_start = fm + "-01"
            if source == "carbon_intensity":
                conn.execute("DELETE FROM agg_carbon_intensity_monthly WHERE month >= ?", (fm,))
                conn.execute("""
                    INSERT INTO agg_carbon_intensity_monthly
                    SELECT substr(timestamp,1,7) AS month, source,
                           AVG(intensity) AS avg_intensity,
                           MIN(intensity) AS min_intensity,
                           MAX(intensity) AS max_intensity,
                           COUNT(*)       AS sample_count
                    FROM   raw_carbon_intensity
                    WHERE  timestamp >= ?
                    GROUP  BY month, source
                """, (month_start,))
            elif source == "generation_mix":
                conn.execute("DELETE FROM agg_generation_mix_monthly WHERE month >= ?", (fm,))
                conn.execute("""
                    INSERT INTO agg_generation_mix_monthly
                    WITH monthly_totals AS (
                        SELECT substr(timestamp,1,7) AS month,
                               SUM(mw) * 0.5          AS month_total_mwh
                        FROM   raw_generation_mix
                        WHERE  timestamp >= ?
                          AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY month
                    )
                    SELECT r.month, r.fuel_type, r.source,
                           AVG(r.mw)                                              AS avg_mw,
                           AVG(r.percent)                                         AS avg_percent,
                           COUNT(*)                                               AS sample_count,
                           SUM(r.mw) * 0.5                                       AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / m.month_total_mwh * 100, 2)  AS total_percent
                    FROM   (SELECT substr(timestamp,1,7) AS month,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  timestamp >= ?
                              AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   monthly_totals m ON r.month = m.month
                    GROUP  BY r.month, r.fuel_type, r.source
                """, (month_start, month_start))
            elif source == "interconnector":
                conn.execute("DELETE FROM agg_interconnector_monthly WHERE month >= ?", (fm,))
                conn.execute("""
                    INSERT INTO agg_interconnector_monthly
                    WITH monthly_totals AS (
                        SELECT substr(timestamp,1,7)   AS month,
                               SUM(ABS(flow_mw)) * 0.5 AS month_total_abs_mwh
                        FROM   raw_interconnector
                        WHERE  timestamp >= ?
                        GROUP  BY month
                    )
                    SELECT r.month, r.name, r.source,
                           AVG(r.flow_mw)                                                       AS avg_flow_mw,
                           COUNT(*)                                                             AS sample_count,
                           SUM(r.flow_mw) * 0.5                                                AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / m.month_total_abs_mwh * 100, 2)  AS total_percent
                    FROM   (SELECT substr(timestamp,1,7) AS month, name, source, flow_mw
                            FROM   raw_interconnector
                            WHERE  timestamp >= ?) r
                    JOIN   monthly_totals m ON r.month = m.month
                    GROUP  BY r.month, r.name, r.source
                """, (month_start, month_start))
        n = conn.execute(f"SELECT COUNT(*) FROM agg_{source}_monthly").fetchone()[0]
        conn.commit()
        conn.close()
        return n


def _quarter_label(date_str: str) -> str:
    """'2026-07-02' -> '2026-Q3'"""
    month = int(date_str[5:7])
    return f"{date_str[:4]}-Q{(month + 2) // 3}"


def _build_quarterly_aggregates(source: str, from_quarter: str = None) -> int:
    # Quarter expression: year || '-Q' || integer-division quarter number.
    # Integer division: months 1-3 → 1, 4-6 → 2, 7-9 → 3, 10-12 → 4.
    _Q = ("substr(timestamp,1,4) || '-Q' || "
          "((CAST(substr(timestamp,6,2) AS INTEGER) + 2) / 3)")

    with _build_lock:
        conn = _conn()
        if from_quarter is None:
            if source == "generation_mix":
                conn.execute("DROP TABLE IF EXISTS agg_generation_mix_quarterly")
                conn.execute(f"""
                    CREATE TABLE agg_generation_mix_quarterly AS
                    WITH quarterly_totals AS (
                        SELECT {_Q} AS quarter,
                               SUM(mw) * 0.5   AS q_total_mwh
                        FROM   raw_generation_mix
                        WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY quarter
                    )
                    SELECT r.quarter, r.fuel_type, r.source,
                           AVG(r.mw)                                             AS avg_mw,
                           AVG(r.percent)                                        AS avg_percent,
                           COUNT(*)                                              AS sample_count,
                           SUM(r.mw) * 0.5                                      AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / q.q_total_mwh * 100, 2)     AS total_percent
                    FROM   (SELECT {_Q} AS quarter,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   quarterly_totals q ON r.quarter = q.quarter
                    GROUP  BY r.quarter, r.fuel_type, r.source
                """)
            elif source == "interconnector":
                conn.execute("DROP TABLE IF EXISTS agg_interconnector_quarterly")
                conn.execute(f"""
                    CREATE TABLE agg_interconnector_quarterly AS
                    WITH quarterly_totals AS (
                        SELECT {_Q} AS quarter,
                               SUM(ABS(flow_mw)) * 0.5 AS q_total_abs_mwh
                        FROM   raw_interconnector
                        GROUP  BY quarter
                    )
                    SELECT r.quarter, r.name, r.source,
                           AVG(r.flow_mw)                                                      AS avg_flow_mw,
                           COUNT(*)                                                            AS sample_count,
                           SUM(r.flow_mw) * 0.5                                               AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / q.q_total_abs_mwh * 100, 2)     AS total_percent
                    FROM   (SELECT {_Q} AS quarter, name, source, flow_mw
                            FROM   raw_interconnector) r
                    JOIN   quarterly_totals q ON r.quarter = q.quarter
                    GROUP  BY r.quarter, r.name, r.source
                """)
        else:
            # Incremental: convert quarter label to the first timestamp of that quarter.
            year, qnum = from_quarter.split("-Q")
            first_month = (int(qnum) - 1) * 3 + 1
            q_start_date = f"{year}-{first_month:02d}-01"

            if source == "generation_mix":
                conn.execute(
                    "DELETE FROM agg_generation_mix_quarterly WHERE quarter >= ?",
                    (from_quarter,),
                )
                conn.execute(f"""
                    INSERT INTO agg_generation_mix_quarterly
                    WITH quarterly_totals AS (
                        SELECT {_Q} AS quarter,
                               SUM(mw) * 0.5   AS q_total_mwh
                        FROM   raw_generation_mix
                        WHERE  timestamp >= ?
                          AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')
                        GROUP  BY quarter
                    )
                    SELECT r.quarter, r.fuel_type, r.source,
                           AVG(r.mw)                                             AS avg_mw,
                           AVG(r.percent)                                        AS avg_percent,
                           COUNT(*)                                              AS sample_count,
                           SUM(r.mw) * 0.5                                      AS total_mwh,
                           ROUND(SUM(r.mw) * 0.5 / q.q_total_mwh * 100, 2)     AS total_percent
                    FROM   (SELECT {_Q} AS quarter,
                                   fuel_type, source, mw, percent
                            FROM   raw_generation_mix
                            WHERE  timestamp >= ?
                              AND  fuel_type NOT IN ('wind_bm','wind_emb','ccgt','ocgt')) r
                    JOIN   quarterly_totals q ON r.quarter = q.quarter
                    GROUP  BY r.quarter, r.fuel_type, r.source
                """, (q_start_date, q_start_date))
            elif source == "interconnector":
                conn.execute(
                    "DELETE FROM agg_interconnector_quarterly WHERE quarter >= ?",
                    (from_quarter,),
                )
                conn.execute(f"""
                    INSERT INTO agg_interconnector_quarterly
                    WITH quarterly_totals AS (
                        SELECT {_Q} AS quarter,
                               SUM(ABS(flow_mw)) * 0.5 AS q_total_abs_mwh
                        FROM   raw_interconnector
                        WHERE  timestamp >= ?
                        GROUP  BY quarter
                    )
                    SELECT r.quarter, r.name, r.source,
                           AVG(r.flow_mw)                                                      AS avg_flow_mw,
                           COUNT(*)                                                            AS sample_count,
                           SUM(r.flow_mw) * 0.5                                               AS total_mwh,
                           ROUND(SUM(ABS(r.flow_mw)) * 0.5 / q.q_total_abs_mwh * 100, 2)     AS total_percent
                    FROM   (SELECT {_Q} AS quarter, name, source, flow_mw
                            FROM   raw_interconnector
                            WHERE  timestamp >= ?) r
                    JOIN   quarterly_totals q ON r.quarter = q.quarter
                    GROUP  BY r.quarter, r.name, r.source
                """, (q_start_date, q_start_date))

        n = conn.execute(f"SELECT COUNT(*) FROM agg_{source}_quarterly").fetchone()[0]
        conn.commit()
        conn.close()
        return n


# ── API fetch functions (ported from GB-Grid-Agent/tools.py) ──────────────────

def _ci_rows_for_window(date_from: str, date_to: str) -> list[dict]:
    url  = f"{_CI_URL}/{date_from}/{date_to}"
    resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    rows = []
    for d in resp.json()["data"]:
        val = (d["intensity"]["actual"]
               if d["intensity"]["actual"] is not None
               else d["intensity"]["forecast"])
        if val is None:
            continue
        rows.append({
            "timestamp":   d["from"],
            "intensity":   float(val),
            "index_label": d["intensity"]["index"],
            "source":      "CarbonIntensityAPI",
        })
    return rows


def _ci_incremental_rows() -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    start  = datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc)
    end    = datetime.now(timezone.utc)
    rows: list[dict] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=14), end)
        rows.extend(_ci_rows_for_window(
            cursor.strftime("%Y-%m-%dT%H:%MZ"),
            window_end.strftime("%Y-%m-%dT%H:%MZ"),
        ))
        cursor = window_end
    return rows


def fetch_regional_carbon_intensity() -> list[dict]:
    """
    Fetch the latest half-hourly regional carbon intensity snapshot
    from the public Carbon Intensity API (no key required).

    Endpoint: https://api.carbonintensity.org.uk/regional
    Returns: list of dicts, one per DNO region (14 entries, regionid 1–14),
             each with keys:
               region_id, short_name, dno_region,
               intensity_gco2_kwh, intensity_index,
               gen_wind_pct, gen_solar_pct, gen_gas_pct,
               gen_nuclear_pct, gen_biomass_pct, gen_hydro_pct,
               gen_coal_pct, gen_imports_pct, gen_other_pct,
               period_start_utc
    Returns [] on any error (page handles gracefully).
    """
    url = "https://api.carbonintensity.org.uk/regional"
    try:
        resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    # Response: {"data": [{"from": "...", "to": "...", "regions": [...18 items...]}]}
    try:
        period_obj = data["data"][0]
        period_from = period_obj.get("from", "")
        regions = period_obj.get("regions", [])
    except (IndexError, KeyError):
        return []

    results = []
    for region in regions:
        rid = region.get("regionid", 0)
        if rid < 1 or rid > 14:
            continue
        intensity = region.get("intensity", {})
        genmix    = {g["fuel"]: g["perc"] for g in region.get("generationmix", [])}
        results.append({
            "region_id":          rid,
            "short_name":         region.get("shortname", ""),
            "dno_region":         region.get("dnoregion", ""),
            "intensity_gco2_kwh": intensity.get("forecast", 0),
            "intensity_index":    intensity.get("index", ""),
            "gen_wind_pct":       genmix.get("wind",    0),
            "gen_solar_pct":      genmix.get("solar",   0),
            "gen_gas_pct":        genmix.get("gas",     0),
            "gen_nuclear_pct":    genmix.get("nuclear", 0),
            "gen_biomass_pct":    genmix.get("biomass", 0),
            "gen_hydro_pct":      genmix.get("hydro",   0),
            "gen_coal_pct":       genmix.get("coal",    0),
            "gen_imports_pct":    genmix.get("imports", 0),
            "gen_other_pct":      genmix.get("other",   0),
            "period_start_utc":   period_from,
        })

    return results


def _fetch_regional_ci_window(from_dt: str, to_dt: str) -> list[dict]:
    """
    Fetch regional CI data for a time window from the API.
    from_dt / to_dt: ISO strings e.g. "2020-01-01T00:00Z"
    Returns list of half-hourly period dicts, each containing
    {from, to, regions: [{regionid, shortname, dnoregion,
                          intensity: {forecast, index},
                          generationmix: [{fuel, perc}]}]}
    Returns [] on error.
    """
    url = (f"https://api.carbonintensity.org.uk/regional/intensity"
           f"/{from_dt}/{to_dt}")
    try:
        resp = requests.get(url, timeout=30,
                            headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"[CI regional fetch error] {from_dt} → {to_dt}: {e}")
        return []


def _aggregate_regional_ci_to_daily(periods: list[dict]) -> list[dict]:
    """
    Aggregate half-hourly period data to daily averages per region.
    Only keeps regions 1-14 (DNO regions, not England/Scotland/Wales/GB).
    Returns list of dicts ready to INSERT into regional_carbon_intensity.
    """
    from collections import defaultdict
    import statistics

    acc: dict = defaultdict(lambda: defaultdict(list))
    meta: dict = {}

    for period in periods:
        date_str = period.get("from", "")[:10]
        for region in period.get("regions", []):
            rid = region.get("regionid", 0)
            if rid < 1 or rid > 14:
                continue
            key = (date_str, rid)
            meta[key] = {
                "short_name": region.get("shortname", ""),
                "dno_region": region.get("dnoregion", ""),
            }
            intensity = region.get("intensity", {})
            acc[key]["intensity"].append(intensity.get("forecast", 0))
            genmix = {g["fuel"]: g["perc"]
                      for g in region.get("generationmix", [])}
            for fuel in ("wind", "solar", "gas", "nuclear",
                         "imports", "biomass", "hydro", "other"):
                acc[key][fuel].append(genmix.get(fuel, 0))

    rows = []
    for (date_str, rid), fields in sorted(acc.items()):
        intensities = fields["intensity"]
        m = meta[(date_str, rid)]
        rows.append({
            "date":            date_str,
            "region_id":       rid,
            "short_name":      m["short_name"],
            "dno_region":      m["dno_region"],
            "avg_intensity":   round(statistics.mean(intensities), 1),
            "min_intensity":   min(intensities),
            "max_intensity":   max(intensities),
            "avg_wind_pct":    round(statistics.mean(fields["wind"]),    1),
            "avg_solar_pct":   round(statistics.mean(fields["solar"]),   1),
            "avg_gas_pct":     round(statistics.mean(fields["gas"]),     1),
            "avg_nuclear_pct": round(statistics.mean(fields["nuclear"]), 1),
            "avg_imports_pct": round(statistics.mean(fields["imports"]), 1),
            "avg_biomass_pct": round(statistics.mean(fields["biomass"]), 1),
            "avg_hydro_pct":   round(statistics.mean(fields["hydro"]),   1),
            "avg_other_pct":   round(statistics.mean(fields["other"]),   1),
            "period_count":    len(intensities),
        })
    return rows


def _upsert_regional_ci_rows(conn, rows: list[dict]) -> int:
    """Insert or replace daily regional CI rows. Returns count inserted."""
    if not rows:
        return 0
    conn.executemany("""
        INSERT OR REPLACE INTO regional_carbon_intensity
        (date, region_id, short_name, dno_region,
         avg_intensity, min_intensity, max_intensity,
         avg_wind_pct, avg_solar_pct, avg_gas_pct,
         avg_nuclear_pct, avg_imports_pct, avg_biomass_pct,
         avg_hydro_pct, avg_other_pct, period_count)
        VALUES
        (:date, :region_id, :short_name, :dno_region,
         :avg_intensity, :min_intensity, :max_intensity,
         :avg_wind_pct, :avg_solar_pct, :avg_gas_pct,
         :avg_nuclear_pct, :avg_imports_pct, :avg_biomass_pct,
         :avg_hydro_pct, :avg_other_pct, :period_count)
    """, rows)
    conn.commit()
    return len(rows)


def sync_regional_ci_history(
    from_date: str = "2020-01-01",
    progress_callback=None,
) -> dict:
    """
    Backfill or incrementally sync regional CI history into SQLite.

    Checks the latest date already in the DB and only fetches
    missing data (from the day after the latest stored date).
    Fetches in 14-day windows to respect API limits.

    from_date: earliest date to fetch if DB is empty (YYYY-MM-DD)
    progress_callback: optional callable(current, total, message)
                       for Streamlit progress bar

    Returns {"inserted": N, "windows": N, "error": str|None}
    """
    from datetime import date as _date, timedelta as _td

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        latest = conn.execute(
            "SELECT MAX(date) FROM regional_carbon_intensity"
        ).fetchone()[0]

        if latest:
            start = _date.fromisoformat(latest) + _td(days=1)
        else:
            start = _date.fromisoformat(from_date)

        today = _date.today()
        end   = today - _td(days=1)

        if start > end:
            return {"inserted": 0, "windows": 0, "error": None,
                    "message": "Already up to date."}

        windows = []
        cursor = start
        while cursor <= end:
            w_end = min(cursor + _td(days=13), end)
            windows.append((cursor, w_end))
            cursor = w_end + _td(days=1)

        total_inserted = 0
        for i, (w_start, w_end) in enumerate(windows):
            if progress_callback:
                progress_callback(
                    i, len(windows),
                    f"Fetching {w_start} → {w_end} ({i + 1}/{len(windows)})"
                )
            periods = _fetch_regional_ci_window(
                f"{w_start}T00:00Z", f"{w_end}T23:30Z"
            )
            if not periods:
                continue
            rows = _aggregate_regional_ci_to_daily(periods)
            total_inserted += _upsert_regional_ci_rows(conn, rows)

        if progress_callback:
            progress_callback(len(windows), len(windows), "Done")

        return {
            "inserted": total_inserted,
            "windows":  len(windows),
            "error":    None,
            "message":  f"Inserted {total_inserted} rows across {len(windows)} API calls.",
        }
    except Exception as e:
        return {"inserted": 0, "windows": 0, "error": str(e), "message": str(e)}
    finally:
        conn.close()


def query_regional_ci_history(
    region_ids: list[int] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """
    Query stored daily regional CI history from SQLite.
    region_ids: list of 1-14, or None for all regions.
    Returns list of row dicts sorted by date, region_id.
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row

    where_clauses = []
    params: list = []
    if region_ids:
        placeholders = ",".join("?" * len(region_ids))
        where_clauses.append(f"region_id IN ({placeholders})")
        params.extend(region_ids)
    if from_date:
        where_clauses.append("date >= ?")
        params.append(from_date)
    if to_date:
        where_clauses.append("date <= ?")
        params.append(to_date)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = conn.execute(
        f"SELECT * FROM regional_carbon_intensity {where} "
        f"ORDER BY date, region_id",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _neso_records_to_rows(records: list[dict]) -> list[dict]:
    rows = []
    for rec in records:
        ts    = rec.get("DATETIME")
        total = float(rec["GENERATION"]) if rec.get("GENERATION") not in (None, "") else None
        wind  = (
            (float(rec["WIND"])     if rec.get("WIND")     not in (None, "") else 0.0) +
            (float(rec["WIND_EMB"]) if rec.get("WIND_EMB") not in (None, "") else 0.0)
        )
        fuel_values = {
            col.lower(): float(rec[col]) if rec.get(col) not in (None, "") else None
            for col in _NESO_FUELS
        }
        fuel_values["wind"] = wind
        for fuel, mw in fuel_values.items():
            if mw is None:
                continue
            percent = round((mw / total * 100), 2) if total else 0.0
            rows.append({
                "timestamp": ts, "fuel_type": fuel,
                "mw": mw, "percent": percent, "source": "NESO",
            })
    return rows


def _neso_incremental_rows() -> list[dict]:
    cutoff    = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    all_rows: list[dict] = []
    offset    = 0
    page_size = 5000
    while True:
        sql = (
            f'SELECT * FROM "{_NESO_RES}" WHERE "DATETIME" >= \'{cutoff}\' '
            f'ORDER BY "DATETIME" ASC LIMIT {page_size} OFFSET {offset}'
        )
        resp = requests.get(_NESO_URL, params={"sql": sql}, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success", False):
            raise ValueError(f"NESO API returned success=false: {payload}")
        records = payload["result"]["records"]
        if not records:
            break
        all_rows.extend(_neso_records_to_rows(records))
        offset += page_size
        time.sleep(1)
        if len(records) < page_size:
            break
    return all_rows


def _elexon_rows_for_window(date_from: str, date_to: str, cable: str) -> list[dict]:
    params = {
        "settlementDateFrom": date_from,
        "settlementDateTo":   date_to,
        "interconnectorName": cable,
        "format":             "json",
    }
    resp = requests.get(_ELEXON_URL, params=params, timeout=8)
    resp.raise_for_status()
    payload = resp.json()
    data    = payload.get("data", []) if isinstance(payload, dict) else []
    return [{
        "timestamp":   d["startTime"],
        "name":        cable,
        "flow_mw":     float(d["generation"]),
        "capacity_mw": 0.0,
        "source":      "ElexonBMRS",
    } for d in data]


def _elexon_incremental_rows() -> list[dict]:
    cutoff   = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    start    = datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc)
    end      = datetime.now(timezone.utc)
    all_rows: list[dict] = []
    cursor   = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=7), end)
        for cable in _IC_CABLES:
            try:
                all_rows.extend(_elexon_rows_for_window(
                    cursor.strftime("%Y-%m-%d"),
                    window_end.strftime("%Y-%m-%d"),
                    cable,
                ))
                time.sleep(0.3)
            except requests.exceptions.RequestException:
                continue
        cursor = window_end
    return all_rows


# ── SYNC ───────────────────────────────────────────────────────────────────────
def sync_if_needed(
    source: str,
    freshness_minutes: int = 60,
    backfill_start: str = "2020-01-01",
) -> dict:
    """
    Pull latest data for source if cache is stale (> freshness_minutes old).
    Rebuilds daily + monthly aggregates after any successful fetch.
    Returns a summary dict: {source, action, rows_added, aggregates_rebuilt}.
    """
    summary: dict = {
        "source": source, "action": None,
        "rows_added": 0, "aggregates_rebuilt": False,
    }
    _init_schema()

    last = get_last_synced(source)
    if last is not None:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        if age <= timedelta(minutes=freshness_minutes):
            summary["action"] = "skipped"
            return summary
        action = "incremental"
    else:
        action = "backfill"

    try:
        if source == "carbon_intensity":
            n = _insert_carbon_intensity_rows(_ci_incremental_rows())
        elif source == "generation_mix":
            n = _insert_generation_mix_rows(_neso_incremental_rows())
        elif source == "interconnector":
            n = _insert_interconnector_rows(_elexon_incremental_rows())
        else:
            raise ValueError(f"Unknown source: {source}")

        _set_last_synced(source)
        _build_daily_aggregates(source)
        _build_monthly_aggregates(source)
        summary["action"] = action
        summary["rows_added"] = n
        summary["aggregates_rebuilt"] = True
    except Exception as exc:
        summary["action"] = "error"
        summary["error"]  = str(exc)

    return summary
