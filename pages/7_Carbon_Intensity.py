"""Carbon Intensity — GB regional map page."""

import json
import sqlite3
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from data.cache_db import resolve_db_path, log_conn_open, fetch_regional_carbon_intensity

# ── Paths ──────────────────────────────────────────────────────────────────
_ROOT          = Path(__file__).parent.parent
_GEOJSON_PATH  = _ROOT / "reference" / "dno_regions.geojson"
_TEMPLATE_PATH = _ROOT / "reference" / "map_template.html"

# ── Load static assets (cached forever — files never change) ───────────────
@st.cache_resource
def _load_geojson() -> str:
    return _GEOJSON_PATH.read_text(encoding="utf-8")

@st.cache_resource
def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")

# ── Live CI data (refreshed every 30 minutes) ─────────────────────────────
@st.cache_data(ttl=1800)
def _get_ci_data() -> tuple[list[dict], str]:
    rows = fetch_regional_carbon_intensity()
    period = rows[0]["period_start_utc"] if rows else ""
    return rows, period

@st.cache_data(ttl=1800)
def _get_flow_data() -> dict:
    """
    Fetch the latest interconnector flow from raw_interconnector.
    Returns dict keyed by GeoJSON cable name -> flow_mw (float).
    Positive = import into GB, negative = export from GB.
    """
    NAME_MAP = {
        "IFA":            "IFA1 interconnector (France)",
        "IFA2":           "IFA2 interconnector (France)",
        "Eleclink":       "Eleclink interconnector (France)",
        "Nemo Link":      "Nemo Link interconnector (Belgium)",
        "BritNed":        "BritNed interconnector (Netherlands)",
        "Viking Link":    "Viking Link interconnector (Denmark)",
        "North Sea Link": "North Sea Link interconnector (Norway)",
        "Moyle":          "Moyle interconnector (Northern Ireland)",
        "East-West":      "East-West interconnector (Ireland)",
        "Greenlink":      "Greenlink interconnector (Ireland)",
    }
    try:
        import sys
        path = resolve_db_path()
        if sys.platform.startswith("win"):
            conn = sqlite3.connect(str(path), timeout=10)
            log_conn_open("page7._get_flow_data[win]", path)
        else:
            # Linux/HF: open read-only, no WAL, against the local /tmp copy
            # — see data/cache_db.py's _conn() and resolve_db_path() for the
            # same pattern and the reasoning behind it.
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            log_conn_open("page7._get_flow_data[linux]", path)
        latest = conn.execute(
            "SELECT MAX(timestamp) FROM raw_interconnector"
        ).fetchone()[0]
        if not latest:
            conn.close()
            return {}
        rows = conn.execute(
            "SELECT name, flow_mw FROM raw_interconnector "
            "WHERE timestamp = ?", (latest,)
        ).fetchall()
        conn.close()
        db_flows = {r[0]: r[1] for r in rows}
        return {
            geojson_name: db_flows.get(db_name, None)
            for geojson_name, db_name in NAME_MAP.items()
        }
    except Exception:
        return {}

