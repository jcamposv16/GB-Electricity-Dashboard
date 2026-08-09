"""
Page registration for GB Grid Dashboard.

ALL_PAGES is the single source of truth for which pages exist and their nav order.
PAGE_GROUPS partitions ALL_PAGES into labelled sidebar sections for render_sidebar_header().
build_navigation() registers them with Streamlit and hides the auto-nav UI.
render_sidebar_header() (in components/sidebar.py) receives PAGE_GROUPS
and passes StreamlitPage objects directly to st.page_link(), bypassing
the url_pathname string-lookup that caused the previous KeyError.
"""

import streamlit as st

ALL_PAGES = [
    # ── Live grid ──────────────────────────────────────────────────────────────
    st.Page("pages/1_Generation_Mix.py",              title="Generation by fuel type",  icon=":material/area_chart:"),
    st.Page("pages/4_Generation_Main_Fuel_Group.py",  title="Generation main groups",   icon=":material/category:"),
    st.Page("pages/2_Interconnector_Flows.py",        title="Interconnector flows",     icon=":material/cable:"),
    st.Page("pages/3_Generation_Flow.py",             title="Generation flow",          icon=":material/hub:"),
    # ── Analysis ───────────────────────────────────────────────────────────────
    st.Page("pages/5_Quarterly_Analysis.py",          title="Quarterly analysis",       icon=":material/calendar_month:"),
    st.Page("pages/6_Comparison_Analysis.py",         title="Comparison analysis",      icon=":material/monitoring:"),
    # ── Environment ────────────────────────────────────────────────────────────
    st.Page("pages/7_Carbon_Intensity.py",            title="Carbon intensity",         icon=":material/eco:"),
]

PAGE_GROUPS = [
    ("Live grid",   ALL_PAGES[0:4]),
    ("Analysis",    ALL_PAGES[4:6]),
    ("Environment", ALL_PAGES[6:7]),
]


def build_navigation() -> st.Page:
    """
    Register ALL_PAGES with Streamlit and return the active page.
    position='hidden' suppresses the auto-rendered sidebar nav entirely —
    no CSS hack needed.  Must be called before st.page_link().
    """
    return st.navigation(ALL_PAGES, position="hidden")
