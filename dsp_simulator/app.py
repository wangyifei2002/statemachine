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

# ============================================================
# 状态机配置定义
# ============================================================

STATE_NAMES = {
    "S0": "自检", "S1": "搜索", "S2": "粗对准",
    "S3": "捕获", "S4": "跟踪", "S5": "回退",
}

STATE_NAMES_CN = {
    "S0": "自检 (Self-Test)", "S1": "搜索 (Search)",
    "S2": "粗对准 (Coarse)", "S3": "捕获 (Acquisition)",
    "S4": "跟踪 (Tracking)", "S5": "回退 (Fallback)",
}

STATE_DESCRIPTIONS = {
    "S0": "系统初始状态，检查毫米波、太赫兹、云台和 DSP 接口连通性",
    "S1": "等待毫米波感知发现目标，连续若干个 slot 检测到有效目标后进入下一状态",
    "S2": "DSP 根据毫米波目标角度控制云台转向，等待云台误差收敛到阈值内",
    "S3": "在云台粗对准前提下，等待太赫兹上行链路锁定，超时则进入回退",
    "S4": "太赫兹链路正常工作，监控链路质量并按需微调云台",
    "S5": "上行切回毫米波模式，依靠毫米波感知维持目标信息并尝试恢复",
}

STATE_TRANSITIONS = {
    "S0": [("S1", "自检通过", "各模块连通性检查正常，准备进入搜索阶段")],
    "S1": [("S2", "检测到稳定目标", "毫米波连续检测到有效目标，准备进入粗对准")],
    "S2": [("S3", "云台到位（误差<阈值）", "云台转向完成，误差已收敛，准备进入捕获")],
    "S3": [
        ("S4", "太赫兹锁定成功", "太赫兹上行链路锁定成功，准备进入跟踪阶段"),
        ("S5", "捕获超时", "太赫兹锁定超时，切换到毫米波回退模式"),
    ],
    "S4": [("S5", "链路质量变差/失锁", "太赫兹链路质量连续变差或失锁，进入回退状态")],
    "S5": [
        ("S2", "毫米波稳定恢复", "毫米波感知恢复稳定，重新进入粗对准阶段"),
        ("S1", "长时间无恢复", "毫米波长时间无法恢复，回到搜索阶段重新搜索目标"),
    ],
}

UPLINK_MODE = {
    "S0": "毫米波", "S1": "毫米波", "S2": "毫米波",
    "S3": "太赫兹", "S4": "太赫兹", "S5": "毫米波",
}

