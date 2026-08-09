"""Comparison Analysis — year-on-year monthly comparison for Solar, Wind & Gas."""

import calendar
import datetime as _dt
import streamlit as st

from utils.comparison_utils import (
    fetch_monthly_fuel_year,
    build_comparison_chart,
    available_years,
    fetch_renewables_monthly,
    build_renewables_bar_chart,
    YEAR_COLORS,
    MONTHS,
    fetch_price_monthly_year,
    fetch_price_daily_month,
    fetch_price_halfhourly_day,
    fetch_nordpool_monthly,
    fetch_nordpool_daily_month,
    fetch_nordpool_halfhourly_day,
    fetch_share_gsw,
    build_price_line_chart,
    build_share_gsw_bar_chart,
    available_price_months_2026,
    max_price_settlement_date,
    PERIOD_INTERVAL_LABELS,
    MID_COLOR,
    NORDPOOL_COLOR,
)

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom:8px; margin-top:-8px;">
  <div style="font-size:22px; font-weight:700; color:#eef4f2;
              letter-spacing:0.02em; margin-bottom:4px;">
    Comparison Analysis
  </div>
  <div style="height:1.5px;
              background:linear-gradient(90deg,#52796f 40%,transparent);
              margin-bottom:4px;"></div>
  <div style="font-size:12px; color:#a3c3bb;">
    Year-on-year monthly comparison &nbsp;&middot;&nbsp;
    Solar, Wind &amp; Gas &nbsp;&middot;&nbsp; complete months only
  </div>
</div>
""", unsafe_allow_html=True)

# ── Year controls ─────────────────────────────────────────────────────────────
_YEARS     = available_years()
_YEARS_STR = [str(y) for y in _YEARS]
_Y3_OPTS   = ["None"] + _YEARS_STR

_def1 = _YEARS_STR.index("2024") if "2024" in _YEARS_STR else 0
_def2 = _YEARS_STR.index("2025") if "2025" in _YEARS_STR else min(1, len(_YEARS_STR) - 1)
_def3 = _Y3_OPTS.index("2026")  if "2026" in _Y3_OPTS  else 0

c1, c2, c3, c4, c5, c6 = st.columns([0.6, 1.5, 0.6, 1.5, 0.6, 1.5])
with c1:
    st.markdown(
        "<p style='color:#ffffff; font-size:13px; font-weight:500;"
        " margin-top:8px; margin-bottom:0; text-align:right;'>Year 1</p>",
        unsafe_allow_html=True,
    )
with c2:
    y1_str = st.selectbox("", _YEARS_STR, index=_def1, key="ca_year1",
                          label_visibility="collapsed")
with c3:
    st.markdown(
        "<p style='color:#ffffff; font-size:13px; font-weight:500;"
        " margin-top:8px; margin-bottom:0; text-align:right;'>Year 2</p>",
        unsafe_allow_html=True,
    )
with c4:
    y2_str = st.selectbox("", _YEARS_STR, index=_def2, key="ca_year2",
                          label_visibility="collapsed")
with c5:
    st.markdown(
        "<p style='color:#ffffff; font-size:13px; font-weight:500;"
        " margin-top:8px; margin-bottom:0; text-align:right;'>Year 3</p>",
        unsafe_allow_html=True,
    )
with c6:
    y3_str = st.selectbox("", _Y3_OPTS, index=_def3, key="ca_year3",
                          label_visibility="collapsed")

year1 = int(y1_str)
year2 = int(y2_str)
year3 = None if y3_str == "None" else int(y3_str)

selected = [year1, year2] + ([year3] if year3 is not None else [])
if len(selected) != len(set(selected)):
    st.warning("Select different years for each slot.")
    st.stop()

# ── Fetch ─────────────────────────────────────────────────────────────────────
_FUELS       = ["solar", "wind", "gas"]
_FUEL_LABELS = {"solar": "Solar", "wind": "Wind", "gas": "Gas"}

data: dict[str, dict[int, object]] = {fuel: {} for fuel in _FUELS}
for fuel in _FUELS:
    for yr in selected:
        df = fetch_monthly_fuel_year(fuel, yr)
        if not df.empty:
            data[fuel][yr] = df

# ── Row 1 — TWh charts ────────────────────────────────────────────────────────
cols_twh = st.columns(3, gap="medium")
for col, fuel in zip(cols_twh, _FUELS):
    label = _FUEL_LABELS[fuel]
    with col:
        st.markdown(
            f"<p style='font-size:15px; font-weight:700; color:#eef4f2; margin-top:0; margin-bottom:2px;'>"
            f"{label} Monthly Electricity Generation (TWh)</p>",
            unsafe_allow_html=True,
        )
        series = [(yr, data[fuel][yr]["twh"]) for yr in selected if yr in data[fuel]]
        if series:
            st.plotly_chart(
                build_comparison_chart(series, "TWh", "Generation (TWh)"),
                use_container_width=True,
            )
        else:
            st.info(f"No data available for {label}.")

# ── Row 2 — Share charts ───────────────────────────────────────────────────────
st.markdown("<div style='margin-top:-24px'></div>", unsafe_allow_html=True)
cols_pct = st.columns(3, gap="medium")
for col, fuel in zip(cols_pct, _FUELS):
    label = _FUEL_LABELS[fuel]
    with col:
        st.markdown(
            f"<p style='font-size:15px; font-weight:700; color:#eef4f2; margin-bottom:2px;'>"
            f"{label} Monthly Share Electricity Generation (%)</p>",
            unsafe_allow_html=True,
        )
        series = [(yr, data[fuel][yr]["share"]) for yr in selected if yr in data[fuel]]
        if series:
            st.plotly_chart(
                build_comparison_chart(series, "%", "Share of Generation (%)"),
                use_container_width=True,
            )
        else:
            st.info(f"No data available for {label}.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:11px; color:#a3c3bb; margin-top:8px;'>"
    "Source: Elexon (Balancing Mechanism Reporting Service) + "
    "National Energy System Operator (NESO)"
    "</p>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# ── Renewables Supply section ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("""
<div style="font-size:20px; font-weight:700;
  color:#eef4f2; margin-bottom:4px;">
  Renewables Supply
</div>
<div style="height:1.5px;
  background:linear-gradient(90deg,#52796f 40%,
  transparent); margin-bottom:12px;"></div>
<div style="font-size:12px; color:#a3c3bb;
  margin-bottom:16px;">
  Monthly stacked contribution of Wind, Solar and
  Other Renewables (Hydro, Biomass, Pumped Storage
  discharge &amp; Other) &nbsp;&middot;&nbsp; complete months only
</div>
""", unsafe_allow_html=True)

# Shared colour legend
st.markdown(
    "<div style='display:flex; gap:24px; "
    "margin-bottom:12px; font-size:12px; "
    "color:#eef4f2;'>"
    "<span><span style='background:#1a5c38; "
    "width:12px; height:12px; display:inline-block;"
    " margin-right:6px;'></span>Wind</span>"
    "<span><span style='background:#27ae60; "
    "width:12px; height:12px; display:inline-block;"
    " margin-right:6px;'></span>Solar</span>"
    "<span><span style='background:#a8dbb5; "
    "width:12px; height:12px; display:inline-block;"
    " margin-right:6px;'></span>"
    "Other Renewables</span>"
    "</div>",
    unsafe_allow_html=True,
)

# years_selected maps 1:1 to the 3 columns (y3_str may be "None")
years_selected = [y1_str, y2_str, y3_str]

# Fetch renewables data for each selected year
ren_data: dict = {}
for yr in years_selected:
    if yr != "None":
        ren_data[yr] = fetch_renewables_monthly(int(yr))

# ── Row 1 — TWh charts ────────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:13px; font-weight:600; "
    "color:#a3c3bb; margin-bottom:4px;'>"
    "Monthly Renewable Generation (TWh)</p>",
    unsafe_allow_html=True,
)
cols_ren_twh = st.columns(3, gap="medium")
for i, yr in enumerate(years_selected):
    with cols_ren_twh[i]:
        if yr == "None" or yr not in ren_data:
            st.empty()
        else:
            _fig = build_renewables_bar_chart(ren_data[yr], int(yr), "twh", YEAR_COLORS[i])
            _fig.add_annotation(
                text=f"<b>{yr}</b>",
                xref="paper", yref="paper",
                x=0, y=1.02,
                xanchor="left", yanchor="bottom",
                showarrow=False,
                font=dict(size=14, color="#eef4f2"),
            )
            _fig.update_layout(margin=dict(l=70, r=20, t=48, b=40))
            st.plotly_chart(_fig, use_container_width=True)

# ── Row 2 — Share charts ──────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:13px; font-weight:600; "
    "color:#a3c3bb; margin-bottom:4px;'>"
    "Monthly Renewable Share of Total Generation (%)</p>",
    unsafe_allow_html=True,
)
cols_ren_share = st.columns(3, gap="medium")
for i, yr in enumerate(years_selected):
    with cols_ren_share[i]:
        if yr == "None" or yr not in ren_data:
            st.empty()
        else:
            _fig = build_renewables_bar_chart(ren_data[yr], int(yr), "share", YEAR_COLORS[i])
            _fig.add_annotation(
                text=f"<b>{yr}</b>",
                xref="paper", yref="paper",
                x=0, y=1.02,
                xanchor="left", yanchor="bottom",
                showarrow=False,
                font=dict(size=14, color="#eef4f2"),
            )
            _fig.update_layout(margin=dict(l=70, r=20, t=48, b=40))
            st.plotly_chart(_fig, use_container_width=True)

# ── Second footer ─────────────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:11px; color:#a3c3bb; margin-top:8px;'>"
    "Source: Elexon (Balancing Mechanism Reporting Service) + "
    "National Energy System Operator (NESO)"
    "</p>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# ── Electricity Price Analysis section ────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("""
<div style="font-size:20px; font-weight:700;
  color:#eef4f2; margin-bottom:4px;">
  Electricity Price Analysis
</div>
<div style="height:1.5px;
  background:linear-gradient(90deg,#52796f 40%,
  transparent); margin-bottom:12px;"></div>
""", unsafe_allow_html=True)

# ── Colour legend (decorative — charts carry their own Plotly legends) ──────────
_BOX = (
    "display:inline-block; width:12px; height:12px; "
    "border-radius:2px; margin-right:5px; vertical-align:middle;"
)
st.markdown(
    "<div style='display:flex; gap:20px; align-items:center; "
    "margin-bottom:14px; font-size:12px; color:#eef4f2;'>"
    f"<span><span style='background:{MID_COLOR};{_BOX}'></span>GB Market Index Price (MID)</span>"
    f"<span><span style='background:{NORDPOOL_COLOR};{_BOX}'></span>Nord Pool Day-Ahead Auction Price</span>"
    "<span style='margin-left:12px; color:#888; font-size:10px;'>|</span>"
    f"<span><span style='background:#9E3A26;{_BOX}'></span>Gas %</span>"
    f"<span><span style='background:#f39c12;{_BOX}'></span>Solar %</span>"
    f"<span><span style='background:#1a8a45;{_BOX}'></span>Wind %</span>"
    "</div>",
    unsafe_allow_html=True,
)

# ── Price controls — columns 2 & 3 ────────────────────────────────────────────
_price_month_nums = available_price_months_2026()
_price_month_opts = [MONTHS[m - 1] for m in _price_month_nums]
_price_month_def  = len(_price_month_opts) - 1 if _price_month_opts else 0
_price_max_sd_str = max_price_settlement_date()
_price_max_date   = _dt.date.fromisoformat(_price_max_sd_str)

_ctrl_empty, _ctrl_m, _ctrl_d = st.columns(3)
with _ctrl_m:
    lc, wc = st.columns([0.6, 3])
    with lc:
        st.markdown(
            "<div style='padding-top:8px;color:#eef4f2;font-size:13px;"
            "text-align:right;'>Month</div>",
            unsafe_allow_html=True,
        )
    with wc:
        _sel_month_label = st.selectbox(
            "Month (middle column)",
            _price_month_opts,
            index=_price_month_def,
            key="ca_price_month",
            label_visibility="collapsed",
        )
    _sel_month = _price_month_nums[_price_month_opts.index(_sel_month_label)]

with _ctrl_d:
    lc, wc = st.columns([0.6, 3])
    with lc:
        st.markdown(
            "<div style='padding-top:8px;color:#eef4f2;font-size:13px;"
            "text-align:right;'>Day</div>",
            unsafe_allow_html=True,
        )
    with wc:
        _sel_date = st.date_input(
            "Day (right column)",
            value=_price_max_date,
            min_value=_dt.date(2026, 1, 1),
            max_value=_price_max_date,
            key="ca_price_day",
            label_visibility="collapsed",
        )

_sel_date_str  = _sel_date.strftime("%Y-%m-%d")
_sel_month_str = f"2026-{_sel_month:02d}"

# ── Precompute x-labels ────────────────────────────────────────────────────────
_x_month = list(MONTHS)  # ["Jan", ..., "Dec"] — 12 labels, always

_days_in_month = calendar.monthrange(2026, _sel_month)[1]
_x_day_price = [f"{d}/{_sel_month}" for d in range(1, _days_in_month + 1)]
_x_day_share = [f"{d}/{_sel_month}/2026" for d in range(1, _days_in_month + 1)]

_x_hh = PERIOD_INTERVAL_LABELS  # 48 "HH:MM-HH:MM" strings

# ── Row 1: price line charts ───────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:13px; font-weight:600; "
    "color:#a3c3bb; margin-bottom:4px;'>"
    "Wholesale Price (£/MWh)</p>",
    unsafe_allow_html=True,
)
_cols_price = st.columns(3, gap="medium")

with _cols_price[0]:
    st.markdown(
        "<p style='font-size:14px; font-weight:700; "
        "color:#eef4f2; margin-bottom:2px;'>"
        "Average Price by Month</p>",
        unsafe_allow_html=True,
    )
    _monthly_series = [
        ("GB Market Index Price (MID)",       fetch_price_monthly_year(2026)),
        ("Nord Pool Day-Ahead Auction Price", fetch_nordpool_monthly()),
    ]
    st.plotly_chart(
        build_price_line_chart(_monthly_series, "month", _x_month),
        use_container_width=True,
    )

with _cols_price[1]:
    st.markdown(
        f"<p style='font-size:14px; font-weight:700; "
        f"color:#eef4f2; margin-bottom:2px;'>"
        f"Average Price by Day &mdash; {_sel_month_label}</p>",
        unsafe_allow_html=True,
    )
    _daily_series = [
        ("GB Market Index Price (MID)",       fetch_price_daily_month(2026, _sel_month)),
        ("Nord Pool Day-Ahead Auction Price", fetch_nordpool_daily_month(_sel_month)),
    ]
    st.plotly_chart(
        build_price_line_chart(_daily_series, "day", _x_day_price),
        use_container_width=True,
    )

with _cols_price[2]:
    st.markdown(
        f"<p style='font-size:14px; font-weight:700; "
        f"color:#eef4f2; margin-bottom:2px;'>"
        f"Half-Hourly Price &mdash; {_sel_date_str}</p>",
        unsafe_allow_html=True,
    )
    _df_mid_hh = fetch_price_halfhourly_day(_sel_date_str)
    _hh_series = [
        ("GB Market Index Price (MID)",       _df_mid_hh["price"]),
        ("Nord Pool Day-Ahead Auction Price", fetch_nordpool_halfhourly_day(_sel_date_str)),
    ]
    st.plotly_chart(
        build_price_line_chart(_hh_series, "period", _x_hh),
        use_container_width=True,
    )

# ── Row 2: share bar charts ────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:13px; font-weight:600; "
    "color:#a3c3bb; margin-bottom:4px;'>"
    "Gas &middot; Solar &middot; Wind Share of Generation &mdash; 2026</p>",
    unsafe_allow_html=True,
)
_cols_share = st.columns(3, gap="medium")

with _cols_share[0]:
    st.markdown(
        "<p style='font-size:14px; font-weight:700; "
        "color:#eef4f2; margin-bottom:2px;'>"
        "Share by Month &mdash; 2026</p>",
        unsafe_allow_html=True,
    )
    _gsw_monthly = fetch_share_gsw("monthly", "")
    st.plotly_chart(
        build_share_gsw_bar_chart(_gsw_monthly, _x_month),
        use_container_width=True,
    )

with _cols_share[1]:
    st.markdown(
        f"<p style='font-size:14px; font-weight:700; "
        f"color:#eef4f2; margin-bottom:2px;'>"
        f"Share by Day &mdash; {_sel_month_label} 2026</p>",
        unsafe_allow_html=True,
    )
    _gsw_daily = fetch_share_gsw("daily", _sel_month_str)
    st.plotly_chart(
        build_share_gsw_bar_chart(_gsw_daily, _x_day_share),
        use_container_width=True,
    )

with _cols_share[2]:
    st.markdown(
        f"<p style='font-size:14px; font-weight:700; "
        f"color:#eef4f2; margin-bottom:2px;'>"
        f"Share by Half Hour &mdash; {_sel_date_str}</p>",
        unsafe_allow_html=True,
    )
    _gsw_hh = fetch_share_gsw("half_hourly", _sel_date_str)
    st.plotly_chart(
        build_share_gsw_bar_chart(_gsw_hh, _x_hh),
        use_container_width=True,
    )

# ── Price footer ───────────────────────────────────────────────────────────────
st.markdown(
    "<p style='font-size:11px; color:#a3c3bb; margin-top:8px;'>"
    "Source: Elexon (Balancing Mechanism Reporting Service)"
    " &nbsp;&middot;&nbsp; National Energy System Operator (NESO)"
    " &nbsp;&middot;&nbsp; Elexon MID (APXMIDP)"
    " &nbsp;&middot;&nbsp; Nord Pool N2EX day-ahead auction"
    "</p>",
    unsafe_allow_html=True,
)
