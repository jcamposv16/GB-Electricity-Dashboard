"""Shared half-hourly date-picker bounds, based on actual data availability."""

from datetime import timedelta

from data.cache_db import get_latest_timestamp

HALF_HOURLY_MAX_DAYS = 89


def half_hourly_picker_bounds(source: str):
    """
    Return (min_date, max_date) for the half-hourly date pickers, based on
    the latest timestamp actually in the data: max_date = latest data date,
    min_date = max_date - 89 days. Returns (None, None) if no data (so
    pickers stay unconstrained rather than breaking).
    """
    latest = get_latest_timestamp(source)
    if latest is None:
        return None, None
    max_date = latest.date()
    min_date = max_date - timedelta(days=HALF_HOURLY_MAX_DAYS)
    return min_date, max_date


def half_hourly_default_window(source: str):
    """
    Return (default_from_date, default_from_time, default_to_date,
    default_to_time) for the half-hourly picker's initial values, anchored
    to the latest timestamp actually in the data (To = latest data
    timestamp, From = To minus 24 hours) rather than the wall clock — the
    deployed snapshot can lag "now" by days, which previously collapsed
    the default From/To to the same value once picker bounds clamped them.

    Returns (None, None, None, None) if there's no data yet (e.g. an empty
    local dev DB); callers should keep their existing wall-clock-based
    default in that case.
    """
    latest = get_latest_timestamp(source)
    if latest is None:
        return None, None, None, None

    def _half_hour(dt):
        return f"{dt.hour:02d}:{'30' if dt.minute >= 30 else '00'}"

    default_to_date   = latest.date()
    default_to_time   = _half_hour(latest)
    default_from_dt   = latest - timedelta(hours=24)
    default_from_date = default_from_dt.date()
    default_from_time = _half_hour(default_from_dt)
    return default_from_date, default_from_time, default_to_date, default_to_time
