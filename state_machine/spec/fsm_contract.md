# Unified DSP State-Machine Contract

## Stable identifiers and units

| State | Code | Meaning |
|---|---:|---|
| IDLE | 0 | Waiting for explicit start |
| FAULT | 1 | Safe terminal state until reset |
| S0 | 2 | Module self-check |
| S1 | 3 | Millimeter-wave search |
| S2 | 4 | Gimbal coarse alignment |
| S3 | 5 | THz capture |
| S4 | 6 | THz tracking |
| S5 | 7 | Millimeter-wave fallback |
| S6 | 8 | THz fast reacquisition |
| S7 | 9 | Module recovery |

- One slot is 100 ms by default. All internal timeouts are integer slot counts.
- Angles and angular errors are signed 32-bit millidegrees (`mdeg`).
- Link and sensing quality use integers in the inclusive range `0..1000`.
- Sample-bearing inputs include `valid`, `seq`, and `age_slots`.
- Priority is reset, module fault, target loss, alignment/lock, then timeout.

## Pure step contract

Python `DspStateMachine.step()` and C `Fsm_Step()` consume one immutable input
snapshot and produce one output snapshot. Neither core may perform I/O, sleep,
allocate network resources, call HAL functions, or wait for a device response.

Normalized test output contains `slot_id`, `previous_state`, `state`, `reason`,
`fault_mask`, and the enable/mode fields of the millimeter-wave, gimbal, and THz
commands. These fields must match exactly for every shared scenario row.
