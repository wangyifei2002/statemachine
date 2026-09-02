# DSP 瞄捕状态机多进程仿真技术方案

## 1. 目标与边界

本项目包含 `v0` Streamlit 可视化演示器和 `v1` 本机五进程仿真框架。`v0` 的核心价值是说明 DSP 瞄捕状态机、物理架构链路和 slot 数据包关系；`v1` 的核心价值是通过独立 DSP 程序和模拟硬件程序测试协议与状态机逻辑。

目标系统需要满足三点：

1. 统一 DSP 与外部模块之间的协议格式和数据包字段。
2. 在没有真实硬件时，用模拟硬件验证 DSP 状态机。
3. 后续接入真实硬件时，复用 DSP 状态机、业务协议、日志和 PC 监控能力。

核心边界原则：

- DSP 状态机只依赖统一业务协议，不依赖硬件真假。
- 真实业务协议和仿真控制协议必须分开。
- PC 在真实部署中负责监控、配置、记录和诊断，不伪造硬件反馈。
- 模拟器通过同一套业务协议与 DSP 通信，仿真状态注入只能走仿真控制面。

## 2. 当前版本定位

当前 `app.py` 是演示型原型，主要能力包括：

- `IDLE/FAULT/S0-S7` 状态拓扑展示。
- 物理架构与数据流向图。
- 当前状态下的 slot 数据包清单。
- 数据包选择与链路高亮联动。
- 手动按钮驱动状态切换。
- 简单状态监控和运行日志。

当前版本不是真实状态机运行程序，原因是：

- 状态转移依赖人工按钮，而不是输入数据条件。
- 云台、毫米波基带、THz 基带和 PC 只是图中节点，没有独立运行逻辑。
- 数据包定义用于展示，尚未作为进程间通信协议执行。

因此硬件模拟逻辑不应继续堆叠在 `app.py` 中，而应通过独立进程和公共协议层实现。

## 3. 目标总体架构

仿真模式包含五个独立程序：

```text
+----------------------+       +------------------+
| sim_mmwave.py        | <---> |                  |
| 毫米波基带模拟器      |       |                  |
+----------------------+       |                  |
                               |                  |
+----------------------+       | dsp_state_       |       +-------------+
| sim_gimbal.py        | <---> | machine.py       | <---> | pc_app.py   |
| 云台模拟器            |       | DSP 状态机主程序  |       | PC 上位机   |
+----------------------+       |                  |       +-------------+
                               |                  |
+----------------------+       |                  |
| sim_thz.py           | <---> |                  |
| THz 基带模拟器        |       +------------------+
+----------------------+
```

推荐代码结构：

```text
dsp_simulator/
├── app.py                  # v0 可视化演示器，暂时保留
├── dsp_state_machine.py    # DSP 固定 slot 主循环
├── sim_gimbal.py           # 云台模拟程序
├── sim_mmwave.py           # 毫米波基带模拟程序
├── sim_thz.py              # THz 基带模拟程序
├── pc_app.py               # PC 上位机程序
└── common/
    ├── protocol.py         # 统一 envelope、packet_id、编解码
    ├── packets.py          # payload schema
    ├── transport.py        # TCP/串口/网口传输抽象
    ├── clock.py            # slot 时钟
    ├── recorder.py         # 运行记录
    └── replay.py           # 数据回放
```

## 4. 分层设计

| 层级 | 职责 | 复用方式 |
|---|---|---|
| `common` 公共层 | 状态枚举、协议、包定义、slot 时钟、日志、记录、回放 | 仿真和真实部署共用 |
| DSP 核心层 | 状态机判断、slot 调度、控制命令生成 | 不关心对端硬件真假 |
| 传输适配层 | TCP JSONL、串口、RS485、网口、光口、SDK | 不解释业务字段 |
| 模拟设备层 | 云台、毫米波、THz 的可调运行逻辑 | 只在仿真模式运行 |
| PC 上位机层 | 监控、配置、日志、诊断、业务数据显示 | 仿真和部署共用，仿真模式额外注入状态 |

