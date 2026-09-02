# 控制板与 THz 通感模块 TCP/UDP 通信协议规范

> 范围：DSP/控制板与 THz/FPGA 基带板之间的控制和状态通信  
> 默认 slot：100 ms / 10 Hz，允许配置

## 1. 总体方案

- **TCP**：可靠命令、配置、ACK/NACK、心跳和关键事件。
- **UDP**：每 slot 上报 THz 状态和感知结果。
- **光口 IEEE 802.3**：THz 高速业务比特流直接输出到 PC/服务器，不经过 STM32。
- TCP 和 UDP 使用相同二进制帧，Python 仿真仍可使用 JSON Lines。

```mermaid
flowchart LR
    FSM["DSP 状态机"] --> ADAPTER["THz 协议适配器"]
    ADAPTER -->|"TCP 命令 / ACK / 事件"| THZ["THz / FPGA 基带板"]
    THZ -->|"UDP 10 Hz 状态"| ADAPTER
    ADAPTER --> FSM
    THZ -->|"光口业务流"| PC["PC / 服务器"]
```

现有仿真包映射：

| 仿真业务包 | 硬件协议 |
|---|---|
| `PKT_THZ_PARAM` | `SET_CONFIG` + `SET_MODE` |
| `PKT_THZ_STATUS` | `THZ_STATUS` |
| `PKT_SYS_HEALTH` | `HEARTBEAT` + `THZ_HEALTH` |
| `PKT_THZ_BITSTREAM` | 仅走 FPGA 光口 |

## 2. 网络约定

| 项目 | 默认值 |
|---|---:|
| IP | IPv4，地址可配置 |
| THz TCP Server | `9200` |
| DSP UDP Receiver | `9201` |
| 应用心跳 | `1 Hz` |
| UDP 状态 | `10 Hz` |
| TCP 应答超时 | `100 ms` |
| 命令重试 | 最多 3 次，使用原 `seq` |
| UDP 数据过期 | 3 slots，默认 `300 ms` |
| 最大 payload | `1024 bytes`，禁止 IP 分片 |

THz 默认作为 TCP Server，DSP 作为 Client。TCP 重连后必须重新执行 `HELLO -> GET_CAPABILITY -> SET_CONFIG -> SET_MODE`。关键锁定/失锁/故障事件走 TCP，并在后续 UDP 状态中持续反映。

> **硬件注意**：阿波罗 V2 STM32H743 的 `ETH_MDIO` 与 `USART2_TX` 共用 `PA2`，`ETH_TX_EN` 与 `USART3_RX` 共用 `PB11`。当前云台使用 USART2 时，启用板载网口前必须先确认引脚重映射或独立网口方案。

## 3. 二进制帧

### 3.1 帧头

V1 固定帧头为 32 字节：

| 偏移 | 长度 | 字段 | 说明 |
|---:|---:|---|---|
| 0 | 4 | `magic` | `54 48 5A 31`，ASCII `THZ1` |
| 4 | 1 | `version_major` | 不兼容变更递增 |
| 5 | 1 | `version_minor` | 兼容变更递增 |
| 6 | 1 | `header_len` | V1 固定 `32` |
| 7 | 1 | `flags` | 帧标志 |
| 8 | 2 | `msg_type` | 消息 ID |
| 10 | 1 | `src_id` | DSP=`0x01`，THz=`0x02`，PC=`0x03` |
| 11 | 1 | `dst_id` | 目标模块 ID |
| 12 | 4 | `seq` | 发送方递增序号 |
| 16 | 4 | `slot_id` | DSP slot，无效时为 0 |
| 20 | 8 | `timestamp_us` | 微秒时间戳，无效时为 0 |
| 28 | 2 | `payload_len` | `0..1024` |
| 30 | 2 | `reserved` | 固定为 0 |
| 32 | N | `payload` | 按 `msg_type` 解析 |
| 32+N | 4 | `crc32` | 覆盖帧头和 payload |

### 3.2 编解码规则

- 多字节整数统一小端序，有符号数使用补码。
- payload 严格按字段表顺序连续编码，无 padding。
- 禁止直接发送 C 结构体，禁止浮点数、字符串和 NaN。
- CRC 使用 `CRC-32/ISO-HDLC`，参数以黄金报文为准。
- TCP 按 `magic + payload_len` 处理拆包/粘包。
- 一个 UDP datagram 只包含一帧，长度必须等于 `36 + payload_len`。

