"""Generation Flow page — animated live snapshot of GB grid power flows."""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from data.cache_db import resolve_db_path, log_conn_open

TEMPLATE_PATH = (
    Path(__file__).parent.parent
    / "energy-data-pipeline"
    / "gb_grid_flow_template.html"
)

# Cable name (as stored in raw_interconnector) → country label
_CABLE_COUNTRY = {
    "Eleclink interconnector (France)":        "French",
    "IFA1 interconnector (France)":            "French",
    "IFA2 interconnector (France)":            "French",
    "BritNed interconnector (Netherlands)":    "Dutch",
    "North Sea Link interconnector (Norway)":  "Norwegian",
    "Nemo Link interconnector (Belgium)":      "Belgian",
    "Viking Link interconnector (Denmark)":    "Danish",
    "Moyle interconnector (Northern Ireland)": "Northern Irish",
    "East-West interconnector (Ireland)":      "Irish",
    "Greenlink interconnector (Ireland)":      "Irish",
}
_IMPORT_ORDER = ["French", "Dutch", "Norwegian", "Belgian", "Danish"]
_EXPORT_ORDER = ["Northern Irish", "Irish"]

_BM_GEN_FUELS = ("ccgt", "ocgt", "coal", "biomass", "wind_bm", "nuclear", "hydro", "other")


@st.cache_data(ttl=30)
def get_flow_snapshot() -> dict:
    import sys
    path = resolve_db_path()
    if sys.platform.startswith("win"):
        conn = sqlite3.connect(str(path), timeout=30)
        log_conn_open("page3.get_flow_snapshot[win]", path)
    else:
        # Linux/HF: open read-only, no WAL, against the local /tmp copy —
        # see data/cache_db.py's _conn() and resolve_db_path() for the same
        # pattern and the reasoning behind it.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        log_conn_open("page3.get_flow_snapshot[linux]", path)
    conn.row_factory = sqlite3.Row

    ts = conn.execute(
        "SELECT MAX(timestamp) FROM raw_generation_mix"
    ).fetchone()[0]

    fuel_rows = conn.execute(
        "SELECT fuel_type, mw FROM raw_generation_mix WHERE timestamp = ?", (ts,)
    ).fetchall()
    mw = {r["fuel_type"]: r["mw"] for r in fuel_rows}

    bm_generation_mw  = sum(mw.get(f, 0.0) for f in _BM_GEN_FUELS)
    lv_wind_mw        = mw.get("wind_emb", 0.0)
    solar_mw          = mw.get("solar", 0.0)
    pumped_storage_mw = mw.get("pumped storage", 0.0)

    ic_ts = conn.execute(
        "SELECT MAX(timestamp) FROM raw_interconnector"
    ).fetchone()[0]
    ic_rows = conn.execute(
        "SELECT name, flow_mw FROM raw_interconnector WHERE timestamp = ?", (ic_ts,)
    ).fetchall()
    conn.close()

    country_net: dict[str, float] = {}
    for r in ic_rows:
        country = _CABLE_COUNTRY.get(r["name"])
        if country:
            country_net[country] = country_net.get(country, 0.0) + r["flow_mw"]

    imports_by_country = [
        {"country": c, "mw": country_net[c]}
        for c in _IMPORT_ORDER
        if country_net.get(c, 0) > 0
    ]
    exports_by_country = [
        {"country": c, "mw": -country_net[c]}
        for c in _EXPORT_ORDER
        if country_net.get(c, 0) < 0
    ]
    for c, net in country_net.items():
        if net > 0 and c not in _IMPORT_ORDER:
            imports_by_country.append({"country": c, "mw": net})
        if net < 0 and c not in _EXPORT_ORDER:
            exports_by_country.append({"country": c, "mw": -net})

    imports_total_mw  = sum(max(v, 0) for v in country_net.values())
    exports_total_mw  = sum(max(-v, 0) for v in country_net.values())
    total_generation_mw = (
        imports_total_mw + bm_generation_mw + lv_wind_mw
        + solar_mw + max(pumped_storage_mw, 0)
    )

    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    settlement_period = dt.hour * 2 + dt.minute // 30 + 1

    return {
        "settlement_date":     dt.strftime("%Y-%m-%d"),
        "settlement_period":   settlement_period,
        "start_time":          dt.strftime("%Y-%m-%d %H:%M"),
        "bm_generation_gw":    bm_generation_mw  / 1000,
        "lv_wind_gw":          lv_wind_mw        / 1000,
        "solar_gw":            solar_mw          / 1000,
        "pumped_storage_gw":   pumped_storage_mw / 1000,
        "imports_gw":          imports_total_mw  / 1000,
        "exports_gw":          exports_total_mw  / 1000,
        "total_generation_gw": total_generation_mw / 1000,
        "imports_by_country":  imports_by_country,
        "exports_by_country":  exports_by_country,
    }


