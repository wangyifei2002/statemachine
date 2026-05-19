"""DSP state-machine process for local five-process simulation."""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from typing import Any

from common.protocol import (
    MODULE_DSP,
    MODULE_GIMBAL,
    MODULE_MMWAVE,
    MODULE_PC,
    MODULE_THZ,
    PKT_GIMBAL_CMD,
    PKT_GIMBAL_FB,
    PKT_MMW_DETECT,
    PKT_MMW_LINK_STATUS,
    PKT_MMW_RF_CTRL,
    PKT_SYS_HEALTH,
    PKT_THZ_PARAM,
    PKT_THZ_STATUS,
    PKT_UPLINK_STATE,
    TRIGGER_EVENT,
    TRIGGER_PERIODIC,
)
from common.recorder import JsonlRecorder
from common.state_machine import DspStateMachine
from common.transport import JsonLineClient


HEALTH_TIMEOUT_SLOTS = 3
CRITICAL_MODULES = (MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DSP state-machine simulator")
    parser.add_argument("--mode", choices=["sim", "deploy"], default="sim")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--gimbal-port", type=int, default=9101)
    parser.add_argument("--mmwave-port", type=int, default=9102)
    parser.add_argument("--thz-port", type=int, default=9103)
    parser.add_argument("--pc-port", type=int, default=9104)
    parser.add_argument("--slot-hz", type=float, default=10.0)
    parser.add_argument("--max-slots", type=int, default=0, help="0 means run forever")
    parser.add_argument("--record", default="", help="optional JSONL record path")
    return parser.parse_args()


def latest_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return messages[-1].get("payload", {}) if messages else {}


def compact_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def output_payload(outputs: list[dict[str, Any]], packet_id: str) -> dict[str, Any]:
    for output in outputs:
        if output.get("packet_id") == packet_id:
            return dict(output.get("payload", {}))
    return {}


def build_slot_io(snapshot: dict[str, Any], outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mmwave_cmd = output_payload(outputs, PKT_MMW_RF_CTRL)
    gimbal_cmd = output_payload(outputs, PKT_GIMBAL_CMD)
    thz_param = output_payload(outputs, PKT_THZ_PARAM)
    uplink_state = output_payload(outputs, PKT_UPLINK_STATE)
    mmwave_detect = dict(snapshot.get(PKT_MMW_DETECT, {}))
    mmwave_link = dict(snapshot.get(PKT_MMW_LINK_STATUS, {}))
    gimbal_fb = dict(snapshot.get(PKT_GIMBAL_FB, {}))
    thz_status = dict(snapshot.get(PKT_THZ_STATUS, {}))

    return {
        MODULE_DSP: {
            "input": {
                "mmwave": compact_payload(mmwave_detect, ("target_valid", "azimuth_deg", "range_m", "snr_db")),
                "gimbal": compact_payload(gimbal_fb, ("in_position", "position_error_deg", "fault_mode")),
                "thz": compact_payload(thz_status, ("lock_flag", "link_quality", "loss_count")),
            },
            "output": {
                "mmwave": compact_payload(mmwave_cmd, ("rf_enable", "sense_enable", "comm_enable", "scan_mode")),
                "gimbal": compact_payload(gimbal_cmd, ("enable", "target_azimuth_deg", "target_elevation_deg", "fine_tune_enable")),
                "thz": compact_payload(thz_param, ("thz_enable", "sense_enable", "comm_enable", "traffic_enable")),
                "pc": compact_payload(uplink_state, ("state_id", "transition", "uplink_mode")),
            },
        },
        MODULE_GIMBAL: {
            "input": compact_payload(gimbal_cmd, ("enable", "target_azimuth_deg", "target_elevation_deg", "angular_speed", "fine_tune_enable")),
            "output": compact_payload(gimbal_fb, ("in_position", "current_azimuth_deg", "current_elevation_deg", "position_error_deg", "fault_mode")),
        },
        MODULE_MMWAVE: {
            "input": compact_payload(mmwave_cmd, ("rf_enable", "sense_enable", "comm_enable", "scan_mode", "comm_rate_level")),
            "output": {
                "detect": compact_payload(mmwave_detect, ("target_valid", "azimuth_deg", "elevation_deg", "range_m", "snr_db")),
                "link": compact_payload(mmwave_link, ("uplink_ready", "link_quality", "sense_quality")),
            },
        },
        MODULE_THZ: {
            "input": compact_payload(thz_param, ("thz_enable", "sense_enable", "comm_enable", "traffic_enable", "rate_level")),
            "output": compact_payload(thz_status, ("lock_flag", "link_quality", "sense_quality", "loss_count")),
        },
    }


def update_health_detail(
    module: str,
    payload: dict[str, Any],
    slot_id: int,
    health: dict[str, bool],
    health_detail: dict[str, dict[str, Any]],
    last_health_slot: dict[str, int],
) -> None:
    online = bool(payload.get("online", False))
    health[module] = online
    last_health_slot[module] = slot_id
    health_detail[module] = {
        "online": online,
        "reported_online": online,
        "fault_code": payload.get("fault_code", "none"),
        "heartbeat_counter": payload.get("heartbeat_counter"),
        "last_seen_slot": slot_id,
        "age_slots": 0,
        "timed_out": False,
    }


def refresh_health_timeouts(
    slot_id: int,
    health: dict[str, bool],
    health_detail: dict[str, dict[str, Any]],
    last_health_slot: dict[str, int],
) -> None:
    for module in CRITICAL_MODULES:
        if module not in last_health_slot:
            health[module] = False
            health_detail[module] = {
                "online": False,
                "reported_online": False,
                "fault_code": "no_heartbeat",
                "heartbeat_counter": None,
                "last_seen_slot": 0,
                "age_slots": None,
                "timed_out": True,
            }
            continue

        age_slots = slot_id - last_health_slot[module]
        detail = dict(health_detail.get(module, {}))
        detail["age_slots"] = age_slots
        detail["last_seen_slot"] = last_health_slot[module]
        if age_slots > HEALTH_TIMEOUT_SLOTS:
            health[module] = False
            detail["online"] = False
            detail["timed_out"] = True
            detail["fault_code"] = "heartbeat_timeout"
        else:
            detail["online"] = bool(detail.get("reported_online", health.get(module, False)))
            detail["timed_out"] = False
            health[module] = bool(detail["online"])
        health_detail[module] = detail


def run_sim(args: argparse.Namespace) -> None:
    clients = {
        MODULE_GIMBAL: JsonLineClient(args.host, args.gimbal_port, "dsp-gimbal"),
        MODULE_MMWAVE: JsonLineClient(args.host, args.mmwave_port, "dsp-mmwave"),
        MODULE_THZ: JsonLineClient(args.host, args.thz_port, "dsp-thz"),
        MODULE_PC: JsonLineClient(args.host, args.pc_port, "dsp-pc"),
    }
    machine = DspStateMachine()
    recorder = JsonlRecorder(args.record or None)
    latest_by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    health: dict[str, bool] = {module: False for module in CRITICAL_MODULES}
    health_detail: dict[str, dict[str, Any]] = {}
    last_health_slot: dict[str, int] = {}
    slot_interval = 1.0 / max(args.slot_hz, 0.1)
    slot_id = 0

    print(f"DSP started in sim mode, slot_hz={args.slot_hz}")
    try:
        while args.max_slots <= 0 or slot_id < args.max_slots:
            started = time.monotonic()
            slot_id += 1

            for module, client in clients.items():
                for message in client.drain():
                    packet_id = message.get("packet_id")
                    if packet_id == PKT_SYS_HEALTH:
                        src = message.get("src", module)
                        update_health_detail(
                            src,
                            message.get("payload", {}),
                            slot_id,
                            health,
                            health_detail,
                            last_health_slot,
                        )
                    elif packet_id:
                        latest_by_packet[packet_id].append(message)
                    recorder.record("rx", message)

            refresh_health_timeouts(slot_id, health, health_detail, last_health_slot)

            snapshot = {
                "health": dict(health),
                "health_detail": {module: dict(detail) for module, detail in health_detail.items()},
                "PKT_MMW_DETECT": latest_payload(latest_by_packet.get("PKT_MMW_DETECT", [])),
                "PKT_MMW_LINK_STATUS": latest_payload(latest_by_packet.get("PKT_MMW_LINK_STATUS", [])),
                "PKT_GIMBAL_FB": latest_payload(latest_by_packet.get("PKT_GIMBAL_FB", [])),
                "PKT_THZ_STATUS": latest_payload(latest_by_packet.get("PKT_THZ_STATUS", [])),
            }
            result = machine.step(slot_id, snapshot)
            recorder.record("state", {
                "slot_id": slot_id,
                "state": result.state,
                "previous_state": result.previous_state,
                "transition": result.transition,
                "alerts": result.alerts,
                "diagnostics": result.diagnostics,
                "trigger_type": TRIGGER_EVENT if result.transition or result.alerts else TRIGGER_PERIODIC,
                "trigger_reason": result.transition or "; ".join(result.alerts) or "slot_step",
            })

            for output in result.outputs:
                dst = output["dst"]
                if output.get("packet_id") == PKT_UPLINK_STATE:
                    output["payload"]["module_health"] = dict(health)
                    output["payload"]["module_health_detail"] = {
                        module: dict(detail) for module, detail in health_detail.items()
                    }
                    output["payload"]["slot_io"] = build_slot_io(snapshot, result.outputs)
                    output["payload"]["slot_hz"] = args.slot_hz
                client = clients.get(dst)
                if client:
                    client.send(output)
                    recorder.record("tx", output)

            transition_text = f" transition={result.transition}" if result.transition else ""
            alert_text = f" alerts={result.alerts}" if result.alerts else ""
            print(f"[slot {slot_id:05d}] state={result.state} health={snapshot.get('health', {})}{transition_text}{alert_text}")

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, slot_interval - elapsed))
    except KeyboardInterrupt:
        print("DSP stopped")
    finally:
        recorder.close()
        for client in clients.values():
            client.close()


def main() -> None:
    args = parse_args()
    if args.mode == "deploy":
        print("deploy mode is reserved: real serial/RS485/network adapters are not implemented yet.")
        return
    run_sim(args)


if __name__ == "__main__":
    main()
