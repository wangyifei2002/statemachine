"""Gimbal hardware simulator."""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass

from common.protocol import (
    MODULE_DSP,
    MODULE_GIMBAL,
    PKT_GIMBAL_CMD,
    PKT_GIMBAL_FB,
    PKT_SYS_HEALTH,
    SIM_SET_FAULT,
    SIM_SET_GIMBAL,
    make_message,
)
from common.transport import JsonLineServer, Peer


@dataclass
class GimbalState:
    online: bool = True
    current_azimuth_deg: float = 0.0
    current_elevation_deg: float = 0.0
    target_azimuth_deg: float = 0.0
    target_elevation_deg: float = 0.0
    speed_limit_deg_s: float = 20.0
    in_position_threshold_deg: float = 0.5
    fault_mode: str = "none"
    drop_rate: float = 0.0
    last_slot_id: int = 0

    def apply_command(self, payload: dict) -> None:
        if not payload.get("enable", True):
            return
        self.target_azimuth_deg = float(payload.get("target_azimuth_deg", self.target_azimuth_deg))
        self.target_elevation_deg = float(payload.get("target_elevation_deg", self.target_elevation_deg))
        self.speed_limit_deg_s = float(payload.get("angular_speed", self.speed_limit_deg_s))

    def step(self, slot_id: int, slot_hz: float = 10.0) -> None:
        delta_slots = max(1, slot_id - self.last_slot_id) if self.last_slot_id else 1
        self.last_slot_id = slot_id
        if not self.online or self.fault_mode in {"stuck", "offline"}:
            return
        max_delta = self.speed_limit_deg_s / slot_hz * delta_slots
        self.current_azimuth_deg = self._move(self.current_azimuth_deg, self.target_azimuth_deg, max_delta)
        self.current_elevation_deg = self._move(self.current_elevation_deg, self.target_elevation_deg, max_delta)

    @staticmethod
    def _move(current: float, target: float, max_delta: float) -> float:
        diff = target - current
        if abs(diff) <= max_delta:
            return target
        return current + (max_delta if diff > 0 else -max_delta)

    def feedback_payload(self) -> dict:
        err_az = self.target_azimuth_deg - self.current_azimuth_deg
        err_el = self.target_elevation_deg - self.current_elevation_deg
        position_error = (err_az * err_az + err_el * err_el) ** 0.5
        return {
            "current_azimuth_deg": round(self.current_azimuth_deg, 3),
            "current_elevation_deg": round(self.current_elevation_deg, 3),
            "angular_speed": self.speed_limit_deg_s,
            "in_position": (
                self.online
                and self.fault_mode == "none"
                and position_error <= self.in_position_threshold_deg
            ),
            "position_error_deg": round(position_error, 3),
            "fault_mode": self.fault_mode,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gimbal simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9101)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = GimbalState()

    def on_message(message: dict, peer: Peer):
        payload = message.get("payload", {})
        slot_id = int(message.get("slot_id", 0))
        if message.get("control_id") == SIM_SET_GIMBAL:
            for key, value in payload.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            print(f"[gimbal] control update: {payload}")
            return None
        if message.get("control_id") == SIM_SET_FAULT:
            state.online = bool(payload.get("online", state.online))
            state.fault_mode = payload.get("fault_mode", state.fault_mode)
            state.drop_rate = float(payload.get("drop_rate", state.drop_rate))
            print(f"[gimbal] fault update: {payload}")
            return None
        if message.get("packet_id") == PKT_GIMBAL_CMD:
            state.apply_command(payload)
        state.step(slot_id)
        if random.random() < state.drop_rate:
            return None
        return [
            make_message(MODULE_GIMBAL, MODULE_DSP, PKT_SYS_HEALTH, {
                "online": state.online and state.fault_mode != "offline",
                "fault_code": state.fault_mode,
                "heartbeat_counter": slot_id,
            }, slot_id=slot_id),
            make_message(MODULE_GIMBAL, MODULE_DSP, PKT_GIMBAL_FB, state.feedback_payload(), slot_id=slot_id),
        ]

    server = JsonLineServer(args.host, args.port, on_message, "sim-gimbal")
    print(f"Gimbal simulator listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
