"""Interconnector Flows dashboard page."""

from datetime import date, datetime, timedelta, timezone

import streamlit as st

from data.fetcher import fetch_interconnector, fetch_interconnector_range, get_last_synced
from components.charts import (
    build_interconnector_trend,
    build_interconnector_stacked_diverging,
)
from styles.theme import CABLE_PALETTE
from utils.halfhourly_bounds import (
    HALF_HOURLY_MAX_DAYS,
    half_hourly_picker_bounds,
    half_hourly_default_window,
)

# ── Granularity options ────────────────────────────────────────────────────────
_GRAN_KEY = {
    "Half Hourly": "half_hourly",
    "Daily":       "daily",
    "Monthly":     "monthly",
}
_TIMES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]

# ── Fetch current snapshot (always half-hourly, always latest) ─────────────────
current_rows = fetch_interconnector("half_hourly", 12)

if not current_rows:
    st.error(
        "No interconnector data in cache. "
        "Run the GB Grid Agent first or click **🔄 Refresh data** in the sidebar.",
    )
    st.stop()

# ── Process current snapshot ───────────────────────────────────────────────────
latest_ts = sorted({r["timestamp"] for r in current_rows}, reverse=True)[0]
snapshot  = [r for r in current_rows if r["timestamp"] == latest_ts]

net_mw  = sum(r["flow_mw"] for r in snapshot)
net_dir = "Importing" if net_mw >= 0 else "Exporting"

imp_rows    = [r for r in snapshot if r["flow_mw"] > 0]
exp_rows    = [r for r in snapshot if r["flow_mw"] < 0]
biggest_imp = max(imp_rows, key=lambda r: r["flow_mw"])  if imp_rows else None
biggest_exp = min(exp_rows, key=lambda r: r["flow_mw"])  if exp_rows else None

# ── KPI metric cards ───────────────────────────────────────────────────────────
st.markdown(
    "<style>"
    "[data-testid='stMetricLabel'] { color: #ffffff !important; }"
    "[data-testid='stMetricValue'] { color: #ffffff !important; }"
    "[data-testid='stMetricDelta'] { color: #e9c46a !important; }"
    "</style>",
    unsafe_allow_html=True,
)
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Net Value", f"{abs(net_mw):,.0f} MW", delta=net_dir, delta_color="off")
with c2:
    if biggest_imp:
        lbl = biggest_imp["name"].split("(")[0].strip()
        st.metric("Largest Import", lbl, delta=f"+{biggest_imp['flow_mw']:,.0f} MW", delta_color="off")
    else:
        st.metric("Largest Import", "None active", delta="—", delta_color="off")
with c3:
    if biggest_exp:
        lbl = biggest_exp["name"].split("(")[0].strip()
        st.metric("Largest Export", lbl, delta=f"{biggest_exp['flow_mw']:,.0f} MW", delta_color="off")
    else:
        st.metric("Largest Export", "None active", delta="—", delta_color="off")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Granularity selector ───────────────────────────────────────────────────────
gran_label = st.segmented_control(
    "Granularity",
    options=list(_GRAN_KEY.keys()),
    default="Daily",
    key="ic_trend_gran",
    label_visibility="collapsed",
)
if gran_label is None:
    gran_label = "Daily"
granularity = _GRAN_KEY[gran_label]

# ── Default windows ────────────────────────────────────────────────────────────
_now   = datetime.now(timezone.utc)
_today = _now.date()

if granularity == "half_hourly":
    _default_from_date = _today - timedelta(days=1)
    _default_to_date   = _today
    _h, _m             = _now.hour, _now.minute
    _default_from_time = f"{_h:02d}:{'30' if _m >= 30 else '00'}"
    _default_to_time   = _default_from_time
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
    _picker_min_date, _picker_max_date = half_hourly_picker_bounds("interconnector")
    # Default From/To are anchored to the latest timestamp actually in the
    # data (not "now") — the deployed snapshot can lag real time by days,
    # which previously collapsed From/To to the same clamped value.
    _dflt_from_date, _dflt_from_time, _dflt_to_date, _dflt_to_time = (
        half_hourly_default_window("interconnector")
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
        key=f"ic_from_date_{granularity}",
        label_visibility="collapsed",
    )
with cols[2]:
    if show_time:
        from_time = st.selectbox(
            "From time",
            _TIMES,
            index=_TIMES.index(_default_from_time) if _default_from_time in _TIMES else 0,
            key=f"ic_from_time_{granularity}",
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
        key=f"ic_to_date_{granularity}",
        label_visibility="collapsed",
    )
