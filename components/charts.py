"""
Plotly chart builders for the GB Grid Dashboard.

Functions here are adapted from GB-Grid-Agent/dashboard_templates.py:
  - build_gen_mix_charts()   ← template_intraday_mix()
  - build_interconnector_charts() ← template_interconnectors() + new trend chart

Key difference from the originals: data is passed in as rows (pre-fetched by
data/fetcher.py) rather than fetched internally from cache_db.  This keeps
chart logic pure and testable.
"""

import pandas as pd
import plotly.graph_objects as go

from styles.theme import (
    FUEL_COLORS, CABLE_PALETTE,
    PLOTLY_LAYOUT_BASE, YAXIS_BASE, LEGEND_H,
    XAXIS_HALF_HOURLY, XAXIS_DAILY, XAXIS_MONTHLY,
    BG_MAIN, PLOT_BG,
)

_XAXIS_FOR = {
    "half_hourly": XAXIS_HALF_HOURLY,
    "daily":       XAXIS_DAILY,
    "monthly":     XAXIS_MONTHLY,
}


# ── Fuel group definitions (Main Fuel Group page) ──────────────────────────────

FUEL_GROUPS: dict[str, str] = {
    "nuclear":        "Nuclear",
    "wind":           "Renewables",
    "solar":          "Renewables",
    "hydro":          "Renewables",
    "pumped storage": "Renewables",
    "biomass":        "Renewables",
    "other":          "Renewables",
    "imports":        "Imports",
    "gas":            "Gas",
    "coal":           "Coal",
}

GROUP_COLORS: dict[str, str] = {
    "Coal":       "#353535",
    "Gas":        "#9E3A26",
    "Renewables": "#13CE74",
    "Nuclear":    "#9D4EDD",
    "Imports":    "#22657f",
}

GROUP_ORDER: list[str] = ["Coal", "Gas", "Imports", "Nuclear", "Renewables"]

FUEL_ORDER: list[str] = [
    "coal", "gas", "solar", "wind", "imports",
    "nuclear", "biomass", "hydro", "pumped storage", "other",
]


def group_fuel_rows(rows: list[dict], granularity: str) -> list[dict]:
    """Collapse raw generation mix rows into 5 fuel groups.

    Pumped storage contributions are clipped at 0 before aggregating so
    charging periods do not subtract from the Renewables group total.
    Percent shares are recomputed from the clipped values.
    """
    if not rows:
        return rows

    df       = pd.DataFrame(rows)
    time_col = {"half_hourly": "timestamp", "daily": "date", "monthly": "month"}[granularity]
    val_col  = "mw" if granularity == "half_hourly" else "total_mwh"

    df["group"] = df["fuel_type"].map(FUEL_GROUPS)
    df = df.dropna(subset=["group"]).copy()

    ps = df["fuel_type"] == "pumped storage"
    df.loc[ps, val_col] = df.loc[ps, val_col].clip(lower=0)
    if "avg_mw" in df.columns:
        df.loc[ps, "avg_mw"] = df.loc[ps, "avg_mw"].clip(lower=0)

    agg_spec = {val_col: "sum"}
    if "avg_mw" in df.columns:
        agg_spec["avg_mw"] = "sum"

    grouped = df.groupby([time_col, "group"]).agg(agg_spec).reset_index()
    grouped.rename(columns={"group": "fuel_type"}, inplace=True)

    period_totals    = grouped.groupby(time_col)[val_col].transform("sum")
    pct_col          = "percent" if granularity == "half_hourly" else "total_percent"
    grouped[pct_col] = (grouped[val_col] / period_totals * 100).fillna(0)

    return grouped.to_dict("records")


# ── Generation Mix ─────────────────────────────────────────────────────────────

