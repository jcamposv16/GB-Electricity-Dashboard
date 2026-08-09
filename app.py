"""
GB Grid Dashboard — entry point.
Run: .venv\\Scripts\\streamlit.exe run app.py --server.port 8502
"""

import faulthandler, sys
faulthandler.enable(file=sys.stderr, all_threads=True)

sys.stdout.reconfigure(encoding='utf-8')

import streamlit as st
from styles.theme import CSS
from navigation import ALL_PAGES, PAGE_GROUPS, build_navigation
from components.sidebar import render_sidebar_header
from data.fetcher import get_last_synced
from data.cache_db import resolve_db_path

# ── Resolve the runtime DB path before anything else touches the database.
# On Linux this copies grid_cache.db to /tmp once per container (see
# resolve_db_path()'s docstring in data/cache_db.py); on Windows it's a
# no-op that returns the original repo path unchanged.
resolve_db_path()

# ── Diagnostic: process RSS memory, logged once per rerun (Linux only) —
# rules memory growth in or out across repeated interactions. Reruns are a
# full top-to-bottom re-execution of this script, so this naturally fires
# every rerun without needing its own once-per-container guard.
if not sys.platform.startswith("win"):
    try:
        with open("/proc/self/status") as _f:
            for _line in _f:
                if _line.startswith("VmRSS:"):
                    _rss_kb = int(_line.split()[1])
                    print(f"[mem] rerun rss_mb={_rss_kb / 1024:.1f}", file=sys.stderr)
                    break
    except Exception as _e:
        print(f"[mem] failed to read RSS: {type(_e).__name__}: {_e}", file=sys.stderr)

st.set_page_config(
    page_title="GB Grid Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global dark theme ──────────────────────────────────────────────────────────
st.markdown(CSS, unsafe_allow_html=True)

# ── Auto-sync: once per session if pipeline data is > 35 minutes stale ────────
# Only generation_mix and interconnector are updated by the pipeline.
# carbon_intensity is excluded — it is never written by sync.py, so including
# it would always show a stale age and either suppress or always trigger sync.
# Windows only: on Linux the deployed snapshot never advances, so the
# staleness check always trips and sync_all_sources() is a no-op — running
# it would only add latency and show a misleading "syncing" banner.
if sys.platform.startswith("win") and not st.session_state.get("auto_synced"):
    from data.fetcher import get_last_synced, sync_all_sources
    from datetime import datetime, timezone, timedelta

    _ts_gm  = get_last_synced("generation_mix")
    _ts_ic  = get_last_synced("interconnector")
    _now    = datetime.now(timezone.utc)
    _ages   = [
        _now - datetime.fromisoformat(ts)
        for ts in (_ts_gm, _ts_ic) if ts
    ]
    oldest_age = max(_ages) if _ages else timedelta(days=999)

    if oldest_age > timedelta(minutes=35):
        sync_all_sources()
        st.session_state["auto_synced"] = True
        st.info(
            "⏳ Syncing latest grid data in background — "
            "refresh the page in ~30 seconds for latest values.",
            icon="🔄",
        )
    else:
        st.session_state["auto_synced"] = True

# ── Navigation: register pages (must come before st.page_link calls) ──────────
pg = build_navigation()

# ── Sidebar header: logo + nav links using registered StreamlitPage objects ───
render_sidebar_header(PAGE_GROUPS, active_page=pg)

# ── Run the active page ────────────────────────────────────────────────────────
pg.run()

# ── Sidebar: refresh button (rendered after pg.run so it sits below page ──────
# ── widgets like the Time Range selector that pages add to the sidebar) ────────
with st.sidebar:
    last = get_last_synced("generation_mix")
    if last:
        st.markdown(
            f"<div style='text-align:center; font-size:10px; color:#5f7d76; "
            f"margin-top:6px;'>Synced {last[:16]} UTC</div>",
            unsafe_allow_html=True,
        )
