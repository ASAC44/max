# ESP32 pulley controller

This firmware controls one low-voltage DC pulley motor through a BTS7960. The
Raspberry Pi sends commands over the ESP32 USB serial port. The ESP32 has no
location awareness: the Pi/VSLAM layer must prove that the robot is stopped on
the pulley platform checkpoint before it sends `MOVE`.

The Pi integration is `apps/robot/max_robot/pulley.py`. Navigation activates it
only when the route contains an explicit pulley AprilTag/waypoint checkpoint.

## Required safety wiring

- Do not connect a motor directly to an ESP32 pin.
- Use a fused external motor supply and a BTS7960 rated for the motor current.
- Share logic ground between the ESP32 and BTS7960.
- Fit normally-closed upper limit, lower limit, and emergency-stop switches.
  Each input connects to GND while healthy; an endpoint, open contact, or broken
  wire reads HIGH and stops motion.
- The physical emergency stop must also interrupt the driver enable or motor
  power in hardware. Firmware detection is an additional stop path, not the
  primary emergency disconnect.
- Add external pull-downs to both BTS7960 enable inputs so the driver stays off
  during ESP32 boot/reset.

Default pins are compile-time settings in `platformio.ini`:

| Signal | ESP32 GPIO |
| --- | ---: |
| BTS7960 RPWM | 25 |
| BTS7960 LPWM | 26 |
| BTS7960 R_EN | 27 |
| BTS7960 L_EN | 14 |
| Upper NC limit | 32 |
| Lower NC limit | 33 |
| NC emergency stop | 23 |

Change these only after checking the exact ESP32 board's boot-strapping and
input capabilities. All pins must be distinct.

## Serial protocol

Use 115200 baud, 8-N-1, newline-terminated ASCII. Request IDs contain 1–24
letters, numbers, `_`, or `-`.

```text
PING
STATUS
MOVE <request_id> UP
MOVE <request_id> DOWN
KEEPALIVE <request_id>
STOP <request_id>
RESET
```

After `MOVE`, send `KEEPALIVE` at least every 500 ms until `DONE`, `STOPPED`, or
`FAULT`. The default 1-second watchdog stops and latches a fault if keepalives
stop. The independent 15-second travel timeout catches a failed limit switch.
Repeated `MOVE` with the same ID and direction is idempotent; reusing an ID for
the opposite direction is rejected.

Responses are single lines:

```text
PONG 1
ACK trip_42 DOWN MOVING
ACK trip_42 DOWN KEEPALIVE
DONE trip_42 DOWN AT_LIMIT
STOPPED trip_42 STOPPED
ERR trip_42 ID_MISMATCH
FAULT trip_42 KEEPALIVE_TIMEOUT
STATE IDLE ACTIVE - DIRECTION NONE UPPER 0 LOWER 1 ESTOP 0 FAULT -
```

`RESET` never clears an active emergency stop, contradictory limit inputs, or
motion in progress.

## Calibration and build

Start with the pulley unloaded. Confirm that `UP` approaches the upper switch;
set `PULLEY_DIRECTION_INVERTED=1` if direction is reversed. Keep the default 35%
PWM until current draw, braking, and limit-switch stopping distance are measured.
Set `PULLEY_MAX_TRAVEL_MS` slightly above the measured worst-case full travel time,
never as the normal position detector.

Build and flash later with:

```bash
cd firmware/pulley_controller
pio run
pio run --target upload
pio device monitor
```

The pure state-machine check requires only a C++17 compiler:

```bash
c++ -std=c++17 -Wall -Wextra -pedantic \
  -Ifirmware/pulley_controller/include \
  firmware/pulley_controller/native/check.cpp \
  -o /tmp/max-pulley-check
/tmp/max-pulley-check
```

Neither check is run as part of this change.
