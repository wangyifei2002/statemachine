"""THz baseband hardware simulator."""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass

from common.protocol import (
    MODULE_DSP,
    MODULE_PC,
    MODULE_THZ,
    PKT_SYS_HEALTH,
    PKT_THZ_BITSTREAM,
    PKT_THZ_PARAM,
    PKT_THZ_STATUS,
    SIM_SET_FAULT,
    SIM_SET_THZ_LINK,
    make_message,
)
from common.transport import JsonLineClient, JsonLineServer, Peer


@dataclass
class ThzState:
    online: bool = True
    thz_enable: bool = False
    sense_enable: bool = False
    comm_enable: bool = False
    traffic_enable: bool = False
    lock_flag: bool = False
    force_lock: bool = False
    auto_lock: bool = True
    link_quality: float = 0.95
    sense_quality: float = 0.9
    velocity_mps: float = 0.0
    position_m: float = 0.0
    angle_deg: float = 0.0
    sense_noise: float = 0.0
    capture_delay_slots: int = 5
    enabled_slots: int = 0
    force_timeout: bool = False
    loss_count: int = 0
    frame_seq: int = 0
    drop_rate: float = 0.0
    fault_mode: str = "none"
    rate_level: int = 0
    modulation_order: int = 0

    def apply_param(self, payload: dict) -> None:
        enabled = bool(payload.get("thz_enable", self.thz_enable))
        if enabled and not self.thz_enable:
            self.enabled_slots = 0
            self.lock_flag = self.lock_flag if self.force_lock else False
        if not enabled:
            self.enabled_slots = 0
            self.lock_flag = False
        self.thz_enable = enabled
        self.sense_enable = bool(payload.get("sense_enable", self.sense_enable))
        self.comm_enable = bool(payload.get("comm_enable", self.comm_enable))
        self.traffic_enable = bool(payload.get("traffic_enable", self.comm_enable))
        self.rate_level = int(payload.get("rate_level", self.rate_level))
        self.modulation_order = int(payload.get("modulation_order", self.modulation_order))

    def step(self) -> None:
        if not self.online or self.fault_mode == "offline":
            self.lock_flag = False
            return
        if not self.thz_enable or not self.sense_enable:
            self.lock_flag = False
            return
        self.enabled_slots += 1
        if self.force_timeout:
            self.lock_flag = False
            return
        if self.force_lock:
            self.lock_flag = True
        elif self.auto_lock and self.enabled_slots >= self.capture_delay_slots:
            self.lock_flag = True
        if not self.lock_flag:
            self.loss_count += 1
        else:
            self.loss_count = 0

    def status_payload(self) -> dict:
        sense_active = self.online and self.thz_enable and self.sense_enable and self.fault_mode != "offline"
        noise = self.sense_noise if sense_active else 0.0
        return {
            "lock_flag": bool(self.lock_flag),
            "force_lock": self.force_lock,
            "auto_lock": self.auto_lock,
            "sense_enable": self.sense_enable,
            "comm_enable": self.comm_enable,
            "link_quality": round(float(self.link_quality), 3),
            "sense_quality": round(float(self.sense_quality if sense_active else 0.0), 3),
            "velocity": round(self.velocity_mps + random.uniform(-noise, noise), 3),
            "position": round(self.position_m + random.uniform(-noise, noise), 3),
            "angle": round(self.angle_deg + random.uniform(-noise, noise), 3),
            "loss_count": self.loss_count,
            "rate_level": self.rate_level,
            "modulation_order": self.modulation_order,
            "fault_mode": self.fault_mode,
        }

    def bitstream_payload(self) -> dict:
        self.frame_seq += 1
        return {
            "payload_bits": 4096,
            "frame_seq": self.frame_seq,
            "crc": "ok",
            "rate_level": self.rate_level,
            "modulation_order": self.modulation_order,
            "link_quality": round(float(self.link_quality), 3),
            "uplink_mode": "thz",
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="THz simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9103)
    parser.add_argument("--pc-host", default="127.0.0.1")
    parser.add_argument("--pc-port", type=int, default=9104)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = ThzState()
    pc_client = JsonLineClient(args.pc_host, args.pc_port, "thz-pc")

    def on_message(message: dict, peer: Peer):
        payload = message.get("payload", {})
        slot_id = int(message.get("slot_id", 0))
        control_id = message.get("control_id")
        if control_id == SIM_SET_THZ_LINK:
            for key, value in payload.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            print(f"[thz] link update: {payload}")
            return None
        if control_id == SIM_SET_FAULT:
            state.online = bool(payload.get("online", state.online))
            state.fault_mode = payload.get("fault_mode", state.fault_mode)
            state.drop_rate = float(payload.get("drop_rate", state.drop_rate))
            print(f"[thz] fault update: {payload}")
            return None
        if message.get("packet_id") == PKT_THZ_PARAM:
            state.apply_param(payload)
        state.step()
        if state.lock_flag and state.comm_enable and state.traffic_enable:
            pc_client.send(make_message(MODULE_THZ, MODULE_PC, PKT_THZ_BITSTREAM, state.bitstream_payload(), slot_id=slot_id))
        if random.random() < state.drop_rate:
            return None
        return [
            make_message(MODULE_THZ, MODULE_DSP, PKT_SYS_HEALTH, {
                "online": state.online and state.fault_mode != "offline",
                "fault_code": state.fault_mode,
                "heartbeat_counter": slot_id,
            }, slot_id=slot_id),
            make_message(MODULE_THZ, MODULE_DSP, PKT_THZ_STATUS, state.status_payload(), slot_id=slot_id),
        ]

    server = JsonLineServer(args.host, args.port, on_message, "sim-thz")
    print(f"THz simulator listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
