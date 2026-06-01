#!/usr/bin/env python3
"""Send pan/tilt angle commands to the STM32 board over USART1."""

from __future__ import annotations

import argparse
import sys
import time

# Force unbuffered output so output appears immediately in terminals
sys.stdout.reconfigure(line_buffering=True)


DEFAULT_BAUDRATE = 115200
DEFAULT_RESPONSE_WAIT_S = 1.0


def require_serial():
    try:
        import serial
    except ImportError as exc:
        raise SystemExit(
            "pyserial is required. Install it with: python3 -m pip install pyserial"
        ) from exc

    return serial


def list_serial_ports() -> None:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise SystemExit(
            "pyserial is required. Install it with: python3 -m pip install pyserial"
        ) from exc

    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    for port in ports:
        desc = port.description or "no description"
        print(f"{port.device}\t{desc}")


def read_available(ser, wait_s: float = 0.2) -> str:
    deadline = time.time() + wait_s
    chunks: list[bytes] = []

    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunks.append(ser.read(waiting))
            deadline = time.time() + 0.05
        else:
            time.sleep(0.01)

    return b"".join(chunks).decode("utf-8", errors="replace")


def send_command(ser, command: str, wait_s: float) -> None:
    command = command.strip()
    if not command:
        return

    ser.write((command + "\n").encode("ascii"))
    ser.flush()
    print(f"> {command}")

    response = read_available(ser, wait_s=wait_s)
    if response:
        print(response, end="" if response.endswith("\n") else "\n")


def interactive_loop(ser, wait_s: float) -> None:
    print("Type commands: PAN 45, TILT -20, GOTO 45 30, BAUD 9600, GET, GET RAW, RETURN RT, LISTEN RAW, HOME, STOP, HELP")
    print("Type quit or exit to close.")

    while True:
        try:
            command = input("angle> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if command.strip().lower() in {"quit", "exit"}:
            return

        send_command(ser, command, wait_s)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Control STM32 Pelco-D pan/tilt angles through USART1."
    )
    parser.add_argument(
        "port",
        nargs="?",
        help="Serial port, for example /dev/cu.usbserial-xxxx or COM3.",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Baudrate, default {DEFAULT_BAUDRATE}.",
    )
    parser.add_argument(
        "-c",
        "--command",
        action="append",
        help="Command to send. Can be used multiple times, e.g. -c 'PAN 45'.",
    )
    parser.add_argument(
        "-w",
        "--wait",
        type=float,
        default=DEFAULT_RESPONSE_WAIT_S,
        help=f"Seconds to wait for each response, default {DEFAULT_RESPONSE_WAIT_S}.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available serial ports and exit.",
    )
    args = parser.parse_args(argv)

    if args.list:
        list_serial_ports()
        return 0

    if not args.port:
        parser.error("port is required unless --list is used")

    serial = require_serial()

    with serial.Serial(args.port, args.baudrate, timeout=0.2) as ser:
        time.sleep(2.0)
        boot_log = read_available(ser, wait_s=0.5)
        if boot_log:
            print(boot_log, end="" if boot_log.endswith("\n") else "\n")

        if args.command:
            for command in args.command:
                send_command(ser, command, args.wait)
                time.sleep(0.1)
        else:
            interactive_loop(ser, args.wait)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
