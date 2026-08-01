#!/usr/bin/env python3
"""Drive two BTS7960 modules from a USB keyboard on a Raspberry Pi 5."""

from __future__ import annotations

import argparse
import glob
import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import lgpio


EV_KEY = 1
KEY_ESC = 1
KEY_R = 19
KEY_W = 17
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_SPACE = 57
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_KP4 = 75
KEY_KP5 = 76
KEY_KP1 = 79
KEY_KP2 = 80
KEY_KP3 = 81
EVENT = struct.Struct("@llHHI")

POWER_MODES = {
    KEY_1: 0.30,
    KEY_KP1: 0.30,
    KEY_2: 0.60,
    KEY_KP2: 0.60,
    KEY_3: 1.00,
    KEY_KP3: 1.00,
}

VOLUME_MODES = {
    KEY_4: 1.50,
    KEY_KP4: 1.50,
    KEY_5: 2.00,
    KEY_KP5: 2.00,
}

LEFT_PINS = {"forward": 12, "reverse": 13, "right_enable": 5, "left_enable": 6}
RIGHT_PINS = {
    "forward": 16,
    "reverse": 20,
    "right_enable": 23,
    "left_enable": 24,
}


class Bts7960:
    def __init__(
        self,
        chip: int,
        pins: dict[str, int],
        *,
        frequency: int,
        inverted: bool,
    ) -> None:
        self.chip = chip
        self.forward_pin = pins["forward"]
        self.reverse_pin = pins["reverse"]
        self.enable_pins = (pins["right_enable"], pins["left_enable"])
        self.frequency = frequency
        self.inverted = inverted
        self.direction = 0

        for pin in (self.forward_pin, self.reverse_pin, *self.enable_pins):
            lgpio.gpio_claim_output(self.chip, pin, 0)

    def _pwm(self, pin: int, duty: float) -> None:
        lgpio.tx_pwm(self.chip, pin, self.frequency, max(0.0, min(100.0, duty)))

    def stop(self) -> None:
        self._pwm(self.forward_pin, 0)
        self._pwm(self.reverse_pin, 0)
        for pin in self.enable_pins:
            lgpio.gpio_write(self.chip, pin, 0)
        self.direction = 0

    def set(self, command: float) -> None:
        command = max(-1.0, min(1.0, command))
        if self.inverted:
            command = -command
        next_direction = 0 if command == 0 else (1 if command > 0 else -1)

        if next_direction == 0:
            self.stop()
            return
        if self.direction and self.direction != next_direction:
            self.stop()
            time.sleep(0.05)

        inactive_pin = self.reverse_pin if next_direction > 0 else self.forward_pin
        active_pin = self.forward_pin if next_direction > 0 else self.reverse_pin
        self._pwm(inactive_pin, 0)
        for pin in self.enable_pins:
            lgpio.gpio_write(self.chip, pin, 1)
        self._pwm(active_pin, abs(command) * 100.0)
        self.direction = next_direction


