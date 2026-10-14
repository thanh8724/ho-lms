from __future__ import annotations

import streamlit as st


def inject_app_css(mode: str = "auto", density: str = "comfortable") -> None:
    mode = mode if mode in {"auto", "light", "dark"} else "auto"
    density = density if density in {"comfortable", "compact"} else "comfortable"
    compact_spacing = "0.75rem" if density == "compact" else "1.1rem"
    input_height = "38px" if density == "compact" else "42px"

    st.html(f"""
    <style>
      :root {{
        --ho-bg: #060F17;
        --ho-sidebar: #080F18;
        --ho-surface: #101C28;
        --ho-surface-elevated: #142331;
        --ho-primary: #0EA5C9;
        --ho-primary-hover: #14C8B8;
        --ho-primary-soft: rgba(14, 165, 201, 0.12);
        --ho-accent: #14C8B8;
        --ho-text: #F1F5F9;
        --ho-muted: #94A3B8;
        --ho-border: #263746;
        --ho-border-soft: #1B2A38;
        --ho-success: #22C55E;
        --ho-success-soft: rgba(34, 197, 94, 0.15);
        --ho-warning: #F59E0B;
        --ho-warning-soft: rgba(245, 158, 11, 0.15);
        --ho-error: #EF4444;
        --ho-error-soft: rgba(239, 68, 68, 0.15);
        --ho-radius: 12px;
        --ho-radius-sm: 8px;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }}

      /* Base layout & typography */
      body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
      [data-testid="stMarkdownContainer"], [data-testid="stText"], label,
      h1, h2, h3, h4, h5, h6, p {{
        color: var(--ho-text);
        font-family: inherit;
      }}

      [data-testid="stAppViewContainer"] {{
        background: var(--ho-bg);
      }}

      [data-testid="stHeader"] {{
        background: color-mix(in srgb, var(--ho-bg) 95%, transparent);
        border-bottom: 1px solid var(--ho-border-soft);
      }}

      [data-testid="stMainBlockContainer"] {{
        max-width: 1440px;
        padding: 1.5rem 2rem 2.5rem;
      }}

      /* Sidebar styling */
      [data-testid="stSidebar"] {{
        min-width: 260px;
        max-width: 280px;
      }}
      [data-testid="stSidebar"] > div:first-child {{
        background: var(--ho-sidebar);
        border-right: 1px solid var(--ho-border);
      }}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
        gap: 0.45rem;
      }}

      /* Brand Header */
      .ho-brand {{
        align-items: center;
        display: flex;
        gap: 0.75rem;
        margin: 0.2rem 0.1rem 1.25rem;
        padding-bottom: 0.85rem;
        border-bottom: 1px solid var(--ho-border-soft);
      }}
      .ho-brand-icon {{
        align-items: center;
        background: linear-gradient(135deg, #0EA5C9 0%, #14C8B8 100%);
        border-radius: 8px;
        color: #060F17;
        display: flex;
        font-weight: 850;
        font-size: 1.15rem;
        height: 36px;
        justify-content: center;
        width: 36px;
        box-shadow: 0 2px 6px rgba(14, 165, 201, 0.25);
      }}
      .ho-brand-text {{
        display: flex;
        flex-direction: column;
      }}
      .ho-brand-title {{
        color: var(--ho-text);
        font-size: 1.05rem;
        font-weight: 750;
        letter-spacing: -0.02em;
        display: flex;
        align-items: center;
        gap: 0.4rem;
      }}
      .ho-brand-badge {{
        background: rgba(14, 165, 201, 0.15);
        border: 1px solid rgba(14, 165, 201, 0.4);
        border-radius: 4px;
        color: var(--ho-primary);
        font-size: 0.65rem;
        font-weight: 700;
        padding: 1px 5px;
        letter-spacing: 0.04em;
      }}
      .ho-brand-subtitle {{
        color: var(--ho-muted);
        font-size: 0.74rem;
        margin-top: 1px;
      }}

      /* Sidebar navigation items */
      .ho-sidebar-group {{
        color: var(--ho-muted);
        font-size: 0.7rem;
        font-weight: 750;
        letter-spacing: 0.08em;
        margin: 1.1rem 0.15rem 0.35rem;
        text-transform: uppercase;
      }}
      [data-testid="stSidebar"] .stButton button {{
        font-size: 0.88rem;
        font-weight: 500;
        text-align: left;
        border-radius: var(--ho-radius-sm);
        padding: 0.55rem 0.85rem;
        transition: all 0.15s ease;
      }}
      [data-testid="stSidebar"] .stButton button[kind="secondary"] {{
        background: transparent;
        border: 1px solid transparent;
        border-left: 3px solid transparent;
        color: var(--ho-muted);
      }}
      [data-testid="stSidebar"] .stButton button[kind="secondary"]:hover {{
        background: var(--ho-surface);
        border-color: transparent;
        border-left: 3px solid var(--ho-border);
        color: var(--ho-text);
      }}
      [data-testid="stSidebar"] .stButton button[kind="primary"] {{
        background: var(--ho-surface-elevated) !important;
        border: 1px solid var(--ho-border) !important;
        border-left: 3px solid var(--ho-primary) !important;
        color: var(--ho-text) !important;
        font-weight: 650;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
      }}

      /* Sidebar Expanders & Admin */
      [data-testid="stSidebar"] [data-testid="stExpander"] {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius-sm);
        margin-bottom: 0.5rem;
      }}
      [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
        color: var(--ho-text);
        font-size: 0.84rem;
        font-weight: 600;
      }}
      [data-testid="stSidebar"] [data-testid="stSelectbox"] label {{
        font-size: 0.76rem;
        color: var(--ho-muted);
      }}

      /* Sidebar Footer */
      .ho-sidebar-footer {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius-sm);
        padding: 0.75rem 0.85rem;
        margin-top: 1.25rem;
      }}
      .ho-footer-tag {{
        color: var(--ho-muted);
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.35rem;
      }}
      .ho-footer-status {{
        display: flex;
        align-items: center;
        gap: 0.45rem;
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--ho-text);
      }}

      /* Header & Breadcrumb */
      .ho-page-header {{
        border-bottom: 1px solid var(--ho-border-soft);
        margin-bottom: 1.1rem;
        padding-bottom: 0.9rem;
      }}
      .ho-breadcrumb {{
        color: var(--ho-muted);
        font-size: 0.78rem;
        font-weight: 550;
        display: flex;
        align-items: center;
        gap: 0.35rem;
        margin-bottom: 0.35rem;
      }}
      .ho-breadcrumb-sep {{
        color: var(--ho-border);
      }}
      .ho-breadcrumb-current {{
        color: var(--ho-primary);
        font-weight: 600;
      }}
      .ho-header-row {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1.5rem;
        flex-wrap: wrap;
      }}
      .ho-header-left {{
        flex: 1;
        min-width: 280px;
      }}
      .ho-page-title {{
        color: var(--ho-text);
        font-size: 1.75rem;
        font-weight: 750;
        letter-spacing: -0.03em;
        line-height: 1.2;
        margin: 0;
      }}
      .ho-page-subtitle {{
        color: var(--ho-muted);
        font-size: 0.88rem;
        margin-top: 0.3rem;
        line-height: 1.4;
      }}
      .ho-header-right {{
        display: flex;
        align-items: center;
        gap: 0.65rem;
        flex-wrap: wrap;
      }}
      .ho-meta-pill {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius-sm);
        padding: 0.45rem 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.8rem;
      }}
      .ho-meta-pill-label {{
        color: var(--ho-muted);
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
      }}
      .ho-code-pill {{
        background: var(--ho-surface-elevated);
        border: 1px solid var(--ho-border);
        border-radius: 4px;
        color: var(--ho-primary);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.78rem;
        padding: 1px 6px;
      }}

      /* Status Dots & Badges */
      .ho-dot {{
        border-radius: 50%;
        display: inline-block;
        height: 7px;
        width: 7px;
      }}
      .ho-dot-success {{ background: var(--ho-success); box-shadow: 0 0 6px rgba(34, 197, 94, 0.45); }}
      .ho-dot-warning {{ background: var(--ho-warning); box-shadow: 0 0 6px rgba(245, 158, 11, 0.45); }}
      .ho-dot-error {{ background: var(--ho-error); box-shadow: 0 0 6px rgba(239, 68, 68, 0.45); }}
      .ho-dot-primary {{ background: var(--ho-primary); box-shadow: 0 0 6px rgba(14, 165, 201, 0.45); }}
      .ho-dot-neutral {{ background: var(--ho-muted); }}

      .ho-badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        border-radius: 6px;
        font-size: 0.76rem;
        font-weight: 600;
        padding: 0.25rem 0.55rem;
      }}
      .ho-badge-success {{ background: var(--ho-success-soft); border: 1px solid rgba(34, 197, 94, 0.3); color: var(--ho-success); }}
      .ho-badge-warning {{ background: var(--ho-warning-soft); border: 1px solid rgba(245, 158, 11, 0.3); color: var(--ho-warning); }}
      .ho-badge-error {{ background: var(--ho-error-soft); border: 1px solid rgba(239, 68, 68, 0.3); color: var(--ho-error); }}
      .ho-badge-primary {{ background: var(--ho-primary-soft); border: 1px solid rgba(14, 165, 201, 0.3); color: var(--ho-primary); }}
      .ho-badge-neutral {{ background: var(--ho-surface-elevated); border: 1px solid var(--ho-border); color: var(--ho-muted); }}

      /* Stepper Component */
      .ho-stepper-container {{
        margin-bottom: 1.15rem;
      }}
      .ho-stepper-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.65rem;
      }}
      @media (max-width: 960px) {{
        .ho-stepper-grid {{
          grid-template-columns: repeat(2, 1fr);
        }}
      }}
      @media (max-width: 580px) {{
        .ho-stepper-grid {{
          grid-template-columns: 1fr;
        }}
      }}
      .ho-step {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: 10px;
        padding: 0.75rem 0.85rem;
        transition: all 0.18s ease;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 72px;
      }}
      .ho-step-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.4rem;
      }}
      .ho-step-badge {{
        align-items: center;
        border-radius: 6px;
        display: flex;
        font-size: 0.72rem;
        font-weight: 750;
        height: 24px;
        justify-content: center;
        width: 24px;
      }}
      .ho-step-badge-complete {{
        background: var(--ho-success);
        color: #060F17;
      }}
      .ho-step-badge-active {{
        background: var(--ho-primary);
        color: #060F17;
      }}
      .ho-step-badge-pending {{
        background: var(--ho-surface-elevated);
        border: 1px solid var(--ho-border);
        color: var(--ho-muted);
      }}
      .ho-step-badge-error {{
        background: var(--ho-error);
        color: #FFFFFF;
      }}
      .ho-step-active {{
        background: var(--ho-surface-elevated);
        border-color: var(--ho-primary);
        box-shadow: 0 0 0 1px rgba(14, 165, 201, 0.25), 0 2px 8px rgba(14, 165, 201, 0.12);
      }}
      .ho-step-complete {{
        border-color: rgba(34, 197, 94, 0.35);
      }}
      .ho-step-error {{
        background: var(--ho-error-soft);
        border-color: var(--ho-error);
      }}
      .ho-step-title {{
        color: var(--ho-text);
        font-size: 0.82rem;
        font-weight: 700;
        line-height: 1.25;
      }}
      .ho-step-description {{
        color: var(--ho-muted);
        font-size: 0.7rem;
        line-height: 1.3;
        margin-top: 0.18rem;
      }}

      /* Summary Cards Component */
      .ho-summary-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.75rem;
        margin-bottom: 1.25rem;
      }}
      @media (max-width: 768px) {{
        .ho-summary-grid {{
          grid-template-columns: 1fr;
        }}
      }}
      .ho-summary-card {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: 10px;
        padding: 0.85rem 1.05rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-height: 78px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
      }}
      .ho-summary-label {{
        color: var(--ho-muted);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
      }}
      .ho-summary-val {{
        color: var(--ho-text);
        font-size: 1.02rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 0.45rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .ho-summary-sub {{
        color: var(--ho-muted);
        font-size: 0.73rem;
        margin-top: 0.2rem;
      }}

      /* Notification & Catalog Panel */
      .ho-catalog-banner {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius-sm);
        padding: 0.85rem 1.1rem;
        margin-bottom: 1.1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
      }}
      .ho-catalog-banner-info {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex: 1;
        min-width: 250px;
      }}
      .ho-catalog-icon {{
        font-size: 1.3rem;
        color: var(--ho-primary);
        display: flex;
        align-items: center;
      }}
      .ho-catalog-text {{
        font-size: 0.84rem;
        color: var(--ho-text);
        line-height: 1.35;
      }}
      .ho-catalog-sub {{
        font-size: 0.74rem;
        color: var(--ho-muted);
        margin-top: 1px;
      }}

      /* Forms & Input Elements */
      [data-testid="stForm"] {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border) !important;
        border-radius: var(--ho-radius);
        padding: {compact_spacing};
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.25);
      }}
      .ho-form-header {{
        border-bottom: 1px solid var(--ho-border-soft);
        padding-bottom: 0.75rem;
        margin-bottom: 1rem;
      }}
      .ho-form-title {{
        color: var(--ho-text);
        font-size: 1.05rem;
        font-weight: 750;
        letter-spacing: -0.01em;
        margin-bottom: 0.15rem;
      }}
      .ho-form-subtitle {{
        color: var(--ho-muted);
        font-size: 0.8rem;
      }}
      .ho-form-section-title {{
        color: var(--ho-primary);
        font-size: 0.75rem;
        font-weight: 750;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin: 0.85rem 0 0.45rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
      }}
      .ho-section-num {{
        background: var(--ho-primary-soft);
        border: 1px solid rgba(14, 165, 201, 0.3);
        border-radius: 4px;
        color: var(--ho-primary);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.65rem;
        height: 18px;
        width: 18px;
        font-weight: 800;
      }}

      /* Streamlit Input Theme Overrides - Strict Dark Surfaces */
      [data-baseweb="input"] > div,
      [data-baseweb="select"] > div,
      input, textarea,
      [data-testid="stDateInput"] input {{
        background: var(--ho-surface-elevated) !important;
        border-color: var(--ho-border) !important;
        color: var(--ho-text) !important;
        border-radius: 8px !important;
        font-size: 0.88rem !important;
        min-height: {input_height} !important;
      }}
      [data-baseweb="input"] > div:focus-within,
      [data-baseweb="select"] > div:focus-within,
      input:focus, textarea:focus {{
        border-color: var(--ho-primary) !important;
        box-shadow: 0 0 0 1px var(--ho-primary) !important;
      }}
      ::placeholder {{
        color: var(--ho-muted) !important;
        opacity: 0.85 !important;
      }}
      [data-baseweb="select"] [data-testid="stMarkdownContainer"] {{
        color: var(--ho-text) !important;
      }}
      label, [data-testid="stWidgetLabel"] p {{
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        color: var(--ho-text) !important;
        margin-bottom: 0.25rem !important;
      }}

      /* Multiselect Tag styling */
      [data-baseweb="tag"] {{
        background: rgba(14, 165, 201, 0.15) !important;
        border: 1px solid rgba(14, 165, 201, 0.35) !important;
        border-radius: 5px !important;
      }}
      [data-baseweb="tag"] span {{
        color: #E2F5FA !important;
        font-size: 0.78rem !important;
        font-weight: 550 !important;
      }}
      [data-baseweb="tag"] svg {{
        fill: var(--ho-primary) !important;
      }}

      /* Dropdown Menu & Popovers */
      [data-baseweb="popover"], [data-baseweb="menu"], ul[role="listbox"] {{
        background: var(--ho-surface-elevated) !important;
        border: 1px solid var(--ho-border) !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4) !important;
      }}
      li[role="option"] {{
        color: var(--ho-text) !important;
        font-size: 0.86rem !important;
      }}
      li[role="option"]:hover, li[aria-selected="true"] {{
        background: rgba(14, 165, 201, 0.18) !important;
        color: var(--ho-primary) !important;
      }}

      /* Buttons */
      button[kind="primary"],
      [data-testid="stForm"] button[kind="primary"],
      button[data-testid="stBaseButton-primary"] {{
        background: var(--ho-primary) !important;
        border: 1px solid var(--ho-primary) !important;
        color: #060F17 !important;
        font-weight: 700 !important;
        font-size: 0.94rem !important;
        border-radius: var(--ho-radius-sm) !important;
        padding: 0.6rem 1.25rem !important;
        box-shadow: 0 2px 6px rgba(14, 165, 201, 0.25) !important;
        transition: all 0.18s ease !important;
      }}
      button[kind="primary"]:hover,
      [data-testid="stForm"] button[kind="primary"]:hover,
      button[data-testid="stBaseButton-primary"]:hover {{
        background: var(--ho-primary-hover) !important;
        border-color: var(--ho-primary-hover) !important;
        box-shadow: 0 3px 12px rgba(14, 165, 201, 0.35) !important;
        color: #060F17 !important;
      }}
      button[kind="secondary"],
      button[data-testid="stBaseButton-secondary"] {{
        background: var(--ho-surface-elevated) !important;
        border: 1px solid var(--ho-border) !important;
        color: var(--ho-text) !important;
        font-weight: 600 !important;
        border-radius: var(--ho-radius-sm) !important;
        font-size: 0.86rem !important;
        transition: all 0.15s ease !important;
      }}
      button[kind="secondary"]:hover,
      button[data-testid="stBaseButton-secondary"]:hover {{
        border-color: var(--ho-primary) !important;
        color: var(--ho-primary) !important;
        background: var(--ho-surface) !important;
      }}

      /* Context Panel (Session Sidebar) */
      .ho-context-card {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius);
        padding: 1.1rem;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
      }}
      .ho-context-header {{
        border-bottom: 1px solid var(--ho-border-soft);
        padding-bottom: 0.65rem;
        margin-bottom: 0.85rem;
      }}
      .ho-context-title {{
        color: var(--ho-text);
        font-size: 0.98rem;
        font-weight: 750;
      }}
      .ho-context-caption {{
        color: var(--ho-muted);
        font-size: 0.74rem;
        margin-top: 1px;
      }}
      .ho-context-section {{
        padding: 0.65rem 0;
        border-bottom: 1px solid var(--ho-border-soft);
      }}
      .ho-context-section:last-child {{
        border-bottom: none;
        padding-bottom: 0.2rem;
      }}
      .ho-context-section-label {{
        color: var(--ho-muted);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 0.4rem;
      }}
      .ho-context-meta-text {{
        color: var(--ho-text);
        font-size: 0.84rem;
        font-weight: 600;
        margin-top: 0.25rem;
      }}
      .ho-context-subtext {{
        color: var(--ho-muted);
        font-size: 0.74rem;
        margin-top: 0.2rem;
      }}
      .ho-context-tip {{
        color: var(--ho-muted);
        font-size: 0.74rem;
        line-height: 1.35;
        margin-top: 0.3rem;
      }}
      .ho-file-box {{
        background: var(--ho-surface-elevated);
        border: 1px solid var(--ho-border);
        border-radius: 6px;
        padding: 0.45rem 0.65rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.78rem;
        color: var(--ho-primary);
        word-break: break-all;
      }}

      /* Job & Task Area */
      .ho-job-section {{
        margin-top: 2rem;
      }}
      .ho-job-heading {{
        align-items: center;
        border-bottom: 1px solid var(--ho-border-soft);
        display: flex;
        justify-content: space-between;
        margin-bottom: 1rem;
        padding-bottom: 0.65rem;
      }}
      .ho-job-title {{
        color: var(--ho-text);
        font-size: 1.05rem;
        font-weight: 750;
        letter-spacing: -0.01em;
      }}
      .ho-empty-job-card {{
        background: var(--ho-surface);
        border: 1px dashed var(--ho-border);
        border-radius: var(--ho-radius);
        padding: 1.5rem;
        display: flex;
        align-items: center;
        gap: 1rem;
      }}
      .ho-empty-icon {{
        font-size: 1.8rem;
        color: var(--ho-muted);
        opacity: 0.6;
      }}
      .ho-empty-title {{
        color: var(--ho-text);
        font-size: 0.92rem;
        font-weight: 650;
      }}
      .ho-empty-desc {{
        color: var(--ho-muted);
        font-size: 0.8rem;
        margin-top: 0.2rem;
      }}
      .ho-job-card {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: var(--ho-radius);
        padding: 1.1rem 1.25rem;
        margin-bottom: 1rem;
      }}
      .ho-job-card-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.75rem;
      }}
      .ho-job-name {{
        color: var(--ho-text);
        font-size: 1rem;
        font-weight: 700;
      }}
      .ho-job-time {{
        color: var(--ho-muted);
        font-size: 0.75rem;
      }}

      /* Terminal style code block for logs */
      [data-testid="stExpander"] {{
        background: var(--ho-surface);
        border: 1px solid var(--ho-border);
        border-radius: 10px;
      }}
      [data-testid="stExpander"] pre {{
        background: #080F18 !important;
        border: 1px solid var(--ho-border) !important;
        border-radius: 8px !important;
        color: #38BDF8 !important;
        font-size: 0.78rem !important;
      }}

      /* Alert callouts */
      [data-testid="stAlert"] {{
        background: var(--ho-surface-elevated) !important;
        border: 1px solid var(--ho-border) !important;
        border-radius: 8px !important;
      }}
    </style>
    """)