with cols[5]:
    if show_time:
        to_time = st.selectbox(
            "To time",
            _TIMES,
            index=_TIMES.index(_default_to_time) if _default_to_time in _TIMES else len(_TIMES) - 1,
            key=f"ic_to_time_{granularity}",
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

# ── Fetch trend data ───────────────────────────────────────────────────────────
trend_rows   = fetch_interconnector_range(granularity, from_ts, to_ts)
window_label = f"{from_ts[:16]} → {to_ts[:16]} · {gran_label.lower()}"

# ── Chart header / source helpers ─────────────────────────────────────────────
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

SOURCE = "Elexon Balancing Mechanism Reporting Service (BMRS)"

def _source_note() -> None:
    st.markdown(
        f"<div style='font-size:10px;color:#a3c3bb;margin-bottom:4px;'>"
        f"<b>Source:</b> {SOURCE}</div>",
        unsafe_allow_html=True,
    )

# ── Chart 2: Historical trend ──────────────────────────────────────────────────
if trend_rows:
    try:
        trend_title, fig_trend = build_interconnector_trend(
            trend_rows, granularity, 9999
        )
        _chart_header(
            trend_title,
            f"Flow per cable · {window_label} · + import into GB  ·  − export from GB",
        )
        _, col2, _ = st.columns([0.5, 9, 0.5])
        with col2:
            st.plotly_chart(fig_trend, width="stretch")
        _source_note()
    except Exception as e:
        st.error(f"Chart 2 failed: {e}")
else:
    st.info("No trend data available for the selected period.")

# ── Chart 3: Stacked diverging bar + net imports line ─────────────────────────
if trend_rows:
    try:
        stacked_title, fig_stacked = build_interconnector_stacked_diverging(
            trend_rows, granularity, 9999
        )
        _chart_header(
            stacked_title,
            f"Stacked import/export by cable · {window_label} · white line = net GB position",
        )
        _, col3, _ = st.columns([0.5, 9, 0.5])
        with col3:
            st.plotly_chart(fig_stacked, width="stretch")
        _source_note()
    except Exception as e:
        st.error(f"Stacked chart failed: {e}")

# ── Cable-group behaviour split ────────────────────────────────────────────────
_UNIDIRECTIONAL_INTO_UK = {
    "Eleclink interconnector (France)",
    "IFA1 interconnector (France)",
    "IFA2 interconnector (France)",
    "North Sea Link interconnector (Norway)",
}
_UNIDIRECTIONAL_OUT_UK = {
    "East-West interconnector (Ireland)",
    "Greenlink interconnector (Ireland)",
    "Moyle interconnector (Northern Ireland)",
}
_CYCLING_CABLES = {
    "BritNed interconnector (Netherlands)",
    "Nemo Link interconnector (Belgium)",
    "Viking Link interconnector (Denmark)",
}

if trend_rows:
    # Derive colour map from the full sorted cable list so filtered charts
    # use identical colours to the Historical Trend chart above
    _all_cables   = sorted({r["name"] for r in trend_rows})
    _cable_colors = {c: CABLE_PALETTE[i % len(CABLE_PALETTE)] for i, c in enumerate(_all_cables)}

    _chart_header(
        "GB Interconnector Split into Three Distinct Behaviours",
        f"Net flow, MW (+ve = into GB) · {window_label}",
    )
    col_in, col_out, col_cyc = st.columns(3, gap="medium")

    with col_in:
        st.markdown(
            "<p style='font-size:15px; font-weight:700; color:#eef4f2; "
            "margin-bottom:2px;'>Unidirectional — Into GB</p>",
            unsafe_allow_html=True,
        )
        _in_rows = [r for r in trend_rows if r["name"] in _UNIDIRECTIONAL_INTO_UK]
        if _in_rows:
            _, fig_in = build_interconnector_trend(_in_rows, granularity, 9999, _cable_colors)
            st.plotly_chart(fig_in, use_container_width=True)

    with col_out:
        st.markdown(
            "<p style='font-size:15px; font-weight:700; color:#eef4f2; "
            "margin-bottom:2px;'>Unidirectional — Out of GB</p>",
            unsafe_allow_html=True,
        )
        _out_rows = [r for r in trend_rows if r["name"] in _UNIDIRECTIONAL_OUT_UK]
        if _out_rows:
            _, fig_out = build_interconnector_trend(_out_rows, granularity, 9999, _cable_colors)
            st.plotly_chart(fig_out, use_container_width=True)

    with col_cyc:
        st.markdown(
            "<p style='font-size:15px; font-weight:700; color:#eef4f2; "
            "margin-bottom:2px;'>Cycling</p>",
            unsafe_allow_html=True,
        )
        _cyc_rows = [r for r in trend_rows if r["name"] in _CYCLING_CABLES]
        if _cyc_rows:
            _, fig_cyc = build_interconnector_trend(_cyc_rows, granularity, 9999, _cable_colors)
            st.plotly_chart(fig_cyc, use_container_width=True)

    _source_note()

# ── Cache freshness ────────────────────────────────────────────────────────────
last = get_last_synced("interconnector")
if last:
    st.markdown(
        f"<div style='font-size:11px;color:#a3c3bb;margin-top:20px;'>"
        f"Cache last synced: {last[:16]} UTC</div>",
        unsafe_allow_html=True,
    )
