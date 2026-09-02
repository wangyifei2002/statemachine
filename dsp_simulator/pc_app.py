"""PC upper-computer Streamlit app and launcher."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from collections import deque
from html import escape
from pathlib import Path
from typing import Any

from common.protocol import (
    MODULE_DSP,
    MODULE_GIMBAL,
    MODULE_MMWAVE,
    MODULE_PC,
    MODULE_THZ,
    PKT_MMW_BITSTREAM,
    PKT_THZ_BITSTREAM,
    PKT_UPLINK_STATE,
    SIM_SET_FAULT,
    SIM_SET_GIMBAL,
    SIM_SET_TARGET,
    SIM_SET_THZ_LINK,
    TRIGGER_EVENT,
    TRIGGER_PERIODIC,
    make_control,
    message_kind,
    message_trigger_type,
)
from common.definitions import STATE_NAMES
from common.transport import JsonLineServer, Peer, send_message_once
from common.visualization import create_state_machine_graph, generate_architecture_html


class PcHub:
    def __init__(self, host: str, port: int, max_messages: int = 300):
        self.host = host
        self.port = port
        self.messages: deque[dict[str, Any]] = deque(maxlen=max_messages)
        self.latest_state: dict[str, Any] = {}
        self.module_health: dict[str, bool] = {}
        self.module_health_detail: dict[str, dict[str, Any]] = {}
        self.uplink_data: dict[str, dict[str, Any]] = {}
        self.last_dsp_seen_ms: int = 0
        self._lock = threading.Lock()
        self._server = JsonLineServer(host, port, self._on_message, "pc-hub")
        self._server.start_background()

    def _on_message(self, message: dict[str, Any], peer: Peer):
        with self._lock:
            self.messages.append(message)
            packet_id = message.get("packet_id")
            if packet_id == PKT_UPLINK_STATE:
                self.latest_state = message.get("payload", {})
                self.module_health = dict(self.latest_state.get("module_health", {}))
                self.module_health_detail = dict(self.latest_state.get("module_health_detail", {}))
                self.last_dsp_seen_ms = int(time.time() * 1000)
            elif packet_id in {PKT_MMW_BITSTREAM, PKT_THZ_BITSTREAM}:
                payload = dict(message.get("payload", {}))
                payload["packet_id"] = packet_id
                payload["src"] = message.get("src")
                payload["slot_id"] = message.get("slot_id")
                payload["timestamp_ms"] = message.get("timestamp_ms")
                self.uplink_data[str(message.get("src"))] = payload
        return None

    def record_local_message(self, message: dict[str, Any], delivered: bool) -> None:
        local_message = dict(message)
        local_message["local_status"] = "sent" if delivered else "send_failed"
        with self._lock:
            self.messages.append(local_message)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "messages": list(self.messages),
                "latest_state": dict(self.latest_state),
                "module_health": dict(self.module_health),
                "module_health_detail": {key: dict(value) for key, value in self.module_health_detail.items()},
                "last_dsp_seen_ms": self.last_dsp_seen_ms,
                "uplink_data": {key: dict(value) for key, value in self.uplink_data.items()},
            }


def parse_launcher_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC upper-computer launcher")
    parser.add_argument("--_streamlit", action="store_true")
    parser.add_argument("--mode", choices=["sim", "deploy"], default="sim")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--pc-port", type=int, default=9104)
    parser.add_argument("--gimbal-port", type=int, default=9101)
    parser.add_argument("--mmwave-port", type=int, default=9102)
    parser.add_argument("--thz-port", type=int, default=9103)
    return parser.parse_known_args()[0]


def launch_streamlit(args: argparse.Namespace) -> None:
    script = Path(__file__).resolve()
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script),
        "--",
        "--_streamlit",
        "--mode",
        args.mode,
        "--host",
        args.host,
        "--pc-port",
        str(args.pc_port),
        "--gimbal-port",
        str(args.gimbal_port),
        "--mmwave-port",
        str(args.mmwave_port),
        "--thz-port",
        str(args.thz_port),
    ]
    raise SystemExit(subprocess.call(cmd))


def running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx() is not None


def run_streamlit_app(args: argparse.Namespace) -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.set_page_config(page_title="DSP 仿真 PC 上位机", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1720px;
            padding: 0.95rem 1.5rem 1.4rem;
        }
        .stApp, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 10% -8%, rgba(0, 122, 255, 0.12), transparent 34%),
                radial-gradient(circle at 92% 0%, rgba(52, 199, 89, 0.10), transparent 30%),
                radial-gradient(circle at 56% 112%, rgba(124, 58, 237, 0.09), transparent 36%),
                #F5F5F7;
            color: #1D1D1F;
        }
        html, body, .stApp {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
        }
        header[data-testid="stHeader"] {
            height: 0;
            background: transparent;
        }
        [data-testid="stToolbar"] {
            display: none;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 0.75rem;
        }
        .dashboard-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.6rem 0.72rem;
            border: 1px solid rgba(255, 255, 255, 0.82);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.72);
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.07), inset 0 1px 0 rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(18px);
            margin-bottom: 0.7rem;
        }
        .traffic-lights {
            display: inline-flex;
            align-items: center;
            gap: 0.43rem;
            min-width: 4.8rem;
        }
        .traffic-lights span {
            width: 0.72rem;
            height: 0.72rem;
            border-radius: 999px;
            display: inline-block;
            box-shadow: inset 0 -1px 1px rgba(0, 0, 0, 0.14);
        }
        .traffic-red { background: #FF5F57; }
        .traffic-yellow { background: #FFBD2E; }
        .traffic-green { background: #28C840; }
        .dashboard-title {
            margin: 0;
            color: #1D1D1F;
            font-size: 1rem !important;
            line-height: 1.2;
            font-weight: 720 !important;
            padding: 0 !important;
            flex: 1;
            text-align: center;
        }
        .dashboard-meta {
            color: #6E6E73;
            display: inline-flex;
            justify-content: flex-end;
            gap: 0.38rem;
            font-size: 0.72rem;
            min-width: 18rem;
            white-space: nowrap;
        }
        .meta-pill {
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.68);
            padding: 0.18rem 0.48rem;
        }
        .kpi-grid, .module-grid {
            display: grid;
            gap: 0.62rem;
            margin-bottom: 0.62rem;
        }
        .kpi-grid {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .module-grid {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .kpi-card, .module-card {
            border: 1px solid rgba(255, 255, 255, 0.86);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.78);
            padding: 0.62rem 0.78rem;
            min-height: 4.78rem;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.85);
        }
        .kpi-label, .module-label {
            color: #6E6E73;
            font-size: 0.72rem;
            line-height: 1.1;
            margin-bottom: 0.28rem;
        }
        .kpi-value {
            color: #1D1D1F;
            font-size: 1.18rem;
            line-height: 1.2;
            font-weight: 740;
            word-break: break-word;
        }
        .kpi-sub {
            color: #86868B;
            font-size: 0.72rem;
            margin-top: 0.18rem;
        }
        .module-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
        }
        .module-name {
            color: #1D1D1F;
            font-size: 0.88rem;
            line-height: 1.15;
            font-weight: 700;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.1rem 0.45rem;
            font-size: 0.66rem;
            font-weight: 760;
            border: 1px solid transparent;
        }
        .badge-online {
            color: #0A7A32;
            background: rgba(52, 199, 89, 0.16);
            border-color: rgba(52, 199, 89, 0.26);
        }
        .badge-offline {
            color: #B42318;
            background: rgba(255, 59, 48, 0.13);
            border-color: rgba(255, 59, 48, 0.22);
        }
        .badge-ok {
            color: #047857;
            background: rgba(52, 199, 89, 0.16);
            border-color: rgba(52, 199, 89, 0.26);
        }
        .badge-warn {
            color: #B45309;
            background: rgba(255, 159, 10, 0.16);
            border-color: rgba(245, 158, 11, 0.28);
        }
        .badge-bad {
            color: #B42318;
            background: rgba(255, 59, 48, 0.13);
            border-color: rgba(255, 59, 48, 0.22);
        }
        .badge-idle {
            color: #52525B;
            background: rgba(142, 142, 147, 0.13);
            border-color: rgba(142, 142, 147, 0.22);
        }
        .badge-info {
            color: #1D4ED8;
            background: rgba(0, 122, 255, 0.10);
            border-color: rgba(0, 122, 255, 0.20);
        }
        .module-io {
            color: #6E6E73;
            display: grid;
            gap: 0.2rem;
            margin-top: 0.4rem;
            font-size: 0.68rem;
        }
        .io-row {
            display: grid;
            grid-template-columns: 2.2rem minmax(0, 1fr);
            gap: 0.35rem;
            align-items: start;
        }
        .io-label {
            color: #424245;
            font-weight: 700;
        }
        .io-text {
            color: #3A3A3C;
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
        }
        .section-title {
            color: #1D1D1F;
            font-size: 0.94rem;
            line-height: 1.2;
            font-weight: 760;
            margin: 0.08rem 0 0.34rem;
        }
        iframe {
            border-radius: 30px;
            box-shadow: 0 24px 80px rgba(15, 23, 42, 0.075);
        }
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {
            background: rgba(232, 232, 237, 0.75);
            border: 1px solid rgba(209, 213, 219, 0.65);
            border-radius: 999px;
            padding: 0.18rem;
            gap: 0.14rem;
            width: fit-content;
        }
        div[data-testid="stTabs"] [role="tab"] {
            color: #424245;
            font-weight: 650;
            border-radius: 999px;
            padding: 0.3rem 0.72rem;
        }
        div[data-testid="stTabs"] [aria-selected="true"] {
            color: #1D1D1F;
            background: rgba(255, 255, 255, 0.92);
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12);
        }
        .stButton button {
            border-radius: 13px;
            background: rgba(255, 255, 255, 0.78);
            color: #1D1D1F;
            border: 1px solid rgba(148, 163, 184, 0.38);
            font-weight: 650;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.78), 0 5px 14px rgba(15, 23, 42, 0.04);
        }
        .stButton button:hover {
            color: #0066CC;
            border-color: rgba(0, 102, 204, 0.26);
            background: rgba(255, 255, 255, 0.95);
        }
        div[data-testid="stTabs"] button {
            padding-top: 0.42rem;
            padding-bottom: 0.42rem;
        }
        .data-card, .packet-card {
            border: 1px solid rgba(255, 255, 255, 0.86);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.78);
            padding: 0.7rem 0.78rem;
            min-height: 9.2rem;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.055), inset 0 1px 0 rgba(255, 255, 255, 0.85);
        }
        .data-title {
            color: #1D1D1F;
            font-size: 0.86rem;
            font-weight: 730;
            margin-bottom: 0.55rem;
        }
        .kv-list {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.38rem 0.58rem;
        }
        .kv-item {
            border-radius: 12px;
            background: rgba(245, 245, 247, 0.82);
            padding: 0.45rem 0.5rem;
            overflow: hidden;
        }
        .kv-key {
            color: #86868B;
            font-size: 0.66rem;
            margin-bottom: 0.08rem;
        }
        .kv-value {
            color: #1D1D1F;
            font-size: 0.76rem;
            font-weight: 680;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .uplink-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem;
        }
        .packet-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 0.34rem;
            font-size: 0.72rem;
        }
        .packet-table th {
            color: #86868B;
            font-weight: 700;
            text-align: left;
            padding: 0 0.5rem 0.12rem;
        }
        .packet-table td {
            color: #2C2C2E;
            background: rgba(245, 245, 247, 0.82);
            padding: 0.42rem 0.5rem;
            border-top: 1px solid rgba(229, 229, 234, 0.55);
            border-bottom: 1px solid rgba(229, 229, 234, 0.55);
            max-width: 18rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .packet-table td:first-child {
            border-left: 1px solid rgba(229, 229, 234, 0.55);
            border-radius: 11px 0 0 11px;
        }
        .packet-table td:last-child {
            border-right: 1px solid rgba(229, 229, 234, 0.55);
            border-radius: 0 11px 11px 0;
        }
        .trigger-chip {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.08rem 0.42rem;
            font-size: 0.66rem;
            font-weight: 700;
            background: rgba(0, 122, 255, 0.1);
            color: #0066CC;
        }
        .trigger-periodic {
            background: rgba(142, 142, 147, 0.12);
            color: #636366;
        }
        .empty-panel {
            color: #86868B;
            border-radius: 14px;
            background: rgba(245, 245, 247, 0.82);
            padding: 1.25rem;
            text-align: center;
            font-size: 0.78rem;
        }
        .packet-split {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.65rem;
        }
        .packet-panel-title {
            color: #1D1D1F;
            font-size: 0.82rem;
            font-weight: 730;
            margin-bottom: 0.25rem;
        }
        .console-frame {
            min-height: 100vh;
            background:
                radial-gradient(circle at 18% 0%, rgba(0, 122, 255, 0.10), transparent 28%),
                radial-gradient(circle at 86% 8%, rgba(52, 199, 89, 0.10), transparent 30%),
                linear-gradient(180deg, #F8FAFC 0%, #EEF2F7 100%);
            border-radius: 30px;
            padding: 1rem;
        }
        .topbar {
            align-items: center;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(255, 255, 255, 0.86);
            border-radius: 28px;
            box-shadow: 0 18px 60px rgba(15, 23, 42, 0.07);
            display: grid;
            grid-template-columns: 9rem 1fr minmax(18rem, auto);
            gap: 1rem;
            padding: 0.72rem 0.86rem;
            margin-bottom: 0.85rem;
            backdrop-filter: blur(20px);
        }
        .topbar-title {
            color: #18181B;
            font-size: 1.12rem;
            font-weight: 830;
            letter-spacing: -0.01em;
            text-align: center;
        }
        .topbar-sub {
            color: #71717A;
            display: block;
            font-size: 0.68rem;
            font-weight: 600;
            margin-top: 0.1rem;
        }
        .panel {
            background: rgba(255, 255, 255, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.76);
            border-radius: 32px;
            box-shadow: 0 24px 80px rgba(15, 23, 42, 0.075), inset 0 1px 0 rgba(255, 255, 255, 0.78);
            padding: 1.25rem;
            backdrop-filter: blur(20px);
        }
        .section-head {
            align-items: flex-start;
            display: flex;
            gap: 0.78rem;
            margin-bottom: 0.85rem;
        }
        .section-icon {
            align-items: center;
            background: #18181B;
            border-radius: 16px;
            color: #FFFFFF;
            display: flex;
            flex: 0 0 auto;
            font-size: 0.74rem;
            font-weight: 850;
            height: 2.35rem;
            justify-content: center;
            letter-spacing: 0.02em;
            width: 2.35rem;
        }
        .section-heading {
            color: #18181B;
            font-size: 0.98rem;
            font-weight: 820;
            line-height: 1.2;
        }
        .section-desc {
            color: #71717A;
            font-size: 0.72rem;
            line-height: 1.5;
            margin-top: 0.15rem;
        }
        .hero-grid {
            display: grid;
            grid-template-columns: 1.45fr 0.9fr 0.95fr;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .state-hero {
            align-items: center;
            display: grid;
            gap: 1.2rem;
            grid-template-columns: minmax(0, 1fr) 17rem;
            overflow: hidden;
            position: relative;
        }
        .state-hero::after {
            background:
                radial-gradient(circle, rgba(16, 185, 129, 0.20), transparent 62%),
                radial-gradient(circle, rgba(59, 130, 246, 0.16), transparent 70%);
            content: "";
            height: 18rem;
            pointer-events: none;
            position: absolute;
            right: -6rem;
            top: -7rem;
            width: 18rem;
        }
        .state-hero > * {
            position: relative;
            z-index: 1;
        }
        .state-label {
            align-items: center;
            color: #71717A;
            display: flex;
            font-size: 0.78rem;
            font-weight: 760;
            gap: 0.45rem;
            margin-bottom: 0.55rem;
        }
        .state-code {
            color: #18181B;
            display: inline-block;
            font-size: 6rem;
            font-weight: 920;
            letter-spacing: -0.06em;
            line-height: 0.82;
            margin-right: 0.7rem;
        }
        .state-name {
            color: #047857;
            display: inline-block;
            font-size: 2.45rem;
            font-weight: 900;
            letter-spacing: -0.03em;
        }
        .state-reason {
            color: #52525B;
            font-size: 0.82rem;
            line-height: 1.65;
            margin-top: 0.75rem;
        }
        .state-reason strong {
            color: #18181B;
        }
        .state-transition-bar {
            background: #18181B;
            border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 24px;
            box-shadow: 0 18px 60px rgba(15, 23, 42, 0.18);
            color: #F4F4F5;
            margin-top: 1rem;
            padding: 0.92rem 1rem;
        }
        .state-transition-label {
            color: #A1A1AA;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }
        .state-transition-text {
            color: #FAFAFA;
            font-size: 0.92rem;
            font-weight: 760;
            line-height: 1.55;
            margin-top: 0.28rem;
        }
        .mini-metrics {
            display: grid;
            gap: 0.55rem;
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .metric-tile {
            background: rgba(244, 244, 245, 0.86);
            border: 1px solid rgba(228, 228, 231, 0.74);
            border-radius: 22px;
            padding: 0.78rem;
        }
        .metric-label {
            color: #71717A;
            font-size: 0.72rem;
            font-weight: 650;
        }
        .metric-value {
            color: #18181B;
            font-size: 1.45rem;
            font-weight: 880;
            letter-spacing: -0.03em;
            margin-top: 0.35rem;
        }
        .metric-value.green { color: #047857; }
        .metric-value.blue { color: #1D4ED8; }
        .metric-value.red { color: #B42318; }
        .metric-sub {
            color: #71717A;
            font-size: 0.68rem;
            margin-top: 0.15rem;
        }
        .link-progress {
            background: rgba(244, 244, 245, 0.84);
            border: 1px solid rgba(24, 24, 27, 0.05);
            border-radius: 26px;
            margin-top: 1rem;
            padding: 0.92rem;
        }
        .link-progress-head {
            align-items: center;
            color: #71717A;
            display: flex;
            font-size: 0.72rem;
            font-weight: 800;
            justify-content: space-between;
            margin-bottom: 0.55rem;
        }
        .link-progress-track {
            background: rgba(212, 212, 216, 0.72);
            border-radius: 999px;
            height: 0.62rem;
            overflow: hidden;
        }
        .link-progress-fill {
            background: linear-gradient(90deg, #2563EB, #10B981);
            border-radius: 999px;
            height: 100%;
        }
        .diagnosis-dark {
            background: rgba(255, 255, 255, 0.75);
            color: #18181B;
        }
        .diagnosis-dark .section-icon {
            background: #18181B;
        }
        .diagnosis-dark .section-heading {
            color: #18181B;
        }
        .diagnosis-dark .section-desc {
            color: #71717A;
        }
        .diagnosis-box {
            background: rgba(236, 253, 245, 0.80);
            border: 1px solid rgba(16, 185, 129, 0.18);
            border-radius: 26px;
            padding: 1.05rem;
        }
        .diagnosis-label {
            color: #047857;
            font-size: 0.78rem;
            font-weight: 780;
            margin-bottom: 0.45rem;
        }
        .diagnosis-value {
            color: #065F46;
            font-size: 1.08rem;
            font-weight: 860;
            line-height: 1.4;
        }
        .online-panel {
            align-items: center;
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.78rem;
        }
        .online-title {
            color: #18181B;
            font-size: 0.95rem;
            font-weight: 850;
        }
        .online-sub {
            color: #71717A;
            font-size: 0.72rem;
            margin-top: 0.18rem;
        }
        .module-card-rich {
            min-height: 14.8rem;
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }
        .module-card-rich:hover {
            box-shadow: 0 32px 90px rgba(15, 23, 42, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.80);
            transform: translateY(-2px);
        }
        .module-card-rich.status-ok {
            border-color: rgba(52, 199, 89, 0.28);
        }
        .module-card-rich.status-warn {
            border-color: rgba(245, 158, 11, 0.34);
        }
        .module-card-rich.status-bad {
            border-color: rgba(255, 59, 48, 0.32);
        }
        .module-card-rich.status-info {
            border-color: rgba(0, 122, 255, 0.26);
        }
        .module-card-rich.status-bad .module-icon {
            background: #B42318;
        }
        .module-card-rich.status-warn .module-icon {
            background: #B45309;
        }
        .module-card-rich.status-info .module-icon {
            background: #1D4ED8;
        }
        .module-title-row {
            align-items: center;
            display: flex;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0.85rem;
        }
        .module-title-main {
            align-items: center;
            display: flex;
            gap: 0.72rem;
        }
        .module-icon {
            align-items: center;
            background: #18181B;
            border-radius: 16px;
            color: #FFFFFF;
            display: flex;
            font-size: 0.72rem;
            font-weight: 880;
            height: 2.55rem;
            justify-content: center;
            width: 2.55rem;
        }
        .module-title {
            color: #18181B;
            font-size: 1.02rem;
            font-weight: 880;
        }
        .module-caption {
            color: #71717A;
            font-size: 0.7rem;
            margin-top: 0.1rem;
        }
        .module-status-line {
            color: #52525B;
            font-size: 0.72rem;
            font-weight: 650;
            margin-top: 0.22rem;
        }
        .io-grid-rich {
            display: grid;
            gap: 0.72rem;
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .io-box {
            border-radius: 26px;
            min-height: 8.7rem;
            padding: 0.78rem;
        }
        .io-box.input {
            background: rgba(250, 250, 250, 0.76);
            border: 1px solid rgba(24, 24, 27, 0.05);
        }
        .io-box.output {
            background: #18181B;
            color: #FFFFFF;
        }
        .io-box-title {
            color: #71717A;
            font-size: 0.72rem;
            font-weight: 820;
            margin-bottom: 0.62rem;
        }
        .io-box.output .io-box-title {
            color: #D4D4D8;
        }
        .io-list {
            display: grid;
            gap: 0.42rem;
        }
        .io-list-item {
            align-items: flex-start;
            color: #27272A;
            display: flex;
            font-size: 0.78rem;
            gap: 0.45rem;
            line-height: 1.35;
        }
        .io-box.output .io-list-item {
            color: #F4F4F5;
        }
        .io-dot {
            background: #A1A1AA;
            border-radius: 999px;
            flex: 0 0 auto;
            height: 0.44rem;
            margin-top: 0.36rem;
            width: 0.44rem;
        }
        .io-arrow {
            color: #6EE7B7;
            flex: 0 0 auto;
            font-weight: 900;
        }
        .module-rich-grid {
            display: grid;
            gap: 1rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin-bottom: 1rem;
        }
        .content-grid {
            display: grid;
            gap: 0.85rem;
            grid-template-columns: minmax(0, 2fr) minmax(27rem, 1fr);
            margin-bottom: 0.85rem;
        }
        .side-stack {
            display: grid;
            gap: 0.85rem;
            align-content: start;
        }
        .business-grid {
            display: grid;
            gap: 0.85rem;
            grid-template-columns: minmax(25rem, 1fr) minmax(0, 2.2fr);
            margin-bottom: 0.85rem;
        }
        .secondary-grid {
            display: grid;
            gap: 0.72rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .secondary-item {
            background: rgba(244, 244, 245, 0.84);
            border: 1px solid rgba(228, 228, 231, 0.72);
            border-radius: 22px;
            padding: 0.82rem;
        }
        .secondary-title {
            color: #18181B;
            font-size: 0.82rem;
            font-weight: 840;
        }
        .secondary-desc {
            color: #71717A;
            font-size: 0.7rem;
            line-height: 1.5;
            margin-top: 0.35rem;
        }
        @media (max-width: 1100px) {
            .kpi-grid, .module-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .dashboard-header {
                align-items: flex-start;
                flex-direction: column;
            }
            .dashboard-meta {
                text-align: left;
                white-space: normal;
                min-width: 0;
                flex-wrap: wrap;
            }
            .uplink-grid, .packet-split {
                grid-template-columns: 1fr;
            }
            .topbar, .hero-grid, .state-hero, .module-rich-grid, .content-grid, .business-grid, .secondary-grid {
                grid-template-columns: 1fr;
            }
            .io-grid-rich {
                grid-template-columns: 1fr;
            }
            .online-panel {
                align-items: flex-start;
                flex-direction: column;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    @st.cache_resource
    def get_hub(host: str, port: int) -> PcHub:
        return PcHub(host, port)

    hub = get_hub(args.host, args.pc_port)
    data = hub.snapshot()
    latest = data["latest_state"]
    module_health = data["module_health"]
    module_health_detail = data["module_health_detail"]
    uplink_data = data["uplink_data"]
    slot_io = latest.get("slot_io", {}) if isinstance(latest.get("slot_io", {}), dict) else {}
    dsp_online = bool(data["last_dsp_seen_ms"]) and (int(time.time() * 1000) - data["last_dsp_seen_ms"] < 3000)
    current_state = latest.get("state_id") or "S0"
    slot_hz = float(latest.get("slot_hz") or 1.0)
    refresh_ms = int(1000 / max(slot_hz, 0.1))

    def kpi_card(label: str, value: Any, sub: Any = "") -> str:
        return (
            "<div class='kpi-card'>"
            f"<div class='kpi-label'>{escape(str(label))}</div>"
            f"<div class='kpi-value'>{escape(str(value))}</div>"
            f"<div class='kpi-sub'>{escape(str(sub))}</div>"
            "</div>"
        )

    def compact_value(value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, float):
            return f"{value:.2f}".rstrip("0").rstrip(".")
        if value is None:
            return "-"
        return str(value)

    def flag(value: Any) -> str:
        return "开" if bool(value) else "关"

    def fmt_pair(azimuth: Any, elevation: Any) -> str:
        return f"{compact_value(azimuth)}/{compact_value(elevation)}"

    def module_io_text(module: str, direction: str, value: Any) -> str:
        if not isinstance(value, dict) or not value:
            return "等待slot包"
        if module == MODULE_DSP:
            if direction == "input":
                mmw = value.get("mmwave", {})
                gimbal = value.get("gimbal", {})
                thz = value.get("thz", {})
                return (
                    f"目标{flag(mmw.get('target_valid'))} SNR {compact_value(mmw.get('snr_db'))} | "
                    f"云台到位{flag(gimbal.get('in_position'))} 误差 {compact_value(gimbal.get('position_error_mdeg'))} | "
                    f"THz锁定{flag(thz.get('lock_flag'))} 质量 {compact_value(thz.get('link_quality'))}"
                )
            mmw = value.get("mmwave", {})
            gimbal = value.get("gimbal", {})
            thz = value.get("thz", {})
            pc = value.get("pc", {})
            return (
                f"毫米波 {mmw.get('scan_mode', '-')} 感知{flag(mmw.get('sense_enable'))}/通信{flag(mmw.get('comm_enable'))} | "
                f"云台{flag(gimbal.get('enable'))} | THz业务{flag(thz.get('traffic_enable'))} | 上报 {pc.get('state_id', '-')}"
            )
        if module == MODULE_GIMBAL:
            if direction == "input":
                return (
                    f"使能{flag(value.get('enable'))} | 目标角 {fmt_pair(value.get('target_azimuth_mdeg'), value.get('target_elevation_mdeg'))} | "
                    f"微调{flag(value.get('fine_tune_enable'))}"
                )
            return (
                f"到位{flag(value.get('in_position'))} | 当前角 {fmt_pair(value.get('current_azimuth_mdeg'), value.get('current_elevation_mdeg'))} | "
                f"误差 {compact_value(value.get('position_error_mdeg'))}"
            )
        if module == MODULE_MMWAVE:
            if direction == "input":
                return (
                    f"射频{flag(value.get('rf_enable'))} 感知{flag(value.get('sense_enable'))} 通信{flag(value.get('comm_enable'))} | "
                    f"模式 {value.get('scan_mode', '-')}"
                )
            detect = value.get("detect", {})
            link = value.get("link", {})
            return (
                f"目标{flag(detect.get('target_valid'))} SNR {compact_value(detect.get('snr_db'))} 距离 {compact_value(detect.get('range_m'))}m | "
                f"上行{flag(link.get('uplink_ready'))} 质量 {compact_value(link.get('link_quality'))}"
            )
        if module == MODULE_THZ:
            if direction == "input":
                return (
                    f"启用{flag(value.get('thz_enable'))} 感知{flag(value.get('sense_enable'))} 通信{flag(value.get('comm_enable'))} | "
                    f"业务{flag(value.get('traffic_enable'))}"
                )
            return (
                f"锁定{flag(value.get('lock_flag'))} | 链路 {compact_value(value.get('link_quality'))} | "
                f"感知 {compact_value(value.get('sense_quality'))} | 丢失 {compact_value(value.get('loss_count'))}"
            )
        return str(value)

    def module_card(module: str, label: str, online: bool) -> str:
        io = slot_io.get(module, {}) if isinstance(slot_io.get(module, {}), dict) else {}
        input_text = module_io_text(module, "input", io.get("input"))
        output_text = module_io_text(module, "output", io.get("output"))
        status_class = "badge-online" if online else "badge-offline"
        status_text = "ONLINE" if online else "OFFLINE"
        return (
            "<div class='module-card'>"
            "<div class='module-head'>"
            f"<div class='module-name'>{escape(label)}</div>"
            f"<span class='badge {status_class}'>{status_text}</span>"
            "</div>"
            "<div class='module-io'>"
            f"<div class='io-row'><span class='io-label'>输入</span><span class='io-text'>{escape(input_text)}</span></div>"
            f"<div class='io-row'><span class='io-label'>输出</span><span class='io-text'>{escape(output_text)}</span></div>"
            "</div>"
            "</div>"
        )

    def split_io_items(text: str) -> list[str]:
        return [item.strip() for item in text.split("|") if item.strip()] or ["等待slot包"]

    def section_head_html(code: str, title: str, desc: str = "") -> str:
        desc_html = f"<div class='section-desc'>{escape(desc)}</div>" if desc else ""
        return (
            "<div class='section-head'>"
            f"<div class='section-icon'>{escape(code)}</div>"
            "<div>"
            f"<div class='section-heading'>{escape(title)}</div>"
            f"{desc_html}"
            "</div>"
            "</div>"
        )

    def metric_tile_html(label: str, value: Any, sub: Any = "", tone: str = "") -> str:
        tone_class = f" {tone}" if tone else ""
        return (
            "<div class='metric-tile'>"
            f"<div class='metric-label'>{escape(str(label))}</div>"
            f"<div class='metric-value{tone_class}'>{escape(str(value))}</div>"
            f"<div class='metric-sub'>{escape(str(sub))}</div>"
            "</div>"
        )

    def hero_panel_html() -> str:
        state_name = STATE_NAMES.get(current_state, "未知")
        previous_state = latest.get("previous_state") or "-"
        transition = latest.get("transition") or "slot 状态保持"
        return (
            "<div class='panel state-hero'>"
            "<div>"
            "<div class='state-label'><span class='trigger-chip'>DSP</span><span>当前状态</span></div>"
            f"<div><span class='state-code'>{escape(current_state)}</span><span class='state-name'>{escape(state_name)}</span></div>"
            "<div class='state-reason'>"
            f"上一状态：<strong>{escape(str(previous_state))}</strong>。当前按 slot 时钟推进。"
            "</div>"
            "<div class='state-transition-bar'>"
            "<div class='state-transition-label'>最近一次状态转移原因</div>"
            f"<div class='state-transition-text'>{escape(str(transition))}</div>"
            "</div>"
            "</div>"
            "<div class='mini-metrics'>"
            f"{metric_tile_html('当前 slot', latest.get('slot_id', '-'), '按 slot 节奏刷新', 'blue')}"
            f"{metric_tile_html('刷新频率', f'{slot_hz:g} Hz', f'{refresh_ms} ms')}"
            "</div>"
            "</div>"
        )

    def uplink_panel_html() -> str:
        uplink_mode = latest.get("uplink_mode", "-")
        active_payload = uplink_data.get(MODULE_THZ if "太赫" in str(uplink_mode) or str(uplink_mode).lower() == "thz" else MODULE_MMWAVE, {})
        link_quality = active_payload.get("link_quality")
        ready = link_quality is not None and float(link_quality) > 0
        raw_quality = float(link_quality or 0.0)
        quality_value = max(0.0, min(1.0, raw_quality / 1000.0))
        quality_percent = int(quality_value * 100)
        return (
            "<div class='panel'>"
            f"{section_head_html('NET', '当前上行链路')}"
            f"<div class='state-code' style='font-size:3rem'>{escape(str(uplink_mode))}</div>"
            "<div class='link-progress'>"
            "<div class='link-progress-head'>"
            f"<span>link_quality</span><span>{quality_percent}%</span>"
            "</div>"
            "<div class='link-progress-track'>"
            f"<div class='link-progress-fill' style='width:{quality_percent}%'></div>"
            "</div>"
            "</div>"
            "<div class='mini-metrics' style='margin-top:0.7rem'>"
            f"{metric_tile_html('Ready', 'YES' if ready else 'NO', '业务流可用' if ready else '等待业务流', 'green' if ready else 'red')}"
            f"{metric_tile_html('链路质量', compact_value(link_quality), 'active uplink', 'green' if ready else '')}"
            "</div>"
            "</div>"
        )

    def diagnosis_panel_html() -> str:
        alerts = latest.get("alerts") if isinstance(latest.get("alerts"), list) else []
        transition = latest.get("transition") or ""
        failure = "; ".join(alerts) or (transition if "失败" in str(transition) or current_state == "S5" else "无失败，最近告警已恢复")
        return (
            "<div class='panel diagnosis-dark'>"
            f"{section_head_html('ALR', '关键告警 / 诊断摘要', '状态变坏时直接给出第一原因。')}"
            "<div class='diagnosis-box'>"
            "<div class='diagnosis-label'>最近一次失败原因</div>"
            f"<div class='diagnosis-value'>{escape(str(failure))}</div>"
            "</div>"
            "</div>"
        )

    def module_io(module: str) -> dict[str, Any]:
        value = slot_io.get(module, {})
        return value if isinstance(value, dict) else {}

    def module_detail(module: str) -> dict[str, Any]:
        value = module_health_detail.get(module, {})
        return value if isinstance(value, dict) else {}

    def status_dict(label: str, summary: str, tone: str) -> dict[str, str]:
        return {
            "label": label,
            "summary": summary,
            "tone": tone,
            "badge_class": f"badge-{tone}",
        }

    def module_status(module: str, online: bool) -> dict[str, str]:
        io = module_io(module)
        detail = module_detail(module)
        fault_code = str(detail.get("fault_code") or "none")

        if not online:
            return status_dict("离线", "当前未收到有效心跳", "bad")

        if module != MODULE_DSP and not io:
            return status_dict("等待", "等待当前 slot 数据", "idle")

        if module == MODULE_DSP:
            alerts = latest.get("alerts") if isinstance(latest.get("alerts"), list) else []
            if alerts:
                return status_dict("告警", str(alerts[0]), "warn")
            if current_state == "S5":
                return status_dict("回退", latest.get("transition") or "毫米波回退链路工作中", "warn")
            if current_state == "S0":
                return status_dict("自检", "等待所有模块通过自检", "info")
            return status_dict("运行", f"{current_state} {STATE_NAMES.get(current_state, '')}", "ok")

        if fault_code not in {"none", "", "0"}:
            if fault_code == "stuck":
                return status_dict("卡死", "云台在线但不可转动", "bad")
            return status_dict("故障", fault_code, "bad")

        age_slots = detail.get("age_slots")
        if isinstance(age_slots, int) and age_slots > 0:
            return status_dict("心跳不稳", "最近 slot 未连续收到包", "warn")

        if module == MODULE_GIMBAL:
            output = io.get("output", {}) if isinstance(io.get("output"), dict) else {}
            input_payload = io.get("input", {}) if isinstance(io.get("input"), dict) else {}
            position_error = output.get("position_error_mdeg")
            if output.get("in_position"):
                return status_dict("到位", f"误差 {compact_value(position_error)} mdeg", "ok")
            if input_payload.get("enable"):
                return status_dict("转动中", f"误差 {compact_value(position_error)} mdeg", "info")
            return status_dict("待命", "未接收转动使能", "idle")

        if module == MODULE_MMWAVE:
            output = io.get("output", {}) if isinstance(io.get("output"), dict) else {}
            detect = output.get("detect", {}) if isinstance(output.get("detect"), dict) else {}
            link = output.get("link", {}) if isinstance(output.get("link"), dict) else {}
            snr = float(detect.get("snr_db", 0.0) or 0.0)
            link_quality = float(link.get("link_quality", 0.0) or 0.0)
            if not detect.get("target_valid"):
                return status_dict("搜索中", "当前无有效目标", "info" if current_state == "S1" else "warn")
            if snr < 10.0:
                return status_dict("低信噪比", f"SNR {compact_value(snr)} dB", "warn")
            if link.get("uplink_ready") and link_quality < 300:
                return status_dict("链路弱", f"质量 {compact_value(link_quality)}", "warn")
            return status_dict("目标稳定", f"SNR {compact_value(snr)} dB", "ok")

        if module == MODULE_THZ:
            output = io.get("output", {}) if isinstance(io.get("output"), dict) else {}
            input_payload = io.get("input", {}) if isinstance(io.get("input"), dict) else {}
            link_quality = float(output.get("link_quality", 0.0) or 0.0)
            sense_quality = float(output.get("sense_quality", 0.0) or 0.0)
            if not input_payload.get("thz_enable"):
                return status_dict("待命", "当前状态未启用 THz", "idle")
            if not output.get("lock_flag"):
                return status_dict("未锁定", f"链路质量 {compact_value(link_quality)}", "warn")
            if link_quality < 400:
                return status_dict("通信弱", f"链路质量 {compact_value(link_quality)}", "warn")
            if sense_quality < 500:
                return status_dict("感知弱", f"感知质量 {compact_value(sense_quality)}", "warn")
            return status_dict("锁定", f"链路质量 {compact_value(link_quality)}", "ok")

        return status_dict("运行", "状态正常", "ok")

    def online_panel_html() -> str:
        modules = [
            (MODULE_DSP, "DSP", dsp_online),
            (MODULE_GIMBAL, "云台", module_health.get(MODULE_GIMBAL, False)),
            (MODULE_MMWAVE, "毫米波", module_health.get(MODULE_MMWAVE, False)),
            (MODULE_THZ, "THz", module_health.get(MODULE_THZ, False)),
        ]
        online_names = "、".join(name for _, name, online in modules if online) or "无"
        pills = "".join(
            f"<span class='badge {module_status(module, online)['badge_class']}'>{escape(name)} {escape(module_status(module, online)['label'])}</span>"
            for module, name, online in modules
        )
        return (
            "<div class='panel online-panel'>"
            "<div>"
            "<div class='online-title'>模块运行状态</div>"
            f"<div class='online-sub'>在线模块：{escape(online_names)}</div>"
            "</div>"
            f"<div style='display:flex;gap:0.45rem;flex-wrap:wrap;justify-content:flex-end'>{pills}</div>"
            "</div>"
        )

    def module_card_rich(module: str, label: str, icon: str, online: bool) -> str:
        status = module_status(module, online)
        io = module_io(module)
        input_items = split_io_items(module_io_text(module, "input", io.get("input")))
        output_items = split_io_items(module_io_text(module, "output", io.get("output")))
        input_html = "".join(
            f"<div class='io-list-item'><span class='io-dot'></span><span>{escape(item)}</span></div>"
            for item in input_items
        )
        output_html = "".join(
            f"<div class='io-list-item'><span class='io-arrow'>→</span><span>{escape(item)}</span></div>"
            for item in output_items
        )
        return (
            f"<div class='panel module-card-rich status-{status['tone']}'>"
            "<div class='module-title-row'>"
            "<div class='module-title-main'>"
            f"<div class='module-icon'>{escape(icon)}</div>"
            "<div>"
            f"<div class='module-title'>{escape(label)}</div>"
            "<div class='module-caption'>当前 slot 输入 / 输出</div>"
            f"<div class='module-status-line'>{escape(status['summary'])}</div>"
            "</div>"
            "</div>"
            f"<span class='badge {status['badge_class']}'>{escape(status['label'])}</span>"
            "</div>"
            "<div class='io-grid-rich'>"
            "<div class='io-box input'>"
            "<div class='io-box-title'>输入</div>"
            f"<div class='io-list'>{input_html}</div>"
            "</div>"
            "<div class='io-box output'>"
            "<div class='io-box-title'>输出</div>"
            f"<div class='io-list'>{output_html}</div>"
            "</div>"
            "</div>"
            "</div>"
        )

    def secondary_panel_html() -> str:
        items = [
            ("完整 payload JSON", "查看每个协议包原始字段，适合调协议格式。"),
            ("健康状态细节", "fault_code、age_slots、timed_out、heartbeat_counter。"),
            ("状态转移诊断", "S1目标计数、S2云台误差、S3捕获计数、S4失锁计数。"),
            ("仿真参数", "丢包率、噪声、SNR、THz capture delay、云台速度。"),
            ("历史趋势", "slot 时间线、状态历史、SNR、link_quality、position_error。"),
            ("记录 / 回放", "开始记录、停止记录、加载 JSONL、按 slot 回放。"),
            ("部署配置", "端口、串口、RS485、网口、SDK 连接状态。"),
        ]
        cards = "".join(
            "<div class='secondary-item'>"
            f"<div class='secondary-title'>{escape(title)}</div>"
            f"<div class='secondary-desc'>{escape(desc)}</div>"
            "</div>"
            for title, desc in items
        )
        return (
            "<div class='panel'>"
            f"{section_head_html('2ND', '二级诊断区', '默认收起，避免首屏被日志、JSON 和低层参数淹没。')}"
            f"<div class='secondary-grid'>{cards}</div>"
            "</div>"
        )

    def payload_summary(payload: Any) -> str:
        if not isinstance(payload, dict) or not payload:
            return "-"
        preferred = (
            "state_id",
            "transition",
            "target_valid",
            "in_position",
            "lock_flag",
            "link_quality",
            "scan_mode",
            "uplink_mode",
        )
        parts = []
        for key in preferred:
            if key in payload:
                parts.append(f"{key}={compact_value(payload[key])}")
        if not parts:
            for key, value in list(payload.items())[:3]:
                if isinstance(value, (dict, list)):
                    continue
                parts.append(f"{key}={compact_value(value)}")
        return ", ".join(parts) if parts else "-"

    def data_card_html(title: str, payload: dict[str, Any] | None) -> str:
        if not payload:
            return (
                "<div class='data-card'>"
                f"<div class='data-title'>{escape(title)}</div>"
                "<div class='empty-panel'>等待上行数据</div>"
                "</div>"
            )
        keys = (
            "uplink_mode",
            "frame_seq",
            "payload_bits",
            "crc",
            "rate_level",
            "modulation_order",
            "link_quality",
            "slot_id",
        )
        items = []
        for key in keys:
            if key in payload:
                items.append(
                    "<div class='kv-item'>"
                    f"<div class='kv-key'>{escape(key)}</div>"
                    f"<div class='kv-value'>{escape(compact_value(payload.get(key)))}</div>"
                    "</div>"
                )
        if not items:
            items.append("<div class='empty-panel'>暂无可展示字段</div>")
        return (
            "<div class='data-card'>"
            f"<div class='data-title'>{escape(title)}</div>"
            f"<div class='kv-list'>{''.join(items)}</div>"
            "</div>"
        )

    def packet_table_inner_html(table_rows: list[dict[str, Any]]) -> str:
        if not table_rows:
            return "<div class='empty-panel'>暂无协议包</div>"
        body = []
        for row in table_rows[:9]:
            trigger = row.get("trigger")
            trigger_class = "trigger-chip" if trigger == TRIGGER_EVENT else "trigger-chip trigger-periodic"
            trigger_text = "事件" if trigger == TRIGGER_EVENT else "周期"
            route = f"{row.get('src', '-')} -> {row.get('dst', '-')}"
            reason = row.get("reason") or row.get("status") or "-"
            body.append(
                "<tr>"
                f"<td>{escape(str(row.get('slot', '-')))}</td>"
                f"<td>{escape(route)}</td>"
                f"<td>{escape(str(row.get('kind', '-')))}</td>"
                f"<td><span class='{trigger_class}'>{trigger_text}</span></td>"
                f"<td>{escape(str(reason))}</td>"
                f"<td>{escape(payload_summary(row.get('payload')))}</td>"
                "</tr>"
            )
        return (
            "<table class='packet-table'>"
            "<thead><tr><th>Slot</th><th>路径</th><th>包</th><th>触发</th><th>原因</th><th>摘要</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody>"
            "</table>"
        )

    def packet_split_html(event_table_rows: list[dict[str, Any]], periodic_table_rows: list[dict[str, Any]]) -> str:
        return (
            "<div class='packet-card'>"
            "<div class='packet-split'>"
            "<div>"
            "<div class='packet-panel-title'>事件触发</div>"
            f"{packet_table_inner_html(event_table_rows)}"
            "</div>"
            "<div>"
            "<div class='packet-panel-title'>周期触发</div>"
            f"{packet_table_inner_html(periodic_table_rows)}"
            "</div>"
            "</div>"
            "</div>"
        )

    mode_label = args.mode.upper()
    st.markdown(
        "<div class='topbar'>"
        "<div class='traffic-lights'><span class='traffic-red'></span><span class='traffic-yellow'></span><span class='traffic-green'></span></div>"
        "<div class='topbar-title'>DSP 瞄捕状态机控制台<span class='topbar-sub'>首屏判断状态，二级追查原因</span></div>"
        "<div class='dashboard-meta'>"
        f"<span class='meta-pill'>{escape(mode_label)}</span>"
        f"<span class='meta-pill'>{escape(args.host)}:{args.pc_port}</span>"
        f"<span class='meta-pill'>{refresh_ms} ms</span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div class='hero-grid'>"
        + hero_panel_html()
        + uplink_panel_html()
        + diagnosis_panel_html()
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(online_panel_html(), unsafe_allow_html=True)

    st.markdown(
        "<div class='module-rich-grid'>"
        + module_card_rich(MODULE_DSP, "DSP", "DSP", dsp_online)
        + module_card_rich(MODULE_GIMBAL, "云台", "GMB", module_health.get(MODULE_GIMBAL, False))
        + module_card_rich(MODULE_MMWAVE, "毫米波", "MMW", module_health.get(MODULE_MMWAVE, False))
        + module_card_rich(MODULE_THZ, "THz", "THZ", module_health.get(MODULE_THZ, False))
        + "</div>",
        unsafe_allow_html=True,
    )

    col_arch, col_side = st.columns([1.65, 1], gap="medium")
    with col_arch:
        st.markdown(
            "<div class='panel'>"
            + section_head_html("PHY", "物理架构与数据流向", "高亮当前状态下的物理链路、控制链路和业务上行路径。")
            + "</div>",
            unsafe_allow_html=True,
        )
        components.html(
            generate_architecture_html(
                current_state,
                slot_id=latest.get("slot_id", 0),
                slot_hz=slot_hz,
            ),
            height=455,
            scrolling=False,
        )
    with col_side:
        st.markdown(section_head_html("FSM", "状态机拓扑", "当前状态高亮，保留主要状态转移边。"), unsafe_allow_html=True)
        st.graphviz_chart(create_state_machine_graph(current_state), width="stretch")

        if args.mode == "sim":
            st.markdown(section_head_html("EVT", "仿真事件注入", "仿真模式下用事件按钮测试状态机。"), unsafe_allow_html=True)
            tab_mmwave, tab_gimbal, tab_thz_sense, tab_comm, tab_transport = st.tabs(
                ["毫米波感知", "云台执行", "THz感知/捕获", "业务通信链路", "传输健康"]
            )
            port_map = {MODULE_GIMBAL: args.gimbal_port, MODULE_MMWAVE: args.mmwave_port, MODULE_THZ: args.thz_port}

            def emit(dst: str, control_id: str, payload: dict[str, Any], label: str) -> bool:
                message = make_control(MODULE_PC, dst, control_id, payload, trigger_reason=label)
                ok = send_message_once(args.host, port_map[dst], message)
                hub.record_local_message(message, ok)
                st.toast(f"{label} 已注入" if ok else f"{dst} 未连接")
                return ok

            def restore_all() -> None:
                for module in (MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ):
                    emit(module, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, f"{module}恢复在线")
                emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                    "target_valid": True,
                    "azimuth_mdeg": 12000,
                    "elevation_mdeg": 2000,
                    "range_m": 120.0,
                    "radial_speed_mps": 0.0,
                    "snr_db": 18.0,
                    "noise_level_mdeg": 0,
                    "comm_link_quality": 750,
                }, "毫米波目标恢复稳定")
                emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                    "force_timeout": False,
                    "auto_lock": True,
                    "force_lock": True,
                    "link_quality": 950,
                    "sense_quality": 900,
                    "sense_noise_mdeg": 0,
                }, "THz链路恢复")

            def current_gimbal_target() -> tuple[int, int]:
                gimbal_input = module_io(MODULE_GIMBAL).get("input", {})
                if not isinstance(gimbal_input, dict):
                    return 12000, 2000
                return (
                    int(gimbal_input.get("target_azimuth_mdeg", 12000) or 12000),
                    int(gimbal_input.get("target_elevation_mdeg", 2000) or 2000),
                )

            with tab_mmwave:
                col_a, col_b = st.columns(2)
                if col_a.button("毫米波目标出现", width="stretch", key="evt_mmw_target_appear"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                        "target_valid": True,
                        "azimuth_mdeg": 12000,
                        "elevation_mdeg": 2000,
                        "range_m": 120.0,
                        "radial_speed_mps": 0.0,
                        "snr_db": 18.0,
                        "noise_level_mdeg": 0,
                    }, "毫米波目标出现")
                if col_b.button("毫米波目标消失", width="stretch", key="evt_mmw_target_lost"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {"target_valid": False}, "毫米波目标消失")
                col_c, col_d = st.columns(2)
                if col_c.button("毫米波感知恢复", width="stretch", key="evt_mmw_sense_restore"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                        "target_valid": True,
                        "snr_db": 18.0,
                        "noise_level_mdeg": 0,
                    }, "毫米波感知恢复")
                if col_d.button("毫米波感知质量下降", width="stretch", key="evt_mmw_sense_degrade"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                        "target_valid": True,
                        "snr_db": 5.0,
                        "noise_level_mdeg": 1500,
                    }, "毫米波感知质量下降")
                col_e, col_f = st.columns(2)
                if col_e.button("毫米波目标角度恢复", width="stretch", key="evt_mmw_angle_restore"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                        "target_valid": True,
                        "azimuth_mdeg": 12000,
                        "elevation_mdeg": 2000,
                        "snr_db": 18.0,
                        "noise_level_mdeg": 0,
                    }, "毫米波目标角度恢复")
                if col_f.button("毫米波目标角度跳变", width="stretch", key="evt_mmw_angle_jump"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {
                        "target_valid": True,
                        "azimuth_mdeg": 28000,
                        "elevation_mdeg": -4000,
                        "snr_db": 18.0,
                        "noise_level_mdeg": 0,
                    }, "毫米波目标角度跳变")
            with tab_gimbal:
                col_a, col_b = st.columns(2)
                if col_a.button("云台恢复可控", width="stretch", key="evt_gimbal_restore"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "云台恢复可控")
                if col_b.button("云台卡死", width="stretch", key="evt_gimbal_stuck"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": True, "fault_mode": "stuck", "drop_rate": 0.0}, "云台卡死")
                col_c, col_d = st.columns(2)
                if col_c.button("云台对准恢复", width="stretch", key="evt_gimbal_align_restore"):
                    target_azimuth, target_elevation = current_gimbal_target()
                    emit(MODULE_GIMBAL, SIM_SET_GIMBAL, {
                        "current_azimuth_mdeg": target_azimuth,
                        "current_elevation_mdeg": target_elevation,
                        "speed_limit_mdeg_s": 20000,
                    }, "云台对准恢复")
                if col_d.button("云台偏离目标", width="stretch", key="evt_gimbal_deviation"):
                    emit(MODULE_GIMBAL, SIM_SET_GIMBAL, {
                        "current_azimuth_mdeg": -25000,
                        "current_elevation_mdeg": 8000,
                        "speed_limit_mdeg_s": 3000,
                    }, "云台偏离目标")

            with tab_thz_sense:
                col_a, col_b = st.columns(2)
                if col_a.button("THz捕获成功", width="stretch", key="evt_thz_capture_success"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": False,
                        "auto_lock": True,
                        "force_lock": True,
                        "link_quality": 950,
                        "sense_quality": 900,
                        "sense_noise_mdeg": 0,
                    }, "THz捕获成功")
                if col_b.button("THz捕获超时", width="stretch", key="evt_thz_capture_timeout"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": True,
                        "auto_lock": False,
                        "force_lock": False,
                        "link_quality": 950,
                    }, "THz捕获超时")
                col_c, col_d = st.columns(2)
                if col_c.button("THz感知质量恢复", width="stretch", key="evt_thz_sense_restore"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": False,
                        "auto_lock": True,
                        "force_lock": True,
                        "sense_quality": 900,
                        "sense_noise_mdeg": 0,
                    }, "THz感知质量恢复")
                if col_d.button("THz感知质量下降", width="stretch", key="evt_thz_sense_degrade"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "sense_quality": 250,
                        "sense_noise_mdeg": 1200,
                    }, "THz感知质量下降")

            with tab_comm:
                col_a, col_b = st.columns(2)
                if col_a.button("THz通信链路恢复", width="stretch", key="evt_thz_comm_restore"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": False,
                        "auto_lock": True,
                        "force_lock": True,
                        "link_quality": 950,
                    }, "THz通信链路恢复")
                if col_b.button("THz通信链路质量低", width="stretch", key="evt_thz_comm_degrade"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": False,
                        "auto_lock": True,
                        "force_lock": True,
                        "link_quality": 200,
                    }, "THz通信链路质量低")
                col_c, col_d = st.columns(2)
                if col_c.button("THz锁定恢复", width="stretch", key="evt_thz_lock_restore"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": False,
                        "auto_lock": True,
                        "force_lock": True,
                        "link_quality": 950,
                    }, "THz锁定恢复")
                if col_d.button("THz失锁", width="stretch", key="evt_thz_unlock"):
                    emit(MODULE_THZ, SIM_SET_THZ_LINK, {
                        "force_timeout": True,
                        "auto_lock": False,
                        "force_lock": False,
                        "link_quality": 200,
                    }, "THz失锁")
                col_e, col_f = st.columns(2)
                if col_e.button("毫米波备用通信恢复", width="stretch", key="evt_mmw_comm_restore"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {"comm_link_quality": 750}, "毫米波备用通信恢复")
                if col_f.button("毫米波备用通信质量低", width="stretch", key="evt_mmw_comm_degrade"):
                    emit(MODULE_MMWAVE, SIM_SET_TARGET, {"comm_link_quality": 150}, "毫米波备用通信质量低")

            with tab_transport:
                if st.button("全系统恢复默认", width="stretch", key="evt_restore_all"):
                    restore_all()
                col_a, col_b, col_c = st.columns(3)
                if col_a.button("毫米波上线", width="stretch", key="evt_mmwave_online"):
                    emit(MODULE_MMWAVE, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "毫米波上线")
                if col_b.button("云台上线", width="stretch", key="evt_gimbal_online_health"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "云台上线")
                if col_c.button("THz上线", width="stretch", key="evt_thz_online"):
                    emit(MODULE_THZ, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "THz上线")
                col_d, col_e, col_f = st.columns(3)
                if col_d.button("毫米波离线", width="stretch", key="evt_mmwave_offline"):
                    emit(MODULE_MMWAVE, SIM_SET_FAULT, {"online": False, "fault_mode": "offline", "drop_rate": 0.0}, "毫米波离线")
                if col_e.button("云台离线", width="stretch", key="evt_gimbal_offline_health"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": False, "fault_mode": "offline", "drop_rate": 0.0}, "云台离线")
                if col_f.button("THz离线", width="stretch", key="evt_thz_offline"):
                    emit(MODULE_THZ, SIM_SET_FAULT, {"online": False, "fault_mode": "offline", "drop_rate": 0.0}, "THz离线")
                col_g, col_h, col_i = st.columns(3)
                if col_g.button("毫米波协议包丢包恢复", width="stretch", key="evt_mmwave_drop_restore"):
                    emit(MODULE_MMWAVE, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "毫米波协议包丢包恢复")
                if col_h.button("云台协议包丢包恢复", width="stretch", key="evt_gimbal_drop_restore"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "云台协议包丢包恢复")
                if col_i.button("THz协议包丢包恢复", width="stretch", key="evt_thz_drop_restore"):
                    emit(MODULE_THZ, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.0}, "THz协议包丢包恢复")
                col_j, col_k, col_l = st.columns(3)
                if col_j.button("毫米波协议包高丢包", width="stretch", key="evt_mmwave_drop"):
                    emit(MODULE_MMWAVE, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.7}, "毫米波协议包高丢包")
                if col_k.button("云台协议包高丢包", width="stretch", key="evt_gimbal_drop"):
                    emit(MODULE_GIMBAL, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.7}, "云台协议包高丢包")
                if col_l.button("THz协议包高丢包", width="stretch", key="evt_thz_drop"):
                    emit(MODULE_THZ, SIM_SET_FAULT, {"online": True, "fault_mode": "none", "drop_rate": 0.7}, "THz协议包高丢包")

    st.markdown(section_head_html("LOG", "业务数据与协议包", "首屏只显示最近包和业务链路概览，完整 payload 放二级诊断。"), unsafe_allow_html=True)
    col_data, col_packets = st.columns([0.9, 2.1], gap="medium")
    uplink_data = data["uplink_data"]
    rows = []
    for msg in reversed(data["messages"][-80:]):
        rows.append({
            "slot": msg.get("slot_id"),
            "src": msg.get("src"),
            "dst": msg.get("dst"),
            "kind": message_kind(msg),
            "trigger": message_trigger_type(msg),
            "reason": msg.get("trigger_reason", ""),
            "status": msg.get("local_status", ""),
            "payload": msg.get("payload", {}),
        })
    event_rows = [row for row in rows if row["trigger"] == TRIGGER_EVENT]
    periodic_rows = [row for row in rows if row["trigger"] == TRIGGER_PERIODIC]
    with col_data:
        st.markdown(
            "<div class='uplink-grid'>"
            + data_card_html("毫米波业务流", uplink_data.get(MODULE_MMWAVE))
            + data_card_html("THz业务流", uplink_data.get(MODULE_THZ))
            + "</div>",
            unsafe_allow_html=True,
        )
        st.button("刷新页面", width="stretch", key="refresh_page")
    with col_packets:
        st.markdown(packet_split_html(event_rows, periodic_rows), unsafe_allow_html=True)

    st.markdown(secondary_panel_html(), unsafe_allow_html=True)

    time.sleep(refresh_ms / 1000.0)
    st.rerun()


def main() -> None:
    args = parse_launcher_args()
    if not args._streamlit and not running_under_streamlit():
        launch_streamlit(args)
    run_streamlit_app(args)


if __name__ == "__main__":
    main()
