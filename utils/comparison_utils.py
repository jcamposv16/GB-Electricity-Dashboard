"""Monthly comparison data helpers and chart builder for Comparison Analysis page."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from datetime import datetime, timezone

from data.cache_db import query_agg_range, query_price_agg, _conn
from styles.theme import BG_MAIN, PLOT_BG, YAXIS_BASE

_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

YEAR_COLORS    = ["#1d3557", "#27ae60", "#e67e22"]
FILL_Y2_HIGHER = "rgba(39, 174, 96, 0.25)"
FILL_Y1_HIGHER = "rgba(29, 53, 87, 0.30)"

MID_COLOR      = "#1d3557"
NORDPOOL_COLOR = "#2a9d8f"
_PRICE_LINE_COLORS = [MID_COLOR, NORDPOOL_COLOR]

MONTHS = _MONTH_LABELS  # alias used by renewables chart builder

RENEWABLES_COMPONENTS = {
    "wind":           "Wind",
    "solar":          "Solar",
    "hydro":          "other_ren",
    "pumped storage": "other_ren",  # clip at 0
    "biomass":        "other_ren",
    "other":          "other_ren",
}

RENEWABLES_COLORS = {
    "Wind":               "#1a5c38",
    "Solar":              "#27ae60",
    "Other Renewables":   "#a8dbb5",
}


def fetch_monthly_fuel_year(fuel: str, year: int) -> pd.DataFrame:
    """
    Monthly TWh + share for one fuel in one year.

    Returns DataFrame indexed by month_number (1–12) with columns:
      twh   = total_mwh / 1e6
      share = total_percent

    Current-year rule: only complete months are returned.
    E.g. on 2026-07-06 only months 1–6 are returned for year 2026.
    Months with no data (None total_mwh) are excluded.
    """
    rows = query_agg_range("generation_mix", "monthly", f"{year}-01", f"{year}-12")

    now = datetime.now(timezone.utc)
    cutoff_month = now.month if year == now.year else 13  # 13 → keep all months

    records = []
    for r in rows:
        r = dict(r)
        if r["fuel_type"] != fuel:
            continue
        month_num = int(r["month"][5:7])
        if month_num >= cutoff_month:
            continue
        if r["total_mwh"] is None:
            continue
        records.append({
            "month": month_num,
            "twh":   r["total_mwh"] / 1e6,
            "share": r["total_percent"] or 0.0,
        })

    if not records:
        return pd.DataFrame(columns=["twh", "share"])

    return pd.DataFrame(records).set_index("month").sort_index()


def available_years() -> list[int]:
    """Distinct years present in agg_generation_mix_monthly."""
    from data.cache_db import _conn
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(month,1,4) AS yr "
            "FROM agg_generation_mix_monthly ORDER BY yr"
        ).fetchall()
        return [int(r[0]) for r in rows]
    except Exception:
        return list(range(2020, datetime.now(timezone.utc).year + 1))
    finally:
        conn.close()


def fetch_renewables_monthly(year: int) -> pd.DataFrame:
    """
    Monthly renewables breakdown for one year.

    Returns DataFrame indexed by month (1–12) with columns:
      wind_twh, solar_twh, other_ren_twh,
      wind_share, solar_share, other_ren_share,
      total_ren_twh, total_ren_share

    NaN rows = months without data (future / current-year incomplete).
    pumped storage contribution clipped at 0 before summing.
    """
    rows = query_agg_range("generation_mix", "monthly", f"{year}-01", f"{year}-12")
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["month_num"] = df["month"].str[5:7].astype(int)

    now = datetime.now(timezone.utc)
    if year == now.year:
        df = df[df["month_num"] < now.month]

    result = pd.DataFrame(index=range(1, 13))
    result.index.name = "month"
    for col in ["wind_twh", "solar_twh", "other_ren_twh",
                "wind_share", "solar_share", "other_ren_share"]:
        result[col] = float("nan")

    for m in sorted(df["month_num"].unique()):
        month_df = df[df["month_num"] == m]

        def get_val(fuel: str, col: str) -> float:
            row = month_df[month_df["fuel_type"] == fuel]
            if row.empty:
                return 0.0
            v = row[col].iloc[0]
            return float(v) if v is not None else 0.0

        # TWh
        wind_t  = get_val("wind",           "total_mwh") / 1e6
        solar_t = get_val("solar",          "total_mwh") / 1e6
        hydro_t = get_val("hydro",          "total_mwh") / 1e6
        ps_t    = max(get_val("pumped storage", "total_mwh") / 1e6, 0.0)
        bio_t   = get_val("biomass",        "total_mwh") / 1e6
        oth_t   = get_val("other",          "total_mwh") / 1e6
        other_ren_t = hydro_t + ps_t + bio_t + oth_t

        # Share (Option A: sum of total_percent values)
        wind_s  = get_val("wind",           "total_percent")
        solar_s = get_val("solar",          "total_percent")
        hydro_s = get_val("hydro",          "total_percent")
        ps_s    = max(get_val("pumped storage", "total_percent"), 0.0)
        bio_s   = get_val("biomass",        "total_percent")
        oth_s   = get_val("other",          "total_percent")
        other_ren_s = hydro_s + ps_s + bio_s + oth_s

        result.loc[m, "wind_twh"]        = wind_t
        result.loc[m, "solar_twh"]       = solar_t
        result.loc[m, "other_ren_twh"]   = other_ren_t
        result.loc[m, "wind_share"]      = wind_s
        result.loc[m, "solar_share"]     = solar_s
        result.loc[m, "other_ren_share"] = other_ren_s

    result["total_ren_twh"]   = (result["wind_twh"]   + result["solar_twh"]   + result["other_ren_twh"])
    result["total_ren_share"] = (result["wind_share"] + result["solar_share"] + result["other_ren_share"])
    return result


def build_comparison_chart(
    series: list[tuple[int, pd.Series]],
    value_label: str,
    y_title: str,
) -> go.Figure:
    """
    Build a year-on-year line chart with a single fill between Y1 and Y2.

    series      : list of (year, monthly_series) — 1 to 3 entries,
                  each Series indexed by month number (1–12).
    value_label : "TWh" or "%"
    y_title     : y-axis title string
    """
    fig = go.Figure()

    # ── Fill between Y1 and Y2 (common months only) ───────────────────────────
    if len(series) >= 2:
        _, s1 = series[0]
        _, s2 = series[1]
        common = sorted(set(s1.index) & set(s2.index))

        if len(common) >= 2:
            x_fill  = [_MONTH_LABELS[m - 1] for m in common]
            y1_fill = [float(s1.loc[m]) for m in common]
            y2_fill = [float(s2.loc[m]) for m in common]

            # Base trace (Y1, invisible line)
            fig.add_trace(go.Scatter(
                x=x_fill, y=y1_fill,
                mode="lines", line=dict(width=0, shape="linear"),
                showlegend=False, hoverinfo="skip",
                name="_fill_base",
            ))
            # Fill trace (Y2, fills to base)
            fig.add_trace(go.Scatter(
                x=x_fill, y=y2_fill,
                mode="lines", line=dict(width=0, shape="linear"),
                fill="tonexty", fillcolor="rgba(39, 174, 96, 0.20)",
                showlegend=False, hoverinfo="skip",
                name="_fill_top",
            ))

    # ── Line traces — added after fills so they render on top ─────────────────
    # Full 12-month x-axis with None for missing months; connectgaps=False
    # stops each line cleanly at its last data point.
    for idx, (year, s) in enumerate(series):
        y_full = [float(s.loc[m]) if m in s.index else None for m in range(1, 13)]
        fig.add_trace(go.Scatter(
            x=_MONTH_LABELS, y=y_full,
            mode="lines", name=str(year),
            line=dict(width=2.5, color=YEAR_COLORS[idx % len(YEAR_COLORS)], shape="linear"),
            connectgaps=False,
            hovertemplate=(
                "%{fullData.name}: %{y:.2f} " + value_label + "<extra></extra>"
            ),
        ))

    # ── Year-end annotations (overlap-safe) ──────────────────────────────────
    raw_annotations = []
    for idx, (year, s) in enumerate(series):
        last_m = max(s.index)
        raw_annotations.append({
            "x":     _MONTH_LABELS[last_m - 1],
            "y":     float(s.loc[last_m]),
            "text":  str(year),
            "color": YEAR_COLORS[idx % len(YEAR_COLORS)],
        })

    all_y = [v for _, s in series for v in s.values.tolist()]
    _resolve_annotation_overlaps(raw_annotations, all_y)

    for ann in raw_annotations:
        fig.add_annotation(
            x=ann["x"],
            y=ann["y"],
            text=ann["text"],
            showarrow=False,
            font=dict(color=ann["color"], size=11, weight=700),
            xanchor="left",
            xshift=8,
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        template="none",
        height=380,
        paper_bgcolor=BG_MAIN,
        plot_bgcolor='#F3F9ED',
        font=dict(color="#ffffff"),
        margin=dict(l=70, r=55, t=20, b=40),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.95)",
            bordercolor="#ddd",
            font={"size": 11, "color": "#333"},
        ),
        showlegend=False,
        xaxis=dict(
            type="category",
            tickmode="array",
            tickvals=_MONTH_LABELS,
            ticktext=_MONTH_LABELS,
            tickangle=0,
            showgrid=False,
            zeroline=False,
            color="#ffffff",
            tickfont=dict(size=10, color="#ffffff"),
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(color="#ffffff")),
            tickformat=".1f" if "TWh" in value_label else ".0f",
            showgrid=False,
            zeroline=False,
            color="#ffffff",
            tickfont=dict(color="#ffffff"),
            rangemode="tozero",
            ticklabelstandoff=8,
        ),
    )
    return fig


def _resolve_annotation_overlaps(
    annotations: list[dict],
    all_y_vals: list[float],
) -> list[dict]:
    """Push overlapping year-label annotations apart on the same x position."""
    y_range = max(all_y_vals) - min(all_y_vals) if all_y_vals else 1
    threshold = y_range * 0.08
    for i in range(len(annotations)):
        for j in range(i + 1, len(annotations)):
            a1, a2 = annotations[i], annotations[j]
            if a1["x"] == a2["x"] and abs(a1["y"] - a2["y"]) < threshold:
                offset = threshold * 0.6
                if a1["y"] >= a2["y"]:
                    annotations[i]["y"] += offset
                    annotations[j]["y"] -= offset
                else:
                    annotations[j]["y"] += offset
                    annotations[i]["y"] -= offset
    return annotations


def build_renewables_bar_chart(
    df: pd.DataFrame,
    year: int,
    mode: str,
    year_color: str,
) -> go.Figure:
    """
    Stacked bar chart for monthly renewables supply.

    df        : result of fetch_renewables_monthly(year)
    year      : calendar year (for future use / title)
    mode      : 'twh' or 'share'
    year_color: colour of the yearly-average dashed line
    """
    fig = go.Figure()

    suffix = "twh" if mode == "twh" else "share"
    y_title = "Generation (TWh)" if mode == "twh" else "Share of Generation (%)"
    unit    = "TWh" if mode == "twh" else "%"

    components = [
        ("Wind",             f"wind_{suffix}",      "#1a5c38"),
        ("Solar",            f"solar_{suffix}",     "#27ae60"),
        ("Other Renewables", f"other_ren_{suffix}", "#a8dbb5"),
    ]

    for name, col, color in components:
        y_vals = [
            float(df.loc[m, col]) if not pd.isna(df.loc[m, col]) else None
            for m in range(1, 13)
        ]
        fig.add_trace(go.Bar(
            x=MONTHS,
            y=y_vals,
            name=name,
            marker_color=color,
            hovertemplate=f"{name}: %{{y:.2f}} {unit}<extra></extra>",
        ))

    # Yearly average dashed line
    total_col = f"total_ren_{suffix}"
    avg_val   = df[total_col].dropna().mean()
    avg_label = (f"Yearly avg = {avg_val:.1f} TWh" if mode == "twh"
                 else f"Yearly avg = {avg_val:.1f}%")

    fig.add_hline(
        y=avg_val,
        line=dict(dash="dash", color="#2c3e50", width=1.5),
        annotation_text=avg_label,
        annotation_position="top left",
        annotation_font=dict(size=10, color="#2c3e50"),
    )

    fig.update_layout(
        template="none",
        barmode="stack",
        height=380,
        paper_bgcolor=BG_MAIN,
        plot_bgcolor='#F3F9ED',
        font=dict(color="#ffffff", size=10),
        margin=dict(l=70, r=20, t=30, b=40),
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(
            type="category",
            tickmode="array",
            tickvals=MONTHS,
            ticktext=MONTHS,
            tickangle=0,
            showgrid=False,
            zeroline=False,
            color="#ffffff",
            tickfont=dict(color="#ffffff"),
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(color="#ffffff")),
            showgrid=False,
            zeroline=False,
            range=[0, 15] if mode == "twh" else [0, 60],
            color="#ffffff",
            tickfont=dict(color="#ffffff"),
            tickformat=".1f",
            ticklabelstandoff=8,
        ),
        bargap=0.15,
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# ── Price analysis helpers + builders ─────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_PERIOD_TICK_VALS = [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45]
_PERIOD_TICK_TEXT = [
    "23:00", "01:00", "03:00", "05:00",
    "07:00", "09:00", "11:00", "13:00",
    "15:00", "17:00", "19:00", "21:00",
]
_GSW_COLORS = {"gas": "#9E3A26", "solar": "#f39c12", "wind": "#1a8a45"}

_PRICE_LAYOUT = dict(
    template="none",
    height=340,
    margin=dict(l=75, r=20, t=30, b=45),
    paper_bgcolor=BG_MAIN,
    plot_bgcolor='#F3F9ED',
    showlegend=False,
    hovermode="x unified",
    hoverlabel=dict(bgcolor="rgba(255,255,255,0.95)", bordercolor="#ddd",
                    font={"size": 11, "color": "#333"}),
)


def _compute_period_intervals() -> list[str]:
    labels = []
    for p in range(1, 49):
        sm = 23 * 60 + (p - 1) * 30
        em = sm + 30
        labels.append(
            f"{(sm // 60) % 24:02d}:{sm % 60:02d}"
            f"-{(em // 60) % 24:02d}:{em % 60:02d}"
        )
    return labels


PERIOD_INTERVAL_LABELS = _compute_period_intervals()


def available_price_months_2026() -> list[int]:
    """Month numbers (1-12) in 2026 with complete price data (month < current)."""
    now = datetime.now(timezone.utc)
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(month,6,2) AS m FROM agg_price_monthly "
            "WHERE month LIKE '2026-%' ORDER BY m"
        ).fetchall()
        return [int(r[0]) for r in rows if int(r[0]) < now.month]
    except Exception:
        return list(range(1, now.month))
    finally:
        conn.close()


def max_price_settlement_date() -> str:
    """Latest settlement_date present in raw_electricity_price."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT MAX(settlement_date) FROM raw_electricity_price"
        ).fetchone()
        return row[0] if row and row[0] else "2026-07-01"
    finally:
        conn.close()


