"""
Sidebar layout for GB Grid Dashboard.

render_sidebar_header() renders logo + nav links. The active page is
rendered as static HTML (gold styling, no click needed). Inactive pages
use st.page_link() for instant internal SPA navigation.
Active page detection via url_path comparison.
"""

import streamlit as st

_LOGO_HTML = """
<div style="display:flex; align-items:center; gap:10px;
            padding:16px 8px 20px 8px;
            border-bottom:1px solid #3a6374; margin-bottom:8px;">
  <div style="width:32px; height:32px; border-radius:50%;
              border:1.5px solid #e9c46a; flex-shrink:0;
              display:flex; align-items:center; justify-content:center;">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="#e9c46a">
      <path d="M11 21h-1l1-7H7.5c-.58 0-.57-.32-.38-.66.19-.34.05-.08.07-.12
               C8.48 10.94 10.42 7.54 13 3h1l-1 7h3.5c.49 0 .56.33.47.51l-.07.15
               C12.96 17.55 11 21 11 21z"/>
    </svg>
  </div>
  <div>
    <div style="font-size:15px; font-weight:700; color:#eef4f2;
                letter-spacing:0.5px;">GB Electricity</div>
    <div style="font-size:10px; color:#a3c3bb; margin-top:2px;
                letter-spacing:1.5px;">DASHBOARD</div>
  </div>
</div>
"""

_SECTION_LABEL = (
    "<div style='padding:0 4px; font-size:10px; font-weight:600; "
    "letter-spacing:0.09em; text-transform:uppercase; color:#84a98c; "
    "margin:14px 0 4px;'>{title}</div>"
)

_DIVIDER = "<div style='height:1px;background:#3a6374;margin:8px 0 4px;'></div>"

# CSS for the inactive st.page_link items. Selector confirmed against the
# Streamlit 1.58 frontend bundle: manual st.page_link renders
# [data-testid="stPageLink"] wrapping [data-testid="stPageLink-NavLink"].
_PAGELINK_CSS = """
<style>
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
    padding: 8px 12px !important;
    border-radius: 6px !important;
    border-left: 2px solid transparent !important;
    margin: 1px 0 !important;
    background: transparent !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span {
    color: #a3c3bb !important;
    font-size: 13px !important;
    font-weight: 400 !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p {
    color: #cad2c5 !important;
    font-size: 13px !important;
    font-weight: 400 !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {
    background: rgba(233,196,106,0.08) !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover span,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover p {
    color: #e9c46a !important;
}
</style>
"""


def _icon_name(icon: str) -> str:
    """Extract Material Symbol name from ':material/icon_name:'."""
    if icon.startswith(":material/") and icon.endswith(":"):
        return icon[len(":material/"):-1]
    return ""


def _active_item_html(page) -> str:
    """The active page as static HTML — no navigation needed."""
    icon_name = _icon_name(page.icon)
    icon_html = (
        f'<span style="font-size:17px; color:#e9c46a; '
        f"font-family:'Material Symbols Rounded'; font-weight:normal; "
        f'font-style:normal; line-height:1; letter-spacing:normal; '
        f'text-transform:none; white-space:nowrap; flex-shrink:0;">'
        f'{icon_name}</span>'
        if icon_name else ""
    )
    return (
        '<div style="display:flex; align-items:center; gap:10px; '
        'padding:8px 12px; border-radius:6px; '
        'border-left:2px solid #e9c46a; '
        'background:rgba(233,196,106,0.14); margin:1px 0;">'
        f'{icon_html}'
        '<span style="font-size:13px; font-weight:600; color:#e9c46a; '
        f'white-space:nowrap;">{page.title}</span>'
        '</div>'
    )


def render_sidebar_header(page_groups: list, active_page) -> None:
    """
    Logo + grouped nav. Inactive pages are st.page_link (instant internal
    navigation). The active page is static HTML with gold styling — it
    needs no click handling since the user is already on it.
    """
    with st.sidebar:
        st.markdown(_LOGO_HTML, unsafe_allow_html=True)
        st.markdown(_PAGELINK_CSS, unsafe_allow_html=True)

        for section_title, pages in page_groups:
            st.markdown(
                _SECTION_LABEL.format(title=section_title),
                unsafe_allow_html=True,
            )
            for page in pages:
                if page.url_path == active_page.url_path:
                    st.markdown(_active_item_html(page), unsafe_allow_html=True)
                else:
                    st.page_link(page, width="stretch")

        st.markdown(_DIVIDER, unsafe_allow_html=True)