def _mode_config(granularity: str) -> dict:
    if granularity == "half_hourly":
        return dict(
            time_col="timestamp",
            value_col="mw",
            scale=0.001,
            unit="GW",
            cumul_scale=0.0005,   # mw * 0.5 half-hours / 1000 → GWh
            cumul_unit="GWh",
            axis="Electricity Generation (GW)",
            cumul_axis="Cumulative Energy (GWh)",
            hover_fmt=".2f",
        )
    elif granularity == "daily":
        return dict(
            time_col="date",
            value_col="total_mwh",
            scale=0.001,
            unit="GWh",
            cumul_scale=0.001,
            cumul_unit="GWh",
            axis="Energy Generated (GWh)",
            cumul_axis="Cumulative Energy (GWh)",
            hover_fmt=",.1f",
        )
    else:  # monthly
        return dict(
            time_col="month",
            value_col="total_mwh",
            scale=1e-6,
            unit="TWh",
            cumul_scale=1e-6,
            cumul_unit="TWh",
            axis="Energy Generated (TWh)",
            cumul_axis="Cumulative Energy (TWh)",
            hover_fmt=",.2f",
        )


def build_gen_mix_charts(
    rows: list[dict],
    granularity: str = "half_hourly",
    window_label: str = "",
    color_map: dict | None = None,
    fuel_order_override: list | None = FUEL_ORDER,
) -> list[tuple[str, go.Figure]]:
    """
    Four-chart generation mix panel.

    Chart 1 — stacked area (GW / GWh / TWh depending on granularity)
    Chart 2 — 100% stacked area (fuel share)
    Chart 3 — line view per fuel + dashed total
    Chart 4 — cumulative energy

    Returns [(title, fig), ...].
    """
    cfg      = _mode_config(granularity)
    time_key = cfg["time_col"]
    val_key  = cfg["value_col"]

    timestamps = sorted({r[time_key] for r in rows})

    # ── Aggregate by fuel ──────────────────────────────────────────────────────
    by_fuel: dict = {}
    for r in rows:
        raw = r.get(val_key, r.get("avg_mw", r.get("mw", 0))) or 0
        by_fuel.setdefault(r["fuel_type"], {})[r[time_key]] = raw

    _ALWAYS_SHOW = {"coal"}
    fuel_order = sorted(by_fuel.keys(), key=lambda f: sum(by_fuel[f].values()), reverse=True)
    if fuel_order_override:
        _specified = [f for f in fuel_order_override if f in by_fuel]
        _rest      = [f for f in fuel_order if f not in fuel_order_override]
        fuel_order = _specified + _rest
    active     = [f for f in fuel_order if f.lower() in _ALWAYS_SHOW or any(by_fuel[f].get(t, 0) > 0 for t in timestamps)]
    _cm        = color_map or FUEL_COLORS

    # Raw series in native units (MW or MWh)
    series_raw   = {f: [by_fuel[f].get(t, 0) for t in timestamps] for f in active}
    totals_raw   = [sum(series_raw[f][i] for f in active) for i in range(len(timestamps))]

    # Scaled series for display (GW / GWh / TWh)
    sc = cfg["scale"]
    series_val       = {f: [round(v * sc, 4) for v in vals] for f, vals in series_raw.items()}
    series_val_nn    = {f: [max(0.0, v) for v in vals] for f, vals in series_val.items()}
    totals_val       = [round(totals_raw[i] * sc, 4) for i in range(len(timestamps))]
    totals_val_nn    = [max(0.0, v) for v in totals_val]

    # Percent shares for fig2
    # half_hourly: compute from clipped MW; daily/monthly: use pre-built total_percent
    if granularity == "half_hourly":
        series_pct = {
            f: [round(series_val_nn[f][i] / totals_val_nn[i] * 100, 2)
                if totals_val_nn[i] else 0
                for i in range(len(timestamps))]
            for f in active
        }
    else:
        by_pct: dict = {}
        for r in rows:
            pct = r.get("total_percent", r.get("avg_percent", 0)) or 0
            by_pct.setdefault(r["fuel_type"], {})[r[time_key]] = pct
        series_pct = {f: [by_pct.get(f, {}).get(t, 0) for t in timestamps] for f in active}

    # ── Shared layout ──────────────────────────────────────────────────────────
    _STD_LEGEND = dict(
        orientation="h", yanchor="bottom", y=1.10,
        xanchor="center", x=0.5,
        font=dict(size=9, color="#a3c3bb"),
        bgcolor="rgba(0,0,0,0)",
        itemwidth=30,
        itemsizing="constant",
    )
    layout_base = dict(
        **PLOTLY_LAYOUT_BASE,
        xaxis={**_XAXIS_FOR[granularity], "showgrid": False, "zeroline": False, "color": "#ffffff", "tickfont": {"size": 11, "color": "#ffffff"}},
        legend={**_STD_LEGEND, "traceorder": "reversed"},
    )
    layout_base["plot_bgcolor"] = '#F3F9ED'
    layout_base["margin"] = dict(l=70, r=20, t=85, b=40)
    layout_base["height"] = 440

    unit       = cfg["unit"]
    hover_fmt  = cfg["hover_fmt"]
    sub        = f" · {window_label}" if window_label else ""

    # ── Figure 1: stacked area ─────────────────────────────────────────────────
    fig1 = go.Figure()
    for fuel in active:
        color = _cm.get(fuel, "#bdc3c7")
        fig1.add_trace(go.Scatter(
            x=timestamps, y=series_val_nn[fuel], name=fuel.title(),
            mode="lines", fill="tonexty", stackgroup="one",
            line={"width": 0.8, "color": color}, fillcolor=color, opacity=0.88,
            customdata=series_pct[fuel],
            hovertemplate=(
                f"<b>{fuel.title()}</b>: %{{y:{hover_fmt}}} {unit}"
                " (%{customdata:.1f}%)<extra></extra>"
            ),
        ))
    fig1.update_layout(
        **layout_base,
        yaxis={
            **YAXIS_BASE,
            "title": {"text": cfg["axis"], "font": {"size": 12, "color": "#ffffff"}, "standoff": 10},
            "rangemode": "tozero",
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
    )

    # ── Figure 2: 100% stacked area ────────────────────────────────────────────
    fig2 = go.Figure()
    for fuel in active:
        color = _cm.get(fuel, "#bdc3c7")
        fig2.add_trace(go.Scatter(
            x=timestamps, y=series_pct[fuel], name=fuel.title(),
            mode="lines", fill="tonexty", stackgroup="one",
            line={"width": 0.8, "color": color}, fillcolor=color, opacity=0.88,
            customdata=series_val_nn[fuel],
            hovertemplate=(
                f"<b>{fuel.title()}</b>: %{{y:.1f}}%"
                f" (%{{customdata:{hover_fmt}}} {unit})<extra></extra>"
            ),
        ))
    fig2.update_layout(
        **layout_base,
        yaxis={
            **YAXIS_BASE,
            "title": {"text": "Share of Generation (%)", "font": {"size": 12, "color": "#ffffff"}, "standoff": 10},
            "range": [0, 100],
            "ticksuffix": "%",
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
    )

    # ── Figure 3: line view — signed values (pumped storage negative visible) ──
    fig3 = go.Figure()
    for fuel in active:
        color = _cm.get(fuel, "#bdc3c7")
        fig3.add_trace(go.Scatter(
            x=timestamps, y=series_val[fuel], name=fuel.title(),
            mode="lines",
            line={"width": 1.8, "color": color},
            hovertemplate=f"<b>{fuel.title()}</b>: %{{y:{hover_fmt}}} {unit}<extra></extra>",
        ))
    fig3.add_trace(go.Scatter(
        x=timestamps, y=totals_val, name="Total",
        mode="lines",
        line={"width": 2.5, "color": "#264653", "dash": "dash"},
        hovertemplate=f"<b>Total</b>: %{{y:{hover_fmt}}} {unit}<extra></extra>",
    ))
    fig3.update_layout(**layout_base)
    fig3.update_layout(
        yaxis={
            **YAXIS_BASE,
            "title": {"text": cfg["axis"], "font": {"size": 12, "color": "#ffffff"}, "standoff": 10},
            "rangemode": "tozero",
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
        legend=_STD_LEGEND,
    )

    # ── Figure 4: share lines ──────────────────────────────────────────────────
    fig4 = build_gen_mix_share_lines(pd.DataFrame(rows), granularity, window_label, color_map=_cm)

    return [
        ("Electricity Generation Mix — Great Britain",  fig1),
        ("Generation Mix — Share by Fuel Type",         fig2),
        ("Generation by Fuel Type — Line View",         fig3),
        ("Generation Share by Fuel Type (%)",           fig4),
    ]


def build_gen_mix_cumulative(
    df: pd.DataFrame,
    granularity: str,
    window_label: str = "",
    color_map: dict | None = None,
    fuel_order_override: list | None = None,
) -> go.Figure:
    """Cumulative stacked area — energy generated over the selected window."""
    _SUB    = {"wind_bm", "wind_emb", "ccgt", "ocgt"}
    _ALWAYS = {"coal"}
    _cm     = color_map or FUEL_COLORS

    cfg       = _mode_config(granularity)
    time_col  = cfg["time_col"]
    val_key   = cfg["value_col"]
    csc       = cfg["cumul_scale"]   # convert raw value to display unit
    c_unit    = cfg["cumul_unit"]
    c_axis    = cfg["cumul_axis"]

    work = df[~df["fuel_type"].isin(_SUB)].copy()

    pivot = (
        work.pivot_table(index=time_col, columns="fuel_type", values=val_key, aggfunc="first")
        .fillna(0)
        .sort_index()
    )
    pivot = pivot.clip(lower=0) * csc

    fuel_totals = pivot.sum()
    fuel_order  = fuel_totals.sort_values(ascending=False).index.tolist()
    if fuel_order_override:
        _specified = [f for f in fuel_order_override if f in pivot.columns]
        _rest      = [f for f in fuel_order if f not in fuel_order_override]
        fuel_order = _specified + _rest
    active      = [f for f in fuel_order if f.lower() in _ALWAYS or fuel_totals[f] > 0]

    cumul       = pivot[active].cumsum()
    total_cumul = cumul.sum(axis=1)
    xvals       = cumul.index.tolist()

    fig = go.Figure()
    for fuel in reversed(active):
        color = _cm.get(fuel, "#bdc3c7")
        fig.add_trace(go.Scatter(
            x=xvals,
            y=cumul[fuel].round(2).tolist(),
            name=fuel.title(),
            mode="lines",
            fill="tonexty",
            stackgroup="one",
            line={"width": 0.8, "color": color},
            fillcolor=color,
            opacity=0.88,
            hovertemplate=f"<b>{fuel.title()}</b>: %{{y:,.1f}} {c_unit}<extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=xvals,
        y=total_cumul.round(2).tolist(),
        name="Total",
        mode="lines",
        line={"color": "#ffffff", "width": 2, "dash": "dot"},
        hovertemplate=f"<b>Total</b>: %{{y:,.1f}} {c_unit}<extra></extra>",
    ))

    fig.update_layout(
        xaxis=dict(gridcolor="#3a6374", color="#ffffff", showgrid=False, zeroline=False, tickfont=dict(color="#ffffff")),
        yaxis=dict(
            title=c_axis,
            tickformat=",.0f",
            ticksuffix=f" {c_unit}",
            gridcolor="#3a6374",
            color="#ffffff",
            rangemode="tozero",
            showgrid=False,
            zeroline=False,
            tickfont=dict(color="#ffffff"),
        ),
        height=440,
        paper_bgcolor="#264653",
        plot_bgcolor='#F3F9ED',
        font=dict(color="#ffffff"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.10,
            xanchor="center", x=0.5,
            font=dict(size=9, color="#a3c3bb"),
            bgcolor="rgba(0,0,0,0)",
            itemwidth=30,
            itemsizing="constant",
        ),
        margin=dict(l=70, r=20, t=85, b=40),
        hovermode="x unified",
    )

    return fig


def build_gen_mix_share_lines(
    df: pd.DataFrame,
    granularity: str,
    window_label: str,
    color_map: dict | None = None,
) -> go.Figure:
    """Line chart — percent share per fuel over time (replaces cumulative fig4)."""
    pct_col = {
        "half_hourly": "percent",
        "daily":       "total_percent",
        "monthly":     "total_percent",
    }[granularity]
    time_col = {
        "half_hourly": "timestamp",
        "daily":       "date",
        "monthly":     "month",
    }[granularity]

    df = df.copy()
    # Grouped rows (page 4) use total_percent instead of avg_percent
    if pct_col not in df.columns and "total_percent" in df.columns:
        pct_col = "total_percent"
    ps_mask = df["fuel_type"] == "pumped storage"
    if ps_mask.any():
        df.loc[ps_mask, pct_col] = df.loc[ps_mask, pct_col].clip(lower=0)

    timestamps = sorted(df[time_col].unique().tolist())

    by_pct: dict = {}
    for _, row in df.iterrows():
        fuel = row["fuel_type"]
        t    = row[time_col]
        pct  = float(row[pct_col]) if pd.notna(row[pct_col]) else 0.0
        by_pct.setdefault(fuel, {})[t] = pct

    _ALWAYS = {"coal"}
    active = [
        f for f in by_pct
        if f.lower() in _ALWAYS or any(v > 0 for v in by_pct[f].values())
    ]
    active = sorted(active, key=lambda f: sum(by_pct[f].values()), reverse=True)

    _STD_LEGEND = dict(
        orientation="h", yanchor="bottom", y=1.10,
        xanchor="center", x=0.5,
        font=dict(size=9, color="#a3c3bb"),
        bgcolor="rgba(0,0,0,0)",
        itemwidth=30,
        itemsizing="constant",
    )

    _cm = color_map or FUEL_COLORS
    fig = go.Figure()
    for fuel in active:
        color  = _cm.get(fuel, "#bdc3c7")
        y_vals = [by_pct[fuel].get(t, None) for t in timestamps]
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=y_vals,
            name=fuel.title(),
            mode="lines",
            line=dict(width=1.5, color=color),
            hovertemplate=f"<b>{fuel.title()}</b>: %{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(**PLOTLY_LAYOUT_BASE)
    fig.update_layout(
        height=440,
        plot_bgcolor='#F3F9ED',
        margin=dict(l=70, r=20, t=85, b=40),
        xaxis={**_XAXIS_FOR[granularity], "showgrid": False, "zeroline": False, "color": "#ffffff", "tickfont": {"size": 11, "color": "#ffffff"}},
        legend=_STD_LEGEND,
        yaxis={
            **YAXIS_BASE,
            "title": {"text": "Share of Generation (%)", "font": {"size": 12, "color": "#ffffff"}, "standoff": 10},
            "tickformat": ".1f",
            "ticksuffix": "%",
            "range": [0, None],
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
    )
    return fig


# ── Interconnector Flows ───────────────────────────────────────────────────────

def build_interconnector_snapshot(snapshot_rows: list[dict]) -> tuple[str, go.Figure]:
    """
    Horizontal diverging bar chart for the current interconnector snapshot.
    Green = import into GB, red = export from GB.

    Adapted from dashboard_templates.template_interconnectors().
    Returns a single (title, fig) tuple.
    """
    snap_sorted  = sorted(snapshot_rows, key=lambda r: r["flow_mw"])
    short_labels = [r["name"].split("(")[0].strip() for r in snap_sorted]
    bar_colors   = ["#27ae60" if r["flow_mw"] >= 0 else "#e74c3c" for r in snap_sorted]
    net          = sum(r["flow_mw"] for r in snapshot_rows)
    direction    = "importer" if net >= 0 else "exporter"

    ts           = snapshot_rows[0].get("timestamp", "") if snapshot_rows else ""
    snap_time    = ts[11:16] if len(ts) > 10 else ""
    snap_time_lbl = f" · snapshot at {snap_time} UTC" if snap_time else ""

    fig = go.Figure(go.Bar(
        x=[r["flow_mw"] for r in snap_sorted],
        y=short_labels,
        orientation="h",
        marker={"color": bar_colors},
        hovertext=[r["name"] for r in snap_sorted],
        hovertemplate="%{hovertext}<br><b>%{x:+,.0f} MW</b><extra></extra>",
        text=[f"{r['flow_mw']:+,.0f} MW" for r in snap_sorted],
        textposition="outside",
        textfont={"size": 11, "color": "#eef4f2"},
        width=0.55,
    ))
    fig.add_vline(x=0, line={"color": "rgba(255,255,255,0.35)", "width": 1.5})
    fig.update_layout(
        template="none",
        plot_bgcolor='#F3F9ED',
        paper_bgcolor=BG_MAIN,
        height=max(280, len(snap_sorted) * 44 + 80),
        margin=dict(t=20, b=20, l=140, r=110),
        xaxis=dict(
            title={
                "text": "MW  ( + import into GB  ·  − export from GB )",
                "font": {"size": 11, "color": "#ffffff"},
            },
            tickfont={"size": 11, "color": "#ffffff"},
            color="#ffffff",
            showgrid=False, gridcolor="rgba(255,255,255,0.12)", gridwidth=1,
            zeroline=False,
        ),
        yaxis=dict(tickfont={"size": 12, "color": "#ffffff"}, color="#ffffff", showgrid=False),
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.95)", bordercolor="#ddd",
            font={"size": 11, "color": "#333"},
        ),
    )

    title = (
        f"Interconnector Flows — GB is net {direction}{snap_time_lbl} "
        f"({net:+,.0f} MW)"
    )
    return title, fig


def build_interconnector_trend(
    trend_rows: list[dict],
    granularity: str = "daily",
    limit: int = 30,
    cable_colors: dict[str, str] | None = None,
) -> tuple[str, go.Figure]:
    """
    Multi-line trend chart — one line per cable, daily/monthly averages.
    Positive values = import into GB; negative = export from GB.
    Returns a single (title, fig) tuple.
    """
    time_key = {"half_hourly": "timestamp", "daily": "date", "monthly": "month"}.get(granularity, "date")

    all_ts   = sorted({r[time_key] for r in trend_rows}, reverse=True)
    latest   = set(all_ts[:limit])
    t_rows   = [r for r in trend_rows if r[time_key] in latest]
    t_stamps = sorted({r[time_key] for r in t_rows})

    cables: dict = {}
    for r in t_rows:
        mw = r.get("avg_flow_mw", r.get("flow_mw", 0))
        cables.setdefault(r["name"], {})[r[time_key]] = mw

    fig = go.Figure()
    for i, cable in enumerate(sorted(cables)):
        color = cable_colors.get(cable) if cable_colors else CABLE_PALETTE[i % len(CABLE_PALETTE)]
        label  = cable
        y_vals = [cables[cable].get(t, None) for t in t_stamps]
        fig.add_trace(go.Scatter(
            x=t_stamps, y=y_vals, name=label,
            mode="lines",
            line={"width": 1.8, "color": color},
            connectgaps=False,
            hovertemplate=f"<b>{label}</b>: %{{y:,.0f}} MW<extra></extra>",
        ))

    # Zero line — marks import/export boundary
    fig.add_hline(
        y=0,
        line=dict(color="#52796f", width=1.5),
    )

    _legend_bottom = dict(
        orientation="h", x=0.5, xanchor="center",
        y=-0.22, yanchor="top",
        font={"size": 10, "color": "#eef4f2"},
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
        itemclick="toggle", itemdoubleclick="toggleothers",
    )

    xaxis_cfg = _XAXIS_FOR.get(granularity, XAXIS_DAILY)
    fig.update_layout(
        **{**PLOTLY_LAYOUT_BASE, "height": 460, "hovermode": "x unified", "margin": dict(t=30, b=120, l=65, r=20)},
        xaxis={
            **xaxis_cfg,
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
        yaxis={
            **YAXIS_BASE,
            "title": {
                "text": "Flow (MW)  ·  +ve = import into GB  ·  −ve = export from GB",
                "font": {"size": 11, "color": "#a3c3bb"},
                "standoff": 12,
            },
            "showgrid": False,
            "zeroline": False,
            "showline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
        legend=_legend_bottom,
    )

    return "Interconnector Flows — Historical Trend", fig


def build_interconnector_stacked_diverging(
    trend_rows: list[dict],
    granularity: str = "daily",
    limit: int = 30,
) -> tuple[str, go.Figure]:
    """
    Stacked diverging bar chart — one bar series per cable.
    Positive flows stack above zero (imports into GB), negative below (exports).
    A white net-imports line overlays the bars.

    Uses barmode="relative" so Plotly handles diverging stacks automatically
    from a single go.Bar trace per cable with actual +/- values.
    """
    time_key = {"half_hourly": "timestamp", "daily": "date", "monthly": "month"}.get(granularity, "date")

    all_ts   = sorted({r[time_key] for r in trend_rows}, reverse=True)
    latest   = set(all_ts[:limit])
    t_rows   = [r for r in trend_rows if r[time_key] in latest]
    t_stamps = sorted({r[time_key] for r in t_rows})

    _CABLE_DISPLAY = {
        "Belgium (Nemolink)":       "Belgium (Nemolink)",
        "Denmark (Viking link)":    "Denmark (Viking Link)",
        "Eleclink (INTELEC)":       "France (Eleclink)",
        "France(IFA)":              "France (IFA1)",
        "IFA2 (INTIFA2)":           "France (IFA2)",
        "Northern Ireland(Moyle)":  "Northern Ireland (Moyle)",
        "Ireland(East-West)":       "Ireland (East-West)",
        "Ireland (Greenlink)":      "Ireland (Greenlink)",
        "Netherlands(BritNed)":     "Netherlands (BritNed)",
        "North Sea Link (INTNSL)":  "Norway (North Sea Link)",
    }

    cables: dict = {}
    for r in t_rows:
        mw = r.get("avg_flow_mw", r.get("flow_mw", 0))
        cables.setdefault(r["name"], {})[r[time_key]] = mw

    fig = go.Figure()
    for i, cable in enumerate(sorted(cables)):
        color  = CABLE_PALETTE[i % len(CABLE_PALETTE)]
        label  = _CABLE_DISPLAY.get(cable, cable)
        y_vals = [cables[cable].get(t, 0) for t in t_stamps]
        fig.add_trace(go.Bar(
            x=t_stamps,
            y=y_vals,
            name=label,
            marker_color=color,
            hovertemplate=f"<b>{label}</b>: %{{y:,.0f}} MW<extra></extra>",
        ))

    # Net imports line — sum all cables at each timestamp
    net_vals = [sum(cables[c].get(t, 0) for c in cables) for t in t_stamps]
    fig.add_trace(go.Scatter(
        x=t_stamps,
        y=net_vals,
        name="Net Imports",
        mode="lines",
        line={"color": "#ffffff", "width": 2},
        hovertemplate="<b>Net Imports</b>: %{y:,.0f} MW<extra></extra>",
    ))

    xaxis_cfg = {**_XAXIS_FOR.get(granularity, XAXIS_DAILY), "showgrid": False, "zeroline": False, "color": "#ffffff", "tickfont": {"size": 11, "color": "#ffffff"}}
    legend_bottom = dict(
        orientation="h", x=0.5, xanchor="center",
        y=-0.25, yanchor="top",
        font={"size": 10, "color": "#eef4f2"},
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
        itemclick="toggle", itemdoubleclick="toggleothers",
    )

    fig.update_layout(**{**PLOTLY_LAYOUT_BASE, "height": 480})
    fig.update_layout(
        barmode="relative",
        bargap=0,
        bargroupgap=0,
        xaxis=xaxis_cfg,
        yaxis={
            **YAXIS_BASE,
            "title": {
                "text": "Flow (MW)  ·  +ve = import into GB  ·  −ve = export",
                "font": {"size": 12, "color": "#ffffff"},
                "standoff": 10,
            },
            "showgrid": False,
            "zeroline": False,
            "color": "#ffffff",
            "tickfont": {"size": 11, "color": "#ffffff"},
        },
        legend=legend_bottom,
        margin=dict(t=30, b=120, l=80, r=20),
    )

    return "Interconnector Flows — Stacked by Cable", fig
