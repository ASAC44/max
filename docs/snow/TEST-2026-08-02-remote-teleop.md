# Remote teleoperation verification — 2026-08-02

## Scope

Verified the real operator-browser → FastAPI WebSocket broker → Linux target
agent path for W/A/S/D, Space, and 1-5. The Raspberry Pi was then brought
online and the final services and configuration were installed at
`192.168.137.43`. No merchant purchase or payment was triggered.

## Automated results

- API suite: **74 passed**
- Raspberry Pi suite on Pi: **47 passed, 4 subtests passed**
- Raspberry Pi suite on Mac: **42 passed, 5 platform skips, 4 subtests passed**
- Focused backend teleoperation tests: **8 passed**
- Focused target-agent tests: **10 passed**
- Real localhost Uvicorn/WebSocket/browser-to-target test: **passed**
- Frontend protocol tests: **2 passed**
- Production Vite build: **passed**
- Python compile, dependency check, shell syntax, Docker Compose validation,
  secret-pattern scan, and `git diff --check`: **passed**
- Production image dependency audit: npm reported **0 vulnerabilities**

## Interaction and failure matrix

The real-browser run confirmed:

- every approved key individually reaches the target and releases;
- simultaneous `W+A+Space+2+4` and `S+D+3+5`;
- held input refresh without repeated target key-down events;
- rapid press/release;
- emergency stop releases simultaneous movement/horn keys;
- browser close releases active input;
- backend shutdown while W is held releases W;
- backend restart reconnects both peers with an empty state and keyboard capture
  off;
- target-agent shutdown while W is held releases W;
- target-agent restart reconnects empty and leaves keyboard capture off;
- exact-origin enforcement, invalid-token rejection, and exclusive-controller
  rejection;
- stale, duplicated, conflicting-duplicate, malformed, and out-of-order packet
  behavior;
- dead-man release under dropped refresh packets;
- clean recovered browser console and no runtime error overlay.

Automated tests also exercise safety-latch persistence, authenticated HTTP
emergency-stop fallback, backend shutdown, local target dead-man expiry, and
target execution failure.

## Production verification

Deployed at `https://max.3-110-105-33.sslip.io`.

- HTTPS health reports `teleop_enabled=true`.
- Purchase remains disabled.
- Unauthenticated teleoperation status returns HTTP 401.
- Public WSS controller authentication succeeds through Caddy.
- API, dashboard, order-status worker, and Caddy are healthy.
- Production target status reports agent `max-pi` version `1.0.0` online.
- The unified mission agent reports version `0.3.0`, dry-run mode, camera/GPS/
  IMU/audio present, motors disabled, and no last error.
- All three Pi services are enabled and active:
  `max-teleop-agent.service`, `max-drive-controller.service`, and
  `max-robot-agent.service`.
- Legacy `max-robot-bridge.service` and `prava-drive.service` are disabled and
  inactive.
- Production controls are disabled after testing.
- Emergency stop is latched and persisted at mode 0600.
- Database backup `max-before-teleop-20260802.db` was created before deployment.

## Live Pi verification

The live transport test stopped `max-drive-controller.service` before sending
movement keys and first confirmed all eight motor GPIO outputs were low. The
real `/dev/input/event11` device named `Max Remote Teleop` then recorded:

- individual W, A, S, and D down/up events;
- simultaneous `W+A+Space+2+4`;
- simultaneous `S+D+3+5`;
- a release for every pressed key.

The drive service was restored before a non-motion test. Through the real AWS
WebSocket and Pi hardware consumer, keys 1-5 selected 30%, 60%, 100%, 150%, and
200% modes; Space exercised the horn input; and the final speaker sink volume
was `2.00`. The test released every key and re-latched emergency stop.

Restarting the Pi teleoperation service also stopped and restarted its dependent
drive service. The drive process initially kept motors disabled, rediscovered
`Max Remote Teleop`, and AWS reconnected with emergency stop latched, controls
disabled, and both active-key sets empty. All motor GPIO outputs were low after
the test. Five final DNS resolutions and five final AWS HTTPS probes succeeded.

## Installed bundle

The Pi bundle is built at
`/tmp/max-robot-agent-bundle-20260802.tar.gz` with SHA-256:

```text
a3afe70ffe37509527d8370d5c3c43603b9acd6d4a88ff52df4a048392b77b60
```

This exact archive was copied to the Pi, checksum-matched, installed into
`/opt/max-robot/venv`, and restarted successfully.

The one remaining physical safety gate is a powered direction test with the
drive wheels raised. It was deliberately not performed remotely because wheel
clearance was not observable. Network transport, key semantics, hardware input
consumption, non-motion actions, reconnect behavior, and motor-off fail-safe
state are all live-verified.