# ── Page ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom:20px; margin-top:-8px;">
  <div style="font-size:22px; font-weight:700; color:#eef4f2;
              letter-spacing:0.02em; margin-bottom:4px;">
    Generation Flow
  </div>
  <div style="height:1.5px;
              background:linear-gradient(90deg,#52796f 40%,transparent);
              margin-bottom:8px;"></div>
  <div style="font-size:12px; color:#a3c3bb;">
    Live power flow snapshot · GB grid · refreshes every 60 seconds
  </div>
</div>
""", unsafe_allow_html=True)

snapshot = get_flow_snapshot()
template = TEMPLATE_PATH.read_text(encoding="utf-8")

# Inject live data and tighten the flex gap
inner_html = template.replace(
    "/* __DATA__ */",
    f"window.__GB_GRID_DATA__ = {json.dumps(snapshot)};",
)
inner_html = inner_html.replace("gap: 24px", "gap: 16px")

# R_NODE=80, R_CENTER=100
# Solar(700,490)→Generation(700,300) gap=190px, sum=180px (10px clearance)
inner_html = inner_html.replace("const R_CENTER = 58;", "const R_CENTER = 100;")
inner_html = inner_html.replace("const R_NODE = 42;",   "const R_NODE = 80;")

# Fully symmetric layout: LV Wind below BM Gen, Solar below Pumped Storage
# BM Gen (320,130)  Pumped (1090,130)
# Imports  TOTAL(700,300)  Exports
# LV Wind(320,490)  Solar(1090,490)
inner_html = inner_html.replace(
    "const NODES = {\n  imports:  { x: 210, y: 250 },\n  generation: { x: 480, y: 250 },\n  exports:  { x: 750, y: 250 },\n  bmGeneration: { x: 335, y: 95 },\n  pumpedStorage: { x: 625, y: 95 },\n  lvWind: { x: 335, y: 405 },\n  solar: { x: 480, y: 410 },\n};",
    "const NODES = {\n  imports:      { x: 120,  y: 300 },\n  generation:   { x: 700,  y: 300 },\n  exports:      { x: 1280, y: 300 },\n  bmGeneration: { x: 320,  y: 130 },\n  pumpedStorage:{ x: 1090, y: 130 },\n  lvWind:       { x: 320,  y: 490 },\n  solar:        { x: 1090, y: 490 },\n};",
)

# S-curve satellite flows: exit circles vertically, arrive at generation horizontally.
# Cubic bezier formula: M x1,y1 C x1,y2  midX,y2  x2,y2
# where midX = (x1+x2)/2 ensures smooth S-shape.
#
# With patched NODES and R_NODE=80, R_CENTER=100:
#   BM Gen exit  (320, 210) → Gen left-above  (600, 280)  midX=460
#   LV Wind exit (320, 410) → Gen left-below  (600, 320)  midX=460
#   PS exit      (1090,210) → Gen right-above (800, 280)  midX=945
#   Solar exit   (1090,410) → Gen right-below (800, 320)  midX=945
#   PS charging reversal: (800,280) → (1090,210)

inner_html = inner_html.replace(
    "straightPath(NODES.solar, { x: NODES.generation.x, y: NODES.generation.y + R_CENTER })",
    "`M1090,410 C1090,320 945,320 800,320`",
)
inner_html = inner_html.replace(
    "curvePath(NODES.bmGeneration, { x: NODES.generation.x - 20, y: NODES.generation.y - R_CENTER + 4 }, 45)",
    "`M320,210 C320,280 460,280 600,280`",
)
inner_html = inner_html.replace(
    "curvePath(NODES.lvWind, { x: NODES.generation.x - 20, y: NODES.generation.y + R_CENTER - 4 }, -45)",
    "`M320,410 C320,320 460,320 600,320`",
)
inner_html = inner_html.replace(
    "curvePath(NODES.pumpedStorage, { x: NODES.generation.x + 20, y: NODES.generation.y - R_CENTER + 4 }, 45)",
    "`M1090,210 C1090,280 945,280 800,280`",
)
inner_html = inner_html.replace(
    "curvePath({ x: NODES.generation.x + 20, y: NODES.generation.y - R_CENTER + 4 }, NODES.pumpedStorage, -45)",
    "`M800,280 C945,280 1090,280 1090,210`",
)

# Full-width viewBox for the wide layout
inner_html = inner_html.replace('viewBox="0 0 940 500"', 'viewBox="0 0 1400 600"')

# Directly patch template CSS font sizes (reduced to fit inside circles)
inner_html = inner_html.replace(
    "    font-size: 15px;\n    fill: #cfd2dc;",   # .node-label
    "    font-size: 26px;\n    fill: #cfd2dc;",
)
inner_html = inner_html.replace(
    "    font-size: 17px;\n    font-weight: 700;\n    fill: #f2f3f7;\n    text-anchor: middle;\n    font-family:",  # .node-value
    "    font-size: 31px;\n    font-weight: 700;\n    fill: #f2f3f7;\n    text-anchor: middle;\n    font-family:",
)
inner_html = inner_html.replace(
    "    font-size: 12px;\n    fill: #9198a8;",   # .node-sublabel
    "    font-size: 20px;\n    fill: #9198a8;",
)

# Central circle: remove "TOTAL" sublabel and external "Generation" label below circle;
# replace with "Generation" rendered inside the circle below the value (y + 34).
inner_html = inner_html.replace(
    '  drawNode(nodesG, {\n    x: NODES.generation.x, y: NODES.generation.y, r: R_CENTER,\n    label: "Generation", value: fmtGW(DATA.total_generation_gw * 1000, 1), sublabel: "TOTAL",\n    color: "#e8eaf0",\n  });',
    '  drawNode(nodesG, {\n    x: NODES.generation.x, y: NODES.generation.y, r: R_CENTER,\n    label: "", value: fmtGW(DATA.total_generation_gw * 1000, 1), sublabel: null,\n    color: "#e8eaf0",\n  });\n  { const gl = svgEl("text", { x: NODES.generation.x, y: NODES.generation.y + 34, class: "node-sublabel" }); gl.textContent = "Generation"; nodesG.appendChild(gl); }',
)

# Extract template parts
style_match  = re.search(r"<style>(.*?)</style>",   inner_html, re.DOTALL)
body_match   = re.search(r"<body>(.*?)</body>",      inner_html, re.DOTALL)
template_styles = style_match.group(1) if style_match else ""
body_content    = body_match.group(1)  if body_match  else inner_html

# Strip <script> blocks from body so they don't run twice
body_no_scripts = re.sub(r"<script>.*?</script>", "", body_content, flags=re.DOTALL)

# Collect all script blocks (data injection + render logic)
scripts = re.findall(r"<script>(.*?)</script>", inner_html, re.DOTALL)
script_content = "\n".join(scripts)

final_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
/* ── Reset ── */
* {{ box-sizing: border-box; }}
/* ── Template styles ── */
{template_styles}
/* ── Full-width chain fix ──
   Root cause: body{{display:flex}} made .scale-wrap shrink to content width,
   collapsing every % width below it. Fix: block layout, explicit widths. */
html, body {{
  margin: 0; padding: 0;
  width: 100%; height: 100%;
  background: #2f3e46;
}}
.scale-wrap {{ width: 100%; height: 100%; }}
.wrap {{
  width: 100% !important;
  min-height: unset !important;
  padding: 12px !important;
  background: #2f3e46;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.wrap > div {{
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.stage {{
  width: 100% !important;
  max-width: none !important;
  display: flex !important;
  align-items: center !important;
  gap: 4px !important;
}}
.side-list.left  {{ min-width: 220px; max-width: 220px; flex-shrink: 0;
                    text-align: right !important; }}
.side-list.right {{ min-width: 220px; max-width: 220px; flex-shrink: 0;
                    text-align: left !important; }}
.side-item .label {{ font-size: 14px !important; }}
.side-item .value {{ font-size: 26px !important; }}
#svg, svg {{
  flex: 1 1 auto;
  width: 1px;          /* flex will grow this to fill available space */
  min-width: 0;
  max-width: calc(100% - 440px);
  height: auto;
}}
#asOf {{ display: none; }}
</style>
</head>
<body>
<div class="scale-wrap">
{body_no_scripts}
</div>
<script>
{script_content}
</script>
</body>
</html>"""

st.markdown(
    "<style>"
    "iframe { width: 100% !important; }"
    ".element-container iframe { width: 100% !important; }"
    "</style>",
    unsafe_allow_html=True,
)
components.html(final_html, height=640, scrolling=False)

st.markdown(
    f"<div style='color:#a3c3bb;font-size:0.72rem;text-align:right;margin-top:4px;'>"
    f"Settlement period {snapshot['settlement_period']} · "
    f"data as of {snapshot['start_time']} UTC</div>",
    unsafe_allow_html=True,
)
