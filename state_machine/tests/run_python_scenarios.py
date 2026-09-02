#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dsp_simulator"))

from common.protocol import (  # noqa: E402
    MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ, PKT_GIMBAL_FB,
    PKT_GIMBAL_CMD, PKT_MMW_DETECT, PKT_MMW_LINK_STATUS, PKT_MMW_RF_CTRL,
    PKT_THZ_PARAM, PKT_THZ_STATUS,
)
from common.state_machine import DspStateMachine  # noqa: E402


def flag(row: dict[str, str], key: str) -> bool:
    return row[key] == "1"


def packet(row: dict[str, str]) -> dict:
    return {
        "start": flag(row, "start"),
        "reset": flag(row, "reset"),
        "health": {
            MODULE_MMWAVE: flag(row, "mmwave_online"),
            MODULE_THZ: flag(row, "thz_online"),
            MODULE_GIMBAL: flag(row, "gimbal_online"),
        },
        PKT_MMW_DETECT: {
            "valid": True, "seq": int(row["slot_id"]), "age_slots": 0,
            "target_valid": flag(row, "target_valid"),
            "azimuth_mdeg": int(row["azimuth_mdeg"]),
            "elevation_mdeg": int(row["elevation_mdeg"]),
        },
        PKT_MMW_LINK_STATUS: {
            "valid": True, "seq": int(row["slot_id"]), "age_slots": 0,
            "uplink_ready": flag(row, "mmwave_uplink_ready"),
            "link_quality": int(row["mmwave_quality"]),
        },
        PKT_GIMBAL_FB: {
            "valid": True, "seq": int(row["slot_id"]), "age_slots": 0,
            "in_position": flag(row, "gimbal_in_position"),
            "position_error_mdeg": int(row["position_error_mdeg"]),
        },
        PKT_THZ_STATUS: {
            "valid": True, "seq": int(row["slot_id"]), "age_slots": 0,
            "lock_flag": flag(row, "thz_locked"),
            "link_quality": int(row["thz_quality"]),
        },
    }


def run(path: Path) -> list[dict]:
    fsm = DspStateMachine()
    records = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            slot_id = int(row["slot_id"])
            result = fsm.step(slot_id, packet(row))
            outputs = {output["packet_id"]: output["payload"] for output in result.outputs}
            mmwave = outputs[PKT_MMW_RF_CTRL]
            gimbal = outputs[PKT_GIMBAL_CMD]
            thz = outputs[PKT_THZ_PARAM]
            record = {
                "slot_id": slot_id,
                "previous_state": result.previous_state,
                "state": result.state,
                "reason": result.reason,
                "fault_mask": result.fault_mask,
                "recovery_action_mask": next(
                    output["payload"].get("recovery_action_mask", 0)
                    for output in result.outputs if output.get("dst") == "pc"
                ),
                "mmwave": {
                    "rf_enable": int(mmwave["rf_enable"]),
                    "sense_enable": int(mmwave["sense_enable"]),
                    "comm_enable": int(mmwave["comm_enable"]),
                    "scan_mode": mmwave["scan_mode"],
                },
                "gimbal": {
                    "enable": int(gimbal["enable"]),
                    "fine_tune_enable": int(gimbal["fine_tune_enable"]),
                    "target_azimuth_mdeg": gimbal["target_azimuth_mdeg"],
                    "target_elevation_mdeg": gimbal["target_elevation_mdeg"],
                    "angular_speed_mdeg_s": gimbal["angular_speed_mdeg_s"],
                },
                "thz": {
                    "thz_enable": int(thz["thz_enable"]),
                    "sense_enable": int(thz["sense_enable"]),
                    "comm_enable": int(thz["comm_enable"]),
                    "traffic_enable": int(thz["traffic_enable"]),
                    "reacquire": int(thz["reacquire"]),
                },
            }
            if result.state != row["expected_state"] or result.reason != row["expected_reason"]:
                raise AssertionError(f"{path.name}:{slot_id}: {record}, expected {row['expected_state']}/{row['expected_reason']}")
            records.append(record)
    return records


def main() -> None:
    for value in sys.argv[1:]:
        for record in run(Path(value)):
            print(json.dumps(record, separators=(",", ":")))


if __name__ == "__main__":
    main()