def render_header(
    eyebrow: str,
    title: str,
    description: str,
    output_name: str,
    auth_state=None,
) -> None:
    lms_connected = bool(auth_state and getattr(auth_state, "token", ""))
    if lms_connected:
        email = getattr(auth_state, "email", "") or "LMS Sẵn sàng"
        lms_badge = (
            f'<div class="ho-meta-pill">'
            f'<span class="ho-dot ho-dot-success"></span>'
            f'<span class="ho-meta-pill-label">LMS</span>'
            f'<span style="color:var(--ho-success);font-weight:600;font-size:0.78rem;">{email}</span>'
            f'</div>'
        )
    else:
        lms_badge = (
            f'<div class="ho-meta-pill">'
            f'<span class="ho-dot ho-dot-warning"></span>'
            f'<span class="ho-meta-pill-label">LMS</span>'
            f'<span style="color:var(--ho-warning);font-weight:600;font-size:0.78rem;">Chưa kết nối</span>'
            f'</div>'
        )

    st.markdown(
        f"""
        <div class="ho-page-header">
          <div class="ho-breadcrumb">
            <span>Không gian làm việc</span>
            <span class="ho-breadcrumb-sep">/</span>
            <span class="ho-breadcrumb-current">{title}</span>
          </div>
          <div class="ho-header-row">
            <div class="ho-header-left">
              <h1 class="ho-page-title">{title}</h1>
              <p class="ho-page-subtitle">{description}</p>
            </div>
            <div class="ho-header-right">
              <div class="ho-meta-pill">
                <span class="ho-meta-pill-label">Tệp xuất</span>
                <code class="ho-code-pill">{output_name}</code>
              </div>
              {lms_badge}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
