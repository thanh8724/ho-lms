from __future__ import annotations

import streamlit as st


def inject_app_css(mode: str = "auto", density: str = "comfortable") -> None:
    mode = mode if mode in {"auto", "light", "dark"} else "auto"
    density = density if density in {"comfortable", "compact"} else "comfortable"
    dark_media = "" if mode != "auto" else "@media (prefers-color-scheme: dark)"
    dark_selector = ":root" if mode == "dark" else ""
    compact_spacing = "0.72rem" if density == "compact" else "1rem"
    st.html("""
    <style>
      :root {
        --ho-bg: #F6F8FB; --ho-surface: #FFFFFF; --ho-sidebar: #FFFFFF;
        --ho-border: #D9E1EA; --ho-border-soft: #E8EDF3; --ho-text: #172033;
        --ho-muted: #64748B; --ho-primary: #2563EB; --ho-primary-soft: #E8F0FF;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      __DARK_SELECTOR__ {
        --ho-bg: #060F17; --ho-surface: #101C28; --ho-sidebar: #080F18;
        --ho-border: #263746; --ho-border-soft: #1B2A38; --ho-text: #F1F5F9;
        --ho-muted: #94A3B8; --ho-primary: #0EA5C9; --ho-primary-soft: #102E43;
      }
      __DARK_MEDIA__ { :root { --ho-bg: #060F17; --ho-surface: #101C28; --ho-sidebar: #080F18; --ho-border: #263746; --ho-border-soft: #1B2A38; --ho-text: #F1F5F9; --ho-muted: #94A3B8; --ho-primary: #0EA5C9; --ho-primary-soft: #102E43; } }
      [data-testid="stSidebar"] { min-width: 250px; max-width: 270px; }
      [data-testid="stSidebar"] > div:first-child { background: var(--ho-sidebar); border-right: 1px solid var(--ho-border-soft); }
      [data-testid="stAppViewContainer"] { background: var(--ho-bg); }
      [data-testid="stHeader"] { background: color-mix(in srgb, var(--ho-bg) 92%, transparent); }
      [data-testid="stMainBlockContainer"] { max-width: 1440px; padding: 2rem 2.2rem 3rem; }
      body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
      [data-testid="stMarkdownContainer"], [data-testid="stText"], label,
      h1, h2, h3, h4, h5, h6, p { color: var(--ho-text); }
      [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--ho-border);
        border-radius: 10px;
        background: var(--ho-surface);
        box-shadow: 0 1px 2px rgba(15, 23, 42, .03);
      }
      div[data-testid="stMetric"] { background: var(--ho-surface); border: 1px solid var(--ho-border); border-radius: 10px; padding: 12px; }
      .ho-brand { align-items: center; display: flex; gap: .65rem; margin: .2rem .1rem 1.55rem; }
      .ho-brand-mark { align-items: center; background: var(--ho-primary); border-radius: 8px; color: white; display: flex; font-weight: 800; height: 32px; justify-content: center; width: 32px; }
      .ho-brand-name, .ho-title, .ho-section-label { color: var(--ho-text); }
      .ho-brand-name { font-size: 1.02rem; font-weight: 750; letter-spacing: -.02em; }
      .ho-eyebrow { color: var(--ho-muted); font-size: .72rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
      .ho-muted, .ho-output { color: var(--ho-muted); font-size: .92rem; }
      .ho-title { font-size: 2rem; font-weight: 750; letter-spacing: -.035em; line-height: 1.15; margin: .18rem 0 .4rem; }
      .ho-output { font-size: .82rem; margin-top: .7rem; }
      .ho-section-label { font-size: 1.05rem; font-weight: 700; }
      .ho-status-card { background: var(--ho-surface); border: 1px solid var(--ho-border); border-radius: 10px; padding: .85rem 1rem; }
      .ho-sidebar-group { color: var(--ho-muted); font-size: .7rem; font-weight: 750; letter-spacing: .06em; margin: 1.2rem .15rem .45rem; text-transform: uppercase; }
      .ho-page-toolbar { align-items: end; border-bottom: 1px solid var(--ho-border-soft); display: flex; justify-content: space-between; margin-bottom: 1.4rem; padding-bottom: 1.1rem; }
      .ho-page-title { color: var(--ho-text); font-size: 1.85rem; font-weight: 760; letter-spacing: -.035em; margin: 0; }
      .ho-page-subtitle { color: var(--ho-muted); font-size: .9rem; margin-top: .35rem; }
      .ho-filter-title { color: var(--ho-text); font-size: 1rem; font-weight: 700; margin-bottom: .2rem; }
      .ho-filter-caption { color: var(--ho-muted); font-size: .82rem; margin-bottom: .8rem; }
      .ho-job-heading { align-items: center; border-bottom: 1px solid var(--ho-border-soft); display: flex; justify-content: space-between; margin: 2rem 0 1rem; padding-bottom: .75rem; }
      .ho-job-title { color: var(--ho-text); font-size: 1rem; font-weight: 700; }
      .ho-step { align-items: flex-start; background: var(--ho-surface); border: 1px solid var(--ho-border); border-radius: 10px; display: flex; gap: .7rem; min-height: 74px; padding: .8rem; transition: border-color .18s ease, background .18s ease; }
      .ho-step-active { background: var(--ho-primary-soft); border-color: var(--ho-primary); box-shadow: 0 0 0 1px color-mix(in srgb, var(--ho-primary) 20%, transparent); }
      .ho-step-complete { border-color: color-mix(in srgb, var(--ho-primary) 48%, var(--ho-border)); }
      .ho-step-number { align-items: center; background: var(--ho-border-soft); border-radius: 8px; color: var(--ho-muted); display: flex; flex: 0 0 30px; font-size: .75rem; font-weight: 750; height: 30px; justify-content: center; }
      .ho-step-active .ho-step-number, .ho-step-complete .ho-step-number { background: var(--ho-primary); color: white; }
      .ho-step-title { color: var(--ho-text); font-size: .82rem; font-weight: 700; }
      .ho-step-description { color: var(--ho-muted); font-size: .7rem; line-height: 1.35; margin-top: .2rem; }
      .ho-panel-title { color: var(--ho-text); font-size: .98rem; font-weight: 700; }
      [data-testid="stForm"] { padding: __COMPACT_SPACING__; }
      [data-testid="stSidebar"] .stButton button { font-size: .86rem; text-align: left; }
      [data-testid="stSidebar"] .stButton button[kind="primary"] { background: var(--ho-primary-soft); border-color: var(--ho-primary-soft); color: var(--ho-primary); }
      [data-testid="stSidebar"] [data-testid="stSelectbox"] label { font-size: .76rem; color: var(--ho-muted); }
      [data-testid="stSidebar"] [data-baseweb="select"] { border-radius: 8px; }
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .55rem; }
      [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] { box-shadow: none; }
      button[kind="primary"] { font-weight: 650; }
      [data-testid="stExpander"] { border: 1px solid var(--ho-border); border-radius: 10px; background: var(--ho-surface); }
      code { color: var(--ho-primary); }
      [data-baseweb="input"] > div, [data-baseweb="select"] > div, textarea,
      input, [data-testid="stDateInput"] input { background: var(--ho-surface) !important; border-color: var(--ho-border) !important; color: var(--ho-text) !important; }
      [data-baseweb="select"] [data-testid="stMarkdownContainer"], [data-baseweb="select"] input { color: var(--ho-text) !important; }
      label, [data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"] { color: var(--ho-text); }
      [data-testid="stCaptionContainer"] { color: var(--ho-muted); }
      [data-testid="stButton"] button, [data-testid="stDownloadButton"] button { background: var(--ho-surface); border: 1px solid var(--ho-border); color: var(--ho-text); }
      [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover { border-color: var(--ho-primary); color: var(--ho-primary); }
      [data-testid="stSidebar"] .stButton button[kind="secondary"] { background: transparent; border-color: transparent; color: var(--ho-text); }
      [data-testid="stSidebar"] .stButton button[kind="secondary"]:hover { background: var(--ho-primary-soft); border-color: var(--ho-primary-soft); color: var(--ho-primary); }
      [data-testid="stSidebar"] [data-testid="stExpander"] summary { color: var(--ho-text); }
    </style>
    """.replace("__DARK_SELECTOR__", dark_selector).replace("__DARK_MEDIA__", dark_media).replace("__COMPACT_SPACING__", compact_spacing))


def render_header(eyebrow: str, title: str, description: str, output_name: str) -> None:
    st.markdown(
        f'<div class="ho-page-toolbar"><div><div class="ho-eyebrow">{eyebrow}</div>'
        f'<div class="ho-page-title">{title}</div><div class="ho-page-subtitle">{description}</div></div>'
        f'<div class="ho-output">Tệp xuất<br><code>{output_name}</code></div></div>',
        unsafe_allow_html=True,
    )
