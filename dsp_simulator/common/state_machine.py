"""Pure, slot-driven DSP state machine shared by simulation and deployment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .definitions import UPLINK_MODE
from .protocol import (
    MODULE_DSP, MODULE_GIMBAL, MODULE_MMWAVE, MODULE_PC, MODULE_THZ,
    PKT_GIMBAL_CMD, PKT_GIMBAL_FB, PKT_MMW_DETECT, PKT_MMW_LINK_STATUS,
    PKT_MMW_RF_CTRL, PKT_THZ_PARAM, PKT_THZ_STATUS, PKT_UPLINK_STATE,
    TRIGGER_EVENT, TRIGGER_PERIODIC, make_message,
)


STATE_CODES = {
    "IDLE": 0, "FAULT": 1, "S0": 2, "S1": 3, "S2": 4,
    "S3": 5, "S4": 6, "S5": 7, "S6": 8, "S7": 9,
}

REASON_TEXT = {
    "NONE": "无状态变化", "START": "启动状态机", "RESET": "人工复位",
    "SELF_OK": "模块自检通过", "SELF_FAIL": "模块自检超时",
    "TARGET_STABLE": "毫米波目标稳定", "TARGET_LOST": "毫米波目标丢失",
    "GIMBAL_ALIGNED": "云台到位", "ALIGN_TIMEOUT": "云台对准超时",
    "THZ_LOCKED": "THz锁定成功", "CAPTURE_TIMEOUT": "THz捕获超时",
    "TRACK_LOST": "THz跟踪失锁", "REACQUIRE_OK": "THz快速重捕获成功",
    "REACQUIRE_TIMEOUT": "THz快速重捕获超时",
    "REACQUIRE_REALIGN": "目标移动，需要重新对准",
    "MMWAVE_RECOVERED": "毫米波链路恢复", "FALLBACK_TIMEOUT": "毫米波回退超时",
    "MODULE_FAULT": "关键模块故障", "RECOVERY_OK_TARGET": "模块恢复且目标有效",
    "RECOVERY_OK_SEARCH": "模块恢复并返回搜索", "RECOVERY_TIMEOUT": "模块恢复失败",
}

MODULE_BITS = {MODULE_MMWAVE: 1 << 0, MODULE_THZ: 1 << 1, MODULE_GIMBAL: 1 << 2}


@dataclass
class StateMachineConfig:
    slot_period_ms: int = 100
    input_max_age_slots: int = 3
    self_check_stable_slots: int = 2
    self_check_timeout_slots: int = 30
    detect_stable_slots: int = 3
    coarse_stable_slots: int = 2
    coarse_timeout_slots: int = 30
    target_lost_tolerance_slots: int = 2
    position_error_threshold_mdeg: int = 500
    capture_lock_stable_slots: int = 2
    capture_timeout_slots: int = 20
    thz_quality_threshold: int = 400
    tracking_loss_slots: int = 3
    fallback_restore_slots: int = 3
    fallback_timeout_slots: int = 30
    mmwave_quality_threshold: int = 300
    reacquire_lock_stable_slots: int = 2
    reacquire_timeout_slots: int = 20
    reacquire_target_delta_mdeg: int = 2000
    recovery_stable_slots: int = 3
    recovery_query_period_slots: int = 5
    recovery_timeout_slots: int = 100
    recovery_max_attempts: int = 3
    default_gimbal_speed_mdeg_s: int = 20000


@dataclass
class StepResult:
    state: str
    previous_state: str
    reason: str = "NONE"
    transition: str | None = None
    fault_mask: int = 0
    outputs: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class DspStateMachine:
    def __init__(self, config: StateMachineConfig | None = None):
        self.config = config or StateMachineConfig()
        self.state = "IDLE"
        self.previous_state = "IDLE"
        self.state_enter_slot = 0
        self.fault_mask = 0
        self.last_target = {"azimuth_mdeg": 0, "elevation_mdeg": 0}
        self.lock_target = dict(self.last_target)
        self.counters: dict[str, int] = {}
        self.recovery_attempts = 0
        self.last_recovery_action_slot = 0

    def step(self, slot_id: int, packets: dict[str, Any]) -> StepResult:
        previous = self.state
        reason = "NONE"
        alerts: list[str] = []

        if packets.get("reset"):
            self._reset(slot_id)
            reason = "RESET"
        elif self.state == "IDLE":
            if packets.get("start"):
                self._transition("S0", slot_id)
                reason = "START"
        elif self.state != "FAULT":
            snapshot = self._normalize_inputs(packets)
            self.fault_mask = snapshot["fault_mask"]
            if self.state in {"S1", "S2", "S3", "S4", "S5", "S6"} and self.fault_mask:
                self._transition("S7", slot_id)
                self.recovery_attempts = 0
                self.last_recovery_action_slot = slot_id
                reason = "MODULE_FAULT"
            else:
                reason = self._run_state(slot_id, snapshot)

        transition = REASON_TEXT[reason] if reason != "NONE" else None
        diagnostics = {
            "state_code": STATE_CODES[self.state],
            "state_age_slots": slot_id - self.state_enter_slot,
            "fault_mask": self.fault_mask,
            "counters": dict(self.counters),
            "last_target": dict(self.last_target),
            "reason": reason,
        }
        if self.state == "FAULT":
            alerts.append(REASON_TEXT.get(reason, "状态机进入安全故障态"))
        outputs = self._build_outputs(slot_id, previous, reason, transition, diagnostics)
        self.previous_state = previous
        return StepResult(
            state=self.state, previous_state=previous, reason=reason,
            transition=transition, fault_mask=self.fault_mask, outputs=outputs,
            alerts=alerts, diagnostics=diagnostics,
        )

    def _run_state(self, slot_id: int, data: dict[str, Any]) -> str:
        age = slot_id - self.state_enter_slot
        if data["target_fresh"]:
            self.last_target = {
                "azimuth_mdeg": data["azimuth_mdeg"],
                "elevation_mdeg": data["elevation_mdeg"],
            }

        if self.state == "S0":
            if data["all_healthy"]:
                if self._count("self_ok", True) >= self.config.self_check_stable_slots:
                    self._transition("S1", slot_id)
                    return "SELF_OK"
            else:
                self._count("self_ok", False)
            if age >= self.config.self_check_timeout_slots:
                self._transition("FAULT", slot_id)
                return "SELF_FAIL"

        elif self.state == "S1":
            if self._count("target", data["target_fresh"]) >= self.config.detect_stable_slots:
                self._transition("S2", slot_id)
                return "TARGET_STABLE"

        elif self.state == "S2":
            if self._count("target_lost", not data["target_fresh"]) >= self.config.target_lost_tolerance_slots:
                self._transition("S1", slot_id)
                return "TARGET_LOST"
            aligned = data["gimbal_fresh"] and data["gimbal_in_position"] and (
                data["position_error_mdeg"] <= self.config.position_error_threshold_mdeg
            )
            if self._count("aligned", aligned) >= self.config.coarse_stable_slots:
                self._transition("S3", slot_id)
                return "GIMBAL_ALIGNED"
            if age >= self.config.coarse_timeout_slots:
                self._transition("S1", slot_id)
                return "ALIGN_TIMEOUT"

        elif self.state == "S3":
            locked = data["thz_fresh"] and data["thz_locked"] and data["thz_quality"] >= self.config.thz_quality_threshold
            if self._count("capture_lock", locked) >= self.config.capture_lock_stable_slots:
                self.lock_target = dict(self.last_target)
                self._transition("S4", slot_id)
                return "THZ_LOCKED"
            if age >= self.config.capture_timeout_slots:
                self._transition("S5", slot_id)
                return "CAPTURE_TIMEOUT"

        elif self.state == "S4":
            tracking_ok = data["thz_fresh"] and data["thz_locked"] and data["thz_quality"] >= self.config.thz_quality_threshold
            if self._count("track_lost", not tracking_ok) >= self.config.tracking_loss_slots:
                self.lock_target = dict(self.last_target)
                self._transition("S6", slot_id)
                return "TRACK_LOST"

        elif self.state == "S5":
            recovered = data["target_fresh"] and data["mmwave_uplink_ready"] and data["mmwave_quality"] >= self.config.mmwave_quality_threshold
            if self._count("fallback_recover", recovered) >= self.config.fallback_restore_slots:
                self._transition("S2", slot_id)
                return "MMWAVE_RECOVERED"
            if age >= self.config.fallback_timeout_slots:
                self._transition("S1", slot_id)
                return "FALLBACK_TIMEOUT"

        elif self.state == "S6":
            if data["target_fresh"] and self._target_moved():
                self._transition("S2", slot_id)
                return "REACQUIRE_REALIGN"
            locked = data["thz_fresh"] and data["thz_locked"] and data["thz_quality"] >= self.config.thz_quality_threshold
            if self._count("reacquire_lock", locked) >= self.config.reacquire_lock_stable_slots:
                self._transition("S4", slot_id)
                return "REACQUIRE_OK"
            if age >= self.config.reacquire_timeout_slots:
                self._transition("S5", slot_id)
                return "REACQUIRE_TIMEOUT"

        elif self.state == "S7":
            if data["all_healthy"]:
                if self._count("recovery_ok", True) >= self.config.recovery_stable_slots:
                    self.fault_mask = 0
                    if data["target_fresh"]:
                        self._transition("S2", slot_id)
                        return "RECOVERY_OK_TARGET"
                    self._transition("S1", slot_id)
                    return "RECOVERY_OK_SEARCH"
            else:
                self._count("recovery_ok", False)
            if age and age % self.config.recovery_query_period_slots == 0:
                self.recovery_attempts += 1
                self.last_recovery_action_slot = slot_id
            if age >= self.config.recovery_timeout_slots or self.recovery_attempts >= self.config.recovery_max_attempts:
                self._transition("FAULT", slot_id)
                return "RECOVERY_TIMEOUT"

        return "NONE"

    def _normalize_inputs(self, packets: dict[str, Any]) -> dict[str, Any]:
        health = packets.get("health", {})
        explicit_mask = int(packets.get("fault_mask", 0) or 0)
        health_mask = 0
        for module, bit in MODULE_BITS.items():
            if not bool(health.get(module, False)):
                health_mask |= bit

        mmwave = packets.get(PKT_MMW_DETECT, {})
        mmwave_link = packets.get(PKT_MMW_LINK_STATUS, {})
        gimbal = packets.get(PKT_GIMBAL_FB, {})
        thz = packets.get(PKT_THZ_STATUS, {})
        target_fresh = self._fresh(mmwave) and bool(mmwave.get("target_valid", False))
        return {
            "fault_mask": explicit_mask | health_mask,
            "all_healthy": (explicit_mask | health_mask) == 0,
            "target_fresh": target_fresh,
            "azimuth_mdeg": int(mmwave.get("azimuth_mdeg", self.last_target["azimuth_mdeg"])),
            "elevation_mdeg": int(mmwave.get("elevation_mdeg", self.last_target["elevation_mdeg"])),
            "mmwave_uplink_ready": bool(mmwave_link.get("uplink_ready", False)) and self._fresh(mmwave_link),
            "mmwave_quality": int(mmwave_link.get("link_quality", 0) or 0),
            "gimbal_fresh": self._fresh(gimbal),
            "gimbal_in_position": bool(gimbal.get("in_position", False)),
            "position_error_mdeg": int(gimbal.get("position_error_mdeg", 2**31 - 1)),
            "thz_fresh": self._fresh(thz),
            "thz_locked": bool(thz.get("lock_flag", False)),
            "thz_quality": int(thz.get("link_quality", 0) or 0),
        }

    def _fresh(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("valid", True)) and int(payload.get("age_slots", 0) or 0) <= self.config.input_max_age_slots

    def _target_moved(self) -> bool:
        return (
            abs(self.last_target["azimuth_mdeg"] - self.lock_target["azimuth_mdeg"]) > self.config.reacquire_target_delta_mdeg
            or abs(self.last_target["elevation_mdeg"] - self.lock_target["elevation_mdeg"]) > self.config.reacquire_target_delta_mdeg
        )

    def _count(self, key: str, condition: bool) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1 if condition else 0
        return self.counters[key]

    def _transition(self, state: str, slot_id: int) -> None:
        self.state = state
        self.state_enter_slot = slot_id
        self.counters.clear()

    def _reset(self, slot_id: int) -> None:
        self.state = "IDLE"
        self.state_enter_slot = slot_id
        self.fault_mask = 0
        self.counters.clear()
        self.recovery_attempts = 0

    def _build_outputs(self, slot_id: int, previous_state: str, reason: str,
                       transition: str | None, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
        active = self.state in {"S1", "S2", "S3", "S4", "S5", "S6"}
        mmwave_comm = self.state in {"S1", "S2", "S5"}
        gimbal_enable = self.state in {"S2", "S4", "S6"}
        thz_enable = self.state in {"S3", "S4", "S6"}
        recovery_action = self.fault_mask if self.state == "S7" and self.last_recovery_action_slot == slot_id else 0
        outputs = [
            make_message(MODULE_DSP, MODULE_MMWAVE, PKT_MMW_RF_CTRL, {
                "rf_enable": active, "sense_enable": active, "comm_enable": mmwave_comm,
                "scan_mode": {"S1": "search", "S2": "coarse", "S3": "capture_assist",
                              "S4": "assist_tracking", "S5": "fallback", "S6": "reacquire_assist"}.get(self.state, "idle"),
                "beam_id": 0, "gain_index": 1,
                "comm_rate_level": 1 if mmwave_comm else 0,
                "comm_modulation_order": 2 if mmwave_comm else 0,
            }, slot_id=slot_id),
            make_message(MODULE_DSP, MODULE_GIMBAL, PKT_GIMBAL_CMD, {
                "cmd_seq": slot_id, "target_azimuth_mdeg": self.last_target["azimuth_mdeg"],
                "target_elevation_mdeg": self.last_target["elevation_mdeg"],
                "angular_speed_mdeg_s": self.config.default_gimbal_speed_mdeg_s,
                "fine_tune_enable": self.state == "S4", "enable": gimbal_enable,
            }, slot_id=slot_id),
            make_message(MODULE_DSP, MODULE_THZ, PKT_THZ_PARAM, {
                "thz_enable": thz_enable, "sense_enable": thz_enable,
                "comm_enable": self.state == "S4", "traffic_enable": self.state == "S4",
                "reacquire": self.state == "S6", "rate_level": 1 if thz_enable else 0,
                "modulation_order": 4 if thz_enable else 0,
                "capture_timeout_slots": self.config.capture_timeout_slots,
                "tracking_threshold": self.config.thz_quality_threshold,
            }, slot_id=slot_id),
        ]
        outputs.append(make_message(MODULE_DSP, MODULE_PC, PKT_UPLINK_STATE, {
            "state_id": self.state, "state_code": STATE_CODES[self.state],
            "previous_state": previous_state, "reason": reason, "transition": transition,
            "uplink_mode": UPLINK_MODE[self.state], "fault_mask": self.fault_mask,
            "recovery_action_mask": recovery_action,
            "fallback_reason": reason if self.state == "S5" else "",
            "restore_flag": reason in {"MMWAVE_RECOVERED", "RECOVERY_OK_TARGET", "RECOVERY_OK_SEARCH"},
            "diagnostics": diagnostics, "slot_id": slot_id,
        }, slot_id=slot_id, trigger_type=TRIGGER_EVENT if reason != "NONE" else TRIGGER_PERIODIC,
            trigger_reason=reason if reason != "NONE" else "slot_status"))
        return outputs
