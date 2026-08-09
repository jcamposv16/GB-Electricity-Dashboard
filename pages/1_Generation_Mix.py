"""Generation Mix dashboard page."""

from datetime import date, datetime, timedelta, timezone

import streamlit as st

from data.fetcher import fetch_generation_mix_range, get_last_synced
from components.charts import build_gen_mix_charts
from utils.halfhourly_bounds import (
    HALF_HOURLY_MAX_DAYS,
    half_hourly_picker_bounds,
    half_hourly_default_window,
)

# ── Time slot options (half-hourly) ───────────────────────────────────────────
_TIMES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]

_GRAN_KEY = {
    "Half Hourly": "half_hourly",
    "Daily":       "daily",
    "Monthly":     "monthly",
}

# ── Granularity selector ───────────────────────────────────────────────────────
gran_label = st.segmented_control(
    "Granularity",
    options=list(_GRAN_KEY.keys()),
    default="Half Hourly",
    key="gen_granularity",
    label_visibility="collapsed",
)
if gran_label is None:
    gran_label = "Half Hourly"
granularity = _GRAN_KEY[gran_label]

# ── Default windows (computed fresh; session_state is NOT used for defaults
#    because the user switching granularity should get a sensible new window) ──
_now     = datetime.now(timezone.utc)
_today   = _now.date()

if granularity == "half_hourly":
    _default_from_date = (_today - timedelta(days=1))
    _default_to_date   = _today
    _default_from_time = _now.strftime("%H:%M")
    # Round _default_from_time down to nearest half hour
    _h, _m             = _now.hour, _now.minute
    _default_from_time = f"{_h:02d}:{'30' if _m >= 30 else '00'}"
    _default_to_time   = _default_from_time  # same half hour, 24h window
elif granularity == "daily":
    _default_from_date = _today - timedelta(days=30)
    _default_to_date   = _today
    _default_from_time = "00:00"
    _default_to_time   = "23:30"
else:  # monthly
    _y, _mo            = _today.year, _today.month
    _from_mo           = _mo - 12
    _from_yr           = _y
    if _from_mo <= 0:
        _from_mo += 12
        _from_yr -= 1
    _default_from_date = date(_from_yr, _from_mo, 1)
    _default_to_date   = _today
    _default_from_time = "00:00"
    _default_to_time   = "23:30"

# ── Half-hourly picker bounds (data-anchored, not wall-clock) ─────────────────
if granularity == "half_hourly":
    _picker_min_date, _picker_max_date = half_hourly_picker_bounds("generation_mix")
    # Default From/To are anchored to the latest timestamp actually in the
    # data (not "now") — the deployed snapshot can lag real time by days,
    # which previously collapsed From/To to the same clamped value.
    _dflt_from_date, _dflt_from_time, _dflt_to_date, _dflt_to_time = (
        half_hourly_default_window("generation_mix")
    )
    if _dflt_to_date is not None:
        _default_from_date = _dflt_from_date
        _default_from_time = _dflt_from_time
        _default_to_date   = _dflt_to_date
        _default_to_time   = _dflt_to_time
    # else: no data yet (e.g. empty local dev DB) — keep the wall-clock
    # defaults computed above.
else:
    _picker_min_date, _picker_max_date = None, None

# ── Date / time range picker ───────────────────────────────────────────────────
show_time = (granularity == "half_hourly")

cols = st.columns([0.6, 2, 1.2, 0.4, 2, 1.2])

with cols[0]:
    st.markdown(
        "<div style='padding-top:8px;color:#eef4f2;font-size:13px;'>From</div>",
        unsafe_allow_html=True,
    )
with cols[1]:
    from_date = st.date_input(
        "From date",
        value=_default_from_date,
        min_value=_picker_min_date,
        max_value=_picker_max_date,
        key=f"gen_from_date_{granularity}",
        label_visibility="collapsed",
    )
with cols[2]:
    if show_time:
        from_time = st.selectbox(
            "From time",
            _TIMES,
            index=_TIMES.index(_default_from_time) if _default_from_time in _TIMES else 0,
            key=f"gen_from_time_{granularity}",
            label_visibility="collapsed",
        )
    else:
        from_time = "00:00"

with cols[3]:
    st.markdown(
        "<div style='padding-top:8px;color:#eef4f2;font-size:13px;text-align:center;'>to</div>",
        unsafe_allow_html=True,
    )
with cols[4]:
    to_date = st.date_input(
        "To date",
        value=_default_to_date,
        min_value=_picker_min_date,
        max_value=_picker_max_date,
        key=f"gen_to_date_{granularity}",
        label_visibility="collapsed",
    )
