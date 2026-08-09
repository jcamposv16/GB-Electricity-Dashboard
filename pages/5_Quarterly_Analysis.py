"""Quarterly Generation Summary page."""

import streamlit as st
import streamlit.components.v1 as components

from data.cache_db import query_quarterly_summary
from utils.quarterly_utils import (
    compute_quarterly_table,
    compute_quarterly_chart_data,
    build_quarterly_area_charts,
)
from utils.quarterly_html import build_quarterly_html
from styles.theme import BG_MAIN, BG_SIDEBAR, BG_ACCENT, TEXT_GREEN, FUEL_COLORS
from components.charts import GROUP_COLORS

_GROUP_COLORS = {**GROUP_COLORS, "Renewables": "#7AE582"}

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom:20px; margin-top:-8px;">
  <div style="font-size:22px; font-weight:700; color:#eef4f2;
              letter-spacing:0.02em; margin-bottom:4px;">
    Quarterly Generation Summary
  </div>
  <div style="height:1.5px;
              background:linear-gradient(90deg,#52796f 40%,transparent);
              margin-bottom:8px;"></div>
</div>
""", unsafe_allow_html=True)

# ── Table controls ────────────────────────────────────────────────────────────
_YEARS    = [str(y) for y in range(2020, 2028)]
_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

cols = st.columns([1, 1, 0.3, 1, 1, 0.3, 1.5])

with cols[0]:
    from_year = st.selectbox("From year", _YEARS, index=_YEARS.index("2024"),
                             key="qa_from_year", label_visibility="collapsed")
with cols[1]:
    from_q = st.selectbox("From quarter", _QUARTERS, index=0,
                          key="qa_from_q", label_visibility="collapsed")
with cols[2]:
    st.markdown("<div style='padding-top:8px;color:#a3c3bb;font-size:13px;text-align:center;'>→</div>",
                unsafe_allow_html=True)
with cols[3]:
    to_year = st.selectbox("To year", _YEARS, index=_YEARS.index("2026"),
                           key="qa_to_year", label_visibility="collapsed")
with cols[4]:
    to_q = st.selectbox("To quarter", _QUARTERS, index=0,
                        key="qa_to_q", label_visibility="collapsed")
with cols[5]:
    st.markdown("<div style='padding-top:8px;color:#a3c3bb;font-size:13px;text-align:center;'>·</div>",
                unsafe_allow_html=True)
with cols[6]:
    highlight_q = st.selectbox(
        "Highlight", _QUARTERS, index=0,
        key="qa_highlight", label_visibility="collapsed",
        help="Highlight every column matching this quarter across years",
    )

from_key = f"{from_year}-{from_q}"
to_key   = f"{to_year}-{to_q}"

if from_key > to_key:
    st.error("'From' quarter must be before or equal to 'To' quarter.")
    st.stop()

# ── Fetch + compute table ─────────────────────────────────────────────────────
rows = query_quarterly_summary(from_key, to_key)

if not rows:
    st.info("No data for the selected range. Try a wider range or run a data sync.")
    st.stop()

table_data = compute_quarterly_table(rows)

# ── Render HTML table ─────────────────────────────────────────────────────────
dashboard_colors = {
    "BG_MAIN":    BG_MAIN,
    "BG_SIDEBAR": BG_SIDEBAR,
    "BG_ACCENT":  BG_ACCENT,
    "TEXT_GREEN": TEXT_GREEN,
}

html = build_quarterly_html(table_data, highlight_q, dashboard_colors)

n_data_rows    = len(table_data["fuel_twh"]) + 5 + 3 + 5  # fuel + derived + pct + shares
n_section_hdrs = 3
height_px      = 40 + n_section_hdrs * 32 + n_data_rows * 29 + 20
height_px      = max(height_px, 600)

st.markdown(
    "<style>iframe { width: 100% !important; }"
    ".element-container iframe { width: 100% !important; }</style>",
    unsafe_allow_html=True,
)
components.html(html, height=height_px, scrolling=False)

# ══════════════════════════════════════════════════════════════════════════════
# ── Quarterly Generation Trends (stacked area charts) ─────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("""
<div style="font-size:18px; font-weight:700; color:#eef4f2; margin-bottom:4px;">
  Quarterly Generation Trends
</div>
<div style="height:1.5px;
            background:linear-gradient(90deg,#52796f 40%,transparent);
            margin-bottom:12px;"></div>
""", unsafe_allow_html=True)

# ── Chart-specific date range controls ───────────────────────────────────────
st.markdown(
    "<p style='font-size:13px; font-weight:600; "
    "color:#a3c3bb; margin-bottom:6px;'>"
    "Chart date range</p>",
    unsafe_allow_html=True,
)
cc = st.columns([1.5, 1.5, 0.5, 1.5, 1.5])

with cc[0]:
    chart_from_year = st.selectbox(
        "From year", _YEARS,
        index=max(0, len(_YEARS) - 5),   # default: 2023
        key="qa_chart_from_year",
        label_visibility="collapsed",
    )
with cc[1]:
    chart_from_q = st.selectbox(
        "From quarter", _QUARTERS, index=0,
        key="qa_chart_from_q",
        label_visibility="collapsed",
    )
with cc[2]:
    st.markdown(
        "<div style='padding-top:28px;text-align:center;color:#a3c3bb;'>→</div>",
        unsafe_allow_html=True,
    )
with cc[3]:
    chart_to_year = st.selectbox(
        "To year", _YEARS,
        index=_YEARS.index("2026"),
        key="qa_chart_to_year",
        label_visibility="collapsed",
    )
with cc[4]:
    chart_to_q = st.selectbox(
        "To quarter", _QUARTERS, index=3,  # default Q4
        key="qa_chart_to_q",
        label_visibility="collapsed",
    )

chart_from_qstr = f"{chart_from_year}-{chart_from_q}"
chart_to_qstr   = f"{chart_to_year}-{chart_to_q}"

if chart_from_qstr > chart_to_qstr:
    st.error("Chart 'From' must be before 'To'.")
    st.stop()

# ── Column layout (subtitles + charts share the same 2-col grid) ──────────────
col1, col2 = st.columns(2, gap="medium")

with col1:
    st.markdown(
        "<p style='font-size:16px; font-weight:700; color:#eef4f2; margin-bottom:2px;'>"
        "Generation by Fuel Type</p>"
        f"<p style='font-size:12px; color:#a3c3bb; margin-top:0;'>"
        f"{chart_from_qstr} → {chart_to_qstr} · stacked area · TWh per quarter</p>",
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        "<p style='font-size:16px; font-weight:700; color:#eef4f2; margin-bottom:2px;'>"
        "Generation by Main Fuel Group</p>"
        f"<p style='font-size:12px; color:#a3c3bb; margin-top:0;'>"
        f"{chart_from_qstr} → {chart_to_qstr} · stacked area · TWh per quarter</p>",
        unsafe_allow_html=True,
    )

# ── Fetch chart data + render ─────────────────────────────────────────────────
chart_rows = query_quarterly_summary(chart_from_qstr, chart_to_qstr)

if not chart_rows:
    st.info("No data for the chart date range.")
else:
    df_fuel, df_group = compute_quarterly_chart_data(chart_rows)
    fig_fuel, fig_group = build_quarterly_area_charts(
        df_fuel, df_group, FUEL_COLORS, _GROUP_COLORS
    )
    with col1:
        st.plotly_chart(fig_fuel, use_container_width=True)
    with col2:
        st.plotly_chart(fig_group, use_container_width=True)

# ── Source footnote ───────────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:11px; color:#a3c3bb; margin-top:8px;'>"
    "Source: Elexon (Balancing Mechanism Reporting Service) + "
    "National Energy System Operator (NESO)"
    "</p>",
    unsafe_allow_html=True,
)
