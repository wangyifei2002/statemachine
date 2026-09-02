#!/usr/bin/env python3
"""Build and compare normalized Python/C output for every shared scenario."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = sorted((ROOT / "state_machine/tests/scenarios").glob("*.csv"))


def run(command: list[str], cwd: Path = ROOT) -> bytes:
    return subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE).stdout


def main() -> int:
    run(["make", "clean", "all"], ROOT / "state_machine/c")
    paths = [str(path) for path in SCENARIOS]
    python_output = run([sys.executable, "state_machine/tests/run_python_scenarios.py", *paths])
    c_output = run([str(ROOT / "state_machine/c/build/scenario_runner"), *paths])
    if python_output != c_output:
        raise AssertionError("Python and C per-slot outputs differ")
    line_count = len(python_output.splitlines())
    digest = hashlib.sha256(python_output).hexdigest()
    print(f"Python/C parity passed: {line_count} slots, sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
