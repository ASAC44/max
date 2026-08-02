# Unified Max runtime

## Runtime ownership

The deployed system has two supervised locations:

1. The AWS control plane runs the API, dashboard, Telegram worker, Prava
   sandbox adapter, Swiggy MCP adapter, and the loopback-only Swiggy Chrome
   profile.
2. The Raspberry Pi runs `max-robot-agent.service` for durable mission/status
   polling, `max-teleop-agent.service` for authenticated manual keyboard input,
   and `max-drive-controller.service` as the single BTS7960/horn hardware
   consumer.

The old inbound bridge and standalone poller are compatibility code, not active
services. The Pi installer disables both known legacy service units before it
enables the unified mission agent and the independently fail-safe teleoperation
agent.

## End-to-end state boundary

```text
Owner request
  -> exact Swiggy quote
  -> Prava sandbox approval
  -> one-shot browser checkout
  -> immutable merchant/Prava result
  -> durable Swiggy status timeline
  -> authenticated Pi status cursor
  -> ARRIVED_AT_DELIVERY_LOCATION gate
  -> separate staged physical fulfilment
  -> authenticated dry-run Pi job
  -> AT_PICKUP
  -> ITEM_SECURED
  -> RETURNING
  -> COMPLETED
```

Production commerce/payment truth is never relabelled as physical fulfilment.
The physical branch is a child mission with `environment=staged_demo`.

The AWS `order-sync-worker` polls Swiggy's authenticated order tools. Each
distinct status is appended as `SWIGGY_ORDER_<NORMALIZED>` and exposed through
`GET /api/robot/v1/order-status?after=<cursor>`. The Pi persists that cursor
before asking for a job, so a restart cannot silently forget the latest
delivery state. Only `ARRIVED_AT_DELIVERY_LOCATION` stages a child mission and
job; every earlier status has `robot_action=WAIT`.

The worker isolates failures per order, stops polling terminal orders, reports
an atomic heartbeat through the shared data volume, and revokes an uncompleted
job if Swiggy later reports cancellation or failure. Telegram notifications use
a retryable reservation so a transient send failure cannot permanently discard
a status update.

## Autonomous motion boundary

The unified Pi agent is intentionally hard-coded to accept only:

```text
dry_run=true
motion_started=false
motion_enabled=false
```

It refuses startup if `MAX_ROBOT_DRY_RUN` is not `true`, rejects any backend
response that enables motion, and reports motors as disabled. The backend also
rejects unsafe acknowledgements and lifecycle reports.

This is required because the physical robot has no measured wheel odometry and
no validated physical emergency-stop input. Camera, GPS, and IMU presence
cannot replace wheel motion measurement or a collision-safe stopping system.

Manual remote keyboard control is a separate, explicitly armed operator path.
It does not change the autonomous `motion_enabled=false` contract. Its
single-controller lease, approved key map, uinput target, dead-man releases,
and emergency-stop latch are specified in
[REMOTE-TELEOP.md](REMOTE-TELEOP.md).

## Pi installation bundle

Build the non-secret bundle on the deployment Mac:

```bash
./infra/pi/build-agent-bundle.sh /tmp/max-robot-agent-bundle.tar.gz
```

When the Pi is online, copy and unpack it as `/tmp/max-robot-source`. Copy a
mode-0600 environment file to `/tmp/max-robot-agent.env`, then run:

```bash
sudo /tmp/max-robot-source/infra/pi/install-agent.sh
```

The installer creates `/opt/max-robot/venv`, installs three root-managed
systemd units, stores configuration in `/etc/max-robot/agent.env`, and creates
writable state under `/var/lib/max-robot`. It disables the legacy user-level
bridge and drive units so they cannot compete for network input or GPIO.

Use `MAX_ROBOT_REHEARSAL=true` only for the labelled no-motion end-to-end
rehearsal. It advances staged lifecycle checkpoints without driving motors.
Normal installed state is `false`, so real pickup checkpoints require future
validated hardware integration.

## Readiness and monitoring

The authenticated backend readiness endpoint reports only redacted state:

```bash
curl -H "Authorization: Bearer $MAX_ADMIN_TOKEN" \
  https://max.example.com/api/readiness
```

It checks:

- Prava sandbox configuration;
- Telegram owner configuration;
- Swiggy MCP OAuth/tool availability;
- loopback-only Chrome CDP;
- Pi heartbeat freshness.

The dashboard polls `/api/robot/v1/status` and shows every Pi subsystem as
`present`, `degraded`, `unavailable`, or `disabled`. `present` means a device
node exists; it is not proof of calibration or correct physical behavior.

## Gates before physical autonomy

Do not remove the dry-run boundary until all of these are evidenced:

- measured wheel odometry or an independently validated localization/control
  source suitable for the route;
- normally-closed physical emergency stop that removes motor power;
- motor direction and braking tests with wheels raised first;
- camera calibration and stable localization on the actual route;
- obstruction stopping distance and latency;
- pickup/cargo confirmation mechanism;
- network-loss and process-restart recovery;
- ten supervised pickup-and-return runs and thirty obstruction approaches.
