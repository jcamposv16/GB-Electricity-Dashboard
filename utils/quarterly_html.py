"""Build the styled HTML table for the Quarterly Analysis page."""

from __future__ import annotations

from utils.quarterly_utils import FUEL_ROWS

# ── Section definitions ───────────────────────────────────────────────────────
# Each section: (section_title, [(row_label, key_in_table_data, unit)])
# key prefix "fuel:" → table_data["fuel_twh"][name]
# key prefix "derived:" → table_data["derived"][name]
_SECTIONS = [
    (
        "Generation by Fuel (TWh)",
        [
            ("Coal",              "fuel:Coal",              "TWh"),
            ("Gas",               "fuel:Gas",               "TWh"),
            ("Imports",           "fuel:Imports",           "TWh"),
            ("Nuclear",           "fuel:Nuclear",           "TWh"),
            ("Biomass",           "fuel:Biomass",           "TWh"),
            ("Wind",              "fuel:Wind",              "TWh"),
            ("Solar",             "fuel:Solar",             "TWh"),
            ("Hydro (NPS+PS)",    "fuel:Hydro (NPS+PS)",    "TWh"),
            ("Other",             "fuel:Other",             "TWh"),
            ("Renewables total",         "derived:renewables_twh",          "TWh"),
            ("Renewables excl. biomass", "derived:renewables_excl_biomass", "TWh"),
            ("Fossil total",             "derived:fossil_twh",              "TWh"),
            ("Total excl. imports",      "derived:total_gen_excl_imports",  "TWh"),
            ("Total consumption",        "derived:Total consumption",       "TWh"),
        ],
    ),
    (
        "Percentage mix",
        [
            ("Fossil %",              "derived:fossil_pct",    "%"),
            ("Clean energy %",        "derived:clean_pct",     "%"),
            ("Renewables of clean %", "derived:ren_clean_pct", "%"),
        ],
    ),
    (
        "Generation shares",
        [
            ("Coal share",       "derived:Coal share",       "%"),
            ("Gas share",        "derived:Gas share",        "%"),
            ("Imports share",    "derived:Imports share",    "%"),
            ("Nuclear share",    "derived:Nuclear share",    "%"),
            ("Renewables share", "derived:Renewables share", "%"),
        ],
    ),
]

_DERIVED_BOLD = {
    "derived:renewables_twh",
    "derived:fossil_twh",
    "derived:Total consumption",
    "derived:clean_pct",
    "derived:Renewables share",
}

_HL_BG   = "#52796f"
_HL_TEXT = "#ffffff"


def build_quarterly_html(
    table_data: dict,
    highlight_q: str,
    dashboard_colors: dict,
) -> str:
    """Return a complete HTML document with an embedded styled table."""

    quarters: list[str] = table_data["quarters"]
    fuel_twh: dict      = table_data["fuel_twh"]
    derived: dict       = table_data["derived"]

    bg_main    = dashboard_colors.get("BG_MAIN",    "#2f3e46")
    bg_sidebar = dashboard_colors.get("BG_SIDEBAR", "#354f52")
    bg_accent  = dashboard_colors.get("BG_ACCENT",  "#52796f")
    text_green = dashboard_colors.get("TEXT_GREEN", "#84a98c")

    def _is_hl(q: str) -> bool:
        return q.endswith(f"-{highlight_q}")

    def _fmt(val, unit: str) -> str:
        if unit == "%":
            return f"{int(round(val))}%"
        return f"{val:.1f}"

    def _cell_val(key: str, q: str) -> float:
        kind, name = key.split(":", 1)
        if kind == "fuel":
            return fuel_twh.get(name, {}).get(q, 0.0)
        return derived.get(name, {}).get(q, 0.0)

    # ── Column header cells ───────────────────────────────────────────────────
    header_cells = ""
    for q in quarters:
        hl     = _is_hl(q)
        bg     = _HL_BG if hl else bg_sidebar
        col    = _HL_TEXT if hl else text_green
        weight = "700" if hl else "600"
        header_cells += (
            f'<th style="background:{bg};color:{col};font-weight:{weight};'
            f'padding:5px 10px;text-align:right;white-space:nowrap;">{q}</th>'
        )

    # ── Table body rows ───────────────────────────────────────────────────────
    body_rows = ""
    for section_title, row_defs in _SECTIONS:
        n_cols = 1 + len(quarters)
        body_rows += (
            f'<tr><td colspan="{n_cols}" style="'
            f'background:#52796f;color:#ffffff;font-weight:700;'
            f'font-size:11px;letter-spacing:0.06em;text-transform:uppercase;'
            f'padding:4px 10px;">{section_title}</td></tr>'
        )
        for row_label, key, unit in row_defs:
            bold    = key in _DERIVED_BOLD
            lbl_wt  = "700" if bold else "400"
            lbl_col = "#ffffff" if bold else "#e8ede9"
            row_bg  = "rgba(255,255,255,0.03)" if bold else "transparent"
            row_html = (
                f'<tr style="background:{row_bg};">'
                f'<td style="padding:3px 10px;color:{lbl_col};'
                f'font-weight:{lbl_wt};white-space:nowrap;">{row_label}</td>'
            )
            for q in quarters:
                val  = _cell_val(key, q)
                text = _fmt(val, unit)
                hl   = _is_hl(q)
                bg   = "rgba(82,121,111,0.18)" if hl else "transparent"
                col  = "#ffffff" if hl else "#e8ede9"
                wt   = "700" if (hl and bold) else ("700" if bold else "400")
                row_html += (
                    f'<td style="padding:3px 10px;text-align:right;'
                    f'background:{bg};color:{col};font-weight:{wt};'
                    f'font-variant-numeric:tabular-nums;">{text}</td>'
                )
            row_html += "</tr>\n"
            body_rows += row_html

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: {bg_main};
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    color: #cad2c5;
    padding: 0;
  }}
  .table-wrap {{
    width: 100%;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  th, td {{
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  tr:hover td {{
    background: rgba(255,255,255,0.04) !important;
  }}
</style>
</head>
<body>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th style="background:{bg_sidebar};color:{text_green};font-weight:700;
                   padding:5px 10px;text-align:left;white-space:nowrap;">Quarter</th>
        {header_cells}
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    return html