SLOT_PACKET_SPECS = [
    {
        "id": "PKT_SYS_HEALTH",
        "name": "系统自检状态包",
        "phase": "T0",
        "states": ["S0"],
        "direction": "DSP内部/各模块 -> DSP",
        "interface": "本地轮询 + 接口在线检测",
        "cadence": "每 slot 1 次",
        "fields": ["slot_id", "mmwave_online", "thz_fpga_online", "gimbal_online", "clock_lock", "pps_lock"],
        "purpose": "确认毫米波、太赫兹/FPGA、云台和时钟同步链路可进入搜索流程",
    },
    {
        "id": "SIG_CLOCK_SYNC",
        "name": "时钟同步信号",
        "phase": "T0",
        "states": ["S0", "S3", "S4"],
        "direction": "铷钟/恒温晶振 -> 发射机射频模块/FPGA基带板",
        "interface": "SMA/BNC",
        "cadence": "连续信号，按 slot 检查锁定状态",
        "fields": ["10MHz参考信号", "1PPS信号", "clock_lock", "pps_valid"],
        "purpose": "给太赫兹发射和基带处理提供统一时钟基准",
    },
    {
        "id": "PKT_MMW_DETECT",
        "name": "毫米波目标感知包",
        "phase": "T1",
        "states": ["S1", "S2", "S4", "S5"],
        "direction": "毫米波通感基带模块 -> DSP",
        "interface": "数字通信接口",
        "cadence": "每 slot 1 次",
        "fields": ["target_valid", "azimuth_deg", "elevation_deg", "range_m", "radial_speed_mps", "snr_db"],
        "purpose": "搜索目标、粗对准角度输入、跟踪辅助和回退恢复判决",
    },
    {
        "id": "PKT_MMW_RF_CTRL",
        "name": "毫米波射频启停控制包",
        "phase": "T1",
        "states": ["S1", "S2", "S4", "S5"],
        "direction": "毫米波通感基带模块 -> 毫米波射频模块",
        "interface": "射频/中频链路控制",
        "cadence": "状态变化时下发，每 slot 可刷新",
        "fields": ["rf_enable", "scan_mode", "beam_id", "gain_index"],
        "purpose": "按状态启用相控阵感知、扫描或辅助跟踪模式",
    },
    {
        "id": "PKT_GIMBAL_CMD",
        "name": "云台控制命令包",
        "phase": "T2",
        "states": ["S2", "S4"],
        "direction": "DSP -> 云台",
        "interface": "RS485",
        "cadence": "每 slot 1 次或角度变化时下发",
        "fields": ["cmd_seq", "target_azimuth_deg", "target_elevation_deg", "angular_speed", "fine_tune_enable"],
        "purpose": "粗对准阶段转向目标，跟踪阶段执行小幅微调",
    },
    {
        "id": "PKT_GIMBAL_FB",
        "name": "云台反馈状态包",
        "phase": "T3",
        "states": ["S2", "S4", "S5"],
        "direction": "云台 -> DSP",
        "interface": "RS485/反馈链路",
        "cadence": "每 slot 1 次",
        "fields": ["current_azimuth_deg", "current_elevation_deg", "angular_speed", "in_position", "position_error_deg"],
        "purpose": "判断云台是否转移到位，并给跟踪微调提供闭环反馈",
    },
    {
        "id": "PKT_THZ_PARAM",
        "name": "太赫兹/基带通信参数包",
        "phase": "T2",
        "states": ["S3", "S4"],
        "direction": "DSP -> FPGA基带板/毫米波通感基带模块",
        "interface": "数字通信接口",
        "cadence": "捕获开始下发，跟踪中按需刷新",
        "fields": ["thz_enable", "rate_level", "modulation_order", "capture_timeout_slot", "tracking_threshold"],
        "purpose": "配置太赫兹捕获、通信速率、调制阶数和跟踪判决阈值",
    },
    {
        "id": "PKT_THZ_STATUS",
        "name": "太赫兹锁定/链路质量包",
        "phase": "T3",
        "states": ["S3", "S4"],
        "direction": "太赫兹接收/基带模块 -> DSP",
        "interface": "数字通信接口",
        "cadence": "每 slot 1 次",
        "fields": ["lock_flag", "link_quality", "velocity", "position", "angle", "loss_count"],
        "purpose": "S3判断捕获成功或超时，S4判断是否失锁并进入回退",
    },
    {
        "id": "PKT_THZ_BITSTREAM",
        "name": "太赫兹业务比特流包",
        "phase": "T4",
        "states": ["S4"],
        "direction": "FPGA基带板 -> 服务器/显示器/PC主机",
        "interface": "光口 IEEE 802.3",
        "cadence": "链路锁定后连续发送",
        "fields": ["payload_bits", "frame_seq", "crc", "rate_level", "modulation_order"],
        "purpose": "向上层灌包软件/显示端输出太赫兹业务数据",
    },
    {
        "id": "PKT_UPLINK_STATE",
        "name": "状态机上报包",
        "phase": "T5",
        "states": ["S0", "S1", "S2", "S3", "S4", "S5"],
        "direction": "DSP -> 服务器/显示器/PC主机",
        "interface": "上层通信链路",
        "cadence": "每 slot 1 次",
        "fields": ["state_id", "uplink_mode", "lock_flag", "fallback_reason", "restore_flag", "slot_id"],
        "purpose": "给上层调度和可视化界面同步当前状态、上行模式和异常/恢复信息",
    },
]

PHASE_LABELS = {
    "T0": "同步/自检",
    "T1": "感知输入",
    "T2": "控制下发",
    "T3": "反馈回读",
    "T4": "业务数据",
    "T5": "状态上报",
}

