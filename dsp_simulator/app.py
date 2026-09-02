"""
DSP 瞄捕状态机模拟器
===================================
基于 Streamlit + ECharts 的 Web 界面，用于演示 DSP 状态机（S0-S5）的状态流转过程。

作者：AI Assistant
日期：2026/04/14
"""

import streamlit as st
import graphviz
from datetime import datetime

from common.definitions import (
    PACKET_HIGHLIGHT_GROUPS,
    PHASE_LABELS,
    SLOT_PACKET_SPECS,
    STATE_DESCRIPTIONS,
    STATE_NAMES,
    STATE_NAMES_CN,
    STATE_TRANSITIONS,
    UPLINK_MODE,
)


# ============================================================
# Streamlit 页面配置
# ============================================================

st.set_page_config(
    page_title="DSP 瞄捕状态机模拟器",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CSS 样式
# ============================================================

st.markdown("""
<style>
    :root {
        color-scheme: light;
        --surface: #FFFFFF;
        --surface-muted: #F5F5F7;
        --surface-raised: rgba(255, 255, 255, 0.86);
        --border: #D9D9DE;
        --border-strong: #C7C7CC;
        --text: #1D1D1F;
        --text-secondary: #6E6E73;
        --blue: #0071E3;
        --blue-soft: #EAF3FF;
        --green: #248A3D;
        --green-soft: #EAF7ED;
        --orange: #C35A00;
        --orange-soft: #FFF3E8;
        --red: #D70015;
        --glass-clear: rgba(255, 255, 255, 0.46);
        --glass-regular: rgba(255, 255, 255, 0.66);
        --glass-thick: rgba(255, 255, 255, 0.82);
        --glass-stroke: rgba(255, 255, 255, 0.82);
        --glass-shadow: 0 18px 48px rgba(36, 46, 66, 0.12),
                        0 2px 10px rgba(36, 46, 66, 0.06),
                        inset 0 1px 0 rgba(255, 255, 255, 0.96);
        --glass-shadow-small: 0 8px 24px rgba(36, 46, 66, 0.1),
                              inset 0 1px 0 rgba(255, 255, 255, 0.92);
        --glass-blur: blur(30px) saturate(185%);
        --glass-radius: 22px;
        --control-radius: 14px;
        --spring-out: cubic-bezier(0.22, 0.78, 0.18, 1);
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    #MainMenu,
    footer,
    [data-testid="stToolbar"] {visibility: hidden;}

    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #EAF1F8 0%, #F4F6FA 38%, #F7F3F7 72%, #EEF4F6 100%);
        background-attachment: fixed;
        color: var(--text);
    }

    [data-testid="stHeader"] {
        background: rgba(238, 243, 248, 0.48);
        backdrop-filter: blur(34px) saturate(180%);
        -webkit-backdrop-filter: blur(34px) saturate(180%);
    }

    .stMainBlockContainer {
        max-width: 1480px;
        padding-top: 1.25rem;
        padding-bottom: 3rem;
    }

    [data-testid="stExpander"] {
        overflow: hidden;
        background: var(--glass-regular);
        border: 1px solid var(--glass-stroke);
        border-radius: 16px;
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(22px) saturate(170%);
        -webkit-backdrop-filter: blur(22px) saturate(170%);
    }

    [data-testid="stMarkdownContainer"] table {
        background: var(--surface);
        border-radius: 8px;
        overflow: hidden;
    }

    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li {
        line-height: 1.55;
    }

    h1, h2, h3, h4, h5, h6 {
        color: var(--text);
        letter-spacing: 0;
    }

    h3 {
        font-size: 1.05rem !important;
        line-height: 1.3 !important;
        font-weight: 650 !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.75rem !important;
    }

    .app-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 20px;
        min-height: 64px;
        margin-bottom: 18px;
    }

    .app-brand {
        min-width: 0;
    }

    .app-title {
        margin: 0;
        color: var(--text);
        font-size: 1.9rem;
        line-height: 1.2;
        font-weight: 700;
        letter-spacing: 0;
    }

    .app-subtitle {
        margin-top: 5px;
        color: var(--text-secondary);
        font-size: 0.84rem;
        line-height: 1.4;
    }

    .header-status {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        flex-wrap: wrap;
        gap: 8px;
    }

    .status-chip {
        display: inline-flex;
        align-items: center;
        min-height: 34px;
        gap: 7px;
        padding: 5px 12px;
        border: 1px solid var(--glass-stroke);
        border-radius: 999px;
        background: var(--glass-clear);
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(24px) saturate(180%);
        -webkit-backdrop-filter: blur(24px) saturate(180%);
        color: var(--text-secondary);
        font-size: 0.78rem;
        white-space: nowrap;
        transition: transform 220ms var(--spring-out), background-color 220ms ease-out,
                    box-shadow 220ms ease-out;
    }

    .status-chip:hover {
        transform: translateY(-1px);
        background: rgba(255, 255, 255, 0.62);
        box-shadow: 0 12px 28px rgba(36, 46, 66, 0.12),
                    inset 0 1px 0 rgba(255, 255, 255, 0.98);
    }

    .status-chip strong {
        color: var(--text);
        font-weight: 650;
    }

    .status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--blue);
        box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.12);
    }

    .status-dot.tone-green {
        background: var(--green);
        box-shadow: 0 0 0 3px rgba(36, 138, 61, 0.12);
    }

    .status-dot.tone-orange {
        background: var(--orange);
        box-shadow: 0 0 0 3px rgba(195, 90, 0, 0.12);
    }

    .section-heading {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin: 0 0 10px;
    }

    .section-title {
        color: var(--text);
        font-size: 1.05rem;
        font-weight: 650;
        line-height: 1.3;
    }

    .section-meta {
        color: var(--text-secondary);
        font-size: 0.76rem;
        white-space: nowrap;
    }

    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button {
        min-height: 2.55rem;
        border-radius: 8px;
        font-weight: 600;
        letter-spacing: 0;
        transition: transform 100ms ease-out, background-color 140ms ease-out,
                    border-color 140ms ease-out, box-shadow 140ms ease-out;
    }

    div[data-testid="stButton"] button:hover,
    div[data-testid="stDownloadButton"] button:hover {
        border-color: var(--border-strong);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.07);
    }

    div[data-testid="stButton"] button:active,
    div[data-testid="stDownloadButton"] button:active {
        transform: scale(0.985);
        box-shadow: none;
    }

    div[data-testid="stButton"] button:focus-visible,
    div[data-testid="stDownloadButton"] button:focus-visible,
    [data-baseweb="select"]:focus-within {
        outline: 3px solid rgba(0, 113, 227, 0.28);
        outline-offset: 2px;
    }

    div[data-testid="stButton"] button[kind="primary"] {
        background: var(--blue) !important;
        border-color: var(--blue) !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 8px rgba(0, 113, 227, 0.2);
    }

    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #0068D1 !important;
        border-color: #0068D1 !important;
        box-shadow: 0 3px 12px rgba(0, 113, 227, 0.26);
    }

    div[data-testid="stButton"] button[kind="primary"]:active {
        background: #005DBB !important;
        border-color: #005DBB !important;
        box-shadow: none;
    }

    .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"],
    .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"] {
        background: var(--red) !important;
        border-color: var(--red) !important;
        box-shadow: 0 2px 8px rgba(215, 0, 21, 0.18);
    }

    .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"]:hover,
    .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #BE0013 !important;
        border-color: #BE0013 !important;
    }

    .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"]:active,
    .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"]:active {
        background: #A60010 !important;
        border-color: #A60010 !important;
    }

    .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"] {
        background: var(--green) !important;
        border-color: var(--green) !important;
        box-shadow: 0 2px 8px rgba(36, 138, 61, 0.18);
    }

    .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #1F7A35 !important;
        border-color: #1F7A35 !important;
    }

    .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"]:active {
        background: #19672C !important;
        border-color: #19672C !important;
    }

    .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"] {
        background: var(--orange) !important;
        border-color: var(--orange) !important;
        box-shadow: 0 2px 8px rgba(195, 90, 0, 0.18);
    }

    .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #AB4F00 !important;
        border-color: #AB4F00 !important;
    }

    .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"]:active {
        background: #914300 !important;
        border-color: #914300 !important;
    }

    [data-baseweb="select"] > div {
        border-radius: 8px;
        border-color: var(--border);
        background: var(--surface);
    }

    [data-testid="stAlert"] {
        border-radius: 8px;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--border) !important;
        border-radius: 8px !important;
        background: var(--surface);
        box-shadow: 0 3px 14px rgba(0, 0, 0, 0.04);
    }

    .stTabs [data-baseweb="tab-list"] {
        width: fit-content;
        gap: 3px;
        padding: 4px;
        border-radius: 8px;
        background: #E8E8ED;
    }

    .stTabs [data-baseweb="tab"] {
        min-width: 138px;
        height: 36px;
        padding: 0 14px;
        border-radius: 6px;
        color: var(--text-secondary);
        font-size: 0.84rem;
        font-weight: 600;
        transition: color 140ms ease-out, background-color 140ms ease-out,
                    box-shadow 140ms ease-out, transform 100ms ease-out;
    }

    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text);
        background: rgba(255, 255, 255, 0.58);
    }

    .stTabs [data-baseweb="tab"]:active {
        transform: scale(0.98);
    }

    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: var(--text);
        background: var(--surface);
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
    }

    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {
        display: none;
    }

    .stTabs [data-baseweb="tab-panel"] {
        padding-top: 1.2rem;
    }

    .control-heading {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
    }

    .control-title {
        color: var(--text);
        font-size: 0.95rem;
        font-weight: 650;
    }

    .control-meta {
        color: var(--text-secondary);
        font-size: 0.74rem;
    }

    .state-description {
        margin-top: 8px;
        color: var(--text-secondary);
        font-size: 0.78rem;
        line-height: 1.5;
    }

    .topology-legend {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px 24px;
        padding: 10px 12px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--surface);
    }

    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        color: var(--text-secondary);
        font-size: 0.78rem;
    }

    .legend-swatch {
        width: 22px;
        height: 3px;
        border-radius: 2px;
        background: var(--blue);
    }

    .legend-swatch.dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }

    .legend-swatch.current { background: var(--green); }
    .legend-swatch.other { background: #AEAEB2; }
    .legend-swatch.error { background: var(--red); }
    .legend-swatch.restore { background: var(--green); }

    .status-card {
        display: grid;
        grid-template-columns: minmax(140px, 0.8fr) minmax(0, 1.2fr);
        gap: 0;
        overflow: hidden;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        color: var(--text);
        box-shadow: 0 3px 14px rgba(0, 0, 0, 0.04);
    }

    .state-primary {
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-height: 142px;
        padding: 18px;
        border-right: 1px solid var(--border);
    }

    .state-label,
    .link-label {
        color: var(--text-secondary);
        font-size: 0.74rem;
        line-height: 1.3;
    }

    .state-code {
        margin-top: 4px;
        color: var(--blue);
        font-size: 2.1rem;
        line-height: 1;
        font-weight: 720;
    }

    .state-primary.tone-green .state-code { color: var(--green); }
    .state-primary.tone-orange .state-code { color: var(--orange); }

    .state-name {
        margin-top: 6px;
        color: var(--text);
        font-size: 0.96rem;
        font-weight: 600;
    }

    .link-status-list {
        display: grid;
        grid-template-rows: 1fr 1fr;
    }

    .link-status {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 13px 16px;
    }

    .link-status + .link-status {
        border-top: 1px solid var(--border);
    }

    .link-name {
        margin-top: 2px;
        color: var(--text);
        font-size: 0.9rem;
        font-weight: 600;
    }

    .link-badge {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        padding: 3px 7px;
        border: 1px solid var(--border);
        border-radius: 6px;
        color: var(--text-secondary);
        background: var(--surface-muted);
        font-size: 0.72rem;
        font-weight: 650;
        white-space: nowrap;
    }

    .link-status.active.mmwave .link-badge {
        color: #0057A8;
        border-color: #B9D8FA;
        background: var(--blue-soft);
    }

    .link-status.active.thz .link-badge {
        color: #8A3F00;
        border-color: #F3C9A6;
        background: var(--orange-soft);
    }

    .log-console {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 12px;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        font-size: 12px;
        color: var(--text);
        height: 280px;
        overflow-y: auto;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.025);
    }

    .log-entry {
        display: grid;
        grid-template-columns: 96px 54px 18px 54px minmax(120px, 1fr);
        gap: 5px;
        align-items: baseline;
        padding: 7px 4px;
        border-bottom: 1px solid #ECECF0;
        line-height: 1.35;
    }

    .slot-panel {
        height: 620px;
        overflow-y: auto;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 12px;
        box-shadow: 0 3px 14px rgba(0, 0, 0, 0.04);
        scrollbar-color: #C7C7CC transparent;
    }

    .slot-panel-header {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border);
    }

    .slot-panel-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: var(--text);
        line-height: 1.3;
    }

    .slot-panel-state {
        white-space: nowrap;
        font-size: 0.82rem;
        font-weight: 700;
        color: #0057A8;
        background: var(--blue-soft);
        border: 1px solid #B9D8FA;
        border-radius: 6px;
        padding: 4px 9px;
    }

    .slot-panel-state.tone-green {
        color: #176B2C;
        background: var(--green-soft);
        border-color: #B8DEBF;
    }

    .slot-panel-state.tone-orange {
        color: #8A3F00;
        background: var(--orange-soft);
        border-color: #F3C9A6;
    }

    .slot-summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-bottom: 12px;
    }

    .slot-summary-item {
        background: var(--surface-muted);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 8px;
    }

    .slot-summary-label {
        font-size: 0.72rem;
        color: var(--text-secondary);
        margin-bottom: 3px;
    }

    .slot-summary-value {
        font-size: 0.9rem;
        font-weight: 700;
        color: var(--text);
    }

    .slot-packet {
        border: 1px solid var(--border);
        border-left: 3px solid var(--blue);
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 10px;
        background: var(--surface);
        transition: border-color 140ms ease-out, background-color 140ms ease-out,
                    box-shadow 140ms ease-out, transform 100ms ease-out;
    }

    .slot-packet:hover {
        border-color: var(--border-strong);
        transform: translateY(-1px);
    }

    .slot-packet.selected {
        border-color: #E0A56E;
        border-left-color: var(--orange);
        background: var(--orange-soft);
        box-shadow: 0 0 0 2px rgba(195, 90, 0, 0.1);
    }

    .slot-packet-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
    }

    .slot-packet-title {
        font-size: 0.95rem;
        font-weight: 700;
        color: var(--text);
    }

    .slot-phase {
        font-family: "Consolas", "Monaco", monospace;
        font-size: 0.75rem;
        font-weight: 700;
        color: #0057A8;
        background: var(--blue-soft);
        border: 1px solid #B9D8FA;
        border-radius: 6px;
        padding: 2px 7px;
        white-space: nowrap;
    }

    .slot-route {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 6px;
        align-items: center;
        margin: 8px 0;
    }

    .route-node {
        min-width: 0;
        background: var(--surface-muted);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 6px 7px;
        font-size: 0.78rem;
        font-weight: 700;
        color: var(--text);
        text-align: center;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }

    .route-source {
        border-color: #B9D8FA;
        background: var(--blue-soft);
    }

    .route-target {
        border-color: #B8DEBF;
        background: var(--green-soft);
    }

    .route-arrow {
        color: var(--orange);
        font-weight: 800;
        font-size: 1rem;
    }

    .slot-meta {
        font-size: 0.78rem;
        color: var(--text-secondary);
        line-height: 1.45;
        margin: 3px 0;
    }

    .slot-meta strong {
        color: var(--text);
    }

    .field-list {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin: 7px 0;
    }

    .field-pill {
        font-family: "Consolas", "Monaco", monospace;
        font-size: 0.72rem;
        color: #0057A8;
        background: var(--blue-soft);
        border: 1px solid #B9D8FA;
        border-radius: 5px;
        padding: 2px 5px;
    }

    .slot-purpose {
        font-size: 0.78rem;
        color: #176B2C;
        line-height: 1.45;
        background: var(--green-soft);
        border: 1px solid #B8DEBF;
        border-radius: 6px;
        padding: 6px 8px;
        margin-top: 7px;
    }

    /* Liquid Glass functional layer */
    @keyframes glass-materialize {
        from {
            opacity: 0;
            transform: translateY(8px) scale(0.985);
            filter: blur(5px);
        }
        to {
            opacity: 1;
            transform: translateY(0) scale(1);
            filter: blur(0);
        }
    }

    .status-card,
    [data-testid="stVerticalBlockBorderWrapper"],
    .stTabs [data-baseweb="tab-list"],
    iframe[title="streamlit.components.v1.html"] {
        animation: glass-materialize 420ms var(--spring-out) both;
    }

    .status-card {
        overflow: hidden;
        background: var(--glass-regular);
        border: 1px solid var(--glass-stroke);
        border-radius: var(--glass-radius);
        box-shadow: var(--glass-shadow);
        backdrop-filter: var(--glass-blur);
        -webkit-backdrop-filter: var(--glass-blur);
    }

    .state-primary {
        border-right-color: rgba(125, 125, 130, 0.18);
        background: linear-gradient(145deg, rgba(255, 255, 255, 0.38), rgba(255, 255, 255, 0.08));
    }

    .link-status + .link-status {
        border-top-color: rgba(125, 125, 130, 0.18);
    }

    .link-badge,
    .slot-panel-state {
        border-radius: 999px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        overflow: hidden;
        background: var(--glass-regular);
        border: 1px solid var(--glass-stroke) !important;
        border-radius: var(--glass-radius) !important;
        box-shadow: var(--glass-shadow);
        backdrop-filter: var(--glass-blur);
        -webkit-backdrop-filter: var(--glass-blur);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 5px;
        padding: 6px;
        border: 1px solid var(--glass-stroke);
        border-radius: 999px;
        background: var(--glass-clear);
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(26px) saturate(185%);
        -webkit-backdrop-filter: blur(26px) saturate(185%);
    }

    .stTabs [data-baseweb="tab"] {
        height: 40px;
        border-radius: 999px;
        transition: color 220ms ease-out, background-color 260ms var(--spring-out),
                    box-shadow 260ms var(--spring-out), transform 140ms var(--spring-out);
    }

    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(255, 255, 255, 0.46);
        transform: translateY(-1px);
    }

    .stTabs [data-baseweb="tab"]:active {
        transform: scale(0.96);
    }

    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: rgba(255, 255, 255, 0.82);
        box-shadow: 0 6px 16px rgba(36, 46, 66, 0.12),
                    inset 0 1px 0 rgba(255, 255, 255, 1),
                    inset 0 -1px 0 rgba(125, 125, 130, 0.08);
    }

    .stTabs [data-baseweb="tab-panel"] {
        animation: glass-materialize 360ms var(--spring-out) both;
    }

    [data-baseweb="select"] > div {
        min-height: 44px;
        border: 1px solid var(--glass-stroke);
        border-radius: var(--control-radius);
        background: var(--glass-regular);
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(22px) saturate(170%);
        -webkit-backdrop-filter: blur(22px) saturate(170%);
        transition: transform 160ms var(--spring-out), box-shadow 220ms ease-out;
    }

    [data-baseweb="select"] > div:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 28px rgba(36, 46, 66, 0.13),
                    inset 0 1px 0 rgba(255, 255, 255, 0.96);
    }

    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button {
        position: relative;
        isolation: isolate;
        overflow: hidden;
        min-height: 44px;
        border: 1px solid var(--glass-stroke);
        border-radius: var(--control-radius);
        background: var(--glass-regular);
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(20px) saturate(175%);
        -webkit-backdrop-filter: blur(20px) saturate(175%);
        transition: transform 180ms var(--spring-out), box-shadow 220ms ease-out,
                    background 220ms ease-out, border-color 220ms ease-out;
    }

    div[data-testid="stButton"] button::after,
    div[data-testid="stDownloadButton"] button::after {
        content: "";
        position: absolute;
        z-index: -1;
        inset: 0;
        background: linear-gradient(155deg, rgba(255, 255, 255, 0.72) 0%, rgba(255, 255, 255, 0.12) 45%, rgba(255, 255, 255, 0.3) 100%);
        opacity: 0.52;
        pointer-events: none;
        transition: opacity 220ms ease-out;
    }

    div[data-testid="stButton"] button:hover,
    div[data-testid="stDownloadButton"] button:hover {
        transform: translateY(-2px) scale(1.008);
        box-shadow: 0 15px 32px rgba(36, 46, 66, 0.16),
                    inset 0 1px 0 rgba(255, 255, 255, 1);
    }

    div[data-testid="stButton"] button:hover::after,
    div[data-testid="stDownloadButton"] button:hover::after {
        opacity: 0.82;
    }

    div[data-testid="stButton"] button:active,
    div[data-testid="stDownloadButton"] button:active {
        transform: translateY(0) scale(0.965);
        box-shadow: 0 3px 10px rgba(36, 46, 66, 0.1),
                    inset 0 2px 5px rgba(36, 46, 66, 0.08);
        transition-duration: 90ms;
    }

    div[data-testid="stButton"] button[kind="primary"] {
        border-color: rgba(255, 255, 255, 0.72) !important;
        border-radius: var(--control-radius);
        background: linear-gradient(180deg, rgba(20, 132, 255, 0.96), rgba(0, 99, 226, 0.94)) !important;
        box-shadow: 0 10px 24px rgba(0, 113, 227, 0.26),
                    inset 0 1px 0 rgba(255, 255, 255, 0.44),
                    inset 0 -1px 0 rgba(0, 64, 150, 0.2);
    }

    .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"],
    .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(180deg, rgba(238, 32, 52, 0.96), rgba(196, 0, 20, 0.94)) !important;
        box-shadow: 0 10px 24px rgba(215, 0, 21, 0.23),
                    inset 0 1px 0 rgba(255, 255, 255, 0.4);
    }

    .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(180deg, rgba(52, 164, 76, 0.96), rgba(27, 122, 48, 0.94)) !important;
        box-shadow: 0 10px 24px rgba(36, 138, 61, 0.22),
                    inset 0 1px 0 rgba(255, 255, 255, 0.4);
    }

    .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(180deg, rgba(225, 112, 20, 0.96), rgba(174, 74, 0, 0.94)) !important;
        box-shadow: 0 10px 24px rgba(195, 90, 0, 0.22),
                    inset 0 1px 0 rgba(255, 255, 255, 0.4);
    }

    iframe[title="streamlit.components.v1.html"] {
        overflow: hidden;
        border: 1px solid var(--glass-stroke) !important;
        border-radius: 24px;
        background: rgba(255, 255, 255, 0.58);
        box-shadow: var(--glass-shadow);
    }

    .slot-panel {
        background: var(--glass-thick);
        border: 1px solid var(--glass-stroke);
        border-radius: 24px;
        box-shadow: var(--glass-shadow);
        backdrop-filter: blur(24px) saturate(160%);
        -webkit-backdrop-filter: blur(24px) saturate(160%);
    }

    .slot-summary-item {
        background: rgba(245, 245, 247, 0.78);
        border-color: rgba(125, 125, 130, 0.14);
        border-radius: 14px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.78);
    }

    .slot-packet {
        border-color: rgba(125, 125, 130, 0.17);
        border-left-color: var(--blue);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.86);
        box-shadow: 0 4px 14px rgba(36, 46, 66, 0.05),
                    inset 0 1px 0 rgba(255, 255, 255, 0.9);
        transition: transform 220ms var(--spring-out), box-shadow 220ms ease-out,
                    border-color 220ms ease-out, background-color 220ms ease-out;
    }

    .slot-packet:hover {
        transform: translateY(-2px) scale(1.004);
        box-shadow: 0 12px 24px rgba(36, 46, 66, 0.1),
                    inset 0 1px 0 rgba(255, 255, 255, 1);
    }

    .slot-packet.selected {
        background: rgba(255, 245, 232, 0.9);
        box-shadow: 0 10px 26px rgba(195, 90, 0, 0.14),
                    inset 0 1px 0 rgba(255, 255, 255, 0.92);
    }

    .slot-summary-item,
    .route-node,
    .slot-phase,
    .field-pill,
    .slot-purpose {
        border-radius: 12px;
    }

    .log-console,
    .topology-legend,
    [data-testid="stAlert"] {
        background: var(--glass-thick);
        border: 1px solid var(--glass-stroke);
        border-radius: 20px;
        box-shadow: var(--glass-shadow-small);
        backdrop-filter: blur(22px) saturate(160%);
        -webkit-backdrop-filter: blur(22px) saturate(160%);
    }

    /* Apple.com composition: content first, one glass control layer */
    [data-testid="stHeader"] {
        display: none;
    }

    [data-testid="stAppViewContainer"] {
        background: #FFFFFF;
    }

    .stMainBlockContainer {
        max-width: 1440px;
        padding-top: 0;
        padding-bottom: 5rem;
    }

    .product-nav {
        position: relative;
        z-index: 1000;
        width: 100vw;
        height: 48px;
        margin-top: -16px;
        margin-left: calc(50% - 50vw);
        background: rgba(250, 250, 252, 0.96);
        border-bottom: 1px solid rgba(0, 0, 0, 0.06);
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
    }

    .product-nav-inner {
        width: min(1280px, calc(100% - 64px));
        height: 100%;
        margin: 0 auto;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 24px;
    }

    .product-name {
        color: #1D1D1F;
        font-size: 0.94rem;
        line-height: 1;
        font-weight: 650;
        letter-spacing: 0;
    }

    .product-nav-status {
        display: flex;
        align-items: center;
        gap: 18px;
        color: #6E6E73;
        font-size: 0.74rem;
        line-height: 1;
    }

    .product-nav-status span {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        white-space: nowrap;
    }

    .product-nav-status .status-dot {
        display: inline-block;
        flex: 0 0 auto;
        width: 6px;
        height: 6px;
        box-shadow: none;
    }

    .product-hero {
        max-width: 980px;
        margin: 0 auto;
        padding: 52px 24px 30px;
        text-align: center;
    }

    .hero-eyebrow {
        margin-bottom: 10px;
        color: #1D1D1F;
        font-size: 1.08rem;
        line-height: 1.3;
        font-weight: 600;
        letter-spacing: 0;
        animation: hero-reveal 500ms var(--spring-out) both;
    }

    .hero-title {
        margin: 0;
        color: #1D1D1F;
        font-size: 3.65rem;
        line-height: 1.04;
        font-weight: 700;
        letter-spacing: 0;
        animation: hero-reveal 540ms 40ms var(--spring-out) both;
    }

    .hero-lead {
        max-width: 760px;
        margin: 18px auto 0;
        color: #6E6E73;
        font-size: 1.16rem;
        line-height: 1.5;
        font-weight: 400;
        letter-spacing: 0;
        animation: hero-reveal 560ms 80ms var(--spring-out) both;
    }

    .hero-facts {
        display: inline-grid;
        grid-template-columns: repeat(3, minmax(180px, 1fr));
        margin-top: 26px;
        animation: hero-reveal 580ms 120ms var(--spring-out) both;
    }

    .hero-fact {
        min-width: 0;
        padding: 0 30px;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .hero-fact + .hero-fact {
        border-left: 1px solid #D2D2D7;
    }

    .hero-fact span,
    .hero-fact small {
        color: #86868B;
        font-size: 0.74rem;
        line-height: 1.35;
        font-weight: 500;
    }

    .hero-fact strong {
        max-width: 230px;
        margin: 5px 0 4px;
        color: #1D1D1F;
        font-size: 1.05rem;
        line-height: 1.25;
        font-weight: 650;
        overflow-wrap: anywhere;
    }

    .product-hero.tone-green .hero-fact:first-child strong { color: #248A3D; }
    .product-hero.tone-orange .hero-fact:first-child strong { color: #C35A00; }
    .product-hero.tone-blue .hero-fact:first-child strong { color: #0071E3; }

    @keyframes hero-reveal {
        from {
            opacity: 0;
            transform: translateY(14px);
            filter: blur(7px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
            filter: blur(0);
        }
    }

    .st-key-state_control_dock {
        max-width: 940px;
        margin: 0 auto;
        padding: 16px 18px 18px;
        overflow: hidden;
        background: rgba(246, 246, 248, 0.72);
        border: 1px solid rgba(255, 255, 255, 0.92) !important;
        border-radius: 26px !important;
        box-shadow: 0 16px 44px rgba(36, 46, 66, 0.11),
                    inset 0 1px 0 rgba(255, 255, 255, 1),
                    inset 0 -1px 0 rgba(0, 0, 0, 0.04);
        backdrop-filter: blur(32px) saturate(180%);
        -webkit-backdrop-filter: blur(32px) saturate(180%);
        animation: dock-materialize 420ms 140ms var(--spring-out) both;
    }

    @keyframes dock-materialize {
        from { opacity: 0; transform: translateY(12px) scale(0.985); filter: blur(8px); }
        to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
    }

    .st-key-state_control_dock .control-heading {
        margin: 0 2px 10px;
    }

    .st-key-state_control_dock .control-title {
        font-size: 0.86rem;
        font-weight: 650;
    }

    .st-key-state_control_dock .control-meta,
    .st-key-state_control_dock [data-testid="stCaptionContainer"] {
        color: #86868B;
        font-size: 0.72rem;
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"] {
        min-height: 44px;
        border: 0 !important;
        border-radius: 999px;
        background: #0071E3 !important;
        box-shadow: none;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
        transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1),
                    background-color 180ms ease-out;
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]::after {
        display: none;
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #0077ED !important;
        box-shadow: none;
        transform: translateY(-1px);
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]:active {
        transform: scale(0.97);
    }

    .st-key-state_control_dock .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"],
    .st-key-state_control_dock .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"] {
        background: #D70015 !important;
    }

    .st-key-state_control_dock .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"] {
        background: #248A3D !important;
    }

    .st-key-state_control_dock .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"] {
        background: #C35A00 !important;
    }

    .st-key-developer_tools {
        max-width: 940px;
        margin: 8px auto 0;
    }

    .st-key-developer_tools [data-testid="stExpander"] {
        background: transparent;
        border: 0;
        border-radius: 0;
        box-shadow: none;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
    }

    .st-key-developer_tools [data-testid="stExpander"] > details {
        background: transparent;
        border: 0;
        border-radius: 0;
    }

    .st-key-developer_tools [data-testid="stExpander"] summary {
        justify-content: center;
        min-height: 34px;
        padding: 0 10px;
        color: #6E6E73;
        font-size: 0.78rem;
        transition: color 160ms ease-out, transform 140ms cubic-bezier(0.23, 1, 0.32, 1);
    }

    .st-key-developer_tools [data-testid="stExpander"] summary:hover {
        color: #1D1D1F;
    }

    .st-key-developer_tools [data-testid="stExpander"] summary:active {
        transform: scale(0.98);
    }

    .workspace-spacer {
        height: 24px;
    }

    .stTabs [data-baseweb="tab-list"] {
        margin: 0 auto;
        gap: 4px;
        padding: 5px;
        background: rgba(232, 232, 237, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.9);
        border-radius: 999px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08),
                    inset 0 1px 0 rgba(255, 255, 255, 0.9);
        backdrop-filter: blur(24px) saturate(170%);
        -webkit-backdrop-filter: blur(24px) saturate(170%);
    }

    .stTabs [data-baseweb="tab"] {
        min-width: 144px;
        height: 40px;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 550;
    }

    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: rgba(255, 255, 255, 0.94);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08),
                    inset 0 1px 0 #FFFFFF;
    }

    .stTabs [data-baseweb="tab-panel"] {
        padding-top: 1.9rem;
    }

    .section-heading {
        align-items: center;
        flex-direction: column;
        justify-content: center;
        gap: 5px;
        margin: 0 0 18px;
        text-align: center;
        animation: section-reveal 480ms var(--spring-out) both;
    }

    .section-title {
        font-size: 1.85rem;
        line-height: 1.15;
        font-weight: 700;
    }

    .section-meta {
        color: #86868B;
        font-size: 0.8rem;
    }

    iframe[data-testid="stIFrame"] {
        overflow: hidden;
        border: 0 !important;
        border-radius: 30px;
        background: #F5F5F7;
        box-shadow: none;
        animation: section-reveal 520ms 50ms var(--spring-out) both;
    }

    .slot-panel {
        padding: 0 4px 0 0;
        background: transparent;
        border: 0;
        border-radius: 0;
        box-shadow: none;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
        animation: section-reveal 520ms 90ms var(--spring-out) both;
    }

    @keyframes section-reveal {
        from { opacity: 0; transform: translateY(12px); filter: blur(6px); }
        to { opacity: 1; transform: translateY(0); filter: blur(0); }
    }

    .slot-panel-header {
        padding: 4px 2px 14px;
        border-bottom-color: #D2D2D7;
    }

    .slot-panel-title {
        font-size: 1.15rem;
        font-weight: 650;
    }

    .slot-summary-item {
        padding: 10px 12px;
        background: #F5F5F7;
        border: 0;
        border-radius: 16px;
        box-shadow: none;
    }

    .slot-packet {
        padding: 14px;
        margin-bottom: 12px;
        background: #FFFFFF;
        border: 1px solid #E5E5EA;
        border-left: 3px solid #0071E3;
        border-radius: 18px;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.05);
    }

    .slot-packet:hover {
        border-color: #D2D2D7;
        transform: translateY(-1px);
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
    }

    .log-console {
        background: #F5F5F7;
        border: 0;
        border-radius: 24px;
        box-shadow: none;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
    }

    [data-testid="stAlert"] {
        border: 0;
        border-radius: 18px;
        box-shadow: none;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
    }

    .topology-legend {
        border: 1px solid rgba(255, 255, 255, 0.9);
        border-radius: 999px;
        background: rgba(246, 246, 248, 0.74);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08),
                    inset 0 1px 0 rgba(255, 255, 255, 1);
        backdrop-filter: blur(24px) saturate(170%);
        -webkit-backdrop-filter: blur(24px) saturate(170%);
    }

    /* Full Liquid Glass workspace */
    [data-testid="stAppViewContainer"] {
        background:
            linear-gradient(118deg, rgba(173, 216, 255, 0.42) 0%, rgba(236, 243, 250, 0.12) 34%, transparent 52%),
            linear-gradient(242deg, rgba(255, 190, 210, 0.3) 0%, rgba(244, 238, 247, 0.1) 32%, transparent 55%),
            linear-gradient(315deg, rgba(177, 232, 208, 0.3) 0%, rgba(239, 246, 244, 0.12) 30%, transparent 54%),
            #EEF2F6;
        background-attachment: fixed;
    }

    .product-nav {
        background: rgba(244, 247, 250, 0.56);
        border-bottom-color: rgba(255, 255, 255, 0.72);
        box-shadow: 0 1px 0 rgba(70, 80, 100, 0.06),
                    inset 0 1px 0 rgba(255, 255, 255, 0.78);
        backdrop-filter: blur(30px) saturate(185%);
        -webkit-backdrop-filter: blur(30px) saturate(185%);
    }

    .glass-module {
        position: relative;
        isolation: isolate;
        overflow: hidden;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.28)),
            rgba(240, 244, 249, 0.36);
        border: 1px solid rgba(255, 255, 255, 0.78);
        border-radius: 28px;
        box-shadow:
            0 22px 54px rgba(55, 65, 85, 0.13),
            0 4px 14px rgba(55, 65, 85, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.96),
            inset 0 -1px 0 rgba(70, 80, 100, 0.06);
        backdrop-filter: blur(36px) saturate(190%);
        -webkit-backdrop-filter: blur(36px) saturate(190%);
        transition: transform 220ms var(--spring-out), box-shadow 220ms ease-out,
                    border-color 220ms ease-out;
        animation: liquid-materialize 520ms var(--spring-out) both;
    }

    .glass-module::before {
        content: "";
        position: absolute;
        z-index: -1;
        inset: 0;
        border-radius: inherit;
        background:
            linear-gradient(152deg, rgba(255, 255, 255, 0.72) 0%, rgba(255, 255, 255, 0.08) 38%, transparent 58%),
            linear-gradient(330deg, rgba(255, 255, 255, 0.26), transparent 44%);
        pointer-events: none;
    }

    .glass-module::after {
        content: "";
        position: absolute;
        z-index: -1;
        top: -120%;
        left: -38%;
        width: 34%;
        height: 320%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.46), transparent);
        transform: rotate(18deg) translateX(0);
        opacity: 0;
        pointer-events: none;
        transition: transform 500ms var(--spring-out), opacity 180ms ease-out;
    }

    .glass-module:hover {
        transform: translateY(-2px);
        border-color: rgba(255, 255, 255, 0.96);
        box-shadow:
            0 28px 64px rgba(55, 65, 85, 0.16),
            0 6px 16px rgba(55, 65, 85, 0.07),
            inset 0 1px 0 #FFFFFF,
            inset 0 -1px 0 rgba(70, 80, 100, 0.06);
    }

    .glass-module:hover::after {
        opacity: 0.72;
        transform: rotate(18deg) translateX(470%);
    }

    @keyframes liquid-materialize {
        from {
            opacity: 0;
            transform: translateY(16px) scale(0.975);
            filter: blur(11px) saturate(140%);
        }
        to {
            opacity: 1;
            transform: translateY(0) scale(1);
            filter: blur(0) saturate(100%);
        }
    }

    .mission-overview {
        max-width: 1280px;
        margin: 0 auto;
        padding: 38px 0 18px;
        display: grid;
        grid-template-columns: minmax(0, 1fr) 238px;
        gap: 42px;
        align-items: stretch;
    }

    .mission-copy {
        padding: 18px 0 12px;
        align-self: center;
    }

    .mission-eyebrow {
        color: #5F6672;
        font-size: 0.76rem;
        line-height: 1.3;
        font-weight: 650;
        letter-spacing: 0;
    }

    .mission-title {
        margin: 8px 0 0;
        color: #16181D;
        font-size: 3.15rem;
        line-height: 1.04;
        font-weight: 720;
        letter-spacing: 0;
    }

    .mission-description {
        max-width: 780px;
        margin: 14px 0 0;
        color: #5F6672;
        font-size: 1rem;
        line-height: 1.55;
    }

    .interface-chips {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 18px;
    }

    .interface-chips span {
        display: inline-flex;
        align-items: center;
        min-height: 27px;
        padding: 3px 10px;
        color: #4C5563;
        background: rgba(255, 255, 255, 0.44);
        border: 1px solid rgba(255, 255, 255, 0.72);
        border-radius: 999px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
        backdrop-filter: blur(14px) saturate(165%);
        -webkit-backdrop-filter: blur(14px) saturate(165%);
        font-family: "SFMono-Regular", Consolas, monospace;
        font-size: 0.7rem;
        font-weight: 600;
    }

    .mission-state {
        min-height: 176px;
        padding: 22px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: flex-start;
        animation-delay: 40ms;
    }

    .module-kicker {
        color: #687180;
        font-size: 0.72rem;
        font-weight: 600;
    }

    .mission-state strong {
        margin-top: 5px;
        color: #0071E3;
        font-size: 3.25rem;
        line-height: 1;
        font-weight: 740;
    }

    .mission-overview.tone-green .mission-state strong { color: #248A3D; }
    .mission-overview.tone-orange .mission-state strong { color: #C35A00; }

    .mission-state b {
        margin-top: 8px;
        color: #1D1D1F;
        font-size: 1rem;
    }

    .mission-state small {
        margin-top: 4px;
        color: #687180;
        font-size: 0.72rem;
    }

    .signal-modules {
        max-width: 1280px;
        margin: 0 auto 16px;
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
    }

    .signal-module {
        min-height: 128px;
        padding: 17px 18px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        border-radius: 22px;
    }

    .signal-module:nth-child(1) { animation-delay: 80ms; }
    .signal-module:nth-child(2) { animation-delay: 120ms; }
    .signal-module:nth-child(3) { animation-delay: 160ms; }
    .signal-module:nth-child(4) { animation-delay: 200ms; }

    .module-topline {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        color: #687180;
        font-size: 0.7rem;
        line-height: 1.2;
        font-weight: 600;
    }

    .signal-module > strong {
        margin: 8px 0 5px;
        color: #1D1D1F;
        font-size: 1.2rem;
        line-height: 1.2;
        font-weight: 680;
    }

    .signal-module > strong em {
        color: #4C5563;
        font-size: 0.82rem;
        font-style: normal;
        font-weight: 550;
    }

    .signal-module > small {
        color: #687180;
        font-size: 0.72rem;
        line-height: 1.35;
    }

    .state-module.tone-green > strong { color: #248A3D; }
    .state-module.tone-orange > strong { color: #C35A00; }
    .state-module.tone-blue > strong { color: #0071E3; }

    .live-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #34C759;
        box-shadow: 0 0 0 0 rgba(52, 199, 89, 0.38);
        animation: live-pulse 1.8s ease-out infinite;
    }

    @keyframes live-pulse {
        0% { box-shadow: 0 0 0 0 rgba(52, 199, 89, 0.38); }
        55%, 100% { box-shadow: 0 0 0 7px rgba(52, 199, 89, 0); }
    }

    .signal-bars {
        height: 15px;
        display: inline-flex;
        align-items: flex-end;
        gap: 2px;
    }

    .signal-bars i {
        width: 3px;
        border-radius: 2px;
        background: #34C759;
        animation: signal-level 900ms ease-in-out infinite alternate;
    }

    .signal-bars i:nth-child(1) { height: 6px; animation-delay: 0ms; }
    .signal-bars i:nth-child(2) { height: 12px; animation-delay: 160ms; }
    .signal-bars i:nth-child(3) { height: 9px; animation-delay: 320ms; }

    @keyframes signal-level {
        from { transform: scaleY(0.55); opacity: 0.62; }
        to { transform: scaleY(1); opacity: 1; }
    }

    .state-rail {
        min-height: 196px;
        padding: 19px 20px 17px;
        animation-delay: 220ms;
    }

    .rail-heading {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 18px;
    }

    .rail-heading > div {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .rail-heading span,
    .rail-heading small {
        color: #687180;
        font-size: 0.7rem;
        line-height: 1.3;
    }

    .rail-heading strong {
        color: #1D1D1F;
        font-size: 0.94rem;
    }

    .state-track {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 0;
    }

    .state-step {
        position: relative;
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .state-step:not(:last-child)::after {
        content: "";
        position: absolute;
        z-index: -1;
        top: 22px;
        left: calc(50% + 21px);
        width: calc(100% - 42px);
        height: 2px;
        background: rgba(128, 137, 150, 0.28);
    }

    .state-step.visited:not(:last-child)::after,
    .state-step.current:not(:last-child)::after {
        background: linear-gradient(90deg, #0A84FF, rgba(10, 132, 255, 0.28));
    }

    .state-node {
        position: relative;
        width: 44px;
        height: 44px;
        display: grid;
        place-items: center;
        color: #6E7682;
        background: rgba(255, 255, 255, 0.52);
        border: 1px solid rgba(255, 255, 255, 0.86);
        border-radius: 50%;
        box-shadow: 0 5px 14px rgba(55, 65, 85, 0.09), inset 0 1px 0 #FFFFFF;
    }

    .state-node b {
        font-size: 0.72rem;
        line-height: 1;
    }

    .state-step.visited .state-node {
        color: #0066CC;
        background: rgba(225, 241, 255, 0.72);
    }

    .state-step.reachable .state-node {
        color: #8A4B00;
        background: rgba(255, 240, 218, 0.76);
        border-color: rgba(255, 205, 145, 0.78);
    }

    .state-step.current .state-node {
        color: #FFFFFF;
        background: linear-gradient(180deg, #168BFF, #0066D6);
        border-color: rgba(255, 255, 255, 0.92);
        box-shadow: 0 8px 20px rgba(0, 113, 227, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.42);
    }

    .state-step.current .state-node i {
        position: absolute;
        inset: -5px;
        border: 2px solid rgba(10, 132, 255, 0.32);
        border-radius: 50%;
        animation: state-orbit 1.9s ease-out infinite;
    }

    @keyframes state-orbit {
        0% { transform: scale(0.9); opacity: 0; }
        35% { opacity: 1; }
        100% { transform: scale(1.22); opacity: 0; }
    }

    .state-step > strong {
        margin-top: 8px;
        color: #303640;
        font-size: 0.72rem;
        line-height: 1.2;
    }

    .state-step > small {
        margin-top: 2px;
        color: #8A919C;
        font-size: 0.62rem;
        line-height: 1.2;
    }

    .st-key-state_control_dock {
        width: 100%;
        max-width: none;
        min-height: 196px;
        margin: 0;
        padding: 19px 20px 17px;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.28)),
            rgba(240, 244, 249, 0.36);
        border: 1px solid rgba(255, 255, 255, 0.78) !important;
        border-radius: 28px !important;
        box-shadow:
            0 22px 54px rgba(55, 65, 85, 0.13),
            0 4px 14px rgba(55, 65, 85, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.96),
            inset 0 -1px 0 rgba(70, 80, 100, 0.06);
        backdrop-filter: blur(36px) saturate(190%);
        -webkit-backdrop-filter: blur(36px) saturate(190%);
        animation: liquid-materialize 520ms 260ms var(--spring-out) both;
    }

    .st-key-state_control_dock .control-heading {
        margin-bottom: 8px;
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"] {
        min-height: 42px;
        border: 1px solid rgba(255, 255, 255, 0.46) !important;
        border-radius: 16px;
        background: linear-gradient(180deg, rgba(18, 128, 246, 0.94), rgba(0, 96, 209, 0.92)) !important;
        box-shadow: 0 8px 18px rgba(0, 113, 227, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.35);
        backdrop-filter: blur(14px) saturate(180%);
        -webkit-backdrop-filter: blur(14px) saturate(180%);
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]:hover {
        background: linear-gradient(180deg, rgba(30, 139, 255, 0.98), rgba(0, 103, 219, 0.95)) !important;
        transform: translateY(-1px) scale(1.006);
        box-shadow: 0 12px 24px rgba(0, 113, 227, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.45);
    }

    .workspace-spacer {
        height: 20px;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: rgba(240, 243, 247, 0.5);
        border-color: rgba(255, 255, 255, 0.8);
        box-shadow: 0 14px 34px rgba(55, 65, 85, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.94);
        backdrop-filter: blur(30px) saturate(185%);
        -webkit-backdrop-filter: blur(30px) saturate(185%);
    }

    .section-heading {
        align-items: baseline;
        flex-direction: row;
        justify-content: space-between;
        text-align: left;
        margin-bottom: 14px;
    }

    .section-title {
        font-size: 1.5rem;
    }

    iframe[data-testid="stIFrame"] {
        border: 1px solid rgba(255, 255, 255, 0.82) !important;
        border-radius: 30px;
        box-shadow: 0 24px 60px rgba(55, 65, 85, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.95);
    }

    [data-baseweb="select"] > div {
        background: rgba(255, 255, 255, 0.52);
        border-color: rgba(255, 255, 255, 0.82);
        box-shadow: 0 8px 22px rgba(55, 65, 85, 0.09), inset 0 1px 0 rgba(255, 255, 255, 0.94);
        backdrop-filter: blur(20px) saturate(175%);
        -webkit-backdrop-filter: blur(20px) saturate(175%);
    }

    .slot-panel {
        padding: 16px;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.58), rgba(255, 255, 255, 0.24)),
            rgba(240, 244, 249, 0.34);
        border: 1px solid rgba(255, 255, 255, 0.8);
        border-radius: 30px;
        box-shadow: 0 24px 60px rgba(55, 65, 85, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.96);
        backdrop-filter: blur(34px) saturate(185%);
        -webkit-backdrop-filter: blur(34px) saturate(185%);
    }

    .slot-summary-item {
        background: rgba(255, 255, 255, 0.38);
        border: 1px solid rgba(255, 255, 255, 0.56);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
    }

    .slot-packet {
        background: rgba(255, 255, 255, 0.48);
        border-color: rgba(255, 255, 255, 0.62);
        box-shadow: 0 8px 20px rgba(55, 65, 85, 0.07), inset 0 1px 0 rgba(255, 255, 255, 0.76);
        backdrop-filter: blur(16px) saturate(165%);
        -webkit-backdrop-filter: blur(16px) saturate(165%);
    }

    .log-console,
    [data-testid="stAlert"] {
        background: rgba(255, 255, 255, 0.46);
        border: 1px solid rgba(255, 255, 255, 0.76);
        box-shadow: 0 20px 48px rgba(55, 65, 85, 0.11), inset 0 1px 0 rgba(255, 255, 255, 0.9);
        backdrop-filter: blur(28px) saturate(180%);
        -webkit-backdrop-filter: blur(28px) saturate(180%);
    }

    [data-testid="stGraphVizChart"] {
        overflow: hidden;
        padding: 18px 20px;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.58), rgba(255, 255, 255, 0.24)),
            rgba(240, 244, 249, 0.34);
        border: 1px solid rgba(255, 255, 255, 0.8);
        border-radius: 30px;
        box-shadow: 0 24px 60px rgba(55, 65, 85, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.96);
        backdrop-filter: blur(34px) saturate(185%);
        -webkit-backdrop-filter: blur(34px) saturate(185%);
        animation: liquid-materialize 520ms 80ms var(--spring-out) both;
    }

    [data-testid="stGraphVizChart"] svg {
        overflow: visible;
    }

    /* Neutral Liquid Glass pass: material quality before decorative color */
    [data-testid="stAppViewContainer"] {
        background:
            linear-gradient(124deg, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0.26) 35%, transparent 57%),
            linear-gradient(304deg, rgba(91, 101, 116, 0.16) 0%, rgba(207, 213, 221, 0.14) 38%, transparent 62%),
            linear-gradient(180deg, #F1F3F5 0%, #DCE1E6 50%, #E9ECEF 100%);
    }

    .product-nav {
        background: rgba(243, 245, 247, 0.4);
        border-bottom-color: rgba(255, 255, 255, 0.68);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.88),
                    inset 0 -1px 0 rgba(47, 55, 68, 0.1),
                    0 8px 24px rgba(39, 47, 59, 0.04);
        backdrop-filter: blur(20px) saturate(132%) contrast(105%);
        -webkit-backdrop-filter: blur(20px) saturate(132%) contrast(105%);
    }

    .glass-module {
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.38), rgba(255, 255, 255, 0.08)),
            rgba(236, 239, 243, 0.1);
        border-color: rgba(255, 255, 255, 0.7);
        outline: 1px solid rgba(45, 53, 65, 0.09);
        outline-offset: -2px;
        box-shadow:
            0 26px 68px rgba(38, 45, 57, 0.16),
            0 5px 16px rgba(38, 45, 57, 0.07),
            0 1px 0 rgba(255, 255, 255, 0.96) inset,
            1px 0 0 rgba(255, 255, 255, 0.48) inset,
            0 -1px 0 rgba(38, 45, 57, 0.15) inset;
        backdrop-filter: blur(21px) saturate(136%) contrast(106%) brightness(1.03);
        -webkit-backdrop-filter: blur(21px) saturate(136%) contrast(106%) brightness(1.03);
    }

    .glass-module::before {
        background:
            linear-gradient(152deg, rgba(255, 255, 255, 0.72) 0%, rgba(255, 255, 255, 0.1) 31%, transparent 53%),
            linear-gradient(328deg, rgba(72, 81, 95, 0.09), transparent 42%);
    }

    .glass-module:hover {
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.44), rgba(255, 255, 255, 0.11)),
            rgba(236, 239, 243, 0.12);
        box-shadow:
            0 32px 78px rgba(38, 45, 57, 0.19),
            0 7px 18px rgba(38, 45, 57, 0.08),
            0 1px 0 #FFFFFF inset,
            1px 0 0 rgba(255, 255, 255, 0.54) inset,
            0 -1px 0 rgba(38, 45, 57, 0.16) inset;
    }

    .interface-chips span {
        background: rgba(247, 248, 249, 0.28);
        border-color: rgba(255, 255, 255, 0.64);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8),
                    inset 0 -1px 0 rgba(47, 55, 68, 0.08);
        backdrop-filter: blur(10px) saturate(128%);
        -webkit-backdrop-filter: blur(10px) saturate(128%);
    }

    .st-key-state_control_dock {
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.38), rgba(255, 255, 255, 0.08)),
            rgba(236, 239, 243, 0.1);
        border-color: rgba(255, 255, 255, 0.7) !important;
        outline: 1px solid rgba(45, 53, 65, 0.09);
        outline-offset: -2px;
        box-shadow:
            0 26px 68px rgba(38, 45, 57, 0.16),
            0 5px 16px rgba(38, 45, 57, 0.07),
            0 1px 0 rgba(255, 255, 255, 0.96) inset,
            1px 0 0 rgba(255, 255, 255, 0.48) inset,
            0 -1px 0 rgba(38, 45, 57, 0.15) inset;
        backdrop-filter: blur(21px) saturate(136%) contrast(106%) brightness(1.03);
        -webkit-backdrop-filter: blur(21px) saturate(136%) contrast(106%) brightness(1.03);
    }

    .stTabs [data-baseweb="tab-list"] {
        background: rgba(235, 238, 242, 0.28);
        border-color: rgba(255, 255, 255, 0.68);
        box-shadow: 0 16px 42px rgba(38, 45, 57, 0.14),
                    0 1px 0 rgba(255, 255, 255, 0.94) inset,
                    0 -1px 0 rgba(38, 45, 57, 0.12) inset;
        backdrop-filter: blur(18px) saturate(132%) contrast(105%);
        -webkit-backdrop-filter: blur(18px) saturate(132%) contrast(105%);
    }

    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: rgba(255, 255, 255, 0.58);
        box-shadow: 0 7px 18px rgba(38, 45, 57, 0.12),
                    inset 0 1px 0 #FFFFFF,
                    inset 0 -1px 0 rgba(38, 45, 57, 0.1);
        backdrop-filter: blur(12px) saturate(126%);
        -webkit-backdrop-filter: blur(12px) saturate(126%);
    }

    [data-baseweb="select"] > div {
        background: rgba(247, 248, 249, 0.3);
        border-color: rgba(255, 255, 255, 0.68);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86),
                    inset 0 -1px 0 rgba(38, 45, 57, 0.08);
        backdrop-filter: blur(14px) saturate(128%) contrast(105%);
        -webkit-backdrop-filter: blur(14px) saturate(128%) contrast(105%);
    }

    .slot-panel,
    [data-testid="stGraphVizChart"] {
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.36), rgba(255, 255, 255, 0.07)),
            rgba(236, 239, 243, 0.09);
        border-color: rgba(255, 255, 255, 0.7);
        outline: 1px solid rgba(45, 53, 65, 0.09);
        outline-offset: -2px;
        box-shadow:
            0 28px 72px rgba(38, 45, 57, 0.16),
            0 1px 0 rgba(255, 255, 255, 0.94) inset,
            0 -1px 0 rgba(38, 45, 57, 0.14) inset;
        backdrop-filter: blur(21px) saturate(132%) contrast(105%);
        -webkit-backdrop-filter: blur(21px) saturate(132%) contrast(105%);
    }

    .slot-summary-item,
    .slot-packet {
        background: rgba(247, 248, 249, 0.25);
        border-color: rgba(255, 255, 255, 0.56);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72),
                    inset 0 -1px 0 rgba(38, 45, 57, 0.07);
        backdrop-filter: blur(10px) saturate(124%);
        -webkit-backdrop-filter: blur(10px) saturate(124%);
    }

    .log-console,
    [data-testid="stAlert"] {
        background: rgba(247, 248, 249, 0.26);
        border-color: rgba(255, 255, 255, 0.66);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82),
                    inset 0 -1px 0 rgba(38, 45, 57, 0.08);
        backdrop-filter: blur(18px) saturate(128%) contrast(105%);
        -webkit-backdrop-filter: blur(18px) saturate(128%) contrast(105%);
    }

    /* Sculpted optics: a neutral material ladder with visible edge refraction. */
    [data-testid="stAppViewContainer"] {
        background:
            linear-gradient(117deg, transparent 0% 36%, rgba(255, 255, 255, 0.66) 45%, rgba(55, 64, 78, 0.055) 48%, transparent 55%),
            linear-gradient(294deg, rgba(42, 50, 63, 0.2) 0%, rgba(126, 136, 149, 0.08) 34%, transparent 59%),
            linear-gradient(135deg, #F8F9FA 0%, #ECEFF2 31%, #CDD4DC 54%, #F4F6F8 74%, #DFE4E9 100%);
        background-attachment: fixed;
    }

    .glass-module {
        border: 1px solid transparent;
        outline: none;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.31), rgba(248, 250, 252, 0.08) 52%, rgba(220, 225, 232, 0.06)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.34) 48%, rgba(39, 47, 59, 0.2)) border-box;
        box-shadow:
            0 30px 78px rgba(31, 38, 49, 0.16),
            0 8px 24px rgba(31, 38, 49, 0.07),
            inset 0 1px 0 rgba(255, 255, 255, 0.98),
            inset 1px 0 0 rgba(255, 255, 255, 0.58),
            inset 0 -1px 0 rgba(31, 38, 49, 0.16),
            inset -1px 0 0 rgba(31, 38, 49, 0.08);
        backdrop-filter: blur(27px) saturate(118%) contrast(110%) brightness(1.04);
        -webkit-backdrop-filter: blur(27px) saturate(118%) contrast(110%) brightness(1.04);
        animation-fill-mode: backwards;
    }

    .glass-module::before {
        z-index: 0;
        padding: 1.5px;
        background: linear-gradient(
            138deg,
            rgba(255, 255, 255, 0.98) 0%,
            rgba(211, 238, 255, 0.5) 28%,
            rgba(255, 255, 255, 0.08) 52%,
            rgba(255, 210, 226, 0.16) 74%,
            rgba(35, 43, 55, 0.24) 82%,
            rgba(255, 255, 255, 0.72) 100%
        );
        -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite: xor;
        mask-composite: exclude;
        opacity: 0.92;
        animation: rim-focus 560ms 120ms var(--spring-out) both;
    }

    .glass-module::after {
        z-index: 0;
        transition: transform 360ms var(--spring-out), opacity 150ms ease-out;
    }

    .glass-module > * {
        position: relative;
        z-index: 1;
    }

    @keyframes rim-focus {
        from {
            opacity: 0;
            transform: scale(0.985);
            filter: blur(3px);
        }
        to {
            opacity: 0.92;
            transform: scale(1);
            filter: blur(0);
        }
    }

    .glass-module:hover {
        border-color: transparent;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.36), rgba(248, 250, 252, 0.1) 52%, rgba(220, 225, 232, 0.07)) padding-box,
            linear-gradient(145deg, #FFFFFF, rgba(255, 255, 255, 0.42) 48%, rgba(39, 47, 59, 0.22)) border-box;
        transform: translateY(-3px) scale(1.002);
        box-shadow:
            0 36px 88px rgba(31, 38, 49, 0.19),
            0 10px 28px rgba(31, 38, 49, 0.08),
            inset 0 1px 0 #FFFFFF,
            inset 1px 0 0 rgba(255, 255, 255, 0.64),
            inset 0 -1px 0 rgba(31, 38, 49, 0.17),
            inset -1px 0 0 rgba(31, 38, 49, 0.09);
    }

    .mission-state,
    .state-rail {
        background:
            linear-gradient(142deg, rgba(255, 255, 255, 0.35), rgba(245, 248, 251, 0.09) 54%, rgba(205, 212, 221, 0.07)) padding-box,
            linear-gradient(142deg, #FFFFFF, rgba(255, 255, 255, 0.38) 46%, rgba(30, 37, 48, 0.22)) border-box;
        box-shadow:
            0 34px 86px rgba(31, 38, 49, 0.18),
            0 9px 28px rgba(31, 38, 49, 0.07),
            inset 0 1px 0 #FFFFFF,
            inset 1px 0 0 rgba(255, 255, 255, 0.62),
            inset 0 -1px 0 rgba(31, 38, 49, 0.18);
        backdrop-filter: blur(32px) saturate(116%) contrast(112%) brightness(1.04);
        -webkit-backdrop-filter: blur(32px) saturate(116%) contrast(112%) brightness(1.04);
    }

    .mission-state strong {
        text-shadow: 0 1px 0 rgba(255, 255, 255, 0.92), 0 12px 30px rgba(0, 113, 227, 0.15);
    }

    .mission-overview.tone-green .mission-state strong {
        text-shadow: 0 1px 0 rgba(255, 255, 255, 0.92), 0 12px 30px rgba(36, 138, 61, 0.14);
    }

    .mission-overview.tone-orange .mission-state strong {
        text-shadow: 0 1px 0 rgba(255, 255, 255, 0.92), 0 12px 30px rgba(195, 90, 0, 0.16);
    }

    .signal-module {
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.25), rgba(247, 249, 251, 0.06) 56%, rgba(211, 218, 227, 0.04)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.94), rgba(255, 255, 255, 0.3) 50%, rgba(43, 51, 63, 0.16)) border-box;
        box-shadow:
            0 22px 54px rgba(31, 38, 49, 0.13),
            0 5px 16px rgba(31, 38, 49, 0.05),
            inset 0 1px 0 rgba(255, 255, 255, 0.96),
            inset 0 -1px 0 rgba(31, 38, 49, 0.13);
        backdrop-filter: blur(19px) saturate(114%) contrast(109%) brightness(1.03);
        -webkit-backdrop-filter: blur(19px) saturate(114%) contrast(109%) brightness(1.03);
    }

    .st-key-state_control_dock {
        position: relative;
        border: 1px solid transparent !important;
        outline: none;
        background:
            linear-gradient(142deg, rgba(255, 255, 255, 0.46), rgba(245, 248, 251, 0.12) 54%, rgba(205, 212, 221, 0.09)) padding-box,
            linear-gradient(142deg, #FFFFFF, rgba(255, 255, 255, 0.36) 46%, rgba(30, 37, 48, 0.22)) border-box;
        box-shadow:
            0 34px 86px rgba(31, 38, 49, 0.18),
            0 9px 28px rgba(31, 38, 49, 0.07),
            inset 0 1px 0 #FFFFFF,
            inset 1px 0 0 rgba(255, 255, 255, 0.6),
            inset 0 -1px 0 rgba(31, 38, 49, 0.18);
        backdrop-filter: blur(31px) saturate(116%) contrast(112%) brightness(1.04);
        -webkit-backdrop-filter: blur(31px) saturate(116%) contrast(112%) brightness(1.04);
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"] {
        position: relative;
        overflow: hidden;
        border: 1px solid transparent !important;
        background:
            linear-gradient(180deg, rgba(38, 151, 255, 0.86), rgba(0, 113, 227, 0.9)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.92), rgba(168, 218, 255, 0.4) 48%, rgba(0, 49, 112, 0.42)) border-box !important;
        box-shadow: 0 9px 22px rgba(0, 91, 191, 0.22),
                    inset 0 1px 0 rgba(255, 255, 255, 0.52),
                    inset 0 -1px 0 rgba(0, 42, 92, 0.24);
        backdrop-filter: blur(14px) saturate(140%);
        -webkit-backdrop-filter: blur(14px) saturate(140%);
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]::after {
        content: "";
        display: block;
        position: absolute;
        inset: 1px 4px auto;
        height: 38%;
        border-radius: 999px 999px 50% 50%;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.25), transparent);
        pointer-events: none;
    }

    .st-key-state_control_dock div[data-testid="stButton"] button[kind="primary"]:hover {
        background:
            linear-gradient(180deg, rgba(52, 161, 255, 0.9), rgba(0, 119, 237, 0.94)) padding-box,
            linear-gradient(145deg, #FFFFFF, rgba(181, 225, 255, 0.48) 48%, rgba(0, 49, 112, 0.4)) border-box !important;
        box-shadow: 0 12px 28px rgba(0, 91, 191, 0.26),
                    inset 0 1px 0 rgba(255, 255, 255, 0.58),
                    inset 0 -1px 0 rgba(0, 42, 92, 0.22);
    }

    .st-key-state_control_dock .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"],
    .st-key-state_control_dock .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"] {
        background:
            linear-gradient(180deg, rgba(255, 55, 95, 0.86), rgba(215, 0, 21, 0.91)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(255, 180, 196, 0.4) 48%, rgba(103, 0, 17, 0.45)) border-box !important;
        box-shadow: 0 9px 22px rgba(190, 0, 28, 0.21),
                    inset 0 1px 0 rgba(255, 255, 255, 0.46),
                    inset 0 -1px 0 rgba(92, 0, 13, 0.24);
    }

    .st-key-state_control_dock .st-key-btn_S3_S5 div[data-testid="stButton"] button[kind="primary"]:hover,
    .st-key-state_control_dock .st-key-btn_S4_S5 div[data-testid="stButton"] button[kind="primary"]:hover {
        background:
            linear-gradient(180deg, rgba(255, 71, 108, 0.91), rgba(226, 0, 27, 0.95)) padding-box,
            linear-gradient(145deg, #FFFFFF, rgba(255, 190, 204, 0.46) 48%, rgba(103, 0, 17, 0.42)) border-box !important;
    }

    .st-key-state_control_dock .st-key-btn_S5_S2 div[data-testid="stButton"] button[kind="primary"] {
        background:
            linear-gradient(180deg, rgba(48, 209, 88, 0.86), rgba(36, 138, 61, 0.91)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(180, 245, 197, 0.4) 48%, rgba(16, 82, 33, 0.44)) border-box !important;
    }

    .st-key-state_control_dock .st-key-btn_S5_S1 div[data-testid="stButton"] button[kind="primary"] {
        background:
            linear-gradient(180deg, rgba(255, 159, 10, 0.86), rgba(195, 90, 0, 0.91)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(255, 218, 164, 0.42) 48%, rgba(99, 43, 0, 0.44)) border-box !important;
    }

    .product-nav-status {
        min-height: 28px;
        padding: 4px 10px;
        border: 1px solid transparent;
        border-radius: 999px;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.3), rgba(225, 230, 236, 0.12)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.94), rgba(43, 51, 63, 0.14)) border-box;
        box-shadow: 0 7px 18px rgba(31, 38, 49, 0.08),
                    inset 0 1px 0 rgba(255, 255, 255, 0.9),
                    inset 0 -1px 0 rgba(31, 38, 49, 0.09);
        backdrop-filter: blur(14px) saturate(112%) contrast(108%);
        -webkit-backdrop-filter: blur(14px) saturate(112%) contrast(108%);
    }

    .state-node {
        background: linear-gradient(145deg, rgba(255, 255, 255, 0.78), rgba(222, 228, 235, 0.5));
        border-color: rgba(255, 255, 255, 0.9);
        box-shadow: 0 7px 18px rgba(31, 38, 49, 0.11),
                    inset 0 1px 0 #FFFFFF,
                    inset 0 -1px 0 rgba(31, 38, 49, 0.12);
    }

    .state-step.current .state-node {
        background: linear-gradient(180deg, #2B9BFF 0%, #0071E3 56%, #0054AF 100%);
        box-shadow: 0 10px 26px rgba(0, 113, 227, 0.3),
                    inset 0 1px 0 rgba(255, 255, 255, 0.62),
                    inset 0 -1px 0 rgba(0, 39, 82, 0.4);
    }

    .stTabs [data-baseweb="tab-list"] {
        border: 1px solid transparent;
        background:
            linear-gradient(145deg, rgba(245, 247, 249, 0.44), rgba(218, 224, 231, 0.2)) padding-box,
            linear-gradient(145deg, #FFFFFF, rgba(255, 255, 255, 0.38) 54%, rgba(39, 47, 59, 0.17)) border-box;
        box-shadow: 0 18px 48px rgba(31, 38, 49, 0.14),
                    inset 0 1px 0 #FFFFFF,
                    inset 0 -1px 0 rgba(31, 38, 49, 0.12);
        backdrop-filter: blur(22px) saturate(114%) contrast(108%);
        -webkit-backdrop-filter: blur(22px) saturate(114%) contrast(108%);
    }

    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        border: 1px solid rgba(255, 255, 255, 0.78);
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(234, 238, 243, 0.58));
        box-shadow: 0 9px 22px rgba(31, 38, 49, 0.14),
                    inset 0 1px 0 #FFFFFF,
                    inset 0 -1px 0 rgba(31, 38, 49, 0.1);
    }

    .slot-panel,
    [data-testid="stGraphVizChart"],
    .log-console,
    [data-testid="stAlert"] {
        border: 1px solid transparent;
        outline: none;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.3), rgba(242, 245, 248, 0.07) 54%, rgba(204, 212, 221, 0.05)) padding-box,
            linear-gradient(145deg, #FFFFFF, rgba(255, 255, 255, 0.34) 48%, rgba(30, 37, 48, 0.2)) border-box;
        box-shadow:
            0 36px 92px rgba(31, 38, 49, 0.17),
            0 9px 28px rgba(31, 38, 49, 0.06),
            inset 0 1px 0 #FFFFFF,
            inset 0 -1px 0 rgba(31, 38, 49, 0.16);
        backdrop-filter: blur(31px) saturate(115%) contrast(111%) brightness(1.03);
        -webkit-backdrop-filter: blur(31px) saturate(115%) contrast(111%) brightness(1.03);
    }

    [data-testid="stAlert"] {
        background:
            linear-gradient(145deg, rgba(0, 113, 227, 0.13), rgba(224, 240, 255, 0.07)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.94), rgba(143, 202, 255, 0.38) 50%, rgba(23, 62, 105, 0.22)) border-box;
        box-shadow: 0 22px 52px rgba(0, 74, 153, 0.12),
                    inset 0 1px 0 rgba(255, 255, 255, 0.9),
                    inset 0 -1px 0 rgba(15, 54, 96, 0.12);
        backdrop-filter: blur(24px) saturate(122%) contrast(109%);
        -webkit-backdrop-filter: blur(24px) saturate(122%) contrast(109%);
    }

    [data-testid="stAlert"] > div {
        background: transparent !important;
    }

    [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
        color: #005EB8;
        font-weight: 560;
    }

    .stTabs div[data-testid="stButton"] button[kind="secondary"],
    .stTabs [data-testid="stDownloadButton"] button {
        border: 1px solid transparent !important;
        background:
            linear-gradient(145deg, rgba(255, 255, 255, 0.3), rgba(225, 230, 236, 0.1)) padding-box,
            linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.34) 52%, rgba(40, 48, 60, 0.16)) border-box !important;
        box-shadow: 0 10px 26px rgba(31, 38, 49, 0.1),
                    inset 0 1px 0 rgba(255, 255, 255, 0.92),
                    inset 0 -1px 0 rgba(31, 38, 49, 0.1);
        backdrop-filter: blur(16px) saturate(112%) contrast(107%);
        -webkit-backdrop-filter: blur(16px) saturate(112%) contrast(107%);
        transition: transform 150ms var(--spring-out), box-shadow 180ms ease-out,
                    background-color 180ms ease-out;
    }

    .stTabs div[data-testid="stButton"] button[kind="secondary"]:hover,
    .stTabs [data-testid="stDownloadButton"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 14px 30px rgba(31, 38, 49, 0.13),
                    inset 0 1px 0 #FFFFFF,
                    inset 0 -1px 0 rgba(31, 38, 49, 0.1);
    }

    .stTabs div[data-testid="stButton"] button[kind="secondary"]:active,
    .stTabs [data-testid="stDownloadButton"] button:active {
        transform: scale(0.98);
    }

    @media (max-width: 900px) {
        .stMainBlockContainer {
            padding-left: 1rem;
            padding-right: 1rem;
        }

        .app-header {
            align-items: flex-start;
            flex-direction: column;
            gap: 10px;
        }

        .header-status {
            justify-content: flex-start;
        }

        .slot-panel {
            height: auto;
            max-height: 720px;
        }
    }

    @media (max-width: 560px) {
        .app-title {
            font-size: 1.3rem;
        }

        .section-heading {
            align-items: flex-start;
            flex-direction: column;
            gap: 3px;
        }

        .section-meta {
            white-space: normal;
        }

        .status-card {
            grid-template-columns: 1fr;
        }

        .state-primary {
            min-height: 112px;
            border-right: 0;
            border-bottom: 1px solid var(--border);
        }

        .slot-summary {
            grid-template-columns: 1fr 1fr 1fr;
        }

        .slot-panel {
            max-height: none;
            overflow-y: visible;
        }

        .log-entry {
            grid-template-columns: 82px 42px 14px 42px minmax(96px, 1fr);
            font-size: 11px;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            scroll-behavior: auto !important;
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }

        .slot-packet:hover {
            transform: none;
        }
    }

    @media (prefers-reduced-transparency: reduce) {
        [data-testid="stHeader"],
        .status-chip,
        [data-testid="stExpander"],
        .product-nav,
        .product-nav-status,
        .glass-module,
        .st-key-state_control_dock,
        .stTabs [data-baseweb="tab-list"],
        [data-baseweb="select"] > div,
        .slot-panel,
        [data-testid="stGraphVizChart"],
        .log-console,
        .interface-chips span {
            background: rgba(248, 249, 251, 0.96) !important;
            backdrop-filter: none;
            -webkit-backdrop-filter: none;
        }

        [data-testid="stAlert"] {
            background: #EAF4FF !important;
            backdrop-filter: none;
            -webkit-backdrop-filter: none;
        }
    }

    @media (prefers-contrast: more) {
        [data-testid="stHeader"],
        .status-chip,
        [data-testid="stExpander"],
        .status-card,
        .slot-panel,
        .slot-packet {
            border-color: #6E6E73;
        }

        .product-nav-status,
        .glass-module,
        .st-key-state_control_dock,
        .stTabs [data-baseweb="tab-list"],
        [data-baseweb="select"] > div,
        [data-testid="stGraphVizChart"],
        .log-console,
        [data-testid="stAlert"] {
            outline: 2px solid #626A75;
            outline-offset: -2px;
        }
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ECharts 架构图生成函数
# ============================================================

def _generate_architecture_echarts_legacy(current_state: str) -> str:
    """
    生成基于 ECharts 的物理架构与数据流向图
    参照物理架构.png的布局，包含信号源、处理模块、输出模块三层架构
    支持动态数据流动画
    """

    # 数据流激活状态 - 根据当前状态激活对应的数据流
    active = {
        # S1搜索: 毫米波感知数据流
        "antenna_mmwave": current_state in ["S1", "S3", "S5"],
        "mmwave_dsp": current_state in ["S1", "S3", "S5"],
        # S2粗对准: 云台控制数据流
        "dsp_gimbal_ctrl": current_state in ["S2", "S4"],
        "gimbal_ctrl_gimbal": current_state in ["S2", "S4"],
        # S3捕获/S4跟踪: 太赫兹数据流
        "antenna_terahertz": current_state in ["S3", "S4"],
        "terahertz_dsp": current_state in ["S3", "S4"],
        "ad_terahertz": current_state in ["S3", "S4"],
        "terahertz_channel": current_state in ["S3", "S4"],
        # S4跟踪: 基带链路数据流
        "dsp_baselink": current_state in ["S4"],
        "baselink_cpu": current_state in ["S4"],
        "cpu_server": current_state in ["S4"],
    }

    # 节点定义 - 参照物理架构.png的三层布局
    # 上层(信号源): 天线矩阵、毫米波基带、太赫兹/FPGA、信道探测
    # 中层(处理): AD参数、目标信息、DSP核心、基带链路
    # 下层(输出): 云台控制箱、云台、CPU、服务器
    nodes = [
        # 上层 - 信号源 (y=15 附近)
        {"name": "天线矩阵", "x": 12, "y": 12, "icon": "📡"},
        {"name": "毫米波基带", "x": 35, "y": 12, "icon": "📶"},
        {"name": "太赫兹/FPGA", "x": 62, "y": 12, "icon": "⚡"},
        {"name": "信道探测", "x": 88, "y": 12, "icon": "🔍"},
        # 中层 - 处理模块 (y=40 附近)
        {"name": "AD参数", "x": 75, "y": 40},
        {"name": "目标信息", "x": 62, "y": 55, "icon": "🎯"},
        {"name": "DSP核心", "x": 38, "y": 55, "icon": "🎯"},
        {"name": "基带链路", "x": 20, "y": 55, "icon": "📶"},
        # 下层 - 输出模块 (y=80 附近)
        {"name": "云台控制箱", "x": 12, "y": 80, "icon": "📦"},
        {"name": "云台", "x": 38, "y": 88, "icon": "🛰️"},
        {"name": "CPU", "x": 62, "y": 88, "icon": "💻"},
        {"name": "服务器", "x": 85, "y": 88, "icon": "🖥️"},
    ]

    # 判断节点是否激活
    node_active_keys = {
        "天线矩阵": ["antenna_mmwave", "antenna_terahertz"],
        "毫米波基带": ["antenna_mmwave", "mmwave_dsp"],
        "太赫兹/FPGA": ["antenna_terahertz", "terahertz_dsp", "ad_terahertz", "terahertz_channel"],
        "信道探测": ["terahertz_channel"],
        "AD参数": ["ad_terahertz"],
        "目标信息": ["terahertz_dsp"],
        "DSP核心": ["mmwave_dsp", "dsp_gimbal_ctrl", "terahertz_dsp", "dsp_baselink"],
        "基带链路": ["dsp_baselink", "baselink_cpu"],
        "云台控制箱": ["dsp_gimbal_ctrl", "gimbal_ctrl_gimbal"],
        "云台": ["gimbal_ctrl_gimbal"],
        "CPU": ["baselink_cpu", "cpu_server"],
        "服务器": ["cpu_server"],
    }

    # 构建节点数据
    nodes_data = []
    for n in nodes:
        # 判断节点是否激活
        is_active = any(active.get(k, False) for k in node_active_keys.get(n["name"], []))
        if n["name"] == "DSP核心":
            is_active = True  # DSP核心始终激活

        itemStyle = {
            "color": "#DCFCE7" if is_active else "#FFFFFF",
            "borderColor": "#16A34A" if is_active else "#C8D1DC",
            "borderWidth": 2 if is_active else 1,
            "shadowBlur": 12 if is_active else 0,
            "shadowColor": "rgba(22, 163, 74, 0.22)" if is_active else "transparent",
        }
        label = f"{n.get('icon', '')} {n['name']}".strip() if n.get('icon') else n['name']
        nodes_data.append({
            "name": n["name"],
            "x": n["x"],
            "y": n["y"],
            "value": [n["x"], n["y"]],
            "symbolSize": 55,
            "itemStyle": itemStyle,
            "label": {
                "show": True,
                "formatter": label,
                "fontSize": 11,
                "fontFamily": "Microsoft YaHei",
                "color": "#166534" if is_active else "#57606A",
            },
        })

    # 连线定义: [from, to, active_key, dashed, bidirectional, label]
    edges_def = [
        # 上层信号源连线
        ("天线矩阵", "毫米波基带", "antenna_mmwave", False, True, "感知数据"),
        ("天线矩阵", "太赫兹/FPGA", "antenna_terahertz", False, True, "发射信号"),
        ("毫米波基带", "DSP核心", "mmwave_dsp", False, True, "目标数据"),
        ("太赫兹/FPGA", "DSP核心", "terahertz_dsp", False, True, "锁定状态"),
        ("太赫兹/FPGA", "信道探测", "terahertz_channel", False, True, ""),
        ("AD参数", "太赫兹/FPGA", "ad_terahertz", False, False, "AD参数"),
        # 中层处理连线
        ("DSP核心", "目标信息", "terahertz_dsp", False, True, ""),
        ("DSP核心", "基带链路", "dsp_baselink", False, True, "基带数据"),
        # 下层输出连线
        ("DSP核心", "云台控制箱", "dsp_gimbal_ctrl", False, True, "控制命令"),
        ("云台控制箱", "云台", "gimbal_ctrl_gimbal", False, True, "驱动"),
        ("基带链路", "CPU", "baselink_cpu", False, True, "数据"),
        ("CPU", "服务器", "cpu_server", False, True, "上报"),
    ]

    # 构建边数据
    links_data = []
    for edge in edges_def:
        src, tgt, act_key, dashed, bidir, lbl = edge
        is_active = active.get(act_key, False)

        lineStyle = {
            "color": "#16A34A" if is_active else "#C8D1DC",
            "width": 2.5 if is_active else 1,
            "opacity": 1 if is_active else 0.55,
            "curveness": 0.15,
        }

        if dashed:
            lineStyle["type"] = "dashed"

        # 正向连线
        link = {
            "source": src,
            "target": tgt,
            "lineStyle": lineStyle,
            "_active": is_active,
            "_origWidth": lineStyle["width"],
        }
        if is_active:
            link["effect"] = {
                "show": True,
                "trailLength": 0.5,
                "symbol": "arrow",
                "symbolSize": 8,
                "color": "#16A34A",
                "period": 1.2,
            }
        links_data.append(link)

        # 双向时添加反向连线
        if bidir:
            link_rev = {
                "source": tgt,
                "target": src,
                "lineStyle": lineStyle.copy(),
                "_active": is_active,
                "_origWidth": lineStyle["width"],
            }
            if is_active:
                link_rev["effect"] = {
                    "show": True,
                    "trailLength": 0.5,
                    "symbol": "arrow",
                    "symbolSize": 8,
                    "color": "#16A34A",
                    "period": 1.2,
                }
            links_data.append(link_rev)

    # 状态颜色和名称
    state_color = "#248A3D" if current_state in ["S0", "S1", "S2"] else "#C35A00" if current_state in ["S3", "S4"] else "#9A6700"
    state_name = STATE_NAMES.get(current_state, "未知")

    # 转换节点和连线数据为 JSON 字符串
    import json
    nodes_json = json.dumps(nodes_data, ensure_ascii=False)
    links_json = json.dumps(links_data, ensure_ascii=False)

    html = f'''
    <!DOCTYPE html>
    <html style="height:100%;margin:0;padding:0;">
    <head>
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
        <style>
            body {{ margin:0; padding:0; height:100%; background:#FFFFFF; font-family: 'Microsoft YaHei', sans-serif; position:relative; }}
            #chart {{ width:100%; height:100%; }}

            #control-bar {{
                position: absolute;
                top: 10px;
                right: 16px;
                display: flex;
                align-items: center;
                gap: 8px;
                z-index: 100;
                background: rgba(255,255,255,0.92);
                border: 1px solid #D8E0EA;
                border-radius: 10px;
                padding: 6px 12px;
                box-shadow: 0 2px 8px rgba(15,23,42,0.08);
            }}

            #control-bar button {{
                border: 1px solid #D0D7DE;
                border-radius: 6px;
                background: #FFFFFF;
                color: #1F2328;
                font-size: 14px;
                cursor: pointer;
                padding: 4px 10px;
                line-height: 1.4;
                transition: background 0.15s;
            }}
            #control-bar button:hover {{ background: #F3F4F6; }}
            #control-bar button.active {{ background: #DCFCE7; border-color: #16A34A; color: #14532D; }}

            #control-bar select {{
                border: 1px solid #D0D7DE;
                border-radius: 6px;
                background: #FFFFFF;
                color: #1F2328;
                font-size: 12px;
                padding: 4px 6px;
                cursor: pointer;
            }}

            #slot-badge {{
                display: inline-flex;
                align-items: center;
                gap: 4px;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 13px;
                color: #1E40AF;
                font-weight: 600;
                white-space: nowrap;
            }}
            #slot-badge .label {{ font-weight: 400; color: #57606A; font-size: 11px; }}
        </style>
    </head>
    <body>
        <div id="chart"></div>
        <div id="control-bar">
            <button id="btn-play" onclick="togglePlay()" title="播放 / 暂停">⏸</button>
            <select id="sel-speed" onchange="changeSpeed(this.value)">
                <option value="0.5">0.5x</option>
                <option value="1" selected>1x</option>
                <option value="2">2x</option>
            </select>
            <span id="slot-badge"><span class="label">Slot</span> 0</span>
        </div>
        <script>
            var chart = echarts.init(document.getElementById('chart'), null, {{renderer: 'canvas'}});

            var option = {{
                backgroundColor: '#FFFFFF',

                title: {{
                    text: '物理架构与数据流向图',
                    subtext: '状态: {current_state} · {state_name}',
                    subtextStyle: {{
                        color: '{state_color}',
                        fontSize: 16,
                        fontWeight: 'bold',
                        fontFamily: 'Microsoft YaHei'
                    }},
                    textStyle: {{ color: '#17324D', fontSize: 16, fontFamily: 'Microsoft YaHei' }},
                    left: 'center',
                    top: 8
                }},

                tooltip: {{
                    trigger: 'item',
                    backgroundColor: '#FFFFFF',
                    borderColor: '#D0D7DE',
                    textStyle: {{ color: '#1F2328' }},
                    formatter: function(params) {{
                        if (params.dataType === 'edge') {{
                            return params.data.source + ' → ' + params.data.target;
                        }}
                        return params.name;
                    }}
                }},

                grid: {{
                    left: '5%',
                    right: '5%',
                    top: '15%',
                    bottom: '8%',
                    containLabel: true
                }},

                xAxis: {{
                    min: 0, max: 100,
                    show: false,
                    type: 'value',
                }},

                yAxis: {{
                    min: 0, max: 100,
                    show: false,
                    type: 'value',
                    inverse: true,
                }},

                series: [{{
                    type: 'graph',
                    layout: 'none',
                    coordinateSystem: 'cartesian2d',
                    roam: true,
                    symbolKeepAspect: true,
                    zoom: 0.85,
                    minZoom: 0.3,
                    maxZoom: 2,

                    data: {nodes_json},

                    links: {links_json},

                    label: {{
                        position: 'inside',
                        fontSize: 11,
                        fontFamily: 'Microsoft YaHei',
                    }},

                    lineStyle: {{
                        curveness: 0.15,
                        opacity: 0.8,
                    }},

                    edgeSymbol: ['circle', 'arrow'],
                    edgeSymbolSize: [4, 8],

                    emphasis: {{
                        focus: 'adjacency',
                        lineStyle: {{ width: 3 }},
                    }},

                    animation: true,
                    animationDuration: 500,
                    animationEasing: 'cubicOut',
                }}]
            }};

            // 剥离自定义字段（_active / _origWidth），避免 ECharts 解析异常
            // 将激活状态保存到独立数组中
            var rawLinks = option.series[0].links;
            var edgeActiveFlags = rawLinks.map(function(l) {{ return !!l._active; }});
            var edgeOrigWidths = rawLinks.map(function(l) {{ return l.lineStyle.width; }});
            option.series[0].links = rawLinks.map(function(l) {{
                var clean = {{ source: l.source, target: l.target, lineStyle: l.lineStyle }};
                if (l.effect) clean.effect = l.effect;
                return clean;
            }});

            chart.setOption(option);

            // ========================================
            // 全局时钟 & 同步脉冲
            // ========================================
            var slotCount = 0;
            var isPlaying = true;
            var speed = 1.0;
            var clockInterval = null;
            var activeEdgeIndices = [];

            // 从激活标记中收集激活边索引
            (function initActiveEdges() {{
                activeEdgeIndices = [];
                for (var i = 0; i < edgeActiveFlags.length; i++) {{
                    if (edgeActiveFlags[i]) activeEdgeIndices.push(i);
                }}
            }})();

            function updateSlotBadge() {{
                document.getElementById('slot-badge').innerHTML = '<span class="label">Slot</span> ' + slotCount;
            }}

            function pulseTick() {{
                if (activeEdgeIndices.length === 0) {{
                    slotCount++;
                    updateSlotBadge();
                    return;
                }}

                // 从 ECharts 取当前完整 links，脉冲激活边后回传
                var opt = chart.getOption();
                var links = opt.series[0].links;
                activeEdgeIndices.forEach(function(idx) {{
                    links[idx].lineStyle.width = 5;
                    links[idx].lineStyle.shadowBlur = 14;
                    links[idx].lineStyle.shadowColor = 'rgba(22, 163, 74, 0.55)';
                }});
                chart.setOption({{ series: [{{ links: links }}] }});

                var indices = activeEdgeIndices;
                var origWidths = edgeOrigWidths;
                setTimeout(function() {{
                    var opt2 = chart.getOption();
                    var links2 = opt2.series[0].links;
                    indices.forEach(function(idx) {{
                        links2[idx].lineStyle.width = origWidths[idx];
                        links2[idx].lineStyle.shadowBlur = 0;
                        links2[idx].lineStyle.shadowColor = 'transparent';
                    }});
                    chart.setOption({{ series: [{{ links: links2 }}] }});
                }}, 120);

                slotCount++;
                updateSlotBadge();
            }}

            function startClock() {{
                stopClock();
                var interval = Math.round(1000 / speed);
                clockInterval = setInterval(pulseTick, interval);
            }}

            function stopClock() {{
                if (clockInterval) {{ clearInterval(clockInterval); clockInterval = null; }}
            }}

            function togglePlay() {{
                isPlaying = !isPlaying;
                var btn = document.getElementById('btn-play');
                if (isPlaying) {{
                    btn.textContent = '⏸';
                    btn.classList.add('active');
                    startClock();
                }} else {{
                    btn.textContent = '▶';
                    btn.classList.remove('active');
                    stopClock();
                }}
            }}

            function changeSpeed(val) {{
                speed = parseFloat(val);
                if (isPlaying) startClock();
            }}

            startClock();
            document.getElementById('btn-play').classList.add('active');

            window.addEventListener('resize', function() {{
                chart.resize();
            }});
        </script>
    </body>
    </html>
    '''

    return html


def generate_architecture_echarts(current_state: str, selected_packet_id=None) -> str:
    """
    生成与《瞄捕状态机设计文档》物理架构图一致的接口/数据流视图。

    这里使用固定坐标 SVG，而不是自动布局图。原因是该图表达的是硬件接线关系，
    协议和传输内容必须贴近对应线缆，自动布局会破坏图纸语义。
    """

    from string import Template

    active_groups_by_state = {
        "S0": {"clock", "sync", "state_report"},
        "S1": {"mmwave", "perception", "state_report"},
        "S2": {"mmwave", "perception", "gimbal", "state_report"},
        "S3": {"clock", "sync", "thz_tx", "fpga", "baseband", "mmwave", "perception", "state_report"},
        "S4": {"clock", "sync", "thz_tx", "fpga", "baseband", "mmwave", "perception", "gimbal", "server", "state_report"},
        "S5": {"mmwave", "perception", "gimbal_feedback", "state_report"},
    }
    active_groups = active_groups_by_state.get(current_state, set())
    selected_groups = PACKET_HIGHLIGHT_GROUPS.get(selected_packet_id, set())

    def edge_cls(*groups):
        if any(g in selected_groups for g in groups):
            return "selected"
        return "active" if any(g in active_groups for g in groups) else "idle"

    def node_cls(*groups):
        classes = []
        if any(g in active_groups for g in groups):
            classes.append("active-node")
        if any(g in selected_groups for g in groups):
            classes.append("selected-node")
        return " ".join(classes)

    state_name = STATE_NAMES.get(current_state, "未知")
    state_color = "#16A34A" if current_state in ["S0", "S1", "S2"] else "#C2410C" if current_state in ["S3", "S4"] else "#A16207"

    template = Template(r'''
    <!DOCTYPE html>
    <html style="height:100%;margin:0;padding:0;">
    <head>
        <meta charset="utf-8">
        <style>
            body {
                margin: 0;
                padding: 0;
                height: 100%;
                background:
                    linear-gradient(117deg, transparent 0% 37%, rgba(255, 255, 255, 0.72) 45%, rgba(55, 64, 78, 0.06) 47%, transparent 54%),
                    linear-gradient(294deg, rgba(42, 50, 63, 0.16) 0%, rgba(126, 136, 149, 0.07) 34%, transparent 59%),
                    linear-gradient(135deg, #F8F9FA 0%, #ECEFF2 31%, #D2D8DF 54%, #F4F6F8 74%, #E2E6EA 100%);
                color: #1D1D1F;
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
                position: relative;
                overflow: auto;
            }
            #chart {
                width: 100%;
                height: 100%;
                overflow: hidden;
                background:
                    linear-gradient(145deg, rgba(255, 255, 255, 0.34), transparent 46%),
                    linear-gradient(325deg, rgba(66, 75, 89, 0.08), transparent 44%);
                animation: chart-materialize 520ms cubic-bezier(0.22, 0.78, 0.18, 1) both;
            }
            @keyframes chart-materialize {
                from { opacity: 0; transform: scale(0.992); filter: blur(5px); }
                to { opacity: 1; transform: scale(1); filter: blur(0); }
            }
            svg {
                width: 100%;
                height: 100%;
                display: block;
            }
            .legend {
                font-size: 13px;
                fill: #57606A;
            }
            .module rect,
            .module polygon {
                fill: rgba(250, 251, 252, 0.54);
                stroke: #1F2328;
                stroke-width: 2;
                rx: 14px;
                filter: drop-shadow(0 5px 10px rgba(36, 46, 66, 0.08));
                transition: fill 0.22s ease-out, stroke 0.22s ease-out, stroke-width 0.22s ease-out, filter 0.22s ease-out, transform 0.22s cubic-bezier(0.22, 0.78, 0.18, 1);
            }
            .module .dashed {
                fill: rgba(250, 251, 252, 0.32);
                stroke: #1F2328;
                stroke-width: 2;
                stroke-dasharray: 9 7;
                rx: 12px;
            }
            .module text {
                font-size: 20px;
                font-weight: 700;
                fill: #1F2328;
                text-anchor: middle;
                dominant-baseline: middle;
            }
            .module .small {
                font-size: 16px;
                font-weight: 700;
            }
            .module .tiny {
                font-size: 13px;
                font-weight: 700;
            }
            .module.active-node rect,
            .module.active-node polygon {
                fill: rgba(220, 252, 231, 0.56);
                stroke: #16A34A;
                stroke-width: 3;
                filter: drop-shadow(0 0 8px rgba(22, 163, 74, 0.35));
            }
            .module.selected-node rect,
            .module.selected-node polygon {
                fill: rgba(254, 243, 199, 0.58);
                stroke: #F59E0B;
                stroke-width: 4;
                filter: drop-shadow(0 0 10px rgba(245, 158, 11, 0.45));
            }
            .network {
                fill: rgba(250, 251, 252, 0.12);
                stroke: #1F2328;
                stroke-width: 2;
                stroke-dasharray: 12 8;
                rx: 18px;
            }
            .car {
                fill: rgba(250, 251, 252, 0.48);
                stroke: #1F2328;
                stroke-width: 2;
                rx: 12px;
            }
            .wire {
                fill: none;
                stroke-linecap: square;
                stroke-linejoin: miter;
                stroke-width: 2.2;
                opacity: 0.42;
                transition: stroke-width 0.16s ease-out, opacity 0.16s ease-out, filter 0.16s ease-out;
            }
            .wire.red {
                stroke: #FF2D2D;
            }
            .wire.blue {
                stroke: #0B6E91;
                stroke-width: 4;
            }
            .wire.active {
                opacity: 1;
                stroke-dasharray: 10 7;
                animation: dash 0.9s linear infinite;
                filter: drop-shadow(0 0 3px rgba(36, 138, 61, 0.32));
            }
            .wire.active.red {
                stroke: #E11D48;
            }
            .wire.active.blue {
                stroke: #0284C7;
            }
            .wire.selected,
            .wire.selected.red,
            .wire.selected.blue {
                opacity: 1;
                stroke: #F59E0B;
                stroke-width: 5;
                stroke-dasharray: 12 6;
                animation: dash 0.65s linear infinite;
                filter: drop-shadow(0 0 5px rgba(195, 90, 0, 0.5));
                marker-end: url(#arrow-orange);
            }
            #chart.slot-pulse .wire.active,
            #chart.slot-pulse .wire.active.red,
            #chart.slot-pulse .wire.active.blue {
                opacity: 1;
                stroke-width: 5;
                filter: drop-shadow(0 0 6px rgba(0, 113, 227, 0.45));
            }
            #chart.slot-pulse .wire.selected,
            #chart.slot-pulse .wire.selected.red,
            #chart.slot-pulse .wire.selected.blue {
                opacity: 1;
                stroke-width: 6.5;
                filter: drop-shadow(0 0 8px rgba(195, 90, 0, 0.65));
            }
            #chart.slot-pulse .module.active-node rect,
            #chart.slot-pulse .module.active-node polygon {
                fill: rgba(187, 247, 208, 0.62);
                stroke-width: 3.5;
                filter: drop-shadow(0 0 8px rgba(36, 138, 61, 0.45));
            }
            #chart.slot-pulse .module.selected-node rect,
            #chart.slot-pulse .module.selected-node polygon {
                fill: rgba(253, 230, 138, 0.64);
                stroke-width: 4.5;
                filter: drop-shadow(0 0 9px rgba(195, 90, 0, 0.58));
            }
            #chart.slot-pulse #slot-glow {
                opacity: 1;
            }
            @keyframes dash {
                to { stroke-dashoffset: -34; }
            }
            #chart.flow-paused .wire.active,
            #chart.flow-paused .wire.selected {
                animation-play-state: paused;
            }
            .label-red,
            .label-blue,
            .label-black {
                font-size: 17px;
                font-weight: 700;
                paint-order: stroke;
                stroke: #FFFFFF;
                stroke-width: 4px;
                stroke-linejoin: round;
            }
            .label-red {
                fill: #E11D48;
            }
            .label-blue {
                fill: #2563EB;
            }
            .label-cyan {
                fill: #0EA5E9;
            }
            .label-black {
                fill: #1F2328;
            }
            .antenna-label {
                font-size: 18px;
                font-weight: 700;
                fill: #1F2328;
                text-anchor: middle;
            }
            .array-cell {
                fill: rgba(255, 255, 255, 0.56);
                stroke: #1F2328;
                stroke-width: 1.5;
            }
            #control-bar {
                position: absolute;
                top: 10px;
                right: 16px;
                display: flex;
                align-items: center;
                gap: 7px;
                z-index: 100;
                overflow: hidden;
                background: rgba(255, 255, 255, 0.22);
                border: 1px solid rgba(255, 255, 255, 0.62);
                border-radius: 999px;
                padding: 6px 8px;
                box-shadow:
                    0 14px 36px rgba(36, 46, 66, 0.16),
                    inset 0 1px 0 rgba(255, 255, 255, 0.98),
                    inset 0 -1px 0 rgba(125, 125, 130, 0.1);
                backdrop-filter: blur(16px) saturate(215%) contrast(104%);
                -webkit-backdrop-filter: blur(16px) saturate(215%) contrast(104%);
                animation: control-materialize 460ms 80ms cubic-bezier(0.22, 0.78, 0.18, 1) both;
            }
            #control-bar::before {
                content: "";
                position: absolute;
                inset: 0;
                border-radius: inherit;
                background: linear-gradient(155deg, rgba(255, 255, 255, 0.7), transparent 42%, rgba(255, 255, 255, 0.18));
                pointer-events: none;
            }
            @keyframes control-materialize {
                from { opacity: 0; transform: translateY(-8px) scale(0.96); filter: blur(6px); }
                to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
            }
            #control-bar button {
                position: relative;
                border: 1px solid rgba(255, 255, 255, 0.82);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.3);
                color: #1D1D1F;
                font-size: 14px;
                cursor: pointer;
                width: 34px;
                height: 34px;
                padding: 0;
                line-height: 1;
                box-shadow: 0 4px 12px rgba(36, 46, 66, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.96);
                backdrop-filter: blur(16px) saturate(170%);
                -webkit-backdrop-filter: blur(16px) saturate(170%);
                transition: transform 180ms cubic-bezier(0.22, 0.78, 0.18, 1), background-color 180ms ease-out, box-shadow 180ms ease-out;
            }
            #control-bar button:hover {
                background: rgba(255, 255, 255, 0.88);
                transform: translateY(-1px) scale(1.035);
                box-shadow: 0 7px 16px rgba(36, 46, 66, 0.14), inset 0 1px 0 #FFFFFF;
            }
            #control-bar button:active {
                transform: translateY(0) scale(0.92);
                transition-duration: 80ms;
            }
            #control-bar button:focus-visible,
            #control-bar select:focus-visible {
                outline: 3px solid rgba(0, 113, 227, 0.28);
                outline-offset: 2px;
            }
            #control-bar button.active {
                background: rgba(220, 252, 231, 0.78);
                border-color: rgba(184, 222, 191, 0.9);
                color: #176B2C;
            }
            #control-bar select {
                position: relative;
                min-height: 34px;
                border: 1px solid rgba(255, 255, 255, 0.82);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.28);
                color: #1D1D1F;
                font-size: 12px;
                padding: 4px 24px 4px 10px;
                cursor: pointer;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.96);
                backdrop-filter: blur(16px) saturate(170%);
                -webkit-backdrop-filter: blur(16px) saturate(170%);
                transition: transform 180ms cubic-bezier(0.22, 0.78, 0.18, 1), background-color 180ms ease-out;
            }
            #control-bar select:hover {
                background: rgba(255, 255, 255, 0.86);
                transform: translateY(-1px);
            }
            #slot-badge {
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: 4px;
                min-height: 32px;
                box-sizing: border-box;
                background: rgba(234, 243, 255, 0.34);
                border: 1px solid rgba(185, 216, 250, 0.82);
                border-radius: 999px;
                padding: 4px 12px;
                font-size: 13px;
                color: #0057A8;
                font-weight: 700;
                white-space: nowrap;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
            }
            #slot-badge .label {
                font-weight: 400;
                color: #6E6E73;
                font-size: 11px;
            }
            #state-badge {
                position: relative;
                display: inline-flex;
                align-items: center;
                border-right: 1px solid rgba(125, 125, 130, 0.2);
                padding-right: 10px;
                margin-right: 2px;
                color: $state_color;
                font-size: 13px;
                font-weight: 700;
                white-space: nowrap;
            }

            @media (max-width: 700px) {
                #chart {
                    min-width: 720px;
                }
                #control-bar {
                    position: absolute;
                    left: 8px;
                    right: auto;
                    width: max-content;
                    max-width: calc(100vw - 16px);
                }
            }

            @media (prefers-reduced-motion: reduce) {
                #chart,
                #control-bar {
                    animation: none;
                }
                .wire.active,
                .wire.selected {
                    animation: none;
                }
                .module rect,
                .module polygon,
                .wire,
                #control-bar button {
                    transition-duration: 0.01ms;
                }
                #chart.slot-pulse .wire.active,
                #chart.slot-pulse .wire.selected {
                    stroke-width: inherit;
                    filter: none;
                }
            }

            @media (prefers-reduced-transparency: reduce) {
                #control-bar {
                    background: #FFFFFF;
                    backdrop-filter: none;
                    -webkit-backdrop-filter: none;
                }
            }

            @media (prefers-contrast: more) {
                #control-bar,
                #control-bar button,
                #control-bar select {
                    border-color: #6E6E73;
                }
            }
        </style>
    </head>
    <body>
        <div id="chart">
            <svg viewBox="0 0 1482 800" preserveAspectRatio="xMidYMid meet" role="img" aria-label="物理架构与数据流向图">
                <defs>
                    <marker id="arrow-red" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#E11D48"></path>
                    </marker>
                    <marker id="arrow-blue" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#0284C7"></path>
                    </marker>
                    <marker id="arrow-dark" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#1F2328"></path>
                    </marker>
                    <marker id="arrow-orange" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#F59E0B"></path>
                    </marker>
                </defs>
                <rect id="slot-glow" x="80" y="26" width="1350" height="720" rx="10" fill="none" stroke="#F59E0B" stroke-width="5" opacity="0"></rect>

                <!-- Wires: clock / sync -->
                <path class="wire red $clock_edge" d="M482 86 V195" marker-end="url(#arrow-red)"></path>
                <text x="388" y="104" class="label-red">SMA/BNC</text>
                <text x="482" y="104" class="label-blue">10MHz参考信号</text>

                <path class="wire red $sync_edge" d="M596 58 H990 V196" marker-end="url(#arrow-red)"></path>
                <text x="598" y="48" class="label-blue">1PPS信号</text>
                <text x="598" y="75" class="label-red">SMA/BNC</text>

                <path class="wire red $sync_edge" d="M482 86 V127 H960 V196" marker-end="url(#arrow-red)"></path>

                <!-- Wires: transmit RF / baseband -->
                <path class="wire red $thz_tx_edge" d="M154 240 H220" marker-end="url(#arrow-red)"></path>
                <text x="178" y="229" class="label-red">WR04</text>

                <path class="wire red $thz_tx_edge" d="M775 210 H590" marker-end="url(#arrow-red)"></path>
                <text x="598" y="207" class="label-red">2.92F</text>
                <text x="735" y="207" class="label-red">SMP</text>
                <text x="632" y="242" class="label-blue">模拟基带信号</text>

                <path class="wire red $server_edge" d="M1075 235 H1255" marker-end="url(#arrow-red)"></path>
                <text x="1080" y="226" class="label-red">光口 IEEE 802.3</text>
                <text x="1080" y="256" class="label-blue">比特流</text>

                <!-- Wires: millimeter-wave sensing -->
                <path class="wire red $mmwave_edge" d="M595 366 H775" marker-end="url(#arrow-red)"></path>
                <text x="622" y="354" class="label-red">射频/中频链路</text>

                <path class="wire blue $mmwave_edge" d="M775 394 H596" marker-end="url(#arrow-blue)"></path>
                <text x="738" y="430" class="label-cyan label-blue">控制是否启用</text>

                <!-- Wires: baseband / DSP / FPGA -->
                <path class="wire blue $baseband_edge" d="M948 352 H1255" marker-end="url(#arrow-blue)"></path>
                <text x="1165" y="342" class="label-cyan label-blue">通信数据</text>

                <path class="wire blue $baseband_edge" d="M948 390 H1255" marker-end="url(#arrow-blue)"></path>
                <text x="1118" y="420" class="label-cyan label-blue">通信/感知数据</text>

                <path class="wire blue $baseband_edge" d="M1008 478 V284" marker-end="url(#arrow-blue)"></path>
                <text x="918" y="304" class="label-cyan label-blue">控制是否</text>
                <text x="918" y="328" class="label-cyan label-blue">启用</text>

                <path class="wire blue $fpga_edge" d="M1040 284 V478" marker-end="url(#arrow-blue)"></path>
                <text x="1046" y="304" class="label-cyan label-blue">通信参数（速率、调制</text>
                <text x="1046" y="328" class="label-cyan label-blue">阶数等）</text>

                <path class="wire blue $baseband_edge" d="M862 412 V478" marker-end="url(#arrow-blue)"></path>
                <text x="858" y="431" class="label-blue">速度/位置/</text>
                <text x="858" y="455" class="label-blue">角度</text>

                <path class="wire blue $baseband_edge" d="M838 478 V412" marker-end="url(#arrow-blue)"></path>
                <text x="868" y="492" class="label-cyan label-blue">通信参数</text>

                <!-- Wires: gimbal network -->
                <path class="wire red $gimbal_edge" d="M775 515 H596" marker-end="url(#arrow-red)"></path>
                <text x="600" y="511" class="label-red">RS485</text>
                <text x="610" y="543" class="label-blue">角度/速度/位置</text>

                <path class="wire blue $gimbal_feedback_edge" d="M596 567 H775" marker-end="url(#arrow-blue)"></path>
                <text x="610" y="587" class="label-cyan label-blue">是否转移到位</text>

                <path class="wire blue $state_edge" d="M1075 522 H1255" marker-end="url(#arrow-blue)"></path>
                <text x="1100" y="508" class="label-cyan label-blue">状态机当前状态</text>

                <path class="wire red $gimbal_feedback_edge" d="M411 623 V653 H1255" marker-end="url(#arrow-red)"></path>
                <text x="412" y="675" class="label-blue">角度/速度/位置</text>

                <!-- External antenna symbols -->
                <text x="86" y="202" class="antenna-label">发端窄波束</text>
                <text x="86" y="226" class="antenna-label">天线</text>
                <polygon points="116,218 155,238 116,258" fill="#111827" stroke="#111827"></polygon>

                <text x="178" y="342" class="antenna-label">相控</text>
                <text x="178" y="366" class="antenna-label">阵天线</text>
                <rect x="225" y="333" width="76" height="66" fill="#FFFFFF" stroke="#1F2328" stroke-width="2"></rect>
                <rect x="234" y="342" width="12" height="10" class="array-cell"></rect>
                <rect x="252" y="342" width="12" height="10" class="array-cell"></rect>
                <rect x="270" y="342" width="12" height="10" class="array-cell"></rect>
                <rect x="288" y="342" width="12" height="10" class="array-cell"></rect>
                <rect x="234" y="360" width="12" height="10" class="array-cell"></rect>
                <rect x="252" y="360" width="12" height="10" class="array-cell"></rect>
                <rect x="270" y="360" width="12" height="10" class="array-cell"></rect>
                <rect x="288" y="360" width="12" height="10" class="array-cell"></rect>
                <rect x="234" y="378" width="12" height="10" class="array-cell"></rect>
                <rect x="252" y="378" width="12" height="10" class="array-cell"></rect>
                <rect x="270" y="378" width="12" height="10" class="array-cell"></rect>
                <rect x="288" y="378" width="12" height="10" class="array-cell"></rect>

                <!-- Modules -->
                <g class="module $clock_node">
                    <rect x="225" y="30" width="372" height="56"></rect>
                    <text x="411" y="58">铷钟/恒温晶振模块</text>
                </g>

                <g class="module $tx_node">
                    <rect x="225" y="196" width="372" height="88"></rect>
                    <text x="332" y="240">发射机射频模块</text>
                    <rect x="440" y="209" width="86" height="60" class="dashed"></rect>
                    <text x="483" y="239" class="small">时钟源</text>
                </g>

                <g class="module $fpga_node">
                    <rect x="775" y="196" width="300" height="88"></rect>
                    <rect x="790" y="208" width="72" height="62" class="dashed"></rect>
                    <rect x="882" y="208" width="156" height="62" class="dashed"></rect>
                    <text x="826" y="239" class="small">DAC</text>
                    <text x="960" y="239" class="small">FPGA基带板</text>
                </g>

                <g class="module $mmwave_node">
                    <rect x="225" y="324" width="372" height="88"></rect>
                    <text x="434" y="368" class="small">毫米波通感系统-射频模块</text>
                </g>

                <g class="module $base_node">
                    <rect x="775" y="324" width="175" height="64"></rect>
                    <text x="862" y="356" class="small">毫米波通感系统-</text>
                    <text x="862" y="379" class="small">基带模块</text>
                </g>

                <rect x="210" y="468" width="870" height="155" class="network"></rect>
                <text x="224" y="605" class="label-black">瞄捕网络</text>

                <g class="module $gimbal_node">
                    <rect x="224" y="483" width="372" height="86"></rect>
                    <text x="410" y="526">云台</text>
                </g>

                <g class="module active-node">
                    <rect x="775" y="478" width="300" height="90"></rect>
                    <text x="925" y="523">转化模块DSP</text>
                </g>

                <g class="module $server_node">
                    <rect x="1255" y="196" width="170" height="548"></rect>
                    <text x="1340" y="218" class="small">服务器/显示器</text>
                    <text x="1340" y="244" class="small">/PC主机</text>
                    <rect x="1305" y="272" width="70" height="54" class="dashed"></rect>
                    <text x="1340" y="292" class="tiny">灌包</text>
                    <text x="1340" y="314" class="tiny">软件</text>
                </g>

                <rect x="211" y="704" width="865" height="38" class="car"></rect>
                <text x="643" y="723" class="label-black" text-anchor="middle">移动车</text>

                <line x1="220" y1="775" x2="275" y2="775" class="wire red active"></line>
                <text x="286" y="780" class="legend">物理接口/协议/线缆</text>
                <line x1="470" y1="775" x2="525" y2="775" class="wire blue active"></line>
                <text x="536" y="780" class="legend">控制、状态和业务数据内容</text>
            </svg>
        </div>
        <div id="control-bar">
            <span id="state-badge">状态: $current_state · $state_name</span>
            <button id="btn-play" onclick="togglePlay()" title="暂停" aria-label="暂停 Slot 时钟" aria-pressed="true">⏸</button>
            <select id="sel-speed" onchange="changeSpeed(this.value)" aria-label="Slot 时钟速度">
                <option value="0.5">0.5x</option>
                <option value="1" selected>1x</option>
                <option value="2">2x</option>
            </select>
            <span id="slot-badge" aria-live="polite"><span class="label">Slot</span> 0</span>
        </div>
        <script>
            var slotCount = 0;
            var isPlaying = true;
            var speed = 1.0;
            var clockInterval = null;
            var pulseTimer = null;
            var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

            function updateSlotBadge() {
                document.getElementById('slot-badge').innerHTML = '<span class="label">Slot</span> ' + slotCount;
            }

            function triggerSlotPulse() {
                if (reduceMotion) return;
                var chart = document.getElementById('chart');
                chart.classList.add('slot-pulse');
                if (pulseTimer) {
                    clearTimeout(pulseTimer);
                }
                pulseTimer = setTimeout(function() {
                    chart.classList.remove('slot-pulse');
                    pulseTimer = null;
                }, 120);
            }

            function pulseTick() {
                slotCount++;
                updateSlotBadge();
                triggerSlotPulse();
            }

            function startClock() {
                stopClock();
                var interval = Math.round(1000 / speed);
                clockInterval = setInterval(pulseTick, interval);
            }

            function stopClock() {
                if (clockInterval) {
                    clearInterval(clockInterval);
                    clockInterval = null;
                }
            }

            function togglePlay() {
                isPlaying = !isPlaying;
                var btn = document.getElementById('btn-play');
                var chart = document.getElementById('chart');
                if (isPlaying) {
                    btn.textContent = '⏸';
                    btn.title = '暂停';
                    btn.setAttribute('aria-label', '暂停 Slot 时钟');
                    btn.setAttribute('aria-pressed', 'true');
                    btn.classList.add('active');
                    chart.classList.remove('flow-paused');
                    startClock();
                } else {
                    btn.textContent = '▶';
                    btn.title = '播放';
                    btn.setAttribute('aria-label', '播放 Slot 时钟');
                    btn.setAttribute('aria-pressed', 'false');
                    btn.classList.remove('active');
                    chart.classList.add('flow-paused');
                    stopClock();
                }
            }

            function changeSpeed(val) {
                speed = parseFloat(val);
                if (isPlaying) startClock();
            }

            startClock();
            document.getElementById('btn-play').classList.add('active');
            triggerSlotPulse();
        </script>
    </body>
    </html>
    ''')

    return template.substitute(
        current_state=current_state,
        state_name=state_name,
        state_color=state_color,
        clock_edge=edge_cls("clock"),
        sync_edge=edge_cls("sync"),
        thz_tx_edge=edge_cls("thz_tx", "fpga"),
        server_edge=edge_cls("server", "fpga"),
        mmwave_edge=edge_cls("mmwave", "perception"),
        baseband_edge=edge_cls("baseband", "perception"),
        fpga_edge=edge_cls("fpga", "baseband"),
        gimbal_edge=edge_cls("gimbal"),
        gimbal_feedback_edge=edge_cls("gimbal", "gimbal_feedback"),
        state_edge=edge_cls("state_report"),
        clock_node=node_cls("clock", "sync"),
        tx_node=node_cls("thz_tx", "clock"),
        fpga_node=node_cls("fpga", "sync"),
        mmwave_node=node_cls("mmwave", "perception"),
        base_node=node_cls("baseband", "perception"),
        gimbal_node=node_cls("gimbal", "gimbal_feedback"),
        server_node=node_cls("server", "state_report", "fpga"),
    )


# ============================================================
# 辅助函数
# ============================================================

def get_available_actions(state):
    return STATE_TRANSITIONS.get(state, [])


def get_state_tone(state):
    if state == "S4":
        return "green"
    if state in {"S3", "S5"}:
        return "orange"
    return "blue"


def create_state_machine_graph(current_state):
    dot = graphviz.Digraph(comment="DSP", format="svg", engine="dot")
    dot.attr(rankdir="LR", splines="polyline", nodesep="0.5", ranksep="0.8",
             fontname="Microsoft YaHei", fontsize="11", bgcolor="transparent",
             pad="0.3", size="12,4", ratio="compress")
    dot.attr("node", fontname="Microsoft YaHei", fontsize="10", margin="0.15,0.1")

    for s in ["S0","S1","S2","S3","S4","S5"]:
        if s == current_state:
            dot.node(s, label=f"<<B><FONT POINT-SIZE='13' COLOR='#14532D'>{s}</FONT><BR/><FONT POINT-SIZE='9' COLOR='#14532D'>{STATE_NAMES[s]}</FONT><BR/><FONT POINT-SIZE='8' COLOR='#16A34A'>●</FONT></B>>",
                     shape="box", style="filled,rounded", fillcolor="#DCFCE7",
                     color="#16A34A", penwidth="2", width="1.2", height="0.6")
        else:
            dot.node(s, label=f"<<B><FONT POINT-SIZE='12' COLOR='#1F2328'>{s}</FONT><BR/><FONT POINT-SIZE='9' COLOR='#57606A'>{STATE_NAMES[s]}</FONT></B>>",
                     shape="box", style="filled,rounded", fillcolor="#FFFFFF",
                     color="#C8D1DC", penwidth="1", width="1.2", height="0.6")

    edges = [
        ("S0","S1","自检\n通过","#58A6FF"),("S1","S2","检测到\n稳定目标","#58A6FF"),
        ("S2","S3","云台\n到位","#58A6FF"),("S3","S4","锁定\n成功","#58A6FF"),
        ("S3","S5","捕获\n超时","#F85149"),("S4","S5","失锁/质量\n变差","#F85149"),
        ("S5","S2","毫米波\n恢复","#3FB950"),("S5","S1","长时间\n无恢复","#FFA657"),
    ]
    for src,dst,lbl,col in edges:
        dot.edge(src, dst, label=lbl, color=col, fontcolor=col, fontsize="8",
                 penwidth="1.5", arrowsize="0.8")
    return dot


def format_log_html(timestamp, from_s, to_s, trigger):
    return f'''<div class="log-entry">
        <span style="color:#6E6E73;">{timestamp}</span>
        <span style="color:#6E6E73;">{from_s}</span>
        <span style="color:#AEAEB2;">→</span>
        <span style="color:#248A3D;font-weight:650;">{to_s}</span>
        <span style="color:#0057A8;">{trigger}</span>
    </div>'''


def get_slot_packets(state):
    packets = [p for p in SLOT_PACKET_SPECS if state in p["states"]]
    return sorted(packets, key=lambda p: (p["phase"], p["id"]))


def split_packet_direction(direction):
    if "->" in direction:
        source, target = direction.split("->", 1)
        return source.strip(), target.strip()
    if "→" in direction:
        source, target = direction.split("→", 1)
        return source.strip(), target.strip()
    return direction.strip(), "本地处理"


def format_packet_option(packet):
    source, target = split_packet_direction(packet["direction"])
    phase = packet["phase"]
    phase_label = PHASE_LABELS.get(phase, phase)
    return f'{phase} {phase_label}｜{packet["name"]}｜{source} -> {target}'


def render_slot_packet_panel(state, selected_packet_id=None):
    import html

    packets = get_slot_packets(state)
    packet_count = len(packets)
    field_count = sum(len(p["fields"]) for p in packets)
    interfaces = sorted({p["interface"] for p in packets})
    state_tone = get_state_tone(state)

    def esc(value):
        return html.escape(str(value), quote=True)

    packet_blocks = []
    for packet in packets:
        source, target = split_packet_direction(packet["direction"])
        selected_class = " selected" if packet["id"] == selected_packet_id else ""
        phase_label = PHASE_LABELS.get(packet["phase"], packet["phase"])
        fields_html = "".join(
            f'<span class="field-pill">{esc(field)}</span>'
            for field in packet["fields"]
        )
        packet_blocks.append(
            f'<div class="slot-packet{selected_class}">'
            '<div class="slot-packet-title-row">'
            f'<div class="slot-packet-title">{esc(packet["name"])}</div>'
            f'<div class="slot-phase">{esc(packet["phase"])} · {esc(phase_label)}</div>'
            '</div>'
            '<div class="slot-route">'
            f'<div class="route-node route-source">{esc(source)}</div>'
            '<div class="route-arrow">→</div>'
            f'<div class="route-node route-target">{esc(target)}</div>'
            '</div>'
            f'<div class="slot-meta"><strong>ID：</strong>{esc(packet["id"])}</div>'
            f'<div class="slot-meta"><strong>接口：</strong>{esc(packet["interface"])}</div>'
            f'<div class="slot-meta"><strong>周期：</strong>{esc(packet["cadence"])}</div>'
            f'<div class="field-list">{fields_html}</div>'
            f'<div class="slot-purpose">{esc(packet["purpose"])}</div>'
            '</div>'
        )

    return (
        '<div class="slot-panel">'
        '<div class="slot-panel-header">'
        '<div class="slot-panel-title">当前 slot 数据包清单</div>'
        f'<div class="slot-panel-state tone-{state_tone}">{esc(state)} · {esc(STATE_NAMES[state])}</div>'
        '</div>'
        '<div class="slot-summary">'
        '<div class="slot-summary-item"><div class="slot-summary-label">包数量</div>'
        f'<div class="slot-summary-value">{packet_count}</div></div>'
        '<div class="slot-summary-item"><div class="slot-summary-label">字段数</div>'
        f'<div class="slot-summary-value">{field_count}</div></div>'
        '<div class="slot-summary-item"><div class="slot-summary-label">接口数</div>'
        f'<div class="slot-summary-value">{len(interfaces)}</div></div>'
        '</div>'
        f'{"".join(packet_blocks)}'
        '</div>'
    )


# ============================================================
# 主程序
# ============================================================

def transition_to(target_state, trigger):
    old_state = st.session_state.current_state
    st.session_state.current_state = target_state
    st.session_state.uplink_mode = UPLINK_MODE[target_state]
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state.log_messages.append({
        "time": timestamp,
        "from": old_state,
        "to": target_state,
        "trigger": trigger,
    })


def render_status_card(current):
    uplink = st.session_state.uplink_mode
    mmwave_active = uplink == "毫米波"
    thz_active = uplink == "太赫兹"
    state_tone = get_state_tone(current)
    st.markdown(f'''
    <div class="status-card" role="status" aria-live="polite">
        <div class="state-primary tone-{state_tone}">
            <div class="state-label">当前状态</div>
            <div class="state-code">{current}</div>
            <div class="state-name">{STATE_NAMES[current]}</div>
        </div>
        <div class="link-status-list">
            <div class="link-status mmwave {'active' if mmwave_active else ''}">
                <div><div class="link-label">上行链路</div><div class="link-name">毫米波</div></div>
                <div class="link-badge">{'工作中' if mmwave_active else '待机'}</div>
            </div>
            <div class="link-status thz {'active' if thz_active else ''}">
                <div><div class="link-label">上行链路</div><div class="link-name">太赫兹</div></div>
                <div class="link-badge">{'工作中' if thz_active else '待机'}</div>
            </div>
        </div>
    </div>
    <div class="state-description">{STATE_DESCRIPTIONS[current]}</div>
    ''', unsafe_allow_html=True)


def render_mission_overview(current, transition_count):
    packets = get_slot_packets(current)
    packet_count = len(packets)
    field_count = sum(len(packet["fields"]) for packet in packets)
    interface_count = len({packet["interface"] for packet in packets})
    next_actions = get_available_actions(current)
    next_state_text = " / ".join(
        f"{target} · {STATE_NAMES[target]}" for target, _, _ in next_actions
    ) or "流程结束"
    uplink = st.session_state.uplink_mode
    state_tone = get_state_tone(current)

    st.markdown(f'''
    <section class="mission-overview tone-{state_tone}">
        <div class="mission-copy">
            <div class="mission-eyebrow">DSP SIMULATOR · MISSION CONTROL</div>
            <h1 class="mission-title">瞄捕状态机</h1>
            <p class="mission-description">{STATE_DESCRIPTIONS[current]}</p>
            <div class="interface-chips" aria-label="关键接口">
                <span>10 MHz</span><span>1 PPS</span><span>RS485</span><span>IEEE 802.3</span>
            </div>
        </div>
        <div class="mission-state glass-module">
            <span class="module-kicker">当前阶段</span>
            <strong>{current}</strong>
            <b>{STATE_NAMES[current]}</b>
            <small>状态转换 {transition_count} 次</small>
        </div>
    </section>
    <section class="signal-modules" aria-label="运行摘要">
        <div class="signal-module glass-module state-module tone-{state_tone}">
            <div class="module-topline"><span>状态判决</span><i class="live-dot"></i></div>
            <strong>{current} · {STATE_NAMES[current]}</strong>
            <small>下一步 {next_state_text}</small>
        </div>
        <div class="signal-module glass-module link-module">
            <div class="module-topline"><span>当前上行</span><span class="signal-bars" aria-hidden="true"><i></i><i></i><i></i></span></div>
            <strong>{uplink}</strong>
            <small>毫米波 {'工作中' if uplink == '毫米波' else '待机'} · 太赫兹 {'工作中' if uplink == '太赫兹' else '待机'}</small>
        </div>
        <div class="signal-module glass-module packet-module">
            <div class="module-topline"><span>当前 slot</span><span>T0-T5</span></div>
            <strong>{packet_count} <em>个数据包</em></strong>
            <small>{field_count} 个字段 · {interface_count} 类接口</small>
        </div>
        <div class="signal-module glass-module session-module">
            <div class="module-topline"><span>本轮会话</span><span>LIVE</span></div>
            <strong>{transition_count} <em>次转换</em></strong>
            <small>{len(next_actions)} 条可用路径 · 当前节点 {current}</small>
        </div>
    </section>
    ''', unsafe_allow_html=True)


def render_state_rail(current):
    visited = {"S0", current}
    for message in st.session_state.log_messages:
        visited.update([message["from"], message["to"]])
    reachable = {target for target, _, _ in get_available_actions(current)}

    steps = []
    for state in ["S0", "S1", "S2", "S3", "S4", "S5"]:
        if state == current:
            status_class, status_label = "current", "当前"
        elif state in reachable:
            status_class, status_label = "reachable", "可达"
        elif state in visited:
            status_class, status_label = "visited", "已访问"
        else:
            status_class, status_label = "idle", "待机"
        steps.append(
            f'<div class="state-step {status_class}">'
            '<span class="state-node">'
            f'<b>{state}</b><i></i>'
            '</span>'
            f'<strong>{STATE_NAMES[state]}</strong>'
            f'<small>{status_label}</small>'
            '</div>'
        )

    st.markdown(
        '<section class="state-rail glass-module">'
        '<div class="rail-heading"><div><span>状态路径</span><strong>S0-S5 运行轨道</strong></div>'
        f'<small>当前 {current} · {STATE_NAMES[current]}</small></div>'
        f'<div class="state-track">{"".join(steps)}</div>'
        '</section>',
        unsafe_allow_html=True,
    )


def render_state_controls(current):
    def render_action(target, button_text, description):
        st.caption(f"下一状态 {target} · {STATE_NAMES[target]}")
        if st.button(
            button_text,
            help=description,
            icon=":material/arrow_forward:",
            key=f"btn_{current}_{target}",
            type="primary",
            width="stretch",
        ):
            transition_to(target, button_text)
            st.rerun()

    with st.container(border=True, key="state_control_dock"):
        st.markdown(f'''
        <div class="control-heading">
            <div class="control-title">状态推进</div>
            <div class="control-meta">当前节点 {current} · {STATE_NAMES[current]}</div>
        </div>
        ''', unsafe_allow_html=True)

        actions = get_available_actions(current)
        if actions:
            if len(actions) == 1:
                render_action(*actions[0])
            else:
                action_columns = st.columns(len(actions))
                for action_column, action in zip(action_columns, actions):
                    with action_column:
                        render_action(*action)
        else:
            st.info("当前状态无可用触发动作")


def render_developer_tools():
    with st.container(key="developer_tools"):
        with st.expander("开发者调试", expanded=False, icon=":material/code:"):
            jump_columns = st.columns(6)
            for index, state in enumerate(["S0", "S1", "S2", "S3", "S4", "S5"]):
                with jump_columns[index]:
                    if st.button(state, key=f"j_{state}", width="stretch"):
                        transition_to(state, "手动跳转")
                        st.rerun()
            if st.button(
                "重置系统",
                icon=":material/restart_alt:",
                type="secondary",
                width="stretch",
            ):
                st.session_state.current_state = "S0"
                st.session_state.uplink_mode = UPLINK_MODE["S0"]
                st.session_state.log_messages = []
                st.rerun()


def render_interface_table():
    with st.expander("接口信息", expanded=False, icon=":material/cable:"):
        st.markdown("""
        | 接口名称 | 方向 | 协议/物理接口 | 传输内容 | 状态机用途 |
        |----------|------|---------------|----------|------------|
        | 时钟同步接口 | 铷钟/恒温晶振 → 发射机射频模块/FPGA基带板 | SMA/BNC | 10MHz参考信号、1PPS信号 | S0自检、S3/S4太赫兹链路同步 |
        | 发射射频接口 | 发射机射频模块 → 发端窄波束天线 | WR04 | 太赫兹发射射频信号 | S3捕获、S4跟踪 |
        | 模拟基带接口 | FPGA基带板/DAC → 发射机射频模块 | SMP、2.92F | 模拟基带信号 | 太赫兹发射链路输入 |
        | 太赫兹比特流接口 | FPGA基带板 ↔ 服务器/显示器/PC主机 | 光口 IEEE 802.3 | 比特流、灌包软件数据 | 太赫兹链路调试和上层显示 |
        | 毫米波射频感知接口 | 相控阵天线/射频模块 → 毫米波通感基带模块 | 射频/中频链路 | 通感回波、目标感知数据 | S1搜索、S2粗对准、S5回退恢复 |
        | 毫米波控制接口 | 毫米波通感基带模块 → 射频模块 | 内部控制链路 | 控制是否启用 | 按状态启停毫米波感知 |
        | 太赫兹状态接口 | 毫米波通感基带模块/FPGA基带板 → DSP | 数字通信接口 | 速度、位置、角度、链路状态 | S3锁定判决、S4跟踪质量判断 |
        | 通信参数接口 | DSP → FPGA基带板/通感基带模块 | 数字通信接口 | 通信参数、速率、调制阶数、控制是否启用 | 捕获和跟踪阶段配置链路 |
        | 云台控制接口 | DSP → 云台 | RS485 | 角度、速度、位置控制量 | S2粗对准、S4微调 |
        | 云台反馈接口 | 云台 → DSP | RS485/反馈链路 | 当前角度、速度、位置、是否转移到位 | 判断云台是否到位 |
        | 状态上报接口 | DSP → 服务器/显示器/PC主机 | 上层通信链路 | 状态机当前状态、失锁/恢复状态 | 页面显示和上层调度 |
        """)


def main():
    if "current_state" not in st.session_state:
        st.session_state.current_state = "S0"
    if "log_messages" not in st.session_state:
        st.session_state.log_messages = []
    if "uplink_mode" not in st.session_state:
        st.session_state.uplink_mode = UPLINK_MODE["S0"]

    current = st.session_state.current_state
    transition_count = len(st.session_state.log_messages)
    state_tone = get_state_tone(current)

    st.markdown(f'''
    <nav class="product-nav" aria-label="产品导航">
        <div class="product-nav-inner">
            <div class="product-name">DSP Simulator</div>
            <div class="product-nav-status" role="status" aria-live="polite">
                <span><i class="status-dot tone-{state_tone}"></i>{current} · {STATE_NAMES[current]}</span>
                <span>转换 {transition_count}</span>
            </div>
        </div>
    </nav>
    ''', unsafe_allow_html=True)

    render_mission_overview(current, transition_count)

    rail_column, control_column = st.columns([1.55, 1], gap="medium")
    with rail_column:
        render_state_rail(current)
    with control_column:
        render_state_controls(current)

    st.markdown('<div class="workspace-spacer"></div>', unsafe_allow_html=True)
    architecture_tab, topology_tab, records_tab = st.tabs(
        ["架构与数据包", "状态拓扑", "运行记录"],
        default="架构与数据包",
    )

    import streamlit.components.v1 as components

    with architecture_tab:
        st.markdown(f'''
        <div class="section-heading">
            <div class="section-title">物理架构与数据流向</div>
            <div class="section-meta">当前状态 {current} · {STATE_NAMES[current]}</div>
        </div>
        ''', unsafe_allow_html=True)

        packets_for_current = get_slot_packets(current)
        packet_options = [""] + [packet["id"] for packet in packets_for_current]
        packet_by_id = {packet["id"]: packet for packet in packets_for_current}
        architecture_column, packet_column = st.columns([2.25, 1], gap="large")

        with packet_column:
            selected_packet_id = st.selectbox(
                "链路高亮",
                options=packet_options,
                format_func=lambda packet_id: "当前状态全部链路"
                if not packet_id else format_packet_option(packet_by_id[packet_id]),
                key=f"packet_highlight_{current}",
            )

        with architecture_column:
            components.html(
                generate_architecture_echarts(current, selected_packet_id or None),
                height=620,
                scrolling=True,
            )

        with packet_column:
            st.markdown(
                render_slot_packet_panel(current, selected_packet_id or None),
                unsafe_allow_html=True,
            )

    with topology_tab:
        st.markdown(f'''
        <div class="section-heading">
            <div class="section-title">状态转移拓扑</div>
            <div class="section-meta">当前节点 {current} · {STATE_NAMES[current]}</div>
        </div>
        ''', unsafe_allow_html=True)
        st.graphviz_chart(
            create_state_machine_graph(current),
            width="stretch",
            height=390,
        )
        st.markdown('''
        <div class="topology-legend">
            <span class="legend-item"><span class="legend-swatch dot current"></span>当前状态</span>
            <span class="legend-item"><span class="legend-swatch dot other"></span>其他状态</span>
            <span class="legend-item"><span class="legend-swatch"></span>正常转移</span>
            <span class="legend-item"><span class="legend-swatch error"></span>异常转移</span>
            <span class="legend-item"><span class="legend-swatch restore"></span>恢复转移</span>
        </div>
        ''', unsafe_allow_html=True)

    with records_tab:
        log_column, state_column = st.columns([2, 1], gap="large")
        with log_column:
            st.subheader("系统运行日志")
            log_html = '<div class="log-console">'
            if not st.session_state.log_messages:
                log_html += '<div style="color:#8C959F;text-align:center;padding:20px;">等待状态变更...</div>'
            else:
                for message in st.session_state.log_messages:
                    log_html += format_log_html(
                        message["time"],
                        message["from"],
                        message["to"],
                        message["trigger"],
                    )
            log_html += '</div>'
            st.markdown(log_html, unsafe_allow_html=True)

            clear_column, download_column = st.columns(2)
            with clear_column:
                if st.button(
                    "清空日志",
                    icon=":material/delete:",
                    disabled=not st.session_state.log_messages,
                    width="stretch",
                ):
                    st.session_state.log_messages = []
                    st.rerun()
            with download_column:
                log_text = "\n".join(
                    f"[{message['time']}] {message['from']}->{message['to']} | {message['trigger']}"
                    for message in st.session_state.log_messages
                )
                st.download_button(
                    "下载日志",
                    log_text or "无日志",
                    "dsp_log.txt",
                    "text/plain",
                    icon=":material/download:",
                    disabled=not st.session_state.log_messages,
                    on_click="ignore",
                    width="stretch",
                )

        with state_column:
            st.subheader("当前状态")
            st.info(f"**{STATE_NAMES_CN[current]}**：{STATE_DESCRIPTIONS[current]}")

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        render_interface_table()
        render_developer_tools()


if __name__ == "__main__":
    main()
