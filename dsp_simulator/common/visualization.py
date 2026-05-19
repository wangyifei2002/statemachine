"""Reusable visualization helpers for the simulator UI."""

from __future__ import annotations

from html import escape
from string import Template
from typing import Any

from .definitions import PACKET_HIGHLIGHT_GROUPS, STATE_NAMES


ACTIVE_GROUPS_BY_STATE = {
    "S0": {"clock", "sync", "state_report"},
    "S1": {"mmwave", "perception", "mmwave_comm", "server", "state_report"},
    "S2": {"mmwave", "perception", "mmwave_comm", "gimbal", "server", "state_report"},
    "S3": {"clock", "sync", "thz_tx", "fpga", "baseband", "mmwave", "perception", "state_report"},
    "S4": {"clock", "sync", "thz_tx", "fpga", "baseband", "mmwave", "perception", "gimbal", "server", "state_report"},
    "S5": {"mmwave", "perception", "mmwave_comm", "gimbal_feedback", "server", "state_report"},
}


def create_state_machine_graph(current_state: str) -> Any:
    try:
        import graphviz
    except ModuleNotFoundError:
        return _create_state_machine_dot_source(current_state)

    dot = graphviz.Digraph(comment="DSP", format="svg", engine="dot")
    dot.attr(
        rankdir="LR",
        splines="polyline",
        nodesep="0.5",
        ranksep="0.8",
        fontname="Microsoft YaHei",
        fontsize="11",
        bgcolor="transparent",
        pad="0.3",
        size="12,4",
        ratio="compress",
    )
    dot.attr("node", fontname="Microsoft YaHei", fontsize="10", margin="0.15,0.1")

    for state in ["S0", "S1", "S2", "S3", "S4", "S5"]:
        if state == current_state:
            dot.node(
                state,
                label=f"<<B><FONT POINT-SIZE='13' COLOR='#14532D'>{state}</FONT><BR/>"
                f"<FONT POINT-SIZE='9' COLOR='#14532D'>{STATE_NAMES[state]}</FONT><BR/>"
                "<FONT POINT-SIZE='8' COLOR='#16A34A'>●</FONT></B>>",
                shape="box",
                style="filled,rounded",
                fillcolor="#DCFCE7",
                color="#16A34A",
                penwidth="2",
                width="1.2",
                height="0.6",
            )
        else:
            dot.node(
                state,
                label=f"<<B><FONT POINT-SIZE='12' COLOR='#1F2328'>{state}</FONT><BR/>"
                f"<FONT POINT-SIZE='9' COLOR='#57606A'>{STATE_NAMES[state]}</FONT></B>>",
                shape="box",
                style="filled,rounded",
                fillcolor="#FFFFFF",
                color="#C8D1DC",
                penwidth="1",
                width="1.2",
                height="0.6",
            )

    edges = [
        ("S0", "S1", "自检\n通过", "#58A6FF"),
        ("S1", "S2", "检测到\n稳定目标", "#58A6FF"),
        ("S2", "S3", "云台\n到位", "#58A6FF"),
        ("S3", "S4", "锁定\n成功", "#58A6FF"),
        ("S3", "S5", "捕获\n超时", "#F85149"),
        ("S4", "S5", "失锁/质量\n变差", "#F85149"),
        ("S5", "S2", "毫米波\n恢复", "#3FB950"),
        ("S5", "S1", "长时间\n无恢复", "#FFA657"),
    ]
    for src, dst, label, color in edges:
        dot.edge(src, dst, label=label, color=color, fontcolor=color, fontsize="8", penwidth="1.5", arrowsize="0.8")
    return dot


def _create_state_machine_dot_source(current_state: str) -> str:
    node_lines = []
    for state in ["S0", "S1", "S2", "S3", "S4", "S5"]:
        fill = "#DCFCE7" if state == current_state else "#FFFFFF"
        color = "#16A34A" if state == current_state else "#C8D1DC"
        label = f"{state}\\n{STATE_NAMES[state]}"
        node_lines.append(f'"{state}" [label="{label}", fillcolor="{fill}", color="{color}"];')
    edge_lines = [
        '"S0" -> "S1" [label="自检通过"];',
        '"S1" -> "S2" [label="检测到稳定目标"];',
        '"S2" -> "S3" [label="云台到位"];',
        '"S3" -> "S4" [label="锁定成功"];',
        '"S3" -> "S5" [label="捕获超时"];',
        '"S4" -> "S5" [label="失锁/质量变差"];',
        '"S5" -> "S2" [label="毫米波恢复"];',
        '"S5" -> "S1" [label="长时间无恢复"];',
    ]
    return (
        "digraph DSP { rankdir=LR; bgcolor=\"transparent\"; "
        "node [shape=box, style=\"filled,rounded\", fontname=\"Microsoft YaHei\"]; "
        "edge [fontname=\"Microsoft YaHei\"]; "
        + " ".join(node_lines + edge_lines)
        + " }"
    )


