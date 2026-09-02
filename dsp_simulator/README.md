# DSP 瞄捕状态机仿真项目

本项目用于验证 DSP 瞄捕状态机、统一设备间协议格式，并在真实硬件未到位时完成状态机逻辑测试。

当前代码包含两部分：

- `v0` 旧版演示器：基于 Streamlit 展示原 `S0-S5` 流程，仅用于保留早期演示能力。
- `v1` 本机五进程仿真框架：DSP 状态机作为独立程序运行，云台、毫米波基带、THz 基带和 PC 上位机分别由独立程序提供模拟硬件行为和上位机能力。

## 当前能力

- `pc_app.py` 状态机拓扑：展示 `IDLE/FAULT/S0-S7` 的正常、异常和恢复路径。
- 物理架构与数据流向图：按当前状态高亮参与工作的模块和链路。
- slot 数据包清单：展示当前状态下每个 slot 涉及的数据包、字段、方向、接口和用途。
- 数据包链路联动：选择右侧数据包后，在左侧物理架构图中高亮对应链路。
- 手动状态切换：通过按钮或调试面板触发状态变化，用于演示和讲解。

当前入口：

```bash
cd dsp_simulator
pip install -r requirements.txt
streamlit run app.py
```

浏览器默认访问 `http://localhost:8501`。

## 五进程架构

`v1` 版本采用多进程仿真系统：

```text
终端 1: dsp_state_machine.py  # DSP 状态机主程序
终端 2: sim_gimbal.py         # 云台模拟器
终端 3: sim_mmwave.py         # 毫米波基带模拟器
终端 4: sim_thz.py            # THz 基带模拟器
终端 5: pc_app.py             # PC 上位机/显示与联调工具
```

当前主要目录：

```text
dsp_simulator/
├── app.py                  # v0 Streamlit 可视化演示器，暂时保留
├── dsp_state_machine.py    # DSP 固定 slot 主循环
├── sim_gimbal.py           # 云台模拟程序
├── sim_mmwave.py           # 毫米波基带模拟程序
├── sim_thz.py              # THz 基带模拟程序
├── pc_app.py               # PC 上位机程序
└── common/
    ├── protocol.py         # 统一消息 envelope、packet_id、编解码
    ├── packets.py          # 业务包 payload schema
    ├── transport.py        # TCP/串口/网口传输抽象
    ├── clock.py            # slot 时钟
    ├── recorder.py         # 日志与包流记录
    └── replay.py           # 历史数据回放
```

## 模块职责边界

| 模块 | 职责 | 边界 |
|---|---|---|
| DSP 状态机 | slot 调度、状态转移、协议收发、控制命令生成 | 不关心对端是真实硬件还是模拟器 |
| 云台模拟器 | 模拟当前位置、目标角度、速度、到位状态和故障 | 不决定状态机是否进入捕获 |
| 毫米波基带模拟器 | 模拟目标有效标志、角度、距离、速度、SNR、丢帧和目标消失 | 不直接控制云台 |
| THz 基带模拟器 | 模拟 THz 启停、捕获锁定、链路质量、失锁和业务链路状态 | 不直接修改 DSP 状态 |
| PC 上位机 | 监控、配置、日志、协议包查看、业务数据显示、告警诊断 | 真实部署时不伪造硬件反馈 |
| 公共协议层 | 定义统一帧格式、packet_id、字段类型和传输抽象 | 不写状态机业务判断 |

## 健康状态策略

健康状态分三层处理，避免把“通信断开”“模块自报离线”和“功能异常”混为一个概念：

| 层级 | 字段/来源 | 用途 |
|---|---|---|
| 心跳状态 | DSP 是否在 `health_timeout_slots` 内收到 `PKT_SYS_HEALTH` | 判断连接是否超时，超时后标记 `fault_code=heartbeat_timeout` |
| 模块在线状态 | `PKT_SYS_HEALTH.online` | 判断模块是否可作为状态机关键依赖 |
| 功能状态 | `fault_code`、业务包字段，如 `target_valid`、`in_position`、`lock_flag`、`link_quality` | 参与 S1-S7 业务状态转移和诊断 |

关键模块为云台、毫米波基带、THz 基带。PC 是监控端，不作为 DSP 状态机自检通过的必要条件。运行中任一关键模块故障时，状态机优先进入 `S7 模块恢复`；恢复失败进入 `FAULT`，只能由人工复位返回 `IDLE`。

## 状态转移矩阵

