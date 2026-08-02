# Remote keyboard teleoperation

## End-to-end path

```text
Operator browser
  -> authenticated controller WebSocket
  -> single-controller lease in the Max API
  -> authenticated target WebSocket
  -> max-teleop-agent.service on the Raspberry Pi
  -> dedicated Linux uinput keyboard
  -> the bot's local keyboard-control process
```

The browser sends complete key-state snapshots rather than isolated key events.
This permits simultaneous keys and makes every update idempotent. While any key
is held, the browser refreshes the current snapshot every 100 ms. The backend
and Pi agent independently release all keys when their 350 ms dead-man deadline
expires.

The operator token and robot token are sent only in the first WebSocket message;
they never appear in a URL. The backend permits exactly one authenticated
controller and one authenticated target. Browser origins must exactly match
`MAX_WEB_ORIGIN`.

## Key contract

| Physical key | Target key | Assigned action |
| --- | --- | --- |
| W | W | Forward |
| A | A | Left |
| S | S | Reverse |
| D | D | Right |
| Space | Space | Horn |
| 1 | 1 | Drive power 30% |
| 2 | 2 | Drive power 60% |
| 3 | 3 | Drive power 100% |
| 4 | 4 | Speaker volume 150% |
| 5 | 5 | Speaker volume 200% |

The relay never accepts arbitrary keys, text, mouse actions, shell commands, or
more than one key from either mode group. It also rejects `W+S` and `A+D`.
Switching direction or mode sends releases before presses on the target.

The Pi emits these keys through `/dev/uinput`. The local bot keyboard controller
consumes Linux input events from the virtual device named `Max Remote Teleop`.
`max-drive-controller.service` is the single owner of the installed BTS7960
and audio hardware:

| Side | BTS7960 input | BCM GPIO |
| --- | --- | --- |
| Left | RPWM / forward | 12 |
| Left | LPWM / reverse | 13 |
| Left | R_EN | 5 |
| Left | L_EN | 6 |
| Right | RPWM / forward | 16 |
| Right | LPWM / reverse | 20 |
| Right | R_EN | 23 |
| Right | L_EN | 24 |

The controller selects the named virtual device first and leaves physical
keyboard fallback disabled by default. This prevents an unrelated keyboard
from becoming a second uncontrolled input path.

## Safety behavior

- The emergency-stop latch defaults to **on** when its state file is absent,
  unreadable, corrupt, or cannot be written.
- Clearing the latch requires an exclusive authenticated controller, an online
  Pi agent, and a matching reset acknowledgement from that agent.
- Emergency stop releases all active keys, disarms the Pi input executor, and
  is saved atomically. An authenticated HTTP endpoint is available as a fallback
  if the controller WebSocket is the failed component.
- Browser blur, visibility loss, page close, controller disconnect, controller
  idle timeout, backend shutdown, Pi-agent disconnect, target dead-man timeout,
  malformed input, or target execution failure releases every active key.
- Reconnection never restores a previously held key. The operator must click
  **Enable keyboard** again after an outage.
- Client and server sequences reject conflicting duplicates and old updates.
  Timestamp and expiry checks reject delayed packets. Target acknowledgements
  and heartbeats are cross-checked against backend state; disagreement releases
  every key and re-arms the target without fabricating an operator E-stop.

This lease is intentionally in-memory and the API must run as one Uvicorn
process. Do not add multiple API workers without first replacing it with a
distributed lease/state coordinator.

## Backend configuration

```env
MAX_TELEOP_ENABLED=true
MAX_TELEOP_DEADMAN_MS=350
MAX_TELEOP_MAX_CLIENT_AGE_MS=1000
MAX_TELEOP_CONTROLLER_IDLE_SECONDS=6
MAX_TELEOP_AGENT_IDLE_SECONDS=10
MAX_TELEOP_STATE_FILE=/data/teleop-state.json
MAX_WEB_ORIGIN=https://max.example.com
```

The Compose service mounts `/data` as a durable volume. Only an explicit
operator E-stop is persisted across API restarts; missing or unreadable state
does not fabricate an E-stop.

## Pi installation

Build and transfer the bundle described in
[UNIFIED-RUNTIME.md](UNIFIED-RUNTIME.md). The Pi environment must include:

```env
MAX_CONTROL_API_URL=https://max.example.com
MAX_ROBOT_TOKEN=the-separate-backend-robot-token
MAX_ROBOT_ID=max-pi
MAX_TELEOP_INPUT_ENABLED=true
MAX_TELEOP_UINPUT_DEVICE=/dev/uinput
MAX_TELEOP_INPUT_DEVICE_NAME=Max Remote Teleop
MAX_DRIVE_PHYSICAL_KEYBOARD_FALLBACK=false
```

The root installer loads the `uinput` kernel module, creates a narrowly scoped
udev rule, installs the Python target and drive agents, and enables
`max-teleop-agent.service`, `max-drive-controller.service`, and
`max-robot-agent.service`. It also disables the legacy user-level
`max-robot-bridge.service` and `prava-drive.service`. The teleoperation service
runs as `pi`, has only `/dev/uinput` device access, and restarts with bounded
reconnect backoff.

After installation, verify without putting the wheels on the ground:

```bash
sudo systemctl status max-teleop-agent.service
sudo systemctl status max-drive-controller.service
sudo journalctl -u max-teleop-agent.service -n 100 --no-pager
sudo journalctl -u max-drive-controller.service -n 100 --no-pager
grep -A5 -B2 "Max Remote Teleop" /proc/bus/input/devices
```

Use the dashboard only with the drive wheels raised for the first physical
direction, hold, release, network-loss, and emergency-stop test. Confirm the
local keyboard-control process observes the virtual device before applying
motor power.

## Operator sequence

1. Enter the operator token in Mission Control.
2. Confirm **PI AGENT ONLINE** and inspect the E-stop badge.
3. Take the exclusive control lease.
4. If a previous explicit stop remains latched, reset it and wait for
   **E-STOP CLEAR**.
5. Click **Enable keyboard**.
6. Hold or combine the approved keys. `W` and `S` drive straight. `A` and `D`
   take priority over throttle and pivot in place by driving the left and right
   wheels in opposite directions. The backend and Pi-applied states must agree
   in the panel.
7. Use **Release all keys** before leaving the page. Use **Emergency stop** for
   any unexpected behavior.