## 5. 模块职责

### 5.1 DSP 状态机

DSP 是系统控制核心，负责：

- 维护当前状态 `IDLE/FAULT/S0-S7`。
- 按固定频率产生 slot。
- 在每个 slot 读取毫米波、云台、THz 和 PC 输入包。
- 根据输入包判断状态转移。
- 向云台发送角度和速度控制命令。
- 向毫米波基带发送启停和扫描模式配置。
- 向 THz 基带发送启停、速率、调制阶数和捕获参数。
- 向 PC 上报当前状态、上行链路、异常原因和日志事件。

DSP 不负责：

- 直接修改模拟硬件内部状态。
- 识别对端是真实硬件还是模拟器。
- 承担 PC 显示、日志分析和人工配置界面。

### 5.2 云台模拟器

云台模拟器负责模拟执行机构行为：

- 接收 `PKT_GIMBAL_CMD`。
- 维护当前方位角、俯仰角、目标角度、角速度和到位阈值。
- 按速度限制逐 slot 靠近目标角度。
- 上报 `PKT_GIMBAL_FB`。
- 支持仿真控制面设置当前位置、速度限制、故障、卡滞、离线和反馈延迟。

云台模拟器不判断是否进入 `S3`，只提供到位反馈。

### 5.3 毫米波基带模拟器

毫米波基带模拟器包含感知面和通信面两类抽象功能：

- 维护虚拟目标的有效标志、角度、距离、径向速度、SNR 和稳定度。
- 周期上报 `PKT_MMW_DETECT`。
- 接收 `PKT_MMW_RF_CTRL`，分别切换 `sense_enable` 和 `comm_enable`。
- 周期上报 `PKT_MMW_LINK_STATUS`，反馈毫米波通信面质量。
- 在搜索、粗对准和回退阶段生成 `PKT_MMW_BITSTREAM` 或业务链路统计。
- 支持仿真控制面设置目标出现、消失、噪声、丢帧、虚警和目标运动。

毫米波基带模拟器不直接控制云台，不直接改变 DSP 状态。

### 5.4 THz 基带模拟器

THz 基带模拟器同样包含感知面和通信面两类抽象功能：

- 接收 `PKT_THZ_PARAM`。
- 根据 `sense_enable`、捕获延迟、锁定策略和链路质量生成 `PKT_THZ_STATUS`。
- 在 `comm_enable` 且锁定后生成 `PKT_THZ_BITSTREAM` 或业务链路统计。
- 在 `PKT_THZ_STATUS` 中上报速度、位置、角度等 THz 感知结果。
- 支持仿真控制面设置强制锁定、强制超时、链路质量下降、失锁、误码和离线。

THz 基带模拟器不直接决定系统是否回退，只上报链路状态。

### 5.5 PC 上位机

PC 软件在真实部署中是上位机，不是硬件模拟器。

通用功能：

- 显示 DSP 当前状态、上行链路和 slot。
- 显示云台、毫米波、THz 和 PC 链路在线状态。
- 查看每个 slot 的协议包、字段、序号、时间戳和异常。
- 下发状态机参数、通信参数和运行控制请求。
- 记录运行日志、原始包流和业务数据。
- 提供告警诊断、数据导出和回放入口。

仿真模式额外功能：

- 设置毫米波目标和噪声。
- 设置云台当前位置、速度、故障和离线。
- 设置 THz 锁定、失锁、链路质量和捕获延迟。
- 设置丢包、延迟、乱序和字段异常。
- 加载测试场景脚本。

真实部署模式必须隐藏或禁用仿真注入能力。

## 6. 运行模式

### 6.1 仿真模式

仿真模式用于无硬件测试：

