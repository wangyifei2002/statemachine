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
    PKT_MMW_DETECT, PKT_MMW_LINK_STATUS, PKT_THZ_STATUS,
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
            record = {
                "slot_id": slot_id,
                "previous_state": result.previous_state,
                "state": result.state,
                "reason": result.reason,
                "fault_mask": result.fault_mask,
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
