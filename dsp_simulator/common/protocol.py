"""JSON Lines protocol helpers for simulator processes."""

from __future__ import annotations

import json
import time
from typing import Any

VERSION = 1

MODULE_DSP = "dsp"
MODULE_GIMBAL = "gimbal"
MODULE_MMWAVE = "mmwave"
MODULE_THZ = "thz"
MODULE_PC = "pc"

PKT_SYS_POLL = "PKT_SYS_POLL"
PKT_SYS_HEALTH = "PKT_SYS_HEALTH"
PKT_MMW_DETECT = "PKT_MMW_DETECT"
PKT_MMW_RF_CTRL = "PKT_MMW_RF_CTRL"
PKT_MMW_LINK_STATUS = "PKT_MMW_LINK_STATUS"
PKT_MMW_BITSTREAM = "PKT_MMW_BITSTREAM"
PKT_GIMBAL_CMD = "PKT_GIMBAL_CMD"
PKT_GIMBAL_FB = "PKT_GIMBAL_FB"
PKT_THZ_PARAM = "PKT_THZ_PARAM"
PKT_THZ_STATUS = "PKT_THZ_STATUS"
PKT_THZ_BITSTREAM = "PKT_THZ_BITSTREAM"
PKT_UPLINK_STATE = "PKT_UPLINK_STATE"

SIM_SET_TARGET = "SIM_SET_TARGET"
SIM_SET_GIMBAL = "SIM_SET_GIMBAL"
SIM_SET_THZ_LINK = "SIM_SET_THZ_LINK"
SIM_SET_FAULT = "SIM_SET_FAULT"
SIM_LOAD_SCENARIO = "SIM_LOAD_SCENARIO"

TRIGGER_PERIODIC = "periodic"
TRIGGER_EVENT = "event"


def now_ms() -> int:
    return int(time.time() * 1000)


def make_message(
    src: str,
    dst: str,
    packet_id: str,
    payload: dict[str, Any] | None = None,
    *,
    slot_id: int = 0,
    seq: int = 0,
    trigger_type: str = TRIGGER_PERIODIC,
    trigger_reason: str = "slot_clock",
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "slot_id": int(slot_id),
        "seq": int(seq),
        "timestamp_ms": now_ms(),
        "src": src,
        "dst": dst,
        "packet_id": packet_id,
        "trigger_type": normalize_trigger_type(trigger_type),
        "trigger_reason": trigger_reason,
        "payload": payload or {},
    }


def make_control(
    src: str,
    dst: str,
    control_id: str,
    payload: dict[str, Any] | None = None,
    *,
    slot_id: int = 0,
    seq: int = 0,
    trigger_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "slot_id": int(slot_id),
        "seq": int(seq),
        "timestamp_ms": now_ms(),
        "src": src,
        "dst": dst,
        "control_id": control_id,
        "trigger_type": TRIGGER_EVENT,
        "trigger_reason": trigger_reason or control_id,
        "payload": payload or {},
    }


def encode_message(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(data: bytes | str) -> dict[str, Any]:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data.strip())


def is_control(message: dict[str, Any]) -> bool:
    return "control_id" in message


def message_kind(message: dict[str, Any]) -> str:
    return message.get("packet_id") or message.get("control_id") or "UNKNOWN"


def normalize_trigger_type(trigger_type: str | None) -> str:
    return TRIGGER_EVENT if trigger_type == TRIGGER_EVENT else TRIGGER_PERIODIC


def message_trigger_type(message: dict[str, Any]) -> str:
    if "trigger_type" in message:
        return normalize_trigger_type(message.get("trigger_type"))
    return TRIGGER_EVENT if is_control(message) else TRIGGER_PERIODIC
