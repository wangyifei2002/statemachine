from __future__ import annotations

import unittest

from common.protocol import (
    MODULE_GIMBAL,
    MODULE_MMWAVE,
    MODULE_THZ,
    PKT_GIMBAL_FB,
    PKT_MMW_DETECT,
    PKT_MMW_LINK_STATUS,
    PKT_THZ_STATUS,
)
from common.state_machine import DspStateMachine, STATE_CODES, StateMachineConfig


def snapshot(*, healthy=True, target=False, aligned=False, locked=False,
             thz_quality=900, mmwave_quality=800, azimuth_mdeg=12000):
    health = {
        MODULE_MMWAVE: healthy,
        MODULE_GIMBAL: healthy,
        MODULE_THZ: healthy,
    }
    return {
        "health": health,
        PKT_MMW_DETECT: {
            "valid": True, "seq": 1, "age_slots": 0,
            "target_valid": target, "azimuth_mdeg": azimuth_mdeg,
            "elevation_mdeg": 2000,
        },
        PKT_MMW_LINK_STATUS: {
            "valid": True, "seq": 1, "age_slots": 0,
            "uplink_ready": True, "link_quality": mmwave_quality,
        },
        PKT_GIMBAL_FB: {
            "valid": True, "seq": 1, "age_slots": 0,
            "in_position": aligned, "position_error_mdeg": 100 if aligned else 5000,
        },
        PKT_THZ_STATUS: {
            "valid": True, "seq": 1, "age_slots": 0,
            "lock_flag": locked, "link_quality": thz_quality,
        },
    }


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = StateMachineConfig(
            self_check_stable_slots=1,
            self_check_timeout_slots=3,
            detect_stable_slots=1,
            coarse_stable_slots=1,
            coarse_timeout_slots=3,
            target_lost_tolerance_slots=1,
            capture_lock_stable_slots=1,
            capture_timeout_slots=3,
            tracking_loss_slots=2,
            fallback_restore_slots=2,
            fallback_timeout_slots=3,
            reacquire_lock_stable_slots=1,
            reacquire_timeout_slots=2,
            recovery_stable_slots=2,
            recovery_query_period_slots=10,
            recovery_timeout_slots=20,
            recovery_max_attempts=3,
        )
        self.fsm = DspStateMachine(self.cfg)
        self.slot = 0

    def step(self, data=None, **control):
        self.slot += 1
        payload = snapshot() if data is None else data
        payload.update(control)
        return self.fsm.step(self.slot, payload)

    def reach_tracking(self):
        self.assertEqual(self.step(start=True).state, "S0")
        self.assertEqual(self.step(snapshot(healthy=True)).state, "S1")
        self.assertEqual(self.step(snapshot(target=True)).state, "S2")
        self.assertEqual(self.step(snapshot(target=True, aligned=True)).state, "S3")
        result = self.step(snapshot(target=True, aligned=True, locked=True))
        self.assertEqual((result.state, result.reason), ("S4", "THZ_LOCKED"))

    def test_state_codes_are_frozen(self):
        self.assertEqual(STATE_CODES, {
            "IDLE": 0, "FAULT": 1, "S0": 2, "S1": 3, "S2": 4,
            "S3": 5, "S4": 6, "S5": 7, "S6": 8, "S7": 9,
        })

    def test_normal_path_and_fast_reacquire(self):
        self.reach_tracking()
        self.assertEqual(self.step(snapshot(target=True, locked=False)).state, "S4")
        lost = self.step(snapshot(target=True, locked=False))
        self.assertEqual((lost.state, lost.reason), ("S6", "TRACK_LOST"))
        recovered = self.step(snapshot(target=True, locked=True))
        self.assertEqual((recovered.state, recovered.reason), ("S4", "REACQUIRE_OK"))

    def test_reacquire_realign_and_timeout(self):
        self.reach_tracking()
        self.step(snapshot(target=True, locked=False))
        self.step(snapshot(target=True, locked=False))
        realign = self.step(snapshot(target=True, locked=False, azimuth_mdeg=16001))
        self.assertEqual((realign.state, realign.reason), ("S2", "REACQUIRE_REALIGN"))

        self.fsm.state = "S6"
        self.fsm.state_enter_slot = self.slot
        self.step(snapshot(target=False, locked=False))
        timeout = self.step(snapshot(target=False, locked=False))
        self.assertEqual((timeout.state, timeout.reason), ("S5", "REACQUIRE_TIMEOUT"))

    def test_fallback_restore_and_timeout(self):
        self.fsm.state = "S5"
        self.fsm.state_enter_slot = self.slot
        self.assertEqual(self.step(snapshot(target=True)).state, "S5")
        restored = self.step(snapshot(target=True))
        self.assertEqual((restored.state, restored.reason), ("S2", "MMWAVE_RECOVERED"))

        self.fsm.state = "S5"
        self.fsm.state_enter_slot = self.slot
        self.step(snapshot(target=False, mmwave_quality=0))
        self.step(snapshot(target=False, mmwave_quality=0))
        timed_out = self.step(snapshot(target=False, mmwave_quality=0))
        self.assertEqual((timed_out.state, timed_out.reason), ("S1", "FALLBACK_TIMEOUT"))

    def test_module_fault_recovery_and_fault_reset(self):
        self.reach_tracking()
        failed = snapshot(target=True, locked=True)
        failed["health"][MODULE_THZ] = False
        entered = self.step(failed)
        self.assertEqual((entered.state, entered.reason, entered.fault_mask), ("S7", "MODULE_FAULT", 2))
        self.assertEqual(self.step(snapshot(target=True)).state, "S7")
        recovered = self.step(snapshot(target=True))
        self.assertEqual((recovered.state, recovered.reason), ("S2", "RECOVERY_OK_TARGET"))

        self.fsm.state = "S7"
        self.fsm.state_enter_slot = self.slot
        self.cfg.recovery_query_period_slots = 1
        self.cfg.recovery_max_attempts = 1
        failed_again = snapshot(healthy=False)
        terminal = self.step(failed_again)
        self.assertEqual((terminal.state, terminal.reason), ("FAULT", "RECOVERY_TIMEOUT"))
        self.assertEqual(self.step(snapshot(), reset=True).state, "IDLE")

    def test_stale_input_does_not_trigger_transition(self):
        self.step(start=True)
        self.step(snapshot())
        stale = snapshot(target=True)
        stale[PKT_MMW_DETECT]["age_slots"] = self.cfg.input_max_age_slots + 1
        result = self.step(stale)
        self.assertEqual(result.state, "S1")


if __name__ == "__main__":
    unittest.main()