def generate_architecture_html(
    current_state: str,
    selected_packet_id: str | None = None,
    *,
    slot_id: int | str = 0,
    slot_hz: float = 1.0,
) -> str:
    active_groups = ACTIVE_GROUPS_BY_STATE.get(current_state, set())
    selected_groups = PACKET_HIGHLIGHT_GROUPS.get(selected_packet_id, set())
    state_name = STATE_NAMES.get(current_state, "未连接")
    interval_ms = max(100, int(1000 / max(float(slot_hz or 1.0), 0.1)))

    def edge_cls(*groups: str) -> str:
        if any(group in selected_groups for group in groups):
            return "selected"
        return "active" if any(group in active_groups for group in groups) else "idle"

    def node_cls(*groups: str) -> str:
        classes: list[str] = []
        if any(group in active_groups for group in groups):
            classes.append("active-node")
        if any(group in selected_groups for group in groups):
            classes.append("selected-node")
        return " ".join(classes)

    template = Template(
        r'''
<!DOCTYPE html>
<html style="height:100%;margin:0;padding:0;">
<head>
<meta charset="utf-8">
<style>
body { margin:0; padding:0; height:100%; background:#F5F5F7; font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif; overflow:hidden; }
#chart { width:100%; height:100%; background:linear-gradient(180deg,rgba(250,250,250,.96),rgba(244,246,250,.96)); border-radius:28px; position:relative; overflow:hidden; }
svg { width:100%; height:100%; display:block; }
.module rect { fill:rgba(255,255,255,.86); stroke:#D4D4D8; stroke-width:1.8; rx:18; ry:18; transition:fill .12s ease,stroke .12s ease,filter .12s ease; filter:drop-shadow(0 14px 18px rgba(15,23,42,.08)); }
.module .dashed { fill:rgba(255,255,255,.75); stroke:#A1A1AA; stroke-width:1.6; stroke-dasharray:7 6; rx:12; ry:12; filter:none; }
.module text { font-size:18px; font-weight:750; fill:#18181B; text-anchor:middle; dominant-baseline:middle; }
.module .small { font-size:15px; }
.module.active-node rect { fill:#ECFDF5; stroke:#10B981; stroke-width:2.6; filter:drop-shadow(0 14px 26px rgba(16,185,129,.18)); }
.module.selected-node rect { fill:#FFFBEB; stroke:#F59E0B; stroke-width:3.2; filter:drop-shadow(0 14px 26px rgba(245,158,11,.24)); }
.wire { fill:none; stroke-linecap:round; stroke-linejoin:round; stroke-width:2.2; opacity:.25; transition:stroke-width .12s ease,opacity .12s ease,filter .12s ease; }
.wire.red { stroke:#E11D48; }
.wire.blue { stroke:#2563EB; stroke-width:3.2; }
.wire.green { stroke:#10B981; stroke-width:5.2; }
.wire.dark { stroke:#1F2328; }
.wire.active { opacity:1; stroke-dasharray:10 7; animation:dash .9s linear infinite; filter:drop-shadow(0 0 5px rgba(37,99,235,.32)); }
.wire.green.active { stroke-dasharray:none; filter:drop-shadow(0 0 9px rgba(16,185,129,.55)); }
.wire.selected { opacity:1; stroke:#F59E0B; stroke-width:6; stroke-dasharray:12 6; animation:dash .65s linear infinite; filter:drop-shadow(0 0 7px rgba(245,158,11,.75)); marker-end:url(#arrow-orange); }
#chart.slot-pulse .wire.active { stroke-width:6; filter:drop-shadow(0 0 11px rgba(37,99,235,.55)); }
#chart.slot-pulse .wire.green.active { stroke-width:8; filter:drop-shadow(0 0 14px rgba(16,185,129,.70)); }
#chart.slot-pulse .module.active-node rect { stroke-width:3.4; filter:drop-shadow(0 0 13px rgba(16,185,129,.38)); }
@keyframes dash { to { stroke-dashoffset:-34; } }
.label-red,.label-blue,.label-black { font-size:15px; font-weight:700; paint-order:stroke; stroke:#FFFFFF; stroke-width:4px; stroke-linejoin:round; }
.label-red { fill:#E11D48; }
.label-blue { fill:#2563EB; }
.label-cyan { fill:#0EA5E9; }
.label-black { fill:#1F2328; }
.antenna-label { font-size:16px; font-weight:700; fill:#1F2328; text-anchor:middle; }
.network { fill:none; stroke:#71717A; stroke-width:1.8; stroke-dasharray:10 8; }
.legend { font-size:13px; fill:#57606A; }
#control-bar { position:absolute; top:12px; right:16px; display:flex; align-items:center; gap:8px; z-index:10; background:rgba(255,255,255,.78); border:1px solid rgba(255,255,255,.84); border-radius:999px; padding:7px 12px; box-shadow:0 16px 45px rgba(15,23,42,.10); backdrop-filter:blur(18px); }
#state-badge { color:#14532D; font-size:13px; font-weight:700; border-right:1px solid #D8E0EA; padding-right:10px; }
#slot-badge { background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; padding:4px 10px; font-size:13px; color:#1E40AF; font-weight:700; }
</style>
</head>
<body>
<div id="chart">
<svg viewBox="0 0 1482 800" preserveAspectRatio="xMidYMid meet" role="img" aria-label="物理架构与数据流向图">
<defs>
<marker id="arrow-red" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#E11D48"></path></marker>
<marker id="arrow-blue" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#2563EB"></path></marker>
<marker id="arrow-green" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#10B981"></path></marker>
<marker id="arrow-orange" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#F59E0B"></path></marker>
</defs>

<path class="wire red $clock_edge" d="M480 86 V196" marker-end="url(#arrow-red)"></path>
<text x="390" y="104" class="label-red">SMA/BNC</text>
<text x="490" y="104" class="label-blue">10MHz参考信号</text>
<path class="wire red $sync_edge" d="M596 58 H990 V196" marker-end="url(#arrow-red)"></path>
<text x="600" y="48" class="label-blue">1PPS信号</text>

<path class="wire red $thz_tx_edge" d="M154 240 H225" marker-end="url(#arrow-red)"></path>
<text x="178" y="229" class="label-red">WR04</text>
<path class="wire red $thz_tx_edge" d="M775 210 H595" marker-end="url(#arrow-red)"></path>
<text x="605" y="207" class="label-red">2.92F / SMP</text>
<text x="635" y="242" class="label-blue">模拟基带信号</text>

<path class="wire red $mmwave_edge" d="M595 366 H775" marker-end="url(#arrow-red)"></path>
<text x="622" y="354" class="label-red">射频/中频链路</text>
<path class="wire blue $mmwave_edge" d="M775 394 H596" marker-end="url(#arrow-blue)"></path>
<text x="730" y="430" class="label-cyan label-blue">控制是否启用</text>

<path class="wire blue $baseband_edge" d="M948 352 H1255" marker-end="url(#arrow-blue)"></path>
<text x="1148" y="342" class="label-cyan label-blue">通信数据</text>
<path class="wire blue $baseband_edge" d="M948 390 H1255" marker-end="url(#arrow-blue)"></path>
<text x="1118" y="420" class="label-cyan label-blue">通信/感知数据</text>
<path class="wire blue $fpga_edge" d="M1040 284 V478" marker-end="url(#arrow-blue)"></path>
<text x="1046" y="312" class="label-cyan label-blue">通信参数</text>
<path class="wire blue $baseband_edge" d="M862 412 V478" marker-end="url(#arrow-blue)"></path>
<text x="858" y="443" class="label-blue">速度/位置/角度</text>
<path class="wire blue $baseband_edge" d="M838 478 V412" marker-end="url(#arrow-blue)"></path>
<text x="868" y="492" class="label-cyan label-blue">控制参数</text>

<path class="wire green $server_edge" d="M1075 235 H1255" marker-end="url(#arrow-green)"></path>
<text x="1080" y="226" class="label-red">光口 IEEE 802.3</text>
<text x="1080" y="256" class="label-blue">业务比特流</text>
<path class="wire blue $mmwave_comm_edge" d="M950 372 C1065 460 1160 520 1255 520" marker-end="url(#arrow-blue)"></path>
<text x="1030" y="486" class="label-cyan label-blue">毫米波业务流</text>
<path class="wire blue $state_edge" d="M1075 552 H1255" marker-end="url(#arrow-blue)"></path>
<text x="1100" y="538" class="label-cyan label-blue">状态机当前状态</text>

<path class="wire red $gimbal_edge" d="M775 515 H596" marker-end="url(#arrow-red)"></path>
<text x="600" y="511" class="label-red">RS485</text>
<text x="610" y="543" class="label-blue">角度/速度/位置</text>
<path class="wire blue $gimbal_feedback_edge" d="M596 567 H775" marker-end="url(#arrow-blue)"></path>
<text x="610" y="587" class="label-cyan label-blue">是否转移到位</text>

<text x="86" y="202" class="antenna-label">发端窄波束</text>
<text x="86" y="226" class="antenna-label">天线</text>
<polygon points="116,218 155,238 116,258" fill="#111827" stroke="#111827"></polygon>
<text x="178" y="342" class="antenna-label">相控</text>
<text x="178" y="366" class="antenna-label">阵天线</text>
<rect x="225" y="333" width="76" height="66" fill="#FFFFFF" stroke="#1F2328" stroke-width="2"></rect>

<g class="module $clock_node"><rect x="225" y="30" width="372" height="56"></rect><text x="411" y="58">铷钟/恒温晶振模块</text></g>
<g class="module $tx_node"><rect x="225" y="196" width="372" height="88"></rect><text x="332" y="240">发射机射频模块</text><rect x="440" y="209" width="86" height="60" class="dashed"></rect><text x="483" y="239" class="small">时钟源</text></g>
<g class="module $fpga_node"><rect x="775" y="196" width="300" height="88"></rect><rect x="790" y="208" width="72" height="62" class="dashed"></rect><rect x="882" y="208" width="156" height="62" class="dashed"></rect><text x="826" y="239" class="small">DAC</text><text x="960" y="239" class="small">FPGA基带板</text></g>
<g class="module $mmwave_node"><rect x="225" y="324" width="372" height="88"></rect><text x="434" y="368" class="small">毫米波通感系统-射频模块</text></g>
<g class="module $base_node"><rect x="775" y="324" width="175" height="64"></rect><text x="862" y="356" class="small">毫米波通感系统-</text><text x="862" y="379" class="small">基带模块</text></g>
<rect x="210" y="468" width="870" height="155" class="network"></rect>
<text x="224" y="605" class="label-black">瞄捕网络</text>
<g class="module $gimbal_node"><rect x="224" y="483" width="372" height="86"></rect><text x="410" y="526">云台</text></g>
<g class="module active-node"><rect x="775" y="478" width="300" height="90"></rect><text x="925" y="523">转化模块DSP</text></g>
<g class="module $server_node"><rect x="1255" y="196" width="170" height="548"></rect><text x="1340" y="218" class="small">服务器/显示器</text><text x="1340" y="244" class="small">/PC主机</text><rect x="1305" y="272" width="70" height="54" class="dashed"></rect><text x="1340" y="292" class="small">灌包</text><text x="1340" y="314" class="small">软件</text></g>
<rect x="211" y="704" width="865" height="38" fill="#FFFFFF" stroke="#1F2328" stroke-width="2"></rect>
<text x="643" y="723" class="label-black" text-anchor="middle">移动车</text>

<line x1="220" y1="775" x2="275" y2="775" class="wire red active"></line>
<text x="286" y="780" class="legend">物理接口/协议/线缆</text>
<line x1="470" y1="775" x2="525" y2="775" class="wire blue active"></line>
<text x="536" y="780" class="legend">控制、状态和业务数据内容</text>
<line x1="795" y1="775" x2="850" y2="775" class="wire green active"></line>
<text x="861" y="780" class="legend">当前业务主链路</text>
</svg>
<div id="control-bar"><span id="state-badge">状态: $current_state · $state_name</span><span id="slot-badge">Slot $slot_id</span></div>
</div>
<script>
var slotCount = Number("$slot_id") || 0;
function pulseTick() {
  slotCount += 1;
  document.getElementById("slot-badge").textContent = "Slot " + slotCount;
  var chart = document.getElementById("chart");
  chart.classList.add("slot-pulse");
  setTimeout(function(){ chart.classList.remove("slot-pulse"); }, 180);
}
setInterval(pulseTick, $interval_ms);
pulseTick();
</script>
</body>
</html>
'''
    )

    return template.substitute(
        current_state=escape(current_state),
        state_name=escape(state_name),
        slot_id=escape(str(slot_id)),
        interval_ms=interval_ms,
        clock_edge=edge_cls("clock"),
        sync_edge=edge_cls("sync"),
        thz_tx_edge=edge_cls("thz_tx", "fpga"),
        server_edge=edge_cls("server", "fpga"),
        mmwave_comm_edge=edge_cls("mmwave_comm", "server"),
        mmwave_edge=edge_cls("mmwave", "perception"),
        baseband_edge=edge_cls("baseband", "perception"),
        fpga_edge=edge_cls("fpga", "baseband"),
        gimbal_edge=edge_cls("gimbal"),
        gimbal_feedback_edge=edge_cls("gimbal", "gimbal_feedback"),
        state_edge=edge_cls("state_report"),
        clock_node=node_cls("clock", "sync"),
        tx_node=node_cls("thz_tx", "clock"),
        fpga_node=node_cls("fpga", "sync"),
        mmwave_node=node_cls("mmwave", "perception", "mmwave_comm"),
        base_node=node_cls("baseband", "perception"),
        gimbal_node=node_cls("gimbal", "gimbal_feedback"),
        server_node=node_cls("server", "state_report", "fpga", "mmwave_comm"),
    )