DSP 状态机应只根据业务协议包和健康状态转移，不读取模拟器内部变量。下表是乘法表式状态转移矩阵：行表示当前状态，列表示目标状态，单元格填写转移条件。`-` 表示无直接转移，对角线表示保持当前状态的条件。

| 状态 | 编码 | 主要出口 |
|---|---:|---|
| `IDLE` | 0 | 启动请求 -> `S0` |
| `FAULT` | 1 | 人工复位 -> `IDLE` |
| `S0 自检` | 2 | 关键模块稳定在线 -> `S1`；超时 -> `FAULT` |
| `S1 搜索` | 3 | 毫米波目标连续有效 -> `S2` |
| `S2 粗对准` | 4 | 云台连续到位 -> `S3`；目标丢失/超时 -> `S1` |
| `S3 捕获` | 5 | THz 连续锁定 -> `S4`；超时 -> `S5` |
| `S4 跟踪` | 6 | 连续失锁或质量差 -> `S6` |
| `S5 回退` | 7 | 毫米波恢复 -> `S2`；超时 -> `S1` |
| `S6 快速重捕获` | 8 | 重捕获成功 -> `S4`；目标移动 -> `S2`；超时 -> `S5` |
| `S7 模块恢复` | 9 | 模块恢复 -> `S1/S2`；恢复失败 -> `FAULT` |

事件优先级固定为：模块故障、目标丢失、到位或锁定、超时。默认 slot 为 `100 ms`，角度使用 `int32 mdeg`，质量使用 `0..1000` 整数，输入统一携带 `valid/seq/age_slots`。

第一版建议阈值：

| 参数 | 建议值 | 含义 |
|---|---:|---|
| `N` | `3 slots` | 连续稳定目标窗口 |
| `coarse_min_slots` | `2 slots` | 进入 `S2` 后至少等待的粗对准反馈窗口 |
| `coarse_target_lost_tolerance_slots` | `2 slots` | `S2` 中允许毫米波目标短暂丢失的 slot 数 |
| `position_error_threshold_mdeg` | `500 mdeg` | 云台进入捕获前的最大角度误差 |
| `capture_min_slots` | `2 slots` | 进入 `S3` 后至少等待的 THz 捕获反馈窗口 |
| `capture_target_lost_tolerance_slots` | `2 slots` | `S3` 中允许毫米波目标短暂抖动/丢失的 slot 数 |
| `capture_gimbal_error_tolerance_slots` | `2 slots` | `S3` 中允许云台短暂偏离或反馈异常的 slot 数 |
| `thz_capture_bad_window_slots` | `3 slots` | `S3` 中 THz 链路质量连续异常后进入回退的窗口 |
| `capture_timeout_slots` | `20 slots` | `S3` 等待 THz 锁定的最大 slot 数 |
| `thz_loss_window_slots` | `3 slots` | `S4` 中 THz 失锁或链路质量低的连续判定窗口 |
| `tracking_target_lost_tolerance_slots` | `3 slots` | `S4` 中允许毫米波辅助目标短暂丢失的 slot 数 |
| `tracking_gimbal_error_tolerance_slots` | `3 slots` | `S4` 中允许云台微调短暂偏离或反馈异常的 slot 数 |
| `thz_quality_threshold` | `400` | THz 链路质量阈值，量程 `0..1000` |
| `mmwave_quality_threshold` | `300` | S5 回退时毫米波通信链路阈值，量程 `0..1000` |
| `fallback_restore_slots` | `3 slots` | S5 中恢复到 S2 前需要连续满足恢复就绪的 slot 数 |
| `fallback_timeout_slots` | `30 slots` | S5 中等待恢复的最大 slot 数 |
| `health_timeout_slots` | `3 slots` | 超过该窗口未收到模块健康包则判为心跳超时 |
| `reacquire_timeout_slots` | `20 slots` | S6 快速重捕获窗口 |
| `recovery_timeout_slots` | `100 slots` | S7 模块恢复最大窗口 |

统一契约、纯 C11 核心和跨语言测试位于 `state_machine/`。可执行：

```bash
python3 state_machine/tests/compare_implementations.py
python3 state_machine/tests/run_five_process_smoke.py
```

## 仿真模式与真实部署

| 项目 | 仿真模式 | 真实部署模式 |
|---|---|---|
| 设备来源 | 四个 Python 模拟程序 | 真实云台、毫米波基带、THz 基带、PC 软件 |
| 传输方式 | 第一版使用本机 TCP + JSON Lines | 串口、RS485、网口、光口或设备 SDK |
| DSP 核心 | 使用同一套状态机逻辑 | 使用同一套状态机逻辑 |
| 业务协议 | 与真实部署保持一致 | 与仿真模式保持一致 |
| PC 功能 | 监控 + 配置 + 仿真注入 | 监控 + 配置 + 日志 + 诊断 |
| 硬件状态调整 | 允许设置目标、故障、丢包、失锁等 | 只能来自真实硬件反馈 |