with cols[5]:
    if show_time:
        to_time = st.selectbox(
            "To time",
            _TIMES,
            index=_TIMES.index(_default_to_time) if _default_to_time in _TIMES else len(_TIMES) - 1,
            key=f"gen_to_time_{granularity}",
            label_visibility="collapsed",
        )
    else:
        to_time = "23:30"

# ── Build from_ts / to_ts strings ─────────────────────────────────────────────
from_ts = f"{from_date}T{from_time}:00"
to_ts   = f"{to_date}T{to_time}:00"

# ── Validation ────────────────────────────────────────────────────────────────
if from_ts >= to_ts:
    st.error("'From' must be before 'To'. Adjust the range.")
    st.stop()

if granularity == "half_hourly":
    max_window = timedelta(days=HALF_HOURLY_MAX_DAYS)
    actual_window = datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
    if actual_window > max_window:
        clipped_to = datetime.fromisoformat(from_ts) + max_window
        to_ts = clipped_to.strftime("%Y-%m-%dT%H:%M:00")
        st.warning(
            f"Half-hourly view is limited to {HALF_HOURLY_MAX_DAYS} days — "
            f"showing {from_ts[:16]} to {to_ts[:16]}."
        )
elif granularity == "daily":
    max_window = timedelta(days=1100)
    actual_window = datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
    if actual_window > max_window:
        to_ts = (datetime.fromisoformat(from_ts) + max_window).strftime("%Y-%m-%dT%H:%M:00")
elif granularity == "monthly":
    # Max 79 months (full history). Convert to months for check.
    from_dt = datetime.fromisoformat(from_ts)
    to_dt   = datetime.fromisoformat(to_ts)
    n_months = (to_dt.year - from_dt.year) * 12 + (to_dt.month - from_dt.month)
    if n_months > 79:
        # Cap to_ts at 79 months forward
        cap_year  = from_dt.year + (from_dt.month + 78) // 12
        cap_month = (from_dt.month + 78) % 12 or 12
        to_ts = f"{cap_year}-{cap_month:02d}-28T23:30:00"

# ── Fetch data ─────────────────────────────────────────────────────────────────
rows = fetch_generation_mix_range(granularity, from_ts, to_ts)

if not rows:
    st.info("No data for the selected window.")
    st.stop()

# ── Window label for chart subtitles ─────────────────────────────────────────
if granularity == "half_hourly":
    window_label = f"{from_ts[:16]} → {to_ts[:16]} · half-hourly"
elif granularity == "daily":
    window_label = f"{from_ts[:10]} → {to_ts[:10]} · daily totals"
else:
    window_label = f"{from_ts[:7]} → {to_ts[:7]} · monthly totals"

# ── Build charts ───────────────────────────────────────────────────────────────
figures = build_gen_mix_charts(rows, granularity, window_label)

# ── Chart headers ─────────────────────────────────────────────────────────────
SUBTITLES = [
    f"Generation output by fuel type · {window_label}",
    f"Share of generation by fuel type (100% stacked) · {window_label}",
    f"Individual fuel lines + dashed total · {window_label}",
    f"Individual fuel share lines · {window_label}",
]


def _chart_header(title: str, subtitle: str, top_margin: bool = True) -> None:
    mt = "margin-top:32px;" if top_margin else ""
    st.markdown(f"""
    <div style="{mt} margin-bottom:6px;">
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
        <div style="width:28px; height:11px; background:#52796f; flex-shrink:0;"></div>
        <div style="height:1.5px; flex:1; background:#52796f;"></div>
      </div>
      <div style="font-size:18px; font-weight:700; color:#eef4f2; letter-spacing:0.01em;">
        {title}
      </div>
      <div style="font-size:12px; color:#a3c3bb; margin-top:2px;">{subtitle}</div>
    </div>
    """, unsafe_allow_html=True)


# ── Draw charts in 2×2 grid ────────────────────────────────────────────────────
row1  = st.columns(2, gap="medium")
row2  = st.columns(2, gap="medium")
slots = [row1[0], row1[1], row2[0], row2[1]]

for i, (title, fig) in enumerate(figures):
    try:
        subtitle = SUBTITLES[i] if i < len(SUBTITLES) else ""
        with slots[i]:
            _chart_header(title, subtitle, top_margin=(i >= 2))
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(
                "<div style='font-size:10px;color:#a3c3bb;margin-bottom:4px;'>"
                "<b>Source:</b> National Energy System Operator (NESO)</div>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.error(f"Chart {i+1} failed: {e}")

# ── Cache freshness ────────────────────────────────────────────────────────────
last = get_last_synced("generation_mix")
if last:
    st.markdown(
        f"<div style='font-size:11px;color:#a3c3bb;margin-top:20px;'>"
        f"Cache last synced: {last[:16]} UTC</div>",
        unsafe_allow_html=True,
    )