```bash
python sim_gimbal.py
python sim_mmwave.py
python sim_thz.py
python pc_app.py --mode sim
python dsp_state_machine.py --mode sim
```

第一版传输建议：

- 本机 TCP。
- JSON Lines，每行一个完整消息。
- 每个模拟设备监听固定端口，DSP 作为客户端连接。

建议端口：

| 模块 | 端口 | 说明 |
|---|---:|---|
| 云台模拟器 | 9101 | DSP 发送云台命令，云台返回反馈 |
| 毫米波模拟器 | 9102 | DSP 接收目标感知，发送启停/扫描控制 |
| THz 模拟器 | 9103 | DSP 发送 THz 参数，接收锁定和链路质量 |
| PC 上位机 | 9104 | DSP 上报状态，PC 下发配置和仿真控制 |

### 6.2 真实部署模式

真实部署模式用于接入真实设备：

```bash
python pc_app.py --mode deploy
python dsp_state_machine.py --mode deploy
```

真实硬件替代 `sim_gimbal.py`、`sim_mmwave.py` 和 `sim_thz.py`。DSP 核心状态机和业务协议保持不变，差异由传输适配器处理：

- 云台：RS485 或 USB 转串口。
- 毫米波基带：待硬件确认，可为串口、网口、USB 或板间接口。
- THz/FPGA 基带：网口、光口、SDK 或板间通信。
- PC：上层通信链路和业务数据链路。

## 7. 协议设计

### 7.1 业务消息 envelope

第一版统一消息使用 JSON Lines：

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

字段约定：

| 字段 | 说明 |
|---|---|
| `version` | 协议版本 |
| `slot_id` | DSP 当前 slot 序号 |
| `seq` | 单连接或单模块递增序号 |
| `timestamp_ms` | 发送端时间戳 |
| `src` | 源模块，如 `dsp`、`gimbal`、`mmwave`、`thz`、`pc` |
| `dst` | 目标模块 |
| `packet_id` | 业务包类型 |
| `trigger_type` | 触发类型，`periodic` 表示 slot 周期触发，`event` 表示事件触发 |
| `trigger_reason` | 触发原因，如 `slot_clock`、状态转移原因或仿真控制 ID |
| `payload` | 具体业务字段 |

### 7.2 业务包清单

| packet_id | 方向 | 主要字段 | 用途 |
|---|---|---|---|
| `PKT_SYS_HEALTH` | 各模块 -> DSP | online、fault_code、heartbeat_counter | 自检和运行期健康监控 |
| `PKT_MMW_DETECT` | 毫米波 -> DSP | target_valid、azimuth_deg、elevation_deg、range_m、radial_speed_mps、snr_db | 搜索、粗对准、辅助跟踪和回退恢复 |
| `PKT_MMW_RF_CTRL` | DSP -> 毫米波 | rf_enable、sense_enable、comm_enable、scan_mode、beam_id、gain_index | 控制低频通感感知面和通信面启停 |
| `PKT_MMW_LINK_STATUS` | 毫米波 -> DSP | comm_enable、link_quality、rate_level、modulation_order、uplink_ready | 反馈毫米波通信面质量和可用状态 |
| `PKT_MMW_BITSTREAM` | 毫米波 -> PC | payload_bits、frame_seq、crc、rate_level、modulation_order | 毫米波通信业务数据输出 |
| `PKT_GIMBAL_CMD` | DSP -> 云台 | target_azimuth_deg、target_elevation_deg、angular_speed、fine_tune_enable | 云台粗对准和微调 |
| `PKT_GIMBAL_FB` | 云台 -> DSP | current_azimuth_deg、current_elevation_deg、in_position、position_error_deg | 判断云台是否到位 |
| `PKT_THZ_PARAM` | DSP -> THz | thz_enable、sense_enable、comm_enable、rate_level、modulation_order、capture_timeout_slot、tracking_threshold | 配置 THz 感知面、通信面、捕获和跟踪参数 |
| `PKT_THZ_STATUS` | THz -> DSP | lock_flag、sense_quality、link_quality、loss_count、velocity、position、angle | 捕获锁定、THz 感知结果和跟踪质量判断 |
| `PKT_THZ_BITSTREAM` | THz/FPGA -> PC | payload_bits、frame_seq、crc、rate_level、modulation_order | 业务数据输出 |
| `PKT_UPLINK_STATE` | DSP -> PC | state_id、uplink_mode、lock_flag、fallback_reason、restore_flag | 上位机显示和日志 |

