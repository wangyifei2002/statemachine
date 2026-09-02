#!/usr/bin/env python3
"""Run a headless five-process normal-path and recovery smoke test."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIMULATOR = ROOT / "dsp_simulator"
sys.path.insert(0, str(SIMULATOR))

from common.protocol import (  # noqa: E402
    MODULE_GIMBAL,
    MODULE_MMWAVE,
    MODULE_PC,
    MODULE_THZ,
    SIM_SET_FAULT,
    SIM_SET_GIMBAL,
    SIM_SET_TARGET,
    SIM_SET_THZ_LINK,
    make_control,
)
from common.transport import send_message_once  # noqa: E402
from pc_app import PcHub  # noqa: E402


HOST = "127.0.0.1"
PORTS = {
    MODULE_GIMBAL: 19101,
    MODULE_MMWAVE: 19102,
    MODULE_THZ: 19103,
    MODULE_PC: 19104,
}


def wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"port {port} did not become ready")


def send_control(module: str, control_id: str, payload: dict) -> None:
    message = make_control(MODULE_PC, module, control_id, payload)
    if not send_message_once(HOST, PORTS[module], message):
        raise RuntimeError(f"failed to send {control_id} to {module}")


def wait_for_state(hub: PcHub, state: str, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = hub.snapshot()
        latest = snapshot["latest_state"]
        if latest.get("state_id") == state:
            return latest
        time.sleep(0.05)
    latest = hub.snapshot()["latest_state"]
    raise RuntimeError(f"state {state} not reached; latest={latest}")


def start_process(script: str, *args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(SIMULATOR / script), *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> int:
    processes: list[subprocess.Popen[str]] = []
    hub: PcHub | None = None
    try:
        hub = PcHub(HOST, PORTS[MODULE_PC])
        processes.extend([
            start_process("sim_gimbal.py", "--port", str(PORTS[MODULE_GIMBAL])),
            start_process(
                "sim_mmwave.py", "--port", str(PORTS[MODULE_MMWAVE]),
                "--pc-port", str(PORTS[MODULE_PC]),
            ),
            start_process(
                "sim_thz.py", "--port", str(PORTS[MODULE_THZ]),
                "--pc-port", str(PORTS[MODULE_PC]),
            ),
        ])
        for module in (MODULE_GIMBAL, MODULE_MMWAVE, MODULE_THZ):
            wait_for_port(PORTS[module])

        send_control(MODULE_MMWAVE, SIM_SET_TARGET, {
            "target_valid": True,
            "azimuth_mdeg": 12000,
            "elevation_mdeg": 2000,
            "comm_link_quality": 800,
        })
        send_control(MODULE_GIMBAL, SIM_SET_GIMBAL, {
            "current_azimuth_mdeg": 12000,
            "current_elevation_mdeg": 2000,
        })
        send_control(MODULE_THZ, SIM_SET_THZ_LINK, {
            "force_lock": True,
            "link_quality": 900,
            "sense_quality": 900,
        })

        dsp = start_process(
            "dsp_state_machine.py",
            "--slot-hz", "20",
            "--max-slots", "240",
            "--gimbal-port", str(PORTS[MODULE_GIMBAL]),
            "--mmwave-port", str(PORTS[MODULE_MMWAVE]),
            "--thz-port", str(PORTS[MODULE_THZ]),
            "--pc-port", str(PORTS[MODULE_PC]),
        )
        processes.append(dsp)

        first_track = wait_for_state(hub, "S4")
        send_control(MODULE_THZ, SIM_SET_FAULT, {
            "online": False,
            "fault_mode": "offline",
        })
        recovery = wait_for_state(hub, "S7")
        send_control(MODULE_THZ, SIM_SET_FAULT, {
            "online": True,
            "fault_mode": "none",
        })
        restored_track = wait_for_state(hub, "S4")

        print(
            "five-process smoke passed: "
            f"S4@{first_track['slot_id']} -> S7@{recovery['slot_id']} "
            f"-> S4@{restored_track['slot_id']}"
        )
        return 0
    finally:
        if hub is not None:
            hub._server.stop()
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