class DriveController:
    def __init__(
        self,
        speed: float,
        horn: Path,
        left_inverted: bool,
        right_inverted: bool,
    ):
        self.running = True
        self.emergency_stopped = False
        self.speed = speed
        self.horn = horn
        self.horn_process: subprocess.Popen[bytes] | None = None
        self.chip = lgpio.gpiochip_open(0)
        self.left = Bts7960(
            self.chip,
            LEFT_PINS,
            frequency=1_000,
            inverted=left_inverted,
        )
        self.right = Bts7960(
            self.chip,
            RIGHT_PINS,
            frequency=1_000,
            inverted=right_inverted,
        )
        self.stop()

    def stop(self) -> None:
        self.left.stop()
        self.right.stop()

    def close(self) -> None:
        self.stop()
        self.stop_horn()
        lgpio.gpiochip_close(self.chip)

    def start_horn(self) -> None:
        if not self.horn.exists():
            print(f"Horn file missing: {self.horn}", flush=True)
            return
        if self.horn_process and self.horn_process.poll() is None:
            return
        self.horn_process = subprocess.Popen(
            [
                "/usr/bin/ffplay",
                "-nodisp",
                "-autoexit",
                "-loop",
                "0",
                "-loglevel",
                "error",
                str(self.horn),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )

    def stop_horn(self) -> None:
        if not self.horn_process or self.horn_process.poll() is not None:
            self.horn_process = None
            return
        self.horn_process.terminate()
        try:
            self.horn_process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self.horn_process.kill()
            self.horn_process.wait()
        self.horn_process = None

    def set_volume(self, volume: float) -> None:
        try:
            subprocess.run(
                [
                    "/usr/bin/wpctl",
                    "set-volume",
                    "--limit",
                    "2.0",
                    "@DEFAULT_AUDIO_SINK@",
                    str(volume),
                ],
                check=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Could not set speaker volume: {exc}", flush=True)
            return
        print(f"Speaker volume set to {volume:.0%}.", flush=True)

    def apply_keys(self, pressed: set[int]) -> None:
        if self.emergency_stopped:
            self.stop()
            return
        throttle = float(KEY_W in pressed) - float(KEY_S in pressed)
        turn = float(KEY_D in pressed) - float(KEY_A in pressed)
        left = max(-1.0, min(1.0, throttle + turn)) * self.speed
        right = max(-1.0, min(1.0, throttle - turn)) * self.speed
        self.left.set(left)
        self.right.set(right)


def find_keyboard() -> str | None:
    preferred = sorted(glob.glob("/dev/input/by-id/*-event-kbd"))
    return preferred[0] if preferred else None


def keyboard_loop(controller: DriveController) -> None:
    pressed: set[int] = set()

    while controller.running:
        keyboard = find_keyboard()
        if not keyboard:
            controller.stop()
            controller.stop_horn()
            print("Keyboard not found; motors disabled. Retrying…", flush=True)
            time.sleep(2)
            continue

        print(f"Keyboard ready: {keyboard}", flush=True)
        try:
            fd = os.open(keyboard, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            print(f"Cannot open keyboard: {exc}", flush=True)
            time.sleep(2)
            continue

        poller = select.poll()
        poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
        try:
            while controller.running:
                events = poller.poll(500)
                if not events:
                    continue
                data = os.read(fd, EVENT.size * 32)
                if not data:
                    raise OSError("keyboard disconnected")
                for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, event_type, code, value = EVENT.unpack_from(data, offset)
                    if event_type != EV_KEY:
                        continue
                    if code == KEY_ESC and value == 1:
                        controller.emergency_stopped = True
                        pressed.clear()
                        controller.stop()
                        controller.stop_horn()
                        print(
                            "EMERGENCY STOP latched. Press R to re-arm.",
                            flush=True,
                        )
                        continue
                    if code == KEY_R and value == 1:
                        if controller.emergency_stopped:
                            pressed.clear()
                            controller.stop()
                            controller.emergency_stopped = False
                            print(
                                (
                                    "Motor control re-armed at zero output. "
                                    "Press a movement key to drive."
                                ),
                                flush=True,
                            )
                        continue
                    if code == KEY_SPACE:
                        if value == 1:
                            controller.start_horn()
                        elif value == 0:
                            controller.stop_horn()
                        continue
                    if code in POWER_MODES and value == 1:
                        controller.speed = POWER_MODES[code]
                        controller.apply_keys(pressed)
                        print(
                            f"Power mode set to {controller.speed:.0%}.",
                            flush=True,
                        )
                        continue
                    if code in VOLUME_MODES and value == 1:
                        controller.set_volume(VOLUME_MODES[code])
                        continue
                    if code not in {KEY_W, KEY_A, KEY_S, KEY_D}:
                        continue
                    if value == 0:
                        pressed.discard(code)
                    elif value == 1:
                        pressed.add(code)
                    controller.apply_keys(pressed)
        except OSError as exc:
            controller.stop()
            controller.stop_horn()
            pressed.clear()
            print(f"Keyboard unavailable ({exc}); motors disabled.", flush=True)
        finally:
            os.close(fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed", type=float, default=0.30)
    parser.add_argument(
        "--horn",
        type=Path,
        default=Path.home() / ".local/share/prava/truck-horn.mp3",
    )
    parser.add_argument("--left-inverted", action="store_true")
    parser.add_argument("--right-inverted", action="store_true")
    args = parser.parse_args()
    if not 0.05 <= args.speed <= 1.0:
        parser.error("--speed must be between 0.05 and 1.0")
    return args


def main() -> int:
    args = parse_args()
    controller = DriveController(
        args.speed,
        args.horn,
        args.left_inverted,
        args.right_inverted,
    )

    def stop_from_signal(_signum: int, _frame: object) -> None:
        controller.running = False
        controller.stop()

    signal.signal(signal.SIGINT, stop_from_signal)
    signal.signal(signal.SIGTERM, stop_from_signal)
    print(
        (
            f"Drive control active at {args.speed:.0%}: W/A/S/D move, "
            "1/2/3 select 30%/60%/100% motor power, "
            "4/5 select 150%/200% speaker volume, Space horn, "
            "Esc emergency stop, R re-arm."
        ),
        flush=True,
    )
    try:
        keyboard_loop(controller)
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
