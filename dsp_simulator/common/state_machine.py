"""Pure DSP state-machine logic used by simulation and future deployment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .definitions import UPLINK_MODE
from .protocol import (
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
    PKT_THZ_PARAM,
    PKT_THZ_STATUS,
    PKT_UPLINK_STATE,
    TRIGGER_EVENT,
    TRIGGER_PERIODIC,
    make_message,
)


@dataclass
class StateMachineConfig:
    detect_window_slots: int = 3
    capture_min_slots: int = 2
    capture_timeout_slots: int = 20
    capture_target_lost_tolerance_slots: int = 2
    capture_gimbal_error_tolerance_slots: int = 2
    thz_capture_bad_window_slots: int = 3
    thz_loss_window_slots: int = 3
    tracking_target_lost_tolerance_slots: int = 3
    tracking_gimbal_error_tolerance_slots: int = 3
    thz_quality_threshold: float = 0.4
    mmwave_snr_threshold: float = 10.0
    mmwave_link_quality_threshold: float = 0.3
    critical_offline_tolerance_slots: int = 3
    fallback_restore_slots: int = 3
    fallback_timeout_slots: int = 30
    coarse_min_slots: int = 2
    coarse_target_lost_tolerance_slots: int = 2
    position_error_threshold_deg: float = 0.5
    default_gimbal_speed: float = 20.0


@dataclass
class StepResult:
    state: str
    previous_state: str
    transition: str | None
    outputs: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class DspStateMachine:
    def __init__(self, config: StateMachineConfig | None = None):
        self.config = config or StateMachineConfig()
        self.state = "S0"
        self.mmwave_valid_count = 0
        self.coarse_slots = 0
        self.coarse_target_lost_count = 0
        self.capture_slots = 0
        self.capture_target_lost_count = 0
        self.capture_gimbal_error_count = 0
        self.capture_thz_quality_bad_count = 0
        self.tracking_thz_unlock_count = 0
        self.tracking_thz_quality_bad_count = 0
        self.tracking_target_lost_count = 0
        self.tracking_gimbal_error_count = 0
        self.critical_offline_count = 0
        self.fallback_restore_count = 0
        self.fallback_slots = 0
        self.last_target = {"azimuth_deg": 0.0, "elevation_deg": 0.0}
        self.last_diagnostics: dict[str, Any] = {}

    def step(self, slot_id: int, packets: dict[str, dict[str, Any]]) -> StepResult:
        previous = self.state
        transition = None
        alerts: list[str] = []
        diagnostics: dict[str, Any] = {}

        health = packets.get("health", {})
        health_detail = packets.get("health_detail", {})
        mmwave_online = health.get(MODULE_MMWAVE, False)
        gimbal_online = health.get(MODULE_GIMBAL, False)
        thz_online = health.get(MODULE_THZ, False)
        offline_modules = self._offline_modules(health)
        if offline_modules:
            self.critical_offline_count += 1
        else:
            self.critical_offline_count = 0
        diagnostics["health"] = {
            "offline_modules": offline_modules,
            "critical_offline_count": self.critical_offline_count,
            "module_detail": health_detail,
        }
        mmwave = packets.get(PKT_MMW_DETECT, {}) if mmwave_online else {}
        mmwave_link = packets.get(PKT_MMW_LINK_STATUS, {}) if mmwave_online else {}
        gimbal = packets.get(PKT_GIMBAL_FB, {}) if gimbal_online else {}
        thz = packets.get(PKT_THZ_STATUS, {}) if thz_online else {}

        if mmwave.get("target_valid"):
            self.last_target = {
                "azimuth_deg": float(mmwave.get("azimuth_deg", self.last_target["azimuth_deg"])),
                "elevation_deg": float(mmwave.get("elevation_deg", self.last_target["elevation_deg"])),
            }

        if (
            self.state != "S0"
            and offline_modules
            and self.critical_offline_count >= self.config.critical_offline_tolerance_slots
        ):
            self._set_state("S0")
            transition = "关键模块离线: " + ", ".join(offline_modules)
            alerts.append(self._format_health_alert(diagnostics["health"]))

        elif self.state == "S0":
            if self._all_modules_online(health):
                self._set_state("S1")
                transition = "自检通过"
            else:
                alerts.append("模块离线/未知: " + ", ".join(offline_modules))

        elif self.state == "S1":
            if mmwave_online and self._mmwave_target_quality_ok(mmwave):
                self.mmwave_valid_count += 1
            else:
                self.mmwave_valid_count = 0
            if self.mmwave_valid_count >= self.config.detect_window_slots:
                self._set_state("S2")
                transition = "检测到稳定目标"

        elif self.state == "S2":
            self.coarse_slots += 1
            if mmwave.get("target_valid"):
                self.coarse_target_lost_count = 0
            else:
                self.coarse_target_lost_count += 1

            position_error = float(gimbal.get("position_error_deg", float("inf")))
            if self.coarse_target_lost_count > self.config.coarse_target_lost_tolerance_slots:
                self._set_state("S1")
                transition = "粗对准目标丢失"
            elif (
                self.coarse_slots >= self.config.coarse_min_slots
                and mmwave.get("target_valid")
                and self._gimbal_feedback_ok(gimbal)
                and position_error <= self.config.position_error_threshold_deg
            ):
                self._set_state("S3")
                transition = "云台到位"

        elif self.state == "S3":
            self.capture_slots += 1

            mmwave_target_ok = bool(mmwave.get("target_valid"))
            gimbal_position_error = float(gimbal.get("position_error_deg", float("inf")))
            gimbal_position_ok = (
                self._gimbal_feedback_ok(gimbal)
                and gimbal_position_error <= self.config.position_error_threshold_deg
            )
            thz_lock_ok = bool(thz.get("lock_flag"))
            thz_link_quality = float(thz.get("link_quality", 0.0 if not thz_online else 1.0))
            thz_quality_ok = thz_online and thz_link_quality >= self.config.thz_quality_threshold

            if mmwave_online and mmwave_target_ok:
                self.capture_target_lost_count = 0
            else:
                self.capture_target_lost_count += 1

            if gimbal_online and gimbal_position_ok:
                self.capture_gimbal_error_count = 0
            else:
                self.capture_gimbal_error_count += 1

            if thz_quality_ok:
                self.capture_thz_quality_bad_count = 0
            else:
                self.capture_thz_quality_bad_count += 1

            diagnostics["capture"] = {
                "capture_slots": self.capture_slots,
                "mmwave_online": mmwave_online,
                "mmwave_target_valid": mmwave_target_ok,
                "target_lost_count": self.capture_target_lost_count,
                "gimbal_online": gimbal_online,
                "gimbal_fault_mode": gimbal.get("fault_mode", "unknown"),
                "gimbal_in_position": bool(gimbal.get("in_position")),
                "gimbal_position_error_deg": None if gimbal_position_error == float("inf") else gimbal_position_error,
                "gimbal_error_count": self.capture_gimbal_error_count,
                "thz_online": thz_online,
                "thz_lock_flag": thz_lock_ok,
                "thz_link_quality": thz_link_quality,
                "thz_quality_bad_count": self.capture_thz_quality_bad_count,
            }

            if not thz_online:
                self._set_state("S5")
                transition = "捕获失败: THz模块离线"
            elif self.capture_target_lost_count > self.config.capture_target_lost_tolerance_slots:
                self._set_state("S5")
                transition = "捕获失败: 毫米波目标丢失"
            elif self.capture_gimbal_error_count > self.config.capture_gimbal_error_tolerance_slots:
                self._set_state("S5")
                transition = "捕获失败: 云台偏离"
            elif self.capture_thz_quality_bad_count >= self.config.thz_capture_bad_window_slots:
                self._set_state("S5")
                transition = "捕获失败: THz链路质量低"
            elif (
                self.capture_slots >= self.config.capture_min_slots
                and mmwave_target_ok
                and gimbal_position_ok
                and thz_lock_ok
                and thz_quality_ok
            ):
                self._set_state("S4")
                transition = "太赫兹锁定成功"
            elif self.capture_slots > self.config.capture_timeout_slots:
                self._set_state("S5")
                transition = "捕获超时: THz未锁定"

            if transition and self.state == "S5":
                alerts.append(self._format_capture_alert(diagnostics["capture"]))

        elif self.state == "S4":
            mmwave_target_ok = bool(mmwave.get("target_valid"))
            gimbal_position_error = float(gimbal.get("position_error_deg", float("inf")))
            gimbal_position_ok = (
                self._gimbal_feedback_ok(gimbal)
                and gimbal_position_error <= self.config.position_error_threshold_deg
            )
            thz_lock_ok = bool(thz.get("lock_flag"))
            thz_link_quality = float(thz.get("link_quality", 0.0 if not thz_online else 1.0))
            thz_quality_ok = thz_online and thz_link_quality >= self.config.thz_quality_threshold

            if thz_online and thz_lock_ok:
                self.tracking_thz_unlock_count = 0
            else:
                self.tracking_thz_unlock_count += 1

            if thz_quality_ok:
                self.tracking_thz_quality_bad_count = 0
            else:
                self.tracking_thz_quality_bad_count += 1

            if mmwave_online and mmwave_target_ok:
                self.tracking_target_lost_count = 0
            else:
                self.tracking_target_lost_count += 1

            if gimbal_online and gimbal_position_ok:
                self.tracking_gimbal_error_count = 0
            else:
                self.tracking_gimbal_error_count += 1

            diagnostics["tracking"] = {
                "mmwave_online": mmwave_online,
                "mmwave_target_valid": mmwave_target_ok,
                "target_lost_count": self.tracking_target_lost_count,
                "gimbal_online": gimbal_online,
                "gimbal_fault_mode": gimbal.get("fault_mode", "unknown"),
                "gimbal_in_position": bool(gimbal.get("in_position")),
                "gimbal_position_error_deg": None if gimbal_position_error == float("inf") else gimbal_position_error,
                "gimbal_error_count": self.tracking_gimbal_error_count,
                "thz_online": thz_online,
                "thz_lock_flag": thz_lock_ok,
                "thz_unlock_count": self.tracking_thz_unlock_count,
                "thz_link_quality": thz_link_quality,
                "thz_quality_bad_count": self.tracking_thz_quality_bad_count,
            }

            if not thz_online:
                self._set_state("S5")
                transition = "跟踪失败: THz模块离线"
            elif self.tracking_thz_unlock_count >= self.config.thz_loss_window_slots:
                self._set_state("S5")
                transition = "跟踪失败: THz失锁"
            elif self.tracking_thz_quality_bad_count >= self.config.thz_loss_window_slots:
                self._set_state("S5")
                transition = "跟踪失败: THz链路质量低"
            elif self.tracking_gimbal_error_count > self.config.tracking_gimbal_error_tolerance_slots:
                self._set_state("S5")
                transition = "跟踪失败: 云台跟踪偏离"
            elif self.tracking_target_lost_count > self.config.tracking_target_lost_tolerance_slots:
                self._set_state("S5")
                transition = "跟踪失败: 毫米波辅助目标丢失"

            if transition and self.state == "S5":
                alerts.append(self._format_tracking_alert(diagnostics["tracking"]))

        elif self.state == "S5":
            self.fallback_slots += 1

            target_quality_ok = mmwave_online and self._mmwave_target_quality_ok(mmwave)
            mmwave_link_quality = float(mmwave_link.get("link_quality", 0.0))
            mmwave_link_ok = (
                mmwave_online
                and bool(mmwave_link.get("uplink_ready"))
                and mmwave_link_quality >= self.config.mmwave_link_quality_threshold
            )
            gimbal_fault_mode = gimbal.get(
                "fault_mode",
                health_detail.get(MODULE_GIMBAL, {}).get("fault_code", "unknown"),
            )
            gimbal_controllable = gimbal_online and gimbal_fault_mode == "none"
            restore_ready = target_quality_ok and gimbal_controllable and thz_online

            if restore_ready:
                self.fallback_restore_count += 1
            else:
                self.fallback_restore_count = 0

            diagnostics["fallback"] = {
                "fallback_slots": self.fallback_slots,
                "mmwave_online": mmwave_online,
                "mmwave_target_valid": bool(mmwave.get("target_valid")),
                "mmwave_snr_db": float(mmwave.get("snr_db", 0.0)),
                "mmwave_target_quality_ok": target_quality_ok,
                "restore_count": self.fallback_restore_count,
                "mmwave_comm_enable": bool(mmwave_link.get("comm_enable")),
                "mmwave_uplink_ready": bool(mmwave_link.get("uplink_ready")),
                "mmwave_link_quality": mmwave_link_quality,
                "mmwave_link_ok": mmwave_link_ok,
                "gimbal_online": gimbal_online,
                "gimbal_fault_mode": gimbal_fault_mode,
                "gimbal_controllable": gimbal_controllable,
                "thz_online": thz_online,
                "restore_ready": restore_ready,
            }

            if self.fallback_restore_count >= self.config.fallback_restore_slots:
                self._set_state("S2")
                transition = "毫米波稳定恢复"
            elif self.fallback_slots > self.config.fallback_timeout_slots:
                self._set_state("S1")
                transition = "长时间无恢复"
                alerts.append(self._format_fallback_alert(diagnostics["fallback"]))

        self.last_diagnostics = diagnostics
        outputs = self._build_outputs(slot_id, previous, transition, alerts, diagnostics)
        return StepResult(
            state=self.state,
            previous_state=previous,
            transition=transition,
            outputs=outputs,
            alerts=alerts,
            diagnostics=diagnostics,
        )

    def _set_state(self, new_state: str) -> None:
        old = self.state
        self.state = new_state
        if old != new_state:
            if new_state == "S1":
                self.mmwave_valid_count = 0
            if new_state == "S0":
                self.mmwave_valid_count = 0
                self.coarse_slots = 0
                self.coarse_target_lost_count = 0
                self.capture_slots = 0
                self.capture_target_lost_count = 0
                self.capture_gimbal_error_count = 0
                self.capture_thz_quality_bad_count = 0
                self.tracking_thz_unlock_count = 0
                self.tracking_thz_quality_bad_count = 0
                self.tracking_target_lost_count = 0
                self.tracking_gimbal_error_count = 0
                self.fallback_slots = 0
                self.fallback_restore_count = 0
            if new_state == "S2":
                self.coarse_slots = 0
                self.coarse_target_lost_count = 0
            if new_state == "S3":
                self.capture_slots = 0
                self.capture_target_lost_count = 0
                self.capture_gimbal_error_count = 0
                self.capture_thz_quality_bad_count = 0
            if new_state == "S4":
                self.tracking_thz_unlock_count = 0
                self.tracking_thz_quality_bad_count = 0
                self.tracking_target_lost_count = 0
                self.tracking_gimbal_error_count = 0
            if new_state == "S5":
                self.fallback_slots = 0
                self.fallback_restore_count = 0

    def _all_modules_online(self, health: dict[str, bool]) -> bool:
        return not self._offline_modules(health)

    def _offline_modules(self, health: dict[str, bool]) -> list[str]:
        return [module for module in (MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ) if not health.get(module, False)]

    def _mmwave_target_quality_ok(self, mmwave: dict[str, Any]) -> bool:
        snr_db = float(mmwave.get("snr_db", self.config.mmwave_snr_threshold))
        return bool(mmwave.get("target_valid")) and snr_db >= self.config.mmwave_snr_threshold

    def _gimbal_feedback_ok(self, gimbal: dict[str, Any]) -> bool:
        return bool(gimbal.get("in_position")) and gimbal.get("fault_mode", "none") == "none"

    def _format_capture_alert(self, capture: dict[str, Any]) -> str:
        return (
            "S3诊断: "
            f"mmwave_online={capture['mmwave_online']}, "
            f"target_valid={capture['mmwave_target_valid']}, "
            f"target_lost_count={capture['target_lost_count']}, "
            f"gimbal_online={capture['gimbal_online']}, "
            f"gimbal_fault_mode={capture['gimbal_fault_mode']}, "
            f"in_position={capture['gimbal_in_position']}, "
            f"position_error_deg={capture['gimbal_position_error_deg']}, "
            f"gimbal_error_count={capture['gimbal_error_count']}, "
            f"thz_online={capture['thz_online']}, "
            f"lock_flag={capture['thz_lock_flag']}, "
            f"link_quality={capture['thz_link_quality']}, "
            f"quality_bad_count={capture['thz_quality_bad_count']}"
        )

    def _format_tracking_alert(self, tracking: dict[str, Any]) -> str:
        return (
            "S4诊断: "
            f"mmwave_online={tracking['mmwave_online']}, "
            f"target_valid={tracking['mmwave_target_valid']}, "
            f"target_lost_count={tracking['target_lost_count']}, "
            f"gimbal_online={tracking['gimbal_online']}, "
            f"gimbal_fault_mode={tracking['gimbal_fault_mode']}, "
            f"in_position={tracking['gimbal_in_position']}, "
            f"position_error_deg={tracking['gimbal_position_error_deg']}, "
            f"gimbal_error_count={tracking['gimbal_error_count']}, "
            f"thz_online={tracking['thz_online']}, "
            f"lock_flag={tracking['thz_lock_flag']}, "
            f"unlock_count={tracking['thz_unlock_count']}, "
            f"link_quality={tracking['thz_link_quality']}, "
            f"quality_bad_count={tracking['thz_quality_bad_count']}"
        )

    def _format_fallback_alert(self, fallback: dict[str, Any]) -> str:
        return (
            "S5诊断: "
            f"mmwave_online={fallback['mmwave_online']}, "
            f"target_valid={fallback['mmwave_target_valid']}, "
            f"snr_db={fallback['mmwave_snr_db']}, "
            f"target_quality_ok={fallback['mmwave_target_quality_ok']}, "
            f"restore_count={fallback['restore_count']}, "
            f"mmwave_uplink_ready={fallback['mmwave_uplink_ready']}, "
            f"mmwave_link_quality={fallback['mmwave_link_quality']}, "
            f"mmwave_link_ok={fallback['mmwave_link_ok']}, "
            f"gimbal_online={fallback['gimbal_online']}, "
            f"gimbal_fault_mode={fallback['gimbal_fault_mode']}, "
            f"gimbal_controllable={fallback['gimbal_controllable']}, "
            f"thz_online={fallback['thz_online']}, "
            f"restore_ready={fallback['restore_ready']}"
        )

    def _format_health_alert(self, health: dict[str, Any]) -> str:
        return (
            "健康状态诊断: "
            f"offline_modules={health['offline_modules']}, "
            f"critical_offline_count={health['critical_offline_count']}"
        )

    def _build_outputs(
        self,
        slot_id: int,
        previous_state: str,
        transition: str | None,
        alerts: list[str],
        diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []

        scan_mode = {
            "S0": "idle",
            "S1": "search",
            "S2": "coarse",
            "S3": "capture_assist",
            "S4": "assist_tracking",
            "S5": "fallback",
        }.get(self.state, "idle")
        outputs.append(make_message(
            MODULE_DSP,
            MODULE_MMWAVE,
            PKT_MMW_RF_CTRL,
            {
                "rf_enable": self.state in {"S1", "S2", "S3", "S4", "S5"},
                "sense_enable": self.state in {"S1", "S2", "S3", "S4", "S5"},
                "comm_enable": self.state in {"S1", "S2", "S5"},
                "scan_mode": scan_mode,
                "beam_id": 0,
                "gain_index": 1,
                "comm_rate_level": 1 if self.state in {"S1", "S2", "S5"} else 0,
                "comm_modulation_order": 2 if self.state in {"S1", "S2", "S5"} else 0,
            },
            slot_id=slot_id,
        ))

        outputs.append(make_message(
            MODULE_DSP,
            MODULE_GIMBAL,
            PKT_GIMBAL_CMD,
            {
                "cmd_seq": slot_id,
                "target_azimuth_deg": self.last_target["azimuth_deg"],
                "target_elevation_deg": self.last_target["elevation_deg"],
                "angular_speed": self.config.default_gimbal_speed,
                "fine_tune_enable": self.state == "S4",
                "enable": self.state in {"S2", "S4"},
            },
            slot_id=slot_id,
        ))

        outputs.append(make_message(
            MODULE_DSP,
            MODULE_THZ,
            PKT_THZ_PARAM,
            {
                "thz_enable": self.state in {"S3", "S4"},
                "sense_enable": self.state in {"S3", "S4"},
                "comm_enable": self.state == "S4",
                "traffic_enable": self.state == "S4",
                "rate_level": 1 if self.state in {"S3", "S4"} else 0,
                "modulation_order": 4 if self.state in {"S3", "S4"} else 0,
                "capture_timeout_slot": self.config.capture_timeout_slots,
                "tracking_threshold": self.config.thz_quality_threshold,
            },
            slot_id=slot_id,
        ))

        state_trigger_type = TRIGGER_EVENT if transition or alerts else TRIGGER_PERIODIC
        state_trigger_reason = transition or "; ".join(alerts) or "slot_status"
        outputs.append(make_message(
            MODULE_DSP,
            MODULE_PC,
            PKT_UPLINK_STATE,
            {
                "state_id": self.state,
                "previous_state": previous_state,
                "uplink_mode": UPLINK_MODE[self.state],
                "transition": transition,
                "fallback_reason": transition if self.state == "S5" else "",
                "restore_flag": transition == "毫米波稳定恢复",
                "alerts": alerts,
                "diagnostics": diagnostics,
                "slot_id": slot_id,
            },
            slot_id=slot_id,
            trigger_type=state_trigger_type,
            trigger_reason=state_trigger_reason,
        ))
        return outputs