`flags`：bit0 `ACK_REQUIRED`，bit1 `RESPONSE`，bit2 `EVENT`，bit3 `ERROR`，bit4 `RETRANSMIT`，bit5 `TIME_VALID`，bit6..7 保留。

## 4. 消息 ID

| ID | 消息 | 方向 | 通道 |
|---:|---|---|---|
| `0x0001` | `HELLO_REQ` | DSP -> THz | TCP |
| `0x0002` | `HEARTBEAT` | 双向 | TCP |
| `0x0003` | `GET_CAPABILITY` | DSP -> THz | TCP |
| `0x0101` | `SET_CONFIG` | DSP -> THz | TCP |
| `0x0102` | `SET_MODE` | DSP -> THz | TCP |
| `0x0103` | `REACQUIRE` | DSP -> THz | TCP |
| `0x0104` | `QUERY_STATUS` | DSP -> THz | TCP |
| `0x0105` | `CLEAR_FAULT` | DSP -> THz | TCP |
| `0x8001` | `HELLO_RESP` | THz -> DSP | TCP |
| `0x8101` | `ACK` | THz -> DSP | TCP |
| `0x8102` | `NACK` | THz -> DSP | TCP |
| `0x8201` | `THZ_STATUS` | THz -> DSP | UDP，查询时 TCP |
| `0x8202` | `THZ_EVENT` | THz -> DSP | TCP |
| `0x8203` | `THZ_HEALTH` | THz -> DSP | TCP |
| `0x8204` | `CAPABILITY_RESP` | THz -> DSP | TCP |

## 5. 核心 payload

### 5.1 `SET_CONFIG`

| 字段 | 类型 | 含义 |
|---|---|---|
| `config_id` | `uint32` | 配置版本 |
| `report_period_slots` | `uint16` | UDP 上报周期 |
| `capture_timeout_slots` | `uint16` | 捕获超时 |
| `tracking_quality_threshold` | `uint16` | 跟踪阈值，`0..1000` |
| `sense_quality_threshold` | `uint16` | 感知阈值，`0..1000` |
| `rate_profile` | `uint8` | 速率档位枚举 |
| `modulation` | `uint8` | 调制方式枚举 |
| `enable_flags` | `uint16` | 功能使能位 |
| `control_watchdog_slots` | `uint16` | 失联安全看门狗 |
| `reserved` | `uint16` | 0 |

### 5.2 `SET_MODE`

payload 为 `mode:uint8 + mode_flags:uint8 + enable_flags:uint16 + config_id:uint32`。

| `mode` | 含义 |
|---:|---|
| `0 SAFE` | 关闭业务发送，保留管理通信 |
| `1 STANDBY` | 就绪待机 |
| `2 CAPTURE` | THz 捕获 |
| `3 TRACK` | 锁定跟踪与通信 |
| `4 REACQUIRE` | 快速重捕获 |
| `5 DIAGNOSTIC` | 联调诊断 |

`enable_flags`：bit0 `thz_enable`，bit1 `sense_enable`，bit2 `comm_enable`，bit3 `traffic_enable`。命令必须表达明确目标状态，禁止 toggle 语义。

### 5.3 `ACK/NACK`

payload 为 `ack_seq:uint32 + ack_msg_type:uint16 + result_code:uint16 + applied_config_id:uint32 + detail:uint32`。

通用结果码：`0 OK`，`1 UNSUPPORTED_VERSION`，`2 INVALID_LENGTH`，`3 INVALID_PARAMETER`，`4 UNSUPPORTED_MESSAGE`，`5 UNSUPPORTED_MODE`，`6 BUSY`，`7 NOT_READY`，`8 CONFIG_MISMATCH`，`9 INTERNAL_FAULT`，`10 TIMEOUT`。

### 5.4 `THZ_STATUS`

V1 payload 固定 64 字节：

