"""Compute the quarterly generation summary table and chart data from raw DB rows."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from styles.theme import BG_MAIN, PLOT_BG, YAXIS_BASE

# ── Fuel rows (display order) ─────────────────────────────────────────────────
# Each entry: (display_label, [db_fuel_keys])
# "Hydro (NPS+PS)" merges hydro + pumped storage (PS clipped to ≥0).
FUEL_ROWS: list[tuple[str, list[str]]] = [
    ("Coal",           ["coal"]),
    ("Gas",            ["gas"]),
    ("Imports",        ["imports"]),
    ("Nuclear",        ["nuclear"]),
    ("Biomass",        ["biomass"]),
    ("Wind",           ["wind"]),
    ("Solar",          ["solar"]),
    ("Hydro (NPS+PS)", ["hydro", "pumped storage"]),
    ("Other",          ["other"]),
]

_RENEWABLE_LABELS        = {"Wind", "Solar", "Hydro (NPS+PS)", "Biomass", "Other"}
_RENEWABLE_EXCL_BIO_LBLS = {"Wind", "Solar", "Hydro (NPS+PS)", "Other"}
_FOSSIL_LABELS           = {"Gas", "Coal"}


def compute_quarterly_table(rows: list[dict]) -> dict:
    """
    Transform flat DB rows into structured table data.

    Returns:
        {
          "quarters": ["2024-Q1", ...],
          "fuel_twh": {"Wind": {"2024-Q1": 12.3, ...}, ...},
          "derived": {
              "renewables_twh":          {...},
              "renewables_excl_biomass": {...},
              "fossil_twh":              {...},
              "total_gen_excl_imports":  {...},
              "Total consumption":       {...},
              "fossil_pct":              {...},
              "clean_pct":               {...},
              "ren_clean_pct":           {...},
              "Coal share":              {...},
              "Gas share":               {...},
              "Imports share":           {...},
              "Nuclear share":           {...},
              "Renewables share":        {...},
          },
        }
    """
    # Index raw DB rows by (quarter, fuel_type) → TWh
    idx: dict[tuple[str, str], float] = {}
    for r in rows:
        twh = (r["total_mwh"] or 0.0) / 1_000_000
        idx[(r["quarter"], r["fuel_type"])] = twh

    quarters = sorted({r["quarter"] for r in rows})

    # ── Per-fuel TWh ──────────────────────────────────────────────────────────
    # For each label, sum its keys; pumped storage is clipped to ≥0.
    fuel_twh: dict[str, dict[str, float]] = {}
    for label, keys in FUEL_ROWS:
        row_data: dict[str, float] = {}
        for q in quarters:
            val = 0.0
            for k in keys:
                v = idx.get((q, k), 0.0)
                if k == "pumped storage":
                    v = max(v, 0.0)
                val += v
            row_data[q] = round(val, 1)
        fuel_twh[label] = row_data

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _sum_labels(label_set: set[str], q: str) -> float:
        return sum(fuel_twh[lbl][q] for lbl in label_set if lbl in fuel_twh)

    def _pct(num: dict, denom: dict) -> dict[str, float]:
        return {
            q: round(num[q] / denom[q] * 100) if denom.get(q) else 0
            for q in quarters
        }

    # ── Derived TWh rows ─────────────────────────────────────────────────────
    _all_labels        = [lbl for lbl, _ in FUEL_ROWS]
    _non_import_labels = [lbl for lbl, keys in FUEL_ROWS if "imports" not in keys]

    renewables_twh      = {q: round(_sum_labels(_RENEWABLE_LABELS, q), 1)        for q in quarters}
    renewables_excl_bio = {q: round(_sum_labels(_RENEWABLE_EXCL_BIO_LBLS, q), 1) for q in quarters}
    fossil_twh          = {q: round(_sum_labels(_FOSSIL_LABELS, q), 1)            for q in quarters}
    total_gen_excl_imp  = {q: round(sum(fuel_twh[lbl][q] for lbl in _non_import_labels), 1) for q in quarters}
    total_consumption   = {q: round(sum(fuel_twh[lbl][q] for lbl in _all_labels), 1)        for q in quarters}

    # ── Percentage rows ───────────────────────────────────────────────────────
    fossil_pct    = _pct(fossil_twh, total_consumption)
    clean_twh     = {q: renewables_twh[q] + fuel_twh["Nuclear"][q] for q in quarters}
    clean_pct     = _pct(clean_twh, total_consumption)
    ren_clean_pct = _pct(renewables_twh, clean_twh)

    # ── Share rows (% of total consumption) ─────────────────────────────────
    coal_share       = _pct({q: fuel_twh["Coal"][q]    for q in quarters}, total_consumption)
    gas_share        = _pct({q: fuel_twh["Gas"][q]     for q in quarters}, total_consumption)
    imports_share    = _pct({q: fuel_twh["Imports"][q] for q in quarters}, total_consumption)
    nuclear_share    = _pct({q: fuel_twh["Nuclear"][q] for q in quarters}, total_consumption)
    renewables_share = _pct(renewables_twh, total_consumption)

    return {
        "quarters": quarters,
        "fuel_twh": fuel_twh,
        "derived": {
            "renewables_twh":          renewables_twh,
            "renewables_excl_biomass": renewables_excl_bio,
            "fossil_twh":              fossil_twh,
            "total_gen_excl_imports":  total_gen_excl_imp,
            "Total consumption":       total_consumption,
            "fossil_pct":              fossil_pct,
            "clean_pct":               clean_pct,
            "ren_clean_pct":           ren_clean_pct,
            "Coal share":              coal_share,
            "Gas share":               gas_share,
            "Imports share":           imports_share,
            "Nuclear share":           nuclear_share,
            "Renewables share":        renewables_share,
        },
    }


# ── Chart data helpers ─────────────────────────────────────────────────────────

# Stacked area trace order: bottom → top of stack
_FUEL_STACK_ORDER  = ["Coal", "Gas", "Imports", "Nuclear", "Biomass", "Solar",
                      "Hydro (NPS+PS)", "Other", "Wind"]
_GROUP_STACK_ORDER = ["Coal", "Gas", "Imports", "Nuclear", "Renewables"]

# Maps display label → FUEL_COLORS key (handles the combined Hydro label)
_FUEL_COLOR_KEY: dict[str, str] = {
    "Coal":           "coal",
    "Gas":            "gas",
    "Imports":        "imports",
    "Nuclear":        "nuclear",
    "Biomass":        "biomass",
    "Solar":          "solar",
    "Hydro (NPS+PS)": "hydro",
    "Other":          "other",
    "Wind":           "wind",
}

_STD_LEGEND = dict(
    orientation="h", yanchor="bottom", y=1.06,
    xanchor="center", x=0.5,
    font=dict(size=9, color="#eef4f2"),
    bgcolor="rgba(0,0,0,0)",
    itemwidth=30,
    itemsizing="constant",
    traceorder="reversed",
)

_XAXIS_QUARTERLY = dict(
    tickfont=dict(size=11, color="#ffffff"),
    color="#ffffff",
    showgrid=False,
    gridcolor="#3a6374",
    gridwidth=1,
    griddash="dash",
    zeroline=False,
    showline=False,
    ticks="outside",
    ticklen=4,
)

_YAXIS_QUARTERLY = {
    **YAXIS_BASE,
    "title": dict(text="Total Generation (TWh)", font=dict(size=12, color="#ffffff"), standoff=10),
    "tickformat": ".0f",
    "ticksuffix": " TWh",
    "rangemode": "tozero",
    "showgrid": False,
    "zeroline": False,
    "color": "#ffffff",
    "tickfont": dict(size=11, color="#ffffff"),
}

_CHART_LAYOUT = dict(
    template="none",
    paper_bgcolor=BG_MAIN,
    plot_bgcolor='#F3F9ED',
    height=440,
    margin=dict(l=70, r=20, t=85, b=70),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor="#ddd",
        font={"size": 11, "color": "#333"},
    ),
    legend=_STD_LEGEND,
    xaxis=_XAXIS_QUARTERLY,
    yaxis=_YAXIS_QUARTERLY,
)


def compute_quarterly_chart_data(rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (df_fuel, df_group) DataFrames ready for Plotly stacked area charts.

    df_fuel  — 9 columns: Coal, Gas, Imports, Nuclear, Biomass, Solar,
               Hydro (NPS+PS), Other, Wind.  Values in TWh.
    df_group — 5 columns: Coal, Gas, Imports, Nuclear, Renewables.  Values in TWh.
    Both indexed by quarter string, sorted ascending.
    Pumped storage is clipped at 0 before being added to Hydro (NPS+PS).
    """
    df   = pd.DataFrame(rows)
    wide = (
        df.pivot_table(index="quarter", columns="fuel_type",
                       values="total_mwh", aggfunc="sum")
        .fillna(0.0)
        / 1e6          # MWh → TWh
    )

    def _col(name: str) -> pd.Series:
        return wide[name] if name in wide.columns else pd.Series(0.0, index=wide.index)

    ps           = _col("pumped storage").clip(lower=0)
    hydro_nps_ps = _col("hydro") + ps

    df_fuel = pd.DataFrame(
        {
            "Coal":           _col("coal"),
            "Gas":            _col("gas"),
            "Imports":        _col("imports"),
            "Nuclear":        _col("nuclear"),
            "Biomass":        _col("biomass"),
            "Solar":          _col("solar"),
            "Hydro (NPS+PS)": hydro_nps_ps,
            "Other":          _col("other"),
            "Wind":           _col("wind"),
        },
        index=wide.index,
    ).round(2).sort_index()

    renewables = (
        df_fuel["Biomass"] + df_fuel["Wind"] + df_fuel["Solar"]
        + df_fuel["Hydro (NPS+PS)"] + df_fuel["Other"]
    )
    df_group = pd.DataFrame(
        {
            "Coal":       df_fuel["Coal"],
            "Gas":        df_fuel["Gas"],
            "Imports":    df_fuel["Imports"],
            "Nuclear":    df_fuel["Nuclear"],
            "Renewables": renewables,
        },
        index=wide.index,
    ).round(2).sort_index()

    return df_fuel, df_group


