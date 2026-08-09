"""
Thin wrapper over the local cache_db module.
Reads from cache/grid_cache.db — no dependency on GB-Grid-Agent.
"""

import streamlit as st

from data import cache_db


@st.cache_data(ttl=30)
def fetch_generation_mix(granularity: str, limit: int) -> list[dict]:
    try:
        if granularity == "half_hourly":
            rows = cache_db.query_latest("generation_mix", limit * 12)
        else:
            rows = cache_db.query_aggregated("generation_mix", granularity, limit * 12)
        return [dict(r) for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_interconnector(granularity: str, limit: int) -> list[dict]:
    try:
        if granularity == "half_hourly":
            rows = cache_db.query_latest("interconnector", limit * 12)
        else:
            rows = cache_db.query_aggregated("interconnector", granularity, limit * 12)
        return [dict(r) for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=30)
def fetch_interconnector_range(
    granularity: str,
    from_ts: str,
    to_ts: str,
) -> list[dict]:
    try:
        if granularity == "half_hourly":
            rows = cache_db.query_raw_range("interconnector", from_ts, to_ts)
        elif granularity == "daily":
            rows = cache_db.query_agg_range(
                "interconnector", "daily", from_ts[:10], to_ts[:10]
            )
        elif granularity == "monthly":
            rows = cache_db.query_agg_range(
                "interconnector", "monthly", from_ts[:7], to_ts[:7]
            )
        else:
            return []
        return [dict(r) for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=30)
def get_last_synced(source: str) -> str | None:
    try:
        return cache_db.get_last_synced(source)
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_generation_mix_range(
    granularity: str,
    from_ts: str,
    to_ts: str,
) -> list[dict]:
    try:
        if granularity == "half_hourly":
            rows = cache_db.query_raw_range("generation_mix", from_ts, to_ts)
        elif granularity == "daily":
            rows = cache_db.query_agg_range(
                "generation_mix", "daily", from_ts[:10], to_ts[:10]
            )
        elif granularity == "monthly":
            rows = cache_db.query_agg_range(
                "generation_mix", "monthly", from_ts[:7], to_ts[:7]
            )
        else:
            return []
        return [dict(r) for r in rows]
    except Exception:
        return []


def check_quality(source: str, days: int = 30) -> dict:
    try:
        return cache_db.check_data_quality(source, days)
    except Exception:
        return {"coverage_pct": 0.0, "incomplete_days": 0, "total_gaps": 0}


def sync_all_sources() -> dict:
    """
    Fire the data pipeline in a background thread and return immediately.
    The thread clears st.cache_data when done so the next page render
    picks up fresh data without blocking startup.
    """
    import sys
    if not sys.platform.startswith("win"):
        # Deployed (Linux/HF) mode: pipeline sync unavailable, and the
        # CI history refresh is a synchronous network call that must
        # never run in the startup path — it previously blocked the
        # HF health check ("Launch timed out, workload was not healthy
        # after 30 min"). The dashboard serves snapshot data; live CI
        # refresh is not worth a failed deployment.
        return {"action": "disabled_on_hf"}

    import threading

    def _run():
        try:
            import subprocess
            import sys
            from pathlib import Path
            root        = Path(__file__).parent.parent
            venv_python = str(root / ".venv" / "Scripts" / "python.exe")
            sync_script = str(root / "energy-data-pipeline" / "sync.py")
            subprocess.run(
                [venv_python, sync_script],
                timeout=300,
                cwd=str(root),
            )
            from data.csv_to_sqlite import sync_csv_to_sqlite
            sync_csv_to_sqlite(incremental=True)
            from data.cache_db import sync_regional_ci_history
            sync_regional_ci_history()
        except Exception:
            pass
        finally:
            st.cache_data.clear()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"action": "sync_started_background"}
