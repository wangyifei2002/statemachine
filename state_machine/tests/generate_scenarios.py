#!/usr/bin/env python3
"""Generate deterministic cross-language CSV scenarios from explicit stimuli."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dsp_simulator"))

from common.protocol import (  # noqa: E402
    MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ, PKT_GIMBAL_FB,
    PKT_MMW_DETECT, PKT_MMW_LINK_STATUS, PKT_THZ_STATUS,
)
from common.state_machine import DspStateMachine  # noqa: E402


FIELDS = [
    "slot_id", "start", "reset", "mmwave_online", "thz_online", "gimbal_online",
    "target_valid", "azimuth_mdeg", "elevation_mdeg", "gimbal_in_position",
    "position_error_mdeg", "thz_locked", "thz_quality", "mmwave_uplink_ready",
    "mmwave_quality", "expected_state", "expected_reason",
]


def stimulus(slot: int, **overrides: int) -> dict[str, int]:
    values = {
        "slot_id": slot, "start": 0, "reset": 0,
        "mmwave_online": 1, "thz_online": 1, "gimbal_online": 1,
        "target_valid": 0, "azimuth_mdeg": 12000, "elevation_mdeg": 2000,
        "gimbal_in_position": 0, "position_error_mdeg": 5000,
        "thz_locked": 0, "thz_quality": 900,
        "mmwave_uplink_ready": 1, "mmwave_quality": 800,
    }
    values.update(overrides)
    return values


def packet(row: dict[str, int]) -> dict:
    slot = row["slot_id"]
    meta = {"valid": True, "seq": slot, "age_slots": 0}
    return {
        "start": bool(row["start"]), "reset": bool(row["reset"]),
        "health": {
            MODULE_MMWAVE: bool(row["mmwave_online"]),
            MODULE_THZ: bool(row["thz_online"]),
            MODULE_GIMBAL: bool(row["gimbal_online"]),
        },
        PKT_MMW_DETECT: {**meta, "target_valid": bool(row["target_valid"]),
                         "azimuth_mdeg": row["azimuth_mdeg"], "elevation_mdeg": row["elevation_mdeg"]},
        PKT_MMW_LINK_STATUS: {**meta, "uplink_ready": bool(row["mmwave_uplink_ready"]),
                              "link_quality": row["mmwave_quality"]},
        PKT_GIMBAL_FB: {**meta, "in_position": bool(row["gimbal_in_position"]),
                        "position_error_mdeg": row["position_error_mdeg"]},
        PKT_THZ_STATUS: {**meta, "lock_flag": bool(row["thz_locked"]),
                         "link_quality": row["thz_quality"]},
    }


def base_to_tracking() -> list[dict[str, int]]:
    return [
        stimulus(1, start=1), stimulus(2),
        stimulus(3),
        stimulus(4, target_valid=1), stimulus(5, target_valid=1), stimulus(6, target_valid=1),
        stimulus(7, target_valid=1, gimbal_in_position=1, position_error_mdeg=100),
        stimulus(8, target_valid=1, gimbal_in_position=1, position_error_mdeg=100),
        stimulus(9, target_valid=1, gimbal_in_position=1, position_error_mdeg=100, thz_locked=1),
        stimulus(10, target_valid=1, gimbal_in_position=1, position_error_mdeg=100, thz_locked=1),
    ]


def base_to_capture() -> list[dict[str, int]]:
    return base_to_tracking()[:8]


def build_scenarios() -> dict[str, list[dict[str, int]]]:
    normal = base_to_tracking()
    normal.extend(stimulus(slot, target_valid=1, gimbal_in_position=1,
                           position_error_mdeg=100, thz_quality=100)
                  for slot in range(11, 14))
    normal.extend([
        stimulus(14, target_valid=1, gimbal_in_position=1, position_error_mdeg=100, thz_locked=1),
        stimulus(15, target_valid=1, gimbal_in_position=1, position_error_mdeg=100, thz_locked=1),
    ])

    recovery = base_to_tracking()
    recovery.append(stimulus(11, target_valid=1, thz_online=0, thz_quality=0))
    recovery.extend(stimulus(slot, target_valid=1, thz_locked=1) for slot in range(12, 15))

    capture_timeout = base_to_capture()
    capture_timeout.extend(stimulus(slot, target_valid=1, gimbal_in_position=1,
                                    position_error_mdeg=100, thz_quality=100)
                           for slot in range(9, 29))

    reacquire_timeout = base_to_tracking()
    reacquire_timeout.extend(stimulus(slot, target_valid=1, thz_quality=100)
                             for slot in range(11, 34))

    target_moved = base_to_tracking()
    target_moved.extend(stimulus(slot, target_valid=1, thz_quality=100)
                        for slot in range(11, 14))
    target_moved.append(stimulus(14, target_valid=1, azimuth_mdeg=16001, thz_quality=100))

    fallback_restore = list(capture_timeout)
    fallback_restore.extend(stimulus(slot, target_valid=1, thz_quality=100)
                            for slot in range(29, 32))

    recovery_failure = base_to_tracking()
    recovery_failure.extend(stimulus(slot, target_valid=1, thz_online=0, thz_quality=0)
                            for slot in range(11, 27))
    recovery_failure.append(stimulus(27, reset=1))

    return {
        "normal_reacquire.csv": normal,
        "module_recovery.csv": recovery,
        "capture_timeout.csv": capture_timeout,
        "reacquire_timeout.csv": reacquire_timeout,
        "reacquire_realign.csv": target_moved,
        "fallback_restore.csv": fallback_restore,
        "recovery_failure_reset.csv": recovery_failure,
    }


def main() -> None:
    destination = Path(__file__).with_name("scenarios")
    destination.mkdir(parents=True, exist_ok=True)
    for filename, rows in build_scenarios().items():
        fsm = DspStateMachine()
        with (destination / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                result = fsm.step(row["slot_id"], packet(row))
                writer.writerow({**row, "expected_state": result.state, "expected_reason": result.reason})


if __name__ == "__main__":
    main()
