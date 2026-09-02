"""Millimeter-wave baseband hardware simulator."""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass

from common.protocol import (
    MODULE_DSP,
    MODULE_MMWAVE,
    MODULE_PC,
    PKT_MMW_BITSTREAM,
    PKT_MMW_DETECT,
    PKT_MMW_LINK_STATUS,
    PKT_MMW_RF_CTRL,
    PKT_SYS_HEALTH,
    SIM_SET_FAULT,
    SIM_SET_TARGET,
    make_message,
)
from common.transport import JsonLineClient, JsonLineServer, Peer


@dataclass
class MmwaveState:
    online: bool = True
    rf_enable: bool = False
    sense_enable: bool = False
    comm_enable: bool = False
    scan_mode: str = "idle"
    target_valid: bool = False
    azimuth_mdeg: int = 12000
    elevation_mdeg: int = 2000
    range_m: float = 120.0
    radial_speed_mps: float = 0.0
    snr_db: float = 18.0
    noise_level_mdeg: int = 0
    comm_link_quality: int = 750
    comm_rate_level: int = 1
    comm_modulation_order: int = 2
    frame_seq: int = 0
    sample_seq: int = 0
    drop_rate: float = 0.0
    fault_mode: str = "none"

    def apply_rf_ctrl(self, payload: dict) -> None:
        self.rf_enable = bool(payload.get("rf_enable", self.rf_enable))
        self.sense_enable = bool(payload.get("sense_enable", self.sense_enable))
        self.comm_enable = bool(payload.get("comm_enable", self.comm_enable))
        self.scan_mode = payload.get("scan_mode", self.scan_mode)
        self.comm_rate_level = int(payload.get("comm_rate_level", self.comm_rate_level))
        self.comm_modulation_order = int(payload.get("comm_modulation_order", self.comm_modulation_order))

    def detect_payload(self) -> dict:
        self.sample_seq += 1
        active = self.sense_active()
        valid = bool(active and self.target_valid)
        noise = self.noise_level_mdeg
        return {
            "valid": active,
            "seq": self.sample_seq,
            "age_slots": 0,
            "target_valid": valid,
            "azimuth_mdeg": int(round(self.azimuth_mdeg + random.uniform(-noise, noise))),
            "elevation_mdeg": int(round(self.elevation_mdeg + random.uniform(-noise, noise))),
            "range_m": round(self.range_m, 3),
            "radial_speed_mps": round(self.radial_speed_mps, 3),
            "snr_db": round(self.snr_db, 3),
            "scan_mode": self.scan_mode,
            "sense_enable": self.sense_enable,
        }

    def sense_active(self) -> bool:
        return self.online and self.rf_enable and self.sense_enable and self.fault_mode != "offline"

    def comm_active(self) -> bool:
        return self.online and self.comm_enable and self.fault_mode != "offline"

    def link_status_payload(self) -> dict:
        return {
            "valid": self.online,
            "seq": self.sample_seq,
            "age_slots": 0,
            "comm_enable": self.comm_enable,
            "link_quality": self.comm_link_quality if self.comm_active() else 0,
            "rate_level": self.comm_rate_level if self.comm_active() else 0,
            "modulation_order": self.comm_modulation_order if self.comm_active() else 0,
            "uplink_ready": self.comm_active() and self.comm_link_quality >= 300,
        }

    def bitstream_payload(self) -> dict:
        self.frame_seq += 1
        return {
            "payload_bits": 1024,
            "frame_seq": self.frame_seq,
            "crc": "ok" if self.comm_link_quality >= 300 else "weak",
            "rate_level": self.comm_rate_level,
            "modulation_order": self.comm_modulation_order,
            "link_quality": self.comm_link_quality,
            "uplink_mode": "mmwave",
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Millimeter-wave simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9102)
    parser.add_argument("--pc-host", default="127.0.0.1")
    parser.add_argument("--pc-port", type=int, default=9104)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = MmwaveState()
    pc_client = JsonLineClient(args.pc_host, args.pc_port, "mmwave-pc")

    def on_message(message: dict, peer: Peer):
        payload = message.get("payload", {})
        slot_id = int(message.get("slot_id", 0))
        control_id = message.get("control_id")
        if control_id == SIM_SET_TARGET:
            for key, value in payload.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            print(f"[mmwave] target update: {payload}")
            return None
        if control_id == SIM_SET_FAULT:
            state.online = bool(payload.get("online", state.online))
            state.fault_mode = payload.get("fault_mode", state.fault_mode)
            state.drop_rate = float(payload.get("drop_rate", state.drop_rate))
            print(f"[mmwave] fault update: {payload}")
            return None
        if message.get("packet_id") == PKT_MMW_RF_CTRL:
            state.apply_rf_ctrl(payload)
        if state.comm_active():
            pc_client.send(make_message(MODULE_MMWAVE, MODULE_PC, PKT_MMW_BITSTREAM, state.bitstream_payload(), slot_id=slot_id))
        if random.random() < state.drop_rate:
            return None
        return [
            make_message(MODULE_MMWAVE, MODULE_DSP, PKT_SYS_HEALTH, {
                "online": state.online and state.fault_mode != "offline",
                "fault_code": state.fault_mode,
                "heartbeat_counter": slot_id,
            }, slot_id=slot_id),
            make_message(MODULE_MMWAVE, MODULE_DSP, PKT_MMW_DETECT, state.detect_payload(), slot_id=slot_id),
            make_message(MODULE_MMWAVE, MODULE_DSP, PKT_MMW_LINK_STATUS, state.link_status_payload(), slot_id=slot_id),
        ]

    server = JsonLineServer(args.host, args.port, on_message, "sim-mmwave")
    print(f"Millimeter-wave simulator listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
