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

    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #1A1A2E;
        letter-spacing: 2px;
    }

    .status-card {
        background: linear-gradient(135deg, #1A1A2E 0%, #16213E 100%);
        border-radius: 12px;
        padding: 15px 20px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }

    .log-console {
        background: #0D1117;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 12px;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 13px;
        color: #E6EDF3;
        height: 320px;
        overflow-y: auto;
    }

    .log-entry {
        margin: 4px 0;
        padding: 2px 0;
        border-bottom: 1px solid #21262D;
    }

    .custom-divider {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, #30363D, transparent);
        margin: 15px 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ECharts 架构图生成函数
# ============================================================

def generate_architecture_echarts(current_state: str) -> str:
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
            "color": "#00FF88" if is_active else "#2D3A4A",
            "borderColor": "#00FF88" if is_active else "#444D56",
            "borderWidth": 2 if is_active else 1,
            "shadowBlur": 15 if is_active else 0,
            "shadowColor": "#00FF88" if is_active else "transparent",
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
                "color": "#00FF88" if is_active else "#8B949E",
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
            "color": "#00FF88" if is_active else "#30363D",
            "width": 2.5 if is_active else 1,
            "opacity": 1 if is_active else 0.15,
            "curveness": 0.15,
        }

        if dashed:
            lineStyle["type"] = "dashed"

        # 正向连线
        link = {
            "source": src,
            "target": tgt,
            "lineStyle": lineStyle,
        }
        if is_active:
            link["effect"] = {
                "show": True,
                "trailLength": 0.5,
                "symbol": "arrow",
                "symbolSize": 8,
                "color": "#00FF88",
                "period": 1.2,
            }
        links_data.append(link)

        # 双向时添加反向连线
        if bidir:
            link_rev = {
                "source": tgt,
                "target": src,
                "lineStyle": lineStyle.copy(),
            }
            if is_active:
                link_rev["effect"] = {
                    "show": True,
                    "trailLength": 0.5,
                    "symbol": "arrow",
                    "symbolSize": 8,
                    "color": "#00FF88",
                    "period": 1.2,
                }
            links_data.append(link_rev)

    # 状态颜色和名称
    state_color = "#00FF88" if current_state in ["S0", "S1", "S2"] else "#F0883E" if current_state in ["S3", "S4"] else "#FFA657"
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
            body {{ margin:0; padding:0; height:100%; background:#0D1117; }}
            #chart {{ width:100%; height:100%; }}
        </style>
    </head>
    <body>
        <div id="chart"></div>
        <script>
            var chart = echarts.init(document.getElementById('chart'), null, {{renderer: 'canvas'}});

            var option = {{
                backgroundColor: '#0D1117',

                title: {{
                    text: '物理架构与数据流向图',
                    subtext: '状态: {current_state} · {state_name}',
                    subtextStyle: {{
                        color: '{state_color}',
                        fontSize: 16,
                        fontWeight: 'bold',
                        fontFamily: 'Microsoft YaHei'
                    }},
                    textStyle: {{ color: '#E6EDF3', fontSize: 16, fontFamily: 'Microsoft YaHei' }},
                    left: 'center',
                    top: 8
                }},

                tooltip: {{
                    trigger: 'item',
                    backgroundColor: '#21262D',
                    borderColor: '#30363D',
                    textStyle: {{ color: '#E6EDF3' }},
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

                roam: true,
                symbolKeepAspect: true,
                zoom: 0.85,
                minZoom: 0.3,
                maxZoom: 2,

                series: [{{
                    type: 'graph',
                    layout: 'none',
                    coordinateSystem: 'cartesian2d',

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

                    xAxis: {{
                        min: 0, max: 100,
                        show: false,
                        type: 'value',
                    }},

                    yAxis: {{
                        min: 0, max: 100,
                        show: false,
                        type: 'value',
                    }},

                    animation: true,
                    animationDuration: 500,
                    animationEasing: 'cubicOut',
                }}]
            }};

            chart.setOption(option);

            window.addEventListener('resize', function() {{
                chart.resize();
            }});
        </script>
    </body>
    </html>
    '''

    return html


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
            dot.node(s, label=f"<<B><FONT POINT-SIZE='13' COLOR='black'>{s}</FONT><BR/><FONT POINT-SIZE='9' COLOR='black'>{STATE_NAMES[s]}</FONT><BR/><FONT POINT-SIZE='8' COLOR='#1A1A2E'>●</FONT></B>>",
                     shape="box", style="filled,rounded", fillcolor="#00FF88",
                     color="#00FF88", penwidth="2", width="1.2", height="0.6")
        else:
            dot.node(s, label=f"<<B><FONT POINT-SIZE='12' COLOR='#E6EDF3'>{s}</FONT><BR/><FONT POINT-SIZE='9' COLOR='#8B949E'>{STATE_NAMES[s]}</FONT></B>>",
                     shape="box", style="filled,rounded", fillcolor="#2D3A4A",
                     color="#444D56", penwidth="1", width="1.2", height="0.6")

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
        <span style="color:#6E7681;">[{timestamp}]</span>
        <span style="color:#8B949E;">{from_s}</span>
        <span style="color:#6E7681;">-&gt;</span>
        <span style="color:#00FF88;font-weight:bold;">{to_s}</span>
        <span style="color:#6E7681;">|</span>
        <span style="color:#58A6FF;">{trigger}</span>
    </div>'''


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
    echarts_html = generate_architecture_echarts(current)

    components.html(
        echarts_html,
        height=550,
        scrolling=False
    )

    st.markdown('<hr class="custom-divider"/>', unsafe_allow_html=True)

    # ---- 中部：状态拓扑 + 控制面板 ----
    col_g, col_c = st.columns([1, 1])

    with col_g:
        st.subheader("📊 状态机拓扑")
        st.graphviz_chart(create_state_machine_graph(current), use_container_width=True)
        cols = st.columns(5)
        for i, (c, sym, txt) in enumerate([
            ("#00FF88","●","当前状态"),("#2D3A4A","●","其他状态"),
            ("#58A6FF","━","正常"),("#F85149","- -","异常"),("#3FB950","- -","恢复")
        ]):
            with cols[i]:
                st.markdown(f'<span style="color:{c};">{sym}</span> <span style="color:#E6EDF3;font-size:0.85em;">{txt}</span>',
                           unsafe_allow_html=True)

    with col_c:
        st.subheader("📌 状态监控")
        uplink = st.session_state.uplink_mode

        st.markdown(f'''
        <div class="status-card">
            <div style="font-size:0.9rem;color:#8B949E;margin-bottom:5px;">当前状态</div>
            <div style="font-size:2.5rem;font-weight:bold;color:#00FF88;">{current}</div>
            <div style="font-size:1.1rem;color:#E6EDF3;">{STATE_NAMES[current]}</div>
        </div>''', unsafe_allow_html=True)

        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            col = "#58A6FF" if uplink=="毫米波" else "#4A5568"
            st.markdown(f'''<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:15px;text-align:center;">
                <div style="font-size:0.8rem;color:#8B949E;">上行链路</div>
                <div style="font-size:1.3rem;font-weight:bold;color:{col};">📡 {uplink}</div>
            </div>''', unsafe_allow_html=True)
        with c2:
            col = "#F0883E" if uplink=="太赫兹" else "#4A5568"
            st.markdown(f'''<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:15px;text-align:center;">
                <div style="font-size:0.8rem;color:#8B949E;">上行链路</div>
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
            log_html += '<div style="color:#484F58;text-align:center;padding:20px;">等待状态变更...</div>'
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
        | 接口名称 | 接口方向 | 传输内容 | 备注 |
        |----------|----------|----------|------|
        | 毫米波感知接口 | 毫米波基带 → DSP | 角度信息、距离信息、速度信息、目标有效标志 | 搜索目标、粗对准、回退后恢复 |
        | 太赫兹状态接口 | 太赫兹接收模块 → DSP | 速度、位置、锁定状态、链路质量 | 判断捕获成功、跟踪质量和失锁 |
        | 云台控制接口 | DSP → 云台 | 目标方位角、俯仰角、微调命令 | 粗对准和跟踪微调 |
        | 云台反馈接口 | 云台 → DSP | 当前角度、到位状态 | 判断是否完成转向 |
        | 上行链路状态接口 | DSP → 上层调度 | 当前上行模式、失锁/恢复状态 | 上行在毫米波与太赫兹之间切换 |
        """)


if __name__ == "__main__":
    main()
