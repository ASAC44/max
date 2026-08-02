import tempfile
import unittest
from pathlib import Path

from max_robot.drive_controller import (
    KEY_2,
    KEY_A,
    KEY_D,
    KEY_S,
    KEY_SPACE,
    KEY_W,
    DriveController,
    detach_keyboard,
    find_named_input_device,
    handle_device_key_event,
    handle_key_event,
)


class FakeGpio:
    def __init__(self):
        self.claims = []
        self.pwm = []
        self.writes = []
        self.closed = []

    def gpiochip_open(self, chip):
        self.opened = chip
        return 7

    def gpio_claim_output(self, chip, pin, initial):
        self.claims.append((chip, pin, initial))

    def tx_pwm(self, chip, pin, frequency, duty):
        self.pwm.append((chip, pin, frequency, duty))

    def gpio_write(self, chip, pin, value):
        self.writes.append((chip, pin, value))

    def gpiochip_close(self, chip):
        self.closed.append(chip)


class DriveControllerTests(unittest.TestCase):
    def test_named_virtual_input_device_is_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sys_root = root / "sys"
            dev_root = root / "dev"
            name_path = sys_root / "event12" / "device" / "name"
            name_path.parent.mkdir(parents=True)
            name_path.write_text("Max Remote Teleop\n")
            dev_root.mkdir()
            (dev_root / "event12").touch()

            self.assertEqual(
                find_named_input_device(
                    "Max Remote Teleop",
                    sys_input_root=sys_root,
                    dev_input_root=dev_root,
                ),
                str(dev_root / "event12"),
            )
            self.assertIsNone(
                find_named_input_device(
                    "Another Device",
                    sys_input_root=sys_root,
                    dev_input_root=dev_root,
                )
            )

    def test_real_pin_contract_movement_release_and_power_mode(self):
        gpio = FakeGpio()
        controller = DriveController(
            0.30,
            Path("/missing-horn.mp3"),
            False,
            False,
            gpio=gpio,
        )
        pressed = set()
        try:
            self.assertEqual(
                {pin for _, pin, _ in gpio.claims},
                {5, 6, 12, 13, 16, 20, 23, 24},
            )

            handle_key_event(controller, pressed, KEY_W, 1)
            self.assertEqual(controller.left.direction, 1)
            self.assertEqual(controller.right.direction, 1)
            self.assertIn((7, 12, 1_000, 30.0), gpio.pwm)
            self.assertIn((7, 16, 1_000, 30.0), gpio.pwm)

            handle_key_event(controller, pressed, KEY_2, 1)
            self.assertEqual(controller.speed, 0.60)
            self.assertIn((7, 12, 1_000, 60.0), gpio.pwm)
            self.assertIn((7, 16, 1_000, 60.0), gpio.pwm)

            handle_key_event(controller, pressed, KEY_W, 0)
            self.assertEqual(controller.left.direction, 0)
            self.assertEqual(controller.right.direction, 0)

            handle_key_event(controller, pressed, KEY_A, 1)
            self.assertEqual(controller.left.direction, -1)
            self.assertEqual(controller.right.direction, 1)
            handle_key_event(controller, pressed, KEY_A, 0)
            self.assertEqual(pressed, set())
        finally:
            controller.close()
        self.assertEqual(gpio.closed, [7])

    def test_turn_keys_dominate_throttle_and_pivot_in_place(self):
        controller = DriveController(
            0.60,
            Path("/missing-horn.mp3"),
            False,
            False,
            gpio=FakeGpio(),
        )
        try:
            controller.apply_keys({KEY_W, KEY_A})
            self.assertEqual(controller.left.direction, -1)
            self.assertEqual(controller.right.direction, 1)

            controller.apply_keys({KEY_S, KEY_D})
            self.assertEqual(controller.left.direction, 1)
            self.assertEqual(controller.right.direction, -1)

            controller.apply_keys({KEY_A, KEY_D})
            self.assertEqual(controller.left.direction, 0)
            self.assertEqual(controller.right.direction, 0)

            controller.apply_keys({KEY_W, KEY_S})
            self.assertEqual(controller.left.direction, 0)
            self.assertEqual(controller.right.direction, 0)
        finally:
            controller.close()

    def test_virtual_and_physical_keyboards_keep_independent_held_state(self):
        controller = DriveController(
            0.30,
            Path("/missing-horn.mp3"),
            False,
            False,
            gpio=FakeGpio(),
        )
        states = {"virtual": set(), "physical": set()}
        horn_events = []
        controller.start_horn = lambda: horn_events.append("start")
        controller.stop_horn = lambda: horn_events.append("stop")
        try:
            handle_device_key_event(controller, states, "virtual", KEY_W, 1)
            self.assertEqual((controller.left.direction, controller.right.direction), (1, 1))

            handle_device_key_event(controller, states, "physical", KEY_A, 1)
            self.assertEqual((controller.left.direction, controller.right.direction), (-1, 1))

            handle_device_key_event(controller, states, "physical", KEY_A, 0)
            self.assertEqual((controller.left.direction, controller.right.direction), (1, 1))

            handle_device_key_event(controller, states, "virtual", KEY_SPACE, 1)
            handle_device_key_event(controller, states, "physical", KEY_SPACE, 1)
            handle_device_key_event(controller, states, "virtual", KEY_SPACE, 0)
            self.assertEqual(horn_events, ["start"])
            handle_device_key_event(controller, states, "physical", KEY_SPACE, 0)
            self.assertEqual(horn_events, ["start", "stop"])

            detach_keyboard(controller, states, "virtual")
            self.assertEqual((controller.left.direction, controller.right.direction), (0, 0))
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
