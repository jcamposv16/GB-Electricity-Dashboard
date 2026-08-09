"""
Colour palette, CSS, and shared Plotly layout constants.
CSS lifted directly from GB-Grid-Agent/ui.py and extended.
Plotly configs lifted from GB-Grid-Agent/dashboard_templates.py.
"""

# ── Fuel colours ───────────────────────────────────────────────────────────────
FUEL_COLORS = {
    "coal":           "#353535",
    "gas":            "#9E3A26",
    "solar":          "#ffca3a",
    "wind":           "#2a9d8f",
    "hydro":          "#1982c4",
    "pumped storage": "#4267ac",
    "nuclear":        "#9D4EDD",
    "biomass":        "#208B3A",
    "imports":        "#22657f",
    "other":          "#CAD2C5",
    "wind_bm":        "#2a9d8f",
    "wind_emb":       "#48c4b5",
    "ccgt":           "#9E3A26",
    "ocgt":           "#b85a44",
}

# Distinct palette for interconnector cables (one colour per cable)
CABLE_PALETTE = [
    "#3498db", "#e67e22", "#9b59b6", "#27ae60",
    "#e74c3c", "#1abc9c", "#f39c12", "#2ecc71",
    "#e91e63", "#00bcd4",
]

# ── Theme colour tokens ────────────────────────────────────────────────────────
BG           = '#2f3e46'   # page background — deep petrol
SIDEBAR_BG   = '#354f52'   # sidebar — darker petrol
CARD_BG      = '#2f5361'   # card / plot surface
ACCENT       = '#e9c46a'   # jasmine gold
TEXT_PRIMARY = '#eef4f2'   # primary text
TEXT_MUTED   = '#a3c3bb'   # muted / secondary text
BORDER_COLOR = '#3a6374'   # borders and grid lines

# Backward-compat aliases (imported by charts.py, comparison_utils.py, quarterly_utils.py, pages/5)
BG_MAIN    = BG
BG_SIDEBAR = SIDEBAR_BG
BG_ACCENT  = ACCENT
TEXT_GREEN = TEXT_MUTED
PLOT_BG    = CARD_BG

# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
<style>

/* ── Hide Streamlit top header / toolbar ── */
header[data-testid="stHeader"] {
    display: none !important;
    height: 0 !important;
}
[data-testid="stToolbar"] {
    display: none !important;
}
#MainMenu {
    display: none !important;
}

/* ── Page background ── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > div,
section[data-testid="stMain"],
.main {
    background-color: #2f3e46 !important;
}
.main .block-container {
    background-color: #2f3e46 !important;
    padding-top: 0.5rem !important;
    margin-top: 0 !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #354f52 !important;
    border-right: 1px solid #3a6374 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {
    color: #eef4f2 !important;
}

/* nav links — base */
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
    padding: 8px 12px !important;
    border-radius: 6px !important;
    border-left: 2px solid transparent !important;
    color: #cad2c5 !important;
    font-size: 13px !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span {
    color: #a3c3bb !important;
    font-size: 13px !important;
    font-weight: 400 !important;
}
/* hover */
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
    background-color: rgba(233,196,106,0.08) !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover span {
    color: #e9c46a !important;
}
/* active page */
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
    background-color: rgba(233,196,106,0.14) !important;
    border-left: 2px solid #e9c46a !important;
    border-radius: 6px !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] span {
    color: #e9c46a !important;
    font-weight: 600 !important;
}
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
}

/* ── Streamlit widgets ── */
.stSelectbox > div > div,
.stDateInput > div > div,
.stTextInput > div > div {
    background-color: #2f5361 !important;
    color: #eef4f2 !important;
    border: 1px solid #3a6374 !important;
    border-radius: 6px !important;
}
.stDateInput input,
.stDateInput input[type="text"],
[data-testid="stDateInput"] input {
    color: #eef4f2 !important;
    -webkit-text-fill-color: #eef4f2 !important;
}
.stSelectbox [data-baseweb="select"] div,
.stSelectbox [data-baseweb="select"] span {
    color: #eef4f2 !important;
}
[data-testid="stSelectbox"] div[value] {
    color: #eef4f2 !important;
}
[data-testid="stSegmentedControl"] {
    background-color: #2f5361 !important;
    border-radius: 8px !important;
    border: 1px solid #3a6374 !important;
}
[data-testid="stSegmentedControl"] button[aria-checked="true"] {
    background-color: #e9c46a !important;
    color: #1f3b47 !important;
    font-weight: 600 !important;
}
[data-testid="stSegmentedControl"] button {
    color: #a3c3bb !important;
}
.stRadio > div {
    background-color: #2f5361 !important;
    border-radius: 8px !important;
    border: 1px solid #3a6374 !important;
}

/* ── Buttons ── */
.stButton > button {
    background-color: #2f5361 !important;
    color: #eef4f2 !important;
    border: 1px solid #3a6374 !important;
    border-radius: 6px !important;
}
.stButton > button:hover {
    background-color: #e9c46a !important;
    color: #1f3b47 !important;
    border-color: #e9c46a !important;
}

/* ── Text ── */
.stMarkdown, .stMarkdown p,
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    color: #eef4f2 !important;
}

/* ── Dividers ── */
hr { border-color: #3a6374 !important; }

/* ── Metrics ── */
[data-testid="stMetric"] {
    background-color: #2f5361 !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
}

/* ── Info / warning boxes ── */
[data-testid="stAlert"] {
    background-color: #2f5361 !important;
    border-color: #3a6374 !important;
    color: #eef4f2 !important;
}

/* ── Caption / small text ── */
.stCaption, .stCaption p {
    color: #a3c3bb !important;
}

</style>
"""

# ── Plotly shared layout ────────────────────────────────────────────────────────
PLOTLY_LAYOUT_BASE = dict(
    template="none",
    plot_bgcolor='#F3F9ED',
    paper_bgcolor=BG,
    height=420,
    margin=dict(t=30, b=60, l=65, r=20),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor="#ddd",
        font={"size": 11, "color": "#333"},
    ),
)

# Shared tick styling — merged into each axis dict
_TICK_BASE = dict(
    tickfont={"size": 11, "color": TEXT_PRIMARY},
    showgrid=True, gridcolor=BORDER_COLOR, gridwidth=1, griddash="dash",
    zeroline=False, showline=False, ticks="outside", ticklen=4,
)

# Per-granularity x-axis configs (from dashboard_templates)
XAXIS_HALF_HOURLY = dict(**_TICK_BASE, tickformat="%H:%M",  hoverformat="%d %b %Y  %H:%M", dtick=7_200_000, tickangle=0)
XAXIS_DAILY       = dict(**_TICK_BASE, tickformat="%d %b",  hoverformat="%d %b %Y",                          tickangle=-30)
XAXIS_MONTHLY     = dict(**_TICK_BASE, tickformat="%b %Y",  hoverformat="%b %Y",                              tickangle=-30)

YAXIS_BASE = dict(
    tickfont={"size": 11, "color": TEXT_PRIMARY},
    showgrid=True, gridcolor=BORDER_COLOR, gridwidth=1, griddash="dash",
    zeroline=True, zerolinecolor="rgba(163,195,187,0.25)",
    showline=True, linecolor=BORDER_COLOR, linewidth=1.5,
    ticks="outside", ticklen=4,
)

LEGEND_H = dict(
    orientation="h", x=0.5, xanchor="center",
    y=1.05, yanchor="bottom",
    font={"size": 10, "color": TEXT_MUTED},
    bgcolor="rgba(0,0,0,0)", borderwidth=0,
    itemclick="toggle", itemdoubleclick="toggleothers",
)