| 字段 | 类型 | 单位/含义 |
|---|---|---|
| `sample_seq` | `uint32` | 样本序号 |
| `sample_slot_id` | `uint32` | 关联 slot |
| `sample_timestamp_us` | `uint64` | 样本时间 |
| `status_flags` | `uint32` | 模块状态位 |
| `valid_mask` | `uint32` | 字段有效位 |
| `mode/rate_profile/modulation/reserved` | `4 * uint8` | 当前模式和参数 |
| `fault_code` | `uint16` | 故障码 |
| `link_quality` | `uint16` | `0..1000` |
| `sense_quality` | `uint16` | `0..1000` |
| `loss_count` | `uint16` | 连续失锁/低质量数 |
| `applied_config_id` | `uint32` | 已应用配置 |
| `velocity_mmps` | `int32` | `mm/s` |
| `position_x/y/z_mm` | `3 * int32` | `mm` |
| `azimuth_mdeg` | `int32` | `0.001 deg` |
| `elevation_mdeg` | `int32` | `0.001 deg` |

`status_flags`：online、ready、config_valid、locked、sense_active、comm_active、traffic_active、time_sync_valid、warning、fault，按 bit0..9 排列。

`valid_mask`：velocity、position_x/y/z、azimuth、elevation、link_quality、sense_quality，按 bit0..7 排列。无效值可填 0，但必须以 `valid_mask` 判断。

### 5.5 `THZ_EVENT`

payload 为 `event_id:uint32 + event_code:uint16 + severity:uint8 + reserved:uint8 + related_seq:uint32 + detail:uint32`。

必须支持：`LOCK_ACQUIRED`、`LOCK_LOST`、`CAPTURE_TIMEOUT`、`REACQUIRE_SUCCEEDED`、`REACQUIRE_FAILED`、`QUALITY_LOW`、`MODULE_READY`、`MODULE_FAULT`、`CONFIG_APPLIED`、`WATCHDOG_ENTER_SAFE`。

## 6. 状态机映射

| DSP 状态 | THz 动作 | 关键输入 |
|---|---|---|
| `S0` | HELLO、能力查询、配置 | online + ready + config_valid |
| `S1/S2` | `STANDBY` | 维持心跳 |
| `S3` | `CAPTURE` | locked + link_quality |
| `S4` | `TRACK` | locked + link_quality + 感知数据 |
| `S5` | `SAFE/STANDBY` | 关闭 THz 业务流 |
| `S6` | `REACQUIRE` | 重捕获结果 |
| `S7` | 重连并重新配置 | online + ready + config_valid |
| `FAULT` | `SAFE` | 等待复位/清错 |

## 7. 可靠性和安全

- 所有控制命令必须幂等；重发时使用原 `seq`。
- THz 缓存最近命令结果，重复 `seq` 只重发 ACK，不重复执行。
- 单个 UDP 丢包不触发状态转移；连续 3 slots 无有效帧则标记 stale。
- 网络回调只更新输入快照，状态机在 slot 主循环中统一判决。
- THz 上电默认 `SAFE`；未完成版本和配置确认前不得启动业务发送。
- 超过 `control_watchdog_slots` 未收到有效心跳/命令时进入 `SAFE`。
- major 版本不同禁止运行；minor 版本不同只使用双方共同能力。

## 8. 联调与验收

1. **协议冻结**：确认网口、IP/端口、坐标系、速率/调制枚举和安全行为。
2. **PC 直连**：Python 工具完成 TCP 命令、UDP 状态、CRC、丢包和日志验证。
3. **STM32 在环**：实现非阻塞网络适配器，打通 `S0 -> S3 -> S4 -> S6/S5/S7`。

验收要求：

- Python、STM32、THz/FPGA 黄金报文解码一致。
- TCP 支持拆包、粘包、超时、幂等重试和重连。
- UDP 10 Hz 稳定上报，丢包/乱序可统计，不误触发状态机。
- 锁定、失锁和故障在 1 slot 内被 DSP 看到。
- THz 重启后 DSP 可自动重连、重新配置并恢复。

## 9. 待确认项

- THz 板是否已支持 TCP Server 和 UDP 主动上报。
- 控制板最终网口方案及 USART2 引脚冲突解决方式。
- IP/MAC/端口管理方式。
- 速度、位置、角度的坐标系、单位、范围和精度。
- `rate_profile`、`modulation`、故障码和锁定/质量判据。
- TCP 断线和看门狗超时后的最终安全动作。
- 10 MHz/1PPS 与 `slot_id/timestamp_us` 的对应关系。

协议冻结后同步产出 C/Python 编解码库、黄金报文、联调工具和验收记录。