### 7.3 仿真控制消息

仿真控制消息只在仿真模式使用，不能作为真实业务协议的一部分。

示例：

```json
{
  "version": 1,
  "src": "pc",
  "dst": "sim_mmwave",
  "control_id": "SIM_SET_TARGET",
  "trigger_type": "event",
  "trigger_reason": "SIM_SET_TARGET",
  "payload": {
    "target_valid": true,
    "azimuth_deg": 15.0,
    "elevation_deg": 2.0,
    "range_m": 120.0,
    "snr_db": 18.0
  }
}
```

常用仿真控制：

| control_id | 目标 | 用途 |
|---|---|---|
| `SIM_SET_TARGET` | 毫米波 | 设置目标出现、消失和目标参数 |
| `SIM_SET_GIMBAL` | 云台 | 设置当前位置、速度限制、故障和离线 |
| `SIM_SET_THZ_LINK` | THz | 设置锁定、失锁、链路质量和捕获延迟 |
| `SIM_SET_FAULT` | 任意模块 | 设置模块离线、丢包、延迟、乱序和字段异常 |
| `SIM_LOAD_SCENARIO` | PC/模拟器 | 加载预定义测试场景 |

### 7.4 周期触发与事件触发

仿真记录必须区分两类触发来源：

| 类型 | 典型来源 | 记录要求 |
|---|---|---|
| `periodic` | DSP slot 时钟、固定频率控制包、固定频率状态回包、THz 业务流 | 保留 `slot_id`、频率、包类型和 payload，用于看连续时序 |
| `event` | PC 仿真状态注入、状态机转移、故障/离线/超时告警、场景脚本动作 | 保留触发原因、触发前后状态和相关 payload，用于定位关键节点 |

业务包可以是周期包，也可以携带事件信息。例如 `PKT_UPLINK_STATE` 每个 slot 都会上报，但当其中包含状态转移或告警时，该条记录应标记为 `event`，便于 PC 页面和 JSONL 记录单独筛选。

## 8. DSP slot 主循环

每个 slot 的建议处理顺序：

| 阶段 | 动作 |
|---|---|
| T0 同步/健康 | 更新 slot_id，读取各模块心跳和健康状态 |
| T1 感知输入 | 读取毫米波目标感知包 |
| T2 控制决策 | 根据当前状态和输入包计算状态转移 |
| T3 控制下发 | 向云台、毫米波和 THz 发送控制或参数包 |
| T4 反馈回读 | 读取云台反馈和 THz 状态 |
| T5 状态上报 | 向 PC 上报状态、异常原因和本 slot 摘要 |

状态转移输入：

| 状态 | 主要输入 | 转移条件 |
|---|---|---|
| `S0 自检` | 各模块健康状态 | 模块在线且接口正常 -> `S1` |
| `S1 搜索` | 毫米波目标感知 | 连续若干 slot 目标有效且稳定 -> `S2` |
| `S2 粗对准` | 毫米波角度、云台反馈 | 云台误差小于阈值 -> `S3` |
| `S3 捕获` | THz 锁定状态、捕获计时器 | 锁定成功 -> `S4`；超时 -> `S5` |
| `S4 跟踪` | THz 链路质量、毫米波辅助、云台反馈 | 连续若干 slot 质量差或失锁 -> `S6` |
| `S5 回退` | 毫米波目标感知、恢复计时器 | 毫米波稳定恢复 -> `S2`；长时间无恢复 -> `S1` |
| `S6 快速重捕获` | THz 锁定、毫米波目标位置 | 锁定恢复 -> `S4`；目标移动 -> `S2`；超时 -> `S5` |
| `S7 模块恢复` | 模块健康和故障掩码 | 恢复成功 -> `S1/S2`；恢复失败 -> `FAULT` |