def fetch_price_monthly_year(year: int) -> pd.Series:
    """avg_price by month number (1-12). Current-year rule: complete months only."""
    rows = query_price_agg("monthly", f"{year}-01", f"{year}-12")
    now = datetime.now(timezone.utc)
    cutoff = now.month if year == now.year else 13
    records: dict[int, float] = {}
    for r in rows:
        mn = int(r["month"][5:7])
        if mn >= cutoff:
            continue
        if r["avg_price"] is not None:
            records[mn] = float(r["avg_price"])
    return pd.Series(records, name="avg_price", dtype=float).sort_index()


def fetch_price_daily_month(year: int, month: int) -> pd.Series:
    """avg_price by day-of-month (1-31). Current-month rule: complete days only."""
    month_str = f"{year}-{month:02d}"
    rows = query_price_agg("daily", f"{month_str}-01", f"{month_str}-31")
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    records: dict[int, float] = {}
    for r in rows:
        date_str = r["date"]
        if not date_str.startswith(month_str):
            continue
        if year == now.year and month == now.month and date_str >= today_str:
            continue
        if r["avg_price"] is not None:
            records[int(date_str[8:10])] = float(r["avg_price"])
    return pd.Series(records, name="avg_price", dtype=float).sort_index()


def fetch_price_halfhourly_day(settlement_date: str) -> pd.DataFrame:
    """price + time_label by settlement_period (1-48) for one settlement_date."""
    conn = _conn()
    rows = conn.execute(
        "SELECT timestamp, settlement_period, price "
        "FROM raw_electricity_price "
        "WHERE settlement_date = ? "
        "ORDER BY settlement_period",
        (settlement_date,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame(columns=["price", "time_label"])
    records = [
        {
            "settlement_period": int(r[1]),
            "price": float(r[2]) if r[2] is not None else None,
            "time_label": r[0][11:16],
        }
        for r in rows
    ]
    return pd.DataFrame(records).set_index("settlement_period")


def fetch_nordpool_monthly() -> pd.Series:
    """Avg day-ahead price per complete month (1-12) for 2026 from agg_nordpool_daily.

    A month is only included when its day count equals the calendar days in that month.
    """
    import calendar as _cal
    conn = _conn()
    rows = conn.execute("""
        SELECT CAST(strftime('%m', date) AS INTEGER) AS month_num,
               COUNT(*)                              AS day_count,
               AVG(avg_price)                        AS avg_price
        FROM   agg_nordpool_daily
        WHERE  date BETWEEN '2026-01-01' AND '2026-12-31'
        GROUP  BY month_num
        ORDER  BY month_num
    """).fetchall()
    conn.close()
    result = pd.Series(index=range(1, 13), dtype=float)
    result[:] = float("nan")
    for m_num, day_count, price in rows:
        m = int(m_num)
        if day_count == _cal.monthrange(2026, m)[1]:
            result[m] = price
    return result


def fetch_nordpool_daily_month(month: int) -> pd.Series:
    """Avg day-ahead price per day for 2026 and the given month number (1-12)."""
    import calendar as _cal
    last_day = _cal.monthrange(2026, month)[1]
    from_d   = f"2026-{month:02d}-01"
    to_d     = f"2026-{month:02d}-{last_day:02d}"
    conn = _conn()
    rows = conn.execute("""
        SELECT CAST(strftime('%d', date) AS INTEGER) AS day_num,
               avg_price
        FROM   agg_nordpool_daily
        WHERE  date BETWEEN ? AND ?
        ORDER  BY date
    """, (from_d, to_d)).fetchall()
    conn.close()
    result = pd.Series(index=range(1, last_day + 1), dtype=float)
    result[:] = float("nan")
    for day_num, price in rows:
        result[int(day_num)] = price
    return result


def fetch_nordpool_halfhourly_day(settlement_date: str) -> pd.Series:
    """Price per settlement period (1-48) for one settlement date from raw_nordpool_n2ex."""
    conn = _conn()
    rows = conn.execute("""
        SELECT settlement_period, price_dayahead
        FROM   raw_nordpool_n2ex
        WHERE  settlement_date = ?
        ORDER  BY settlement_period
    """, (settlement_date,)).fetchall()
    conn.close()
    result = pd.Series(index=range(1, 49), dtype=float)
    result[:] = float("nan")
    for period, price in rows:
        if 1 <= period <= 48:
            result[int(period)] = price
    return result


def fetch_share_gsw(granularity: str, key: str) -> pd.DataFrame:
    """Gas/Solar/Wind generation share (%) aligned to a settlement period axis.

    granularity='monthly': key ignored; 2026 complete months.
    granularity='daily':   key='2026-MM'; 2026 complete days for that month.
    granularity='half_hourly': key=settlement_date 'YYYY-MM-DD'.
    """
    _FUELS = ("gas", "solar", "wind")
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    if granularity == "monthly":
        rows = query_agg_range("generation_mix", "monthly", "2026-01", "2026-12")
        bucket: dict[int, dict] = {}
        for r in rows:
            r = dict(r)
            if r["fuel_type"] not in _FUELS:
                continue
            mn = int(r["month"][5:7])
            if mn >= now.month:
                continue
            bucket.setdefault(mn, {})[r["fuel_type"]] = float(r["total_percent"] or 0)
        records = [
            {
                "month": m,
                "gas_share":   float(bucket[m].get("gas",   0)) if m in bucket else None,
                "solar_share": float(bucket[m].get("solar", 0)) if m in bucket else None,
                "wind_share":  float(bucket[m].get("wind",  0)) if m in bucket else None,
            }
            for m in range(1, 13)  # always all 12 months; None for months without data
        ]
        return pd.DataFrame(records).set_index("month")

    elif granularity == "daily":
        rows = query_agg_range("generation_mix", "daily", f"{key}-01", f"{key}-31")
        bucket: dict[int, dict] = {}
        for r in rows:
            r = dict(r)
            if r["fuel_type"] not in _FUELS:
                continue
            date_str = r["date"]
            if not date_str.startswith(key) or date_str >= today_str:
                continue
            dn = int(date_str[8:10])
            bucket.setdefault(dn, {})[r["fuel_type"]] = float(r["total_percent"] or 0)
        records = [
            {"day": d, "gas_share": b.get("gas", 0.0),
             "solar_share": b.get("solar", 0.0), "wind_share": b.get("wind", 0.0)}
            for d, b in sorted(bucket.items())
        ]
        return pd.DataFrame(records).set_index("day") if records else pd.DataFrame()

    elif granularity == "half_hourly":
        conn = _conn()
        price_rows = conn.execute(
            "SELECT timestamp, settlement_period FROM raw_electricity_price "
            "WHERE settlement_date = ? ORDER BY settlement_period",
            (key,),
        ).fetchall()
        if not price_rows:
            conn.close()
            return pd.DataFrame()
        ts_to_period = {r[0]: int(r[1]) for r in price_rows}
        ts_list = sorted(ts_to_period)
        gen_rows = conn.execute(
            "SELECT timestamp, fuel_type, percent FROM raw_generation_mix "
            "WHERE fuel_type IN ('gas','solar','wind') "
            "AND timestamp >= ? AND timestamp <= ?",
            (ts_list[0], ts_list[-1]),
        ).fetchall()
        conn.close()
        gen_data: dict[str, dict[str, float]] = {}
        for r in gen_rows:
            gen_data.setdefault(r[0], {})[r[1]] = float(r[2]) if r[2] is not None else 0.0
        records = [
            {
                "settlement_period": ts_to_period[ts],
                "gas_share":   gen_data.get(ts, {}).get("gas",   0.0),
                "solar_share": gen_data.get(ts, {}).get("solar", 0.0),
                "wind_share":  gen_data.get(ts, {}).get("wind",  0.0),
            }
            for ts in ts_list
        ]
        return pd.DataFrame(records).set_index("settlement_period") if records else pd.DataFrame()

    return pd.DataFrame()


def _x_axis_from_labels(x_mode: str, x_labels: list) -> dict:
    """Build xaxis dict for a given mode, using x_labels as the category values."""
    n = len(x_labels)
    base = dict(type="category", tickmode="array", tickangle=0,
                showgrid=False, zeroline=False,
                color="#ffffff", tickfont=dict(size=10, color="#ffffff"))
    if x_mode == "period":
        # Only show every-4th tick; ticktext shows start-time only
        tick_idxs = [p - 1 for p in _PERIOD_TICK_VALS if p - 1 < n]
        tickvals = [x_labels[i] for i in tick_idxs]
        ticktext = [x_labels[i].split("-")[0] for i in tick_idxs]
    elif x_mode == "day":
        # Tick text is just the day number; x_label may include "/M" or "/M/YYYY"
        tickvals = x_labels
        ticktext = [lbl.split("/")[0] for lbl in x_labels]
    else:  # month
        tickvals = x_labels
        ticktext = x_labels
    return {**base, "tickvals": tickvals, "ticktext": ticktext}


def build_price_line_chart(
    series: list[tuple[str, pd.Series]],
    x_mode: str,
    x_labels: list,
) -> go.Figure:
    """Price line chart — one trace per (label, series) pair.

    x_labels : formatted label per x position (index 0 = series index 1).
    Series must be 1-based integer indexed (1-12 month, 1-31 day, 1-48 period).
    Colors assigned by index position from _PRICE_LINE_COLORS.
    """
    fig = go.Figure()
    n = len(x_labels)

    for idx, (label, s) in enumerate(series):
        y_full = [float(s.loc[i]) if i in s.index else None for i in range(1, n + 1)]
        fig.add_trace(go.Scatter(
            x=x_labels, y=y_full,
            mode="lines", name=label,
            line=dict(width=2.5, color=_PRICE_LINE_COLORS[idx % len(_PRICE_LINE_COLORS)], shape="linear"),
            connectgaps=False,
            hovertemplate=f"%{{fullData.name}}: £%{{y:.1f}}/MWh<extra></extra>",
        ))

    fig.update_layout(
        **_PRICE_LAYOUT,
        font=dict(color="#ffffff"),
        xaxis=_x_axis_from_labels(x_mode, x_labels),
        yaxis=dict(title=dict(text="Price (£/MWh)", font=dict(color="#ffffff")), showgrid=False,
                   zeroline=False, color="#ffffff", tickformat=".0f", ticklabelstandoff=8, tickfont=dict(color="#ffffff")),
    )
    return fig


def build_share_gsw_bar_chart(df: pd.DataFrame, x_labels: list) -> go.Figure:
    """Stacked Gas / Solar / Wind generation-share bar chart.

    x_labels  : one label per x position (index 0 → series index 1).
    df must be indexed 1-based integers matching x_labels positions.
    Positions absent from df.index render as no bar (None y-value).
    """
    fig = go.Figure()
    n = len(x_labels)

    idx_name = df.index.name if not df.empty else "month"
    x_mode   = "period" if idx_name == "settlement_period" else (
                "day"    if idx_name == "day"               else "month")

    for name, col, color in [
        ("Gas",   "gas_share",   _GSW_COLORS["gas"]),
        ("Solar", "solar_share", _GSW_COLORS["solar"]),
        ("Wind",  "wind_share",  _GSW_COLORS["wind"]),
    ]:
        y_vals = []
        for i in range(1, n + 1):
            if not df.empty and i in df.index and col in df.columns:
                v = df.loc[i, col]
                y_vals.append(float(v) if pd.notna(v) else None)
            else:
                y_vals.append(None)
        fig.add_trace(go.Bar(
            x=x_labels, y=y_vals, name=name,
            marker_color=color,
            hovertemplate=f"{name}: %{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(
        **_PRICE_LAYOUT,
        barmode="stack",
        font=dict(color="#ffffff", size=10),
        bargap=0.15,
        xaxis=_x_axis_from_labels(x_mode, x_labels),
        yaxis=dict(title=dict(text="Share of Generation (%)", font=dict(color="#ffffff")), showgrid=False,
                   zeroline=False, color="#ffffff", range=[0, 100], tickformat=".0f", ticklabelstandoff=8, tickfont=dict(color="#ffffff")),
    )
    return fig