def build_quarterly_area_charts(
    df_fuel: pd.DataFrame,
    df_group: pd.DataFrame,
    fuel_colors: dict,
    group_colors: dict,
) -> tuple[go.Figure, go.Figure]:
    """Return (fig_fuel, fig_group) Plotly stacked area figures."""

    def _make_fig(df: pd.DataFrame, stack_order: list[str], color_fn) -> go.Figure:
        x_values = df.index.astype(str).tolist()
        fig = go.Figure()
        for col in stack_order:
            if col not in df.columns:
                continue
            c = color_fn(col)
            fig.add_trace(go.Scatter(
                x=x_values,
                y=df[col].tolist(),
                name=col,
                fill="tonexty",
                stackgroup="one",
                mode="none",
                line=dict(width=0.8, color=c),
                fillcolor=c,
                opacity=0.88,
                hovertemplate="%{fullData.name}: %{y:.1f} TWh<extra></extra>",
            ))
        fig.update_layout(**_CHART_LAYOUT)
        fig.update_layout(xaxis=dict(
            type="category",
            categoryorder="array",
            categoryarray=x_values,
            tickmode="array",
            tickvals=x_values,
            ticktext=[str(v) for v in x_values],
            tickangle=-45,
            automargin=True,
            showgrid=False,
            zeroline=False,
            gridcolor="#3a6374",
            tickfont=dict(size=10, color="#ffffff"),
            color="#ffffff",
            title=dict(
                text="Quarter",
                font=dict(size=12, color="#ffffff"),
                standoff=20,
            ),
        ))
        return fig

    _lookup = {k.lower(): v for k, v in fuel_colors.items()}
    _name_map = {
        "hydro (nps+ps)": "hydro",
        "pumped storage":  "pumped storage",
    }

    def get_fuel_color(col_name: str) -> str:
        key = _name_map.get(col_name.lower(), col_name.lower())
        return _lookup.get(key, "#a3c3bb")

    fig_fuel  = _make_fig(df_fuel,  _FUEL_STACK_ORDER,  get_fuel_color)
    fig_group = _make_fig(df_group, _GROUP_STACK_ORDER, lambda c: group_colors.get(c, "#bdc3c7"))
    return fig_fuel, fig_group