关键原则：

- DSP 只通过业务协议感知外部世界。
- 仿真控制协议只用于测试，不混入真实业务协议。
- 替换真实硬件时，应替换传输适配器和设备端实现，而不是重写 DSP 状态机。

## 统一协议方向

第一版业务消息建议采用 JSON Lines，每行一个消息：

```json
{
  "version": 1,
  "slot_id": 125,
  "seq": 42,
  "timestamp_ms": 1710000000000,
  "src": "dsp",
  "dst": "gimbal",
  "packet_id": "PKT_GIMBAL_CMD",
  "trigger_type": "periodic",
  "trigger_reason": "slot_clock",
  "payload": {}
}
```

`trigger_type=periodic` 表示固定 slot 周期触发，`trigger_type=event` 表示 PC 注入、状态转移、故障、超时等事件触发。PC 页面和 JSONL 记录都应按该字段分组，便于区分连续时序和关键事件。

业务包示例：

| packet_id | 方向 | 用途 |
|---|---|---|
| `PKT_SYS_HEALTH` | 各模块 -> DSP | 在线、自检和健康状态 |
| `PKT_MMW_DETECT` | 毫米波基带 -> DSP | 目标角度、距离、速度和有效标志 |
| `PKT_MMW_RF_CTRL` | DSP -> 毫米波基带/射频 | 感知面启停、通信面启停、扫描模式、波束和增益 |
| `PKT_MMW_LINK_STATUS` | 毫米波基带 -> DSP | 毫米波通信面质量、速率、调制阶数和可用状态 |
| `PKT_MMW_BITSTREAM` | 毫米波基带 -> PC | 毫米波通信业务比特流、帧序号和链路质量 |
| `PKT_GIMBAL_CMD` | DSP -> 云台 | 目标角度、速度和微调命令 |
| `PKT_GIMBAL_FB` | 云台 -> DSP | 当前角度、速度、到位状态和误差 |
| `PKT_THZ_PARAM` | DSP -> THz/FPGA 基带 | THz 感知面启停、通信面启停、速率、调制阶数和阈值 |
| `PKT_THZ_STATUS` | THz 基带 -> DSP | 锁定状态、感知速度/位置/角度、链路质量和失锁计数 |
| `PKT_THZ_BITSTREAM` | THz/FPGA 基带 -> PC | 业务比特流、帧序号和校验 |
| `PKT_UPLINK_STATE` | DSP -> PC | 当前状态、上行模式和异常原因 |

## 开发计划

1. 文档阶段
   - README 作为项目入口，说明当前能力、目标架构和开发顺序。
   - TECHNICAL_SOLUTION 作为详细设计，说明协议分层、模块边界和测试场景。

2. 公共协议阶段（已具备第一版）
   - 抽出 `common` 层，定义状态枚举、packet_id、统一 envelope 和 payload schema。
   - 实现 TCP + JSON Lines 传输抽象。
   - 分离业务协议和仿真控制协议。
   - 区分周期触发包和事件触发包，支持按触发类型查看与记录。

3. 多进程仿真阶段（已具备第一版）
   - 实现四个模拟硬件程序，支持启动、监听、收发包和打印日志。
   - 实现 DSP 固定 slot 主循环，按输入包自动推进状态机。
   - 实现 PC 控制台版，显示状态、包流和仿真注入命令。

4. 状态机测试阶段
   - 将 `app.py` 中按钮触发的状态转移改造为数据条件触发。
   - 验证正常路径、捕获超时、跟踪失锁、回退恢复和设备离线。
   - 增加场景脚本，用于复现典型流程和异常流程。

5. 可视化复用阶段
   - 复用当前 Streamlit 的物理架构图、状态拓扑和 slot 数据包清单。
   - PC 支持仿真模式和部署模式。
   - 部署模式隐藏仿真注入，只保留监控、配置、日志、回放和诊断。

## 验收目标

- 新成员能通过 README 理解当前项目、目标架构和运行方式。
- DSP 状态机不依赖模拟器内部状态，只依赖统一业务协议包。
- 替换真实硬件传输适配器时，不需要重写状态机核心。
- PC 的仿真注入能力只在仿真模式启用。
- 典型状态路径可通过模拟硬件自动触发，而不是依赖手动按钮。