## 9. 记录、回放与诊断

公共记录能力需要覆盖：

- 每个 slot 的输入包和输出包。
- 状态变化事件。
- PC 下发的配置和控制请求。
- 模块在线/离线和异常事件。
- THz 业务数据统计。
- 按 `trigger_type` 分组保存周期记录与事件记录，方便回放和排障。

建议输出格式：

- JSONL：保存原始包流，便于回放。
- CSV：保存关键指标，便于分析。
- 文本日志：保存人工可读的状态变化和告警。

回放模式应能读取历史 JSONL，将数据重新喂给 DSP 状态机，用于复现问题。

## 10. 开发计划

### 阶段 1：文档与边界整理

- 更新 README 和本技术方案。
- 明确当前 `app.py` 是 v0 演示器。
- 确定仿真模式和真实部署模式边界。

### 阶段 2：公共协议层

- 建立 `common` 目录。
- 定义状态枚举、模块 ID、packet_id、统一 envelope。
- 定义业务包 payload schema。
- 实现 TCP + JSON Lines 传输封装。

### 阶段 3：模拟设备程序

- 实现云台、毫米波、THz 模拟器。
- 每个模拟器支持业务协议收发和仿真控制消息。
- 每个模拟器打印本地状态和包日志。

### 阶段 4：DSP 主程序

- 实现固定 slot 时钟。
- 实现 `IDLE/FAULT/S0-S7` 自动状态转移。
- 向各模块发送控制包，向 PC 上报状态。
- 支持日志记录和回放输入。

### 阶段 5：PC 上位机

- 第一版使用控制台界面，显示状态、包流和告警。
- 仿真模式提供状态注入命令。
- 后续复用 Streamlit 可视化能力，形成图形化上位机。

### 阶段 6：真实硬件适配

- 增加串口、RS485、网口、光口或 SDK transport。
- 保持 DSP 状态机和业务协议不变。
- 将真实硬件反馈接入统一协议层。

## 11. 验收场景

| 场景 | 期望结果 |
|---|---|
| 正常路径 | `S0 -> S1 -> S2 -> S3 -> S4` |
| 捕获失败 | THz 超时后 `S3 -> S5` |
| 跟踪失锁 | THz 质量连续变差后 `S4 -> S6`，重捕获失败再进入 `S5` |
| 回退恢复 | 毫米波稳定恢复后 `S5 -> S2` |
| 长时间无恢复 | 回退超时后 `S5 -> S1` |
| 云台不到位 | DSP 停留在 `S2`，PC 显示到位超时告警 |
| 毫米波目标丢失 | DSP 无法从 `S1` 进入 `S2`，或在 `S5` 无法恢复 |
| 设备离线 | DSP 进入自检失败或异常告警状态 |
| 模块恢复 | 运行中设备离线进入 `S7`，恢复成功返回 `S1/S2`，失败进入 `FAULT` |
| 包丢失/延迟 | 日志记录超时和丢包统计，状态机不误触发 |

## 12. 后续与当前可视化的关系

当前 `app.py` 中的可视化能力应保留并逐步拆分复用：

- 物理架构图用于 PC 上位机监控页面。
- 状态机拓扑用于显示当前状态和可达路径。
- slot 数据包清单用于协议包查看。
- 链路高亮用于显示当前状态或选中数据包的实际传输路径。

最终目标不是丢弃当前 Streamlit 页面，而是把它从“状态机本体”中解耦出来，转化为 PC 上位机的一部分。