# ── Page header ────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom:20px; margin-top:-8px;">
  <div style="font-size:22px; font-weight:700; color:#eef4f2;
              letter-spacing:0.02em; margin-bottom:4px;">
    Carbon Intensity by Region
  </div>
  <div style="height:1.5px;
              background:linear-gradient(90deg,#52796f 40%,transparent);
              margin-bottom:8px;"></div>
  <div style="font-size:12px; color:#a3c3bb;">
    Live regional carbon intensity &nbsp;&middot;&nbsp; GB grid &nbsp;&middot;&nbsp;
    gCO&#8322;/kWh &nbsp;&middot;&nbsp; refreshes every 30 minutes
  </div>
</div>
""", unsafe_allow_html=True)

# ── Fetch data ─────────────────────────────────────────────────────────────
ci_rows, period_label = _get_ci_data()
flow_data = _get_flow_data()

if not ci_rows:
    st.error(
        "Could not fetch regional carbon intensity data. "
        "Check your internet connection and try refreshing."
    )
    st.stop()

# ── Build CI data dict for the map template ────────────────────────────────
# Template expects: {region_id_str: {name, ci, index, wind, solar, gas,
#                                    nuclear, imports}}
ci_data = {}
for r in ci_rows:
    ci_data[str(r["region_id"])] = {
        "name":    r["short_name"],
        "ci":      r["intensity_gco2_kwh"],
        "index":   r["intensity_index"],
        "wind":    round(r["gen_wind_pct"],    1),
        "solar":   round(r["gen_solar_pct"],   1),
        "gas":     round(r["gen_gas_pct"],     1),
        "nuclear": round(r["gen_nuclear_pct"], 1),
        "imports": round(r["gen_imports_pct"], 1),
    }

# ── Load template and inject data ─────────────────────────────────────────
regions_geojson = _load_geojson()
template        = _load_template()

_intercon_path = _ROOT / "reference" / "interconnectors.geojson"
intercon_geojson = (
    _intercon_path.read_text(encoding="utf-8")
    if _intercon_path.exists()
    else '{"type":"FeatureCollection","features":[]}'
)

html = (template
    .replace("__REGIONS_GEOJSON__",  regions_geojson)
    .replace("__INTERCON_GEOJSON__", intercon_geojson)
    .replace("__CI_DATA__",          json.dumps(ci_data))
    .replace('"__PERIOD_LABEL__"',   json.dumps(period_label))
    .replace('"__FLOW_DATA__"',      json.dumps(flow_data))
)

# ── Render map + CI ranking table ─────────────────────────────────────────
col_map, col_table = st.columns([2.2, 1], gap="small")

with col_map:
    st.markdown(
        "<style>iframe { width: 100% !important; }"
        ".element-container iframe { width: 100% !important; }</style>",
        unsafe_allow_html=True,
    )
    components.html(html, height=600, scrolling=False)

with col_table:
    sorted_regions = sorted(ci_data.items(), key=lambda x: x[1]["ci"])
    INDEX_COLORS = {
        "very low": "#4ade80",
        "low":      "#a3e635",
        "moderate": "#facc15",
        "high":     "#f97316",
        "very high":"#ef4444",
    }
    rows_html = ""
    for rank, (rid, r) in enumerate(sorted_regions, 1):
        ci_val   = r["ci"]
        idx      = r["index"].lower()
        ci_color = INDEX_COLORS.get(idx, "#eef4f2")
        rows_html += (
            f'<tr>'
            f'<td style="padding:7px 10px;color:#a3c3bb;'
            f'font-size:13px;text-align:center;">{rank}</td>'
            f'<td style="padding:7px 10px;color:#eef4f2;'
            f'font-size:14px;font-weight:600;">{r["name"]}</td>'
            f'<td style="padding:7px 10px;color:{ci_color};'
            f'font-size:14px;font-weight:700;text-align:right;">'
            f'{ci_val}</td>'
            f'<td style="padding:7px 10px;color:{ci_color};'
            f'font-size:12px;text-align:center;'
            f'text-transform:capitalize;">{r["index"]}</td>'
            f'</tr>'
        )
    table_html = f"""
    <div style="background:#2f5361; border-radius:8px;
                border:1px solid #3a6374; overflow:hidden;
                margin-top:0; height:592px; display:flex;
                flex-direction:column;">
      <div style="background:#354f52; padding:8px 12px;
                  border-bottom:1px solid #3a6374;">
        <span style="font-size:13px; font-weight:700;
                     color:#e9c46a; letter-spacing:0.05em;
                     text-transform:uppercase;">
          CI Ranking
        </span>
        <span style="font-size:11px; color:#a3c3bb;
                     margin-left:8px;">gCO&#8322;/kWh</span>
      </div>
      <div style="overflow-y:auto; flex:1;">
        <table style="width:100%; border-collapse:collapse;">
          <thead>
            <tr style="background:#354f52;">
              <th style="padding:6px 10px; color:#a3c3bb;
                  font-size:11px; font-weight:600;
                  letter-spacing:0.05em; text-align:center;
                  border-bottom:1px solid #3a6374;">#</th>
              <th style="padding:6px 10px; color:#a3c3bb;
                  font-size:11px; font-weight:600;
                  letter-spacing:0.05em; text-align:left;
                  border-bottom:1px solid #3a6374;">Region</th>
              <th style="padding:6px 10px; color:#a3c3bb;
                  font-size:11px; font-weight:600;
                  letter-spacing:0.05em; text-align:right;
                  border-bottom:1px solid #3a6374;">CI</th>
              <th style="padding:6px 10px; color:#a3c3bb;
                  font-size:11px; font-weight:600;
                  letter-spacing:0.05em; text-align:center;
                  border-bottom:1px solid #3a6374;">Index</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)

# ── Period caption ─────────────────────────────────────────────────────────
if period_label:
    st.markdown(
        f"<div style='font-size:11px; color:#a3c3bb; margin-top:4px;'>"
        f"Data period: {period_label} UTC &nbsp;&middot;&nbsp; "
        f"Source: Carbon Intensity API (carbonintensity.org.uk)</div>",
        unsafe_allow_html=True,
    )