PACKET_HIGHLIGHT_GROUPS = {
    "PKT_SYS_HEALTH": {"clock", "sync", "mmwave", "baseband", "gimbal", "state_report"},
    "SIG_CLOCK_SYNC": {"clock", "sync"},
    "PKT_MMW_DETECT": {"mmwave", "perception", "baseband"},
    "PKT_MMW_RF_CTRL": {"mmwave"},
    "PKT_GIMBAL_CMD": {"gimbal"},
    "PKT_GIMBAL_FB": {"gimbal_feedback"},
    "PKT_THZ_PARAM": {"fpga", "baseband"},
    "PKT_THZ_STATUS": {"fpga", "baseband"},
    "PKT_THZ_BITSTREAM": {"fpga", "server"},
    "PKT_UPLINK_STATE": {"state_report", "server"},
}


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
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #F8FBFF 0%, #F4F7FB 100%);
    }
    [data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0);
    }
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.75);
        border: 1px solid #D8E0EA;
        border-radius: 12px;
        padding: 8px 12px;
    }
    [data-testid="stExpander"] {
        background: rgba(255, 255, 255, 0.78);
        border: 1px solid #D8E0EA;
        border-radius: 12px;
    }
    [data-testid="stMarkdownContainer"] table {
        background: #FFFFFF;
    }

    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #17324D;
        letter-spacing: 2px;
    }

    .status-card {
        background: linear-gradient(135deg, #FFFFFF 0%, #F5F9FF 100%);
        border: 1px solid #D8E0EA;
        border-radius: 12px;
        padding: 15px 20px;
        color: #1F2328;
        text-align: center;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }

    .log-console {
        background: #FFFFFF;
        border: 1px solid #D0D7DE;
        border-radius: 8px;
        padding: 12px;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 13px;
        color: #1F2328;
        height: 320px;
        overflow-y: auto;
    }

    .log-entry {
        margin: 4px 0;
        padding: 2px 0;
        border-bottom: 1px solid #EAECEF;
    }

    .custom-divider {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, #D8E0EA, transparent);
        margin: 15px 0;
    }

    .slot-panel {
        height: 620px;
        overflow-y: auto;
        background: #FFFFFF;
        border: 1px solid #D8E0EA;
        border-radius: 8px;
        padding: 14px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }

    .slot-panel-header {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid #EAECEF;
    }

    .slot-panel-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #17324D;
        line-height: 1.3;
    }

    .slot-panel-state {
        white-space: nowrap;
        font-size: 0.82rem;
        font-weight: 700;
        color: #166534;
        background: #DCFCE7;
        border: 1px solid #86EFAC;
        border-radius: 999px;
        padding: 4px 9px;
    }

    .slot-summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-bottom: 12px;
    }

    .slot-summary-item {
        background: #F6F8FA;
        border: 1px solid #D8E0EA;
        border-radius: 6px;
        padding: 8px;
    }

    .slot-summary-label {
        font-size: 0.72rem;
        color: #57606A;
        margin-bottom: 3px;
    }

    .slot-summary-value {
        font-size: 0.9rem;
        font-weight: 700;
        color: #1F2328;
    }

    .slot-packet {
        border: 1px solid #D8E0EA;
        border-left: 4px solid #2563EB;
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 10px;
        background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
    }

    .slot-packet.selected {
        border-color: #F59E0B;
        border-left-color: #F59E0B;
        background: linear-gradient(180deg, #FFFBEB 0%, #FFFFFF 100%);
        box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.18);
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
        color: #17324D;
    }

    .slot-phase {
        font-family: "Consolas", "Monaco", monospace;
        font-size: 0.75rem;
        font-weight: 700;
        color: #0969DA;
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 999px;
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
        background: #F6F8FA;
        border: 1px solid #D8E0EA;
        border-radius: 6px;
        padding: 6px 7px;
        font-size: 0.78rem;
        font-weight: 700;
        color: #17324D;
        text-align: center;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }

    .route-source {
        border-color: #BFDBFE;
        background: #EFF6FF;
    }

    .route-target {
        border-color: #BBF7D0;
        background: #F0FDF4;
    }

    .route-arrow {
        color: #F59E0B;
        font-weight: 800;
        font-size: 1rem;
    }

    .slot-meta {
        font-size: 0.78rem;
        color: #57606A;
        line-height: 1.45;
        margin: 3px 0;
    }

    .slot-meta strong {
        color: #1F2328;
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
        color: #1E40AF;
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 5px;
        padding: 2px 5px;
    }

    .slot-purpose {
        font-size: 0.78rem;
        color: #1A7F37;
        line-height: 1.45;
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 6px;
        padding: 6px 8px;
        margin-top: 7px;
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
        "antenna_mmwave": current_state in ["S1", "S5"],
        "mmwave_dsp": current_state in ["S1", "S5"],
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
    state_color = "#16A34A" if current_state in ["S0", "S1", "S2"] else "#C2410C" if current_state in ["S3", "S4"] else "#A16207"
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
        "S3": {"clock", "sync", "thz_tx", "fpga", "baseband", "state_report"},
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
                background: #FFFFFF;
                color: #1F2328;
                font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
                position: relative;
                overflow: hidden;
            }
            #chart {
                width: 100%;
                height: 100%;
                background: #FFFFFF;
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
                fill: #FFFFFF;
                stroke: #1F2328;
                stroke-width: 2;
                rx: 0;
                transition: fill 0.12s ease, stroke 0.12s ease, stroke-width 0.12s ease, filter 0.12s ease;
            }
            .module .dashed {
                fill: #FFFFFF;
                stroke: #1F2328;
                stroke-width: 2;
                stroke-dasharray: 9 7;
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
                fill: #F0FDF4;
                stroke: #16A34A;
                stroke-width: 3;
                filter: drop-shadow(0 0 8px rgba(22, 163, 74, 0.35));
            }
            .module.selected-node rect,
            .module.selected-node polygon {
                fill: #FFFBEB;
                stroke: #F59E0B;
                stroke-width: 4;
                filter: drop-shadow(0 0 10px rgba(245, 158, 11, 0.45));
            }
            .network {
                fill: none;
                stroke: #1F2328;
                stroke-width: 2;
                stroke-dasharray: 12 8;
            }
            .car {
                fill: #FFFFFF;
                stroke: #1F2328;
                stroke-width: 2;
            }
            .wire {
                fill: none;
                stroke-linecap: square;
                stroke-linejoin: miter;
                stroke-width: 2.2;
                opacity: 0.42;
                transition: stroke-width 0.12s ease, opacity 0.12s ease, filter 0.12s ease;
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
                filter: drop-shadow(0 0 4px rgba(22, 163, 74, 0.45));
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
                stroke-width: 5.5;
                stroke-dasharray: 12 6;
                animation: dash 0.65s linear infinite;
                filter: drop-shadow(0 0 6px rgba(245, 158, 11, 0.75));
                marker-end: url(#arrow-orange);
            }
            #chart.slot-pulse .wire.active,
            #chart.slot-pulse .wire.active.red,
            #chart.slot-pulse .wire.active.blue {
                opacity: 1;
                stroke-width: 6.5;
                filter: drop-shadow(0 0 10px rgba(14, 165, 233, 0.75));
            }
            #chart.slot-pulse .wire.selected,
            #chart.slot-pulse .wire.selected.red,
            #chart.slot-pulse .wire.selected.blue {
                opacity: 1;
                stroke-width: 8;
                filter: drop-shadow(0 0 12px rgba(245, 158, 11, 0.95));
            }
            #chart.slot-pulse .module.active-node rect,
            #chart.slot-pulse .module.active-node polygon {
                fill: #DCFCE7;
                stroke-width: 4;
                filter: drop-shadow(0 0 12px rgba(22, 163, 74, 0.65));
            }
            #chart.slot-pulse .module.selected-node rect,
            #chart.slot-pulse .module.selected-node polygon {
                fill: #FEF3C7;
                stroke-width: 5;
                filter: drop-shadow(0 0 14px rgba(245, 158, 11, 0.85));
            }
            #chart.slot-pulse #slot-glow {
                opacity: 1;
            }
            @keyframes dash {
                to { stroke-dashoffset: -34; }
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
                fill: #FFFFFF;
                stroke: #1F2328;
                stroke-width: 1.5;
            }
            #control-bar {
                position: absolute;
                top: 10px;
                right: 16px;
                display: flex;
                align-items: center;
                gap: 8px;
                z-index: 100;
                background: rgba(255,255,255,0.94);
                border: 1px solid #D8E0EA;
                border-radius: 10px;
                padding: 6px 12px;
                box-shadow: 0 2px 8px rgba(15,23,42,0.08);
            }
            #control-bar button {
                border: 1px solid #D0D7DE;
                border-radius: 6px;
                background: #FFFFFF;
                color: #1F2328;
                font-size: 14px;
                cursor: pointer;
                padding: 4px 10px;
                line-height: 1.4;
            }
            #control-bar button.active {
                background: #DCFCE7;
                border-color: #16A34A;
                color: #14532D;
            }
            #control-bar select {
                border: 1px solid #D0D7DE;
                border-radius: 6px;
                background: #FFFFFF;
                color: #1F2328;
                font-size: 12px;
                padding: 4px 6px;
                cursor: pointer;
            }
            #slot-badge {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 13px;
                color: #1E40AF;
                font-weight: 700;
                white-space: nowrap;
            }
            #slot-badge .label {
                font-weight: 400;
                color: #57606A;
                font-size: 11px;
            }
            #state-badge {
                display: inline-flex;
                align-items: center;
                border-right: 1px solid #D8E0EA;
                padding-right: 10px;
                margin-right: 2px;
                color: $state_color;
                font-size: 13px;
                font-weight: 700;
                white-space: nowrap;
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
            <button id="btn-play" onclick="togglePlay()" title="播放 / 暂停">⏸</button>
            <select id="sel-speed" onchange="changeSpeed(this.value)">
                <option value="0.5">0.5x</option>
                <option value="1" selected>1x</option>
                <option value="2">2x</option>
            </select>
            <span id="slot-badge"><span class="label">Slot</span> 0</span>
        </div>
        <script>
            var slotCount = 0;
            var isPlaying = true;
            var speed = 1.0;
            var clockInterval = null;
            var pulseTimer = null;

            function updateSlotBadge() {
                document.getElementById('slot-badge').innerHTML = '<span class="label">Slot</span> ' + slotCount;
            }

            function triggerSlotPulse() {
                var chart = document.getElementById('chart');
                chart.classList.add('slot-pulse');
                if (pulseTimer) {
                    clearTimeout(pulseTimer);
                }
                pulseTimer = setTimeout(function() {
                    chart.classList.remove('slot-pulse');
                    pulseTimer = null;
                }, 180);
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
                if (isPlaying) {
                    btn.textContent = '⏸';
                    btn.classList.add('active');
                    startClock();
                } else {
                    btn.textContent = '▶';
                    btn.classList.remove('active');
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
        <span style="color:#57606A;">[{timestamp}]</span>
        <span style="color:#57606A;">{from_s}</span>
        <span style="color:#8C959F;">-&gt;</span>
        <span style="color:#1A7F37;font-weight:bold;">{to_s}</span>
        <span style="color:#8C959F;">|</span>
        <span style="color:#0969DA;">{trigger}</span>
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
        f'<div class="slot-panel-state">{esc(state)} · {esc(STATE_NAMES[state])}</div>'
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

def main():
    # 标题栏
    col_t, col_m = st.columns([3, 1])
    with col_t:
        st.markdown('<p class="main-title">🎯 DSP 瞄捕状态机模拟器</p>', unsafe_allow_html=True)
    with col_m:
        st.markdown("###")
        n = len(st.session_state.get("log_messages", []))
        st.metric("转换次数", n - 1 if n > 0 else 0)

    st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

    # 初始化 state
    if "current_state" not in st.session_state:
        st.session_state.current_state = "S0"
    if "log_messages" not in st.session_state:
        st.session_state.log_messages = []
    if "uplink_mode" not in st.session_state:
        st.session_state.uplink_mode = UPLINK_MODE["S0"]

    current = st.session_state.current_state

    # ---- 顶部：ECharts 物理架构图 ----
    st.subheader("🔗 物理架构与数据流向图")

    import streamlit.components.v1 as components
    packets_for_current = get_slot_packets(current)
    packet_options = [""] + [p["id"] for p in packets_for_current]
    packet_by_id = {p["id"]: p for p in packets_for_current}

    col_arch, col_slot = st.columns([2.25, 1], gap="large")
    with col_slot:
        selected_packet_id = st.selectbox(
            "在左图高亮数据包链路",
            options=packet_options,
            format_func=lambda packet_id: "不单独高亮（显示当前状态链路）"
            if not packet_id else format_packet_option(packet_by_id[packet_id]),
            key=f"packet_highlight_{current}",
        )
    echarts_html = generate_architecture_echarts(current, selected_packet_id or None)
    with col_arch:
        components.html(
            echarts_html,
            height=620,
            scrolling=False
        )
    with col_slot:
        st.markdown(render_slot_packet_panel(current, selected_packet_id or None), unsafe_allow_html=True)

    st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

    # ---- 中部：状态拓扑 + 控制面板 ----
    col_g, col_c = st.columns([1, 1])

    with col_g:
        st.subheader("📊 状态机拓扑")
        st.graphviz_chart(create_state_machine_graph(current), use_container_width=True)
        cols = st.columns(5)
        for i, (c, sym, txt) in enumerate([
            ("#16A34A","●","当前状态"),("#94A3B8","●","其他状态"),
            ("#2563EB","━","正常"),("#DC2626","- -","异常"),("#16A34A","- -","恢复")
        ]):
            with cols[i]:
                st.markdown(f'<span style="color:{c};">{sym}</span> <span style="color:#57606A;font-size:0.85em;">{txt}</span>',
                           unsafe_allow_html=True)

    with col_c:
        st.subheader("📌 状态监控")
        uplink = st.session_state.uplink_mode

        st.markdown(f'''
        <div class="status-card">
            <div style="font-size:0.9rem;color:#57606A;margin-bottom:5px;">当前状态</div>
            <div style="font-size:2.5rem;font-weight:bold;color:#16A34A;">{current}</div>
            <div style="font-size:1.1rem;color:#17324D;">{STATE_NAMES[current]}</div>
        </div>''', unsafe_allow_html=True)

        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            col = "#2563EB" if uplink=="毫米波" else "#94A3B8"
            bg = "#EFF6FF" if uplink=="毫米波" else "#FFFFFF"
            border = "#BFDBFE" if uplink=="毫米波" else "#D8E0EA"
            st.markdown(f'''<div style="background:{bg};border:1px solid {border};border-radius:8px;padding:15px;text-align:center;">
                <div style="font-size:0.8rem;color:#57606A;">上行链路</div>
                <div style="font-size:1.3rem;font-weight:bold;color:{col};">📡 {uplink}</div>
            </div>''', unsafe_allow_html=True)
        with c2:
            col = "#C2410C" if uplink=="太赫兹" else "#94A3B8"
            bg = "#FFF7ED" if uplink=="太赫兹" else "#FFFFFF"
            border = "#FED7AA" if uplink=="太赫兹" else "#D8E0EA"
            st.markdown(f'''<div style="background:{bg};border:1px solid {border};border-radius:8px;padding:15px;text-align:center;">
                <div style="font-size:0.8rem;color:#57606A;">上行链路</div>
                <div style="font-size:1.3rem;font-weight:bold;color:{col};">📡 {uplink}</div>
            </div>''', unsafe_allow_html=True)

        st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

        st.subheader("🎮 手动控制")
        actions = get_available_actions(current)
        if actions:
            for tgt, btn_txt, desc in actions:
                if st.button(f"**{btn_txt}**", help=desc,
                            key=f"btn_{current}_{tgt}", type="primary",
                            use_container_width=True):
                    old = st.session_state.current_state
                    st.session_state.current_state = tgt
                    st.session_state.uplink_mode = UPLINK_MODE[tgt]
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    st.session_state.log_messages.append({
                        "time": ts, "from": old, "to": tgt, "trigger": btn_txt
                    })
                    st.rerun()
        else:
            st.info("当前状态无可用触发动作", icon="ℹ️")

        st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

        with st.expander("🔧 开发者调试", expanded=False):
            st.markdown("**强制跳转：**")
            jc = st.columns(6)
            for i, s in enumerate(["S0","S1","S2","S3","S4","S5"]):
                with jc[i]:
                    if st.button(s, key=f"j_{s}", use_container_width=True):
                        old = st.session_state.current_state
                        st.session_state.current_state = s
                        st.session_state.uplink_mode = UPLINK_MODE[s]
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        st.session_state.log_messages.append({
                            "time": ts, "from": old, "to": s, "trigger": "手动跳转"
                        })
                        st.rerun()
            if st.button("🔄 重置系统", type="secondary", use_container_width=True):
                st.session_state.current_state = "S0"
                st.session_state.uplink_mode = UPLINK_MODE["S0"]
                st.session_state.log_messages = []
                st.rerun()

    st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

    # ---- 底部：日志 + 说明 ----
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("📋 系统运行日志")
        log_html = '<div class="log-console">'
        if not st.session_state.log_messages:
            log_html += '<div style="color:#8C959F;text-align:center;padding:20px;">等待状态变更...</div>'
        else:
            for m in st.session_state.log_messages:
                log_html += format_log_html(m["time"], m["from"], m["to"], m["trigger"])
        log_html += '</div>'
        st.markdown(log_html, unsafe_allow_html=True)

        c_cl, c_ex = st.columns(2)
        with c_cl:
            if st.button("🗑️ 清空日志", use_container_width=True):
                st.session_state.log_messages = []
                st.rerun()
        with c_ex:
            txt = "\n".join([f"[{m['time']}] {m['from']}->{m['to']} | {m['trigger']}"
                             for m in st.session_state.log_messages])
            st.download_button("📥 下载", txt or "无日志", "dsp_log.txt",
                              "text/plain", use_container_width=True)

    with col_r:
        st.subheader("📖 当前状态")
        st.info(f"**{STATE_NAMES_CN[current]}**：{STATE_DESCRIPTIONS[current]}")

    st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

    with st.expander("📚 接口信息说明", expanded=False):
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


if __name__ == "__main__":
    main()
