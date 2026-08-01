# Raspberry Pi field controls

These files implement the Raspberry Pi side of the temporary Prava live page.

Production view: <https://prava-ashen.vercel.app/live>

## One-command startup

After connecting over SSH, start the keyboard controller, GPS telemetry and
200% speaker-volume default with:

```bash
prava-control
```

The same command supports explicit lifecycle actions:

```bash
prava-control start
prava-control status
prava-control restart
prava-control stop
```

GPS telemetry is intentionally separated from the disabled camera encoder and
public video tunnel.

## Keyboard controls

- `W`: forward
- `S`: reverse
- `A`: pivot left
- `D`: pivot right
- `1`: 30% power
- `2`: 60% power
- `3`: 100% power
- `4`: 150% speaker volume
- `5`: 200% speaker volume
- Hold `Space`: continuously loop the truck horn
- Release `Space`: stop the horn immediately
- `Esc`: latch the emergency software stop
- `R`: re-arm motor control at zero output

The drive controller starts at 30% duty cycle, commands zero PWM and disables all
four BTS7960 enable pins whenever no movement key is held, and pauses before a
direction reversal. The number-row and numeric-keypad `1`, `2`, and `3` keys
select the motor power mode immediately. Number-row and numeric-keypad `4` and
`5` set speaker volume to 150% and 200%, respectively. The service is
intentionally started but not enabled at boot during initial testing.

After an emergency stop, `R` only re-arms the controller; it does not move the
motors. Press a fresh `W`, `A`, `S`, or `D` key after re-arming to drive again.

```bash
systemctl --user start prava-drive.service
systemctl --user stop prava-drive.service
systemctl --user status prava-drive.service
```

Raise the driven wheels and keep the motor battery emergency disconnect within
reach during the first direction test. If a wheel runs backward, use the matching
`--left-inverted` or `--right-inverted` option in `prava-drive.service`.

## Telemetry

MediaMTX continuously encodes Camera Module 3 as a 1920×1080, 30 fps H.264
low-latency HLS stream. A temporary outbound HTTPS tunnel exposes only the HLS
server, so no router port forwarding is required. The tunnel URL changes when the
tunnel service restarts and is reported automatically to the website.

Raspberry Pi 5 performs this H.264 encode in software. Use an active cooler or
fan for sustained 1080p30 operation and check temperature/throttling with:

```bash
vcgencmd measure_temp
vcgencmd get_throttled
```

The telemetry uploader reads NMEA fixes from `/dev/ttyAMA0` and sends the current
stream endpoint and GPS state to the authenticated ingestion endpoint every three
seconds. The server marks the Pi offline after 15 seconds and expires telemetry
after five minutes.

It also writes live GPS acquisition details to
`~/.local/state/prava/gps-status.json`. View them without competing for the UART:

```bash
prava-gps-dashboard
```

The upload token is stored only on the Pi at:

`/home/pi/.config/prava/telemetry.token`

## Speaker volume

`prava-volume.service` sets the default MAX98357A PipeWire output to 200%
software volume after audio starts and reapplies it on every boot/login. This
gain is above the unclipped 100% level, so loud audio can distort.

```bash
systemctl --user status prava-volume.service
wpctl get-volume @DEFAULT_AUDIO_SINK@
```

The public camera encoder and tunnel are intentionally disabled. Telemetry
remains enabled across reboots:

```bash
systemctl --user is-enabled prava-video.service prava-stream-tunnel.service
systemctl --user status prava-telemetry.service
```

## Max VSLAM integration

The non-actuating readiness audit and fail-closed `/cmd_vel` safety boundary are
documented in [`autonomy/README.md`](autonomy/README.md). Autonomous motor output
remains disabled until measured wheel odometry, physical emergency stop,
obstacle sensing, active cooling, ROS 2, and sensor calibration are validated.
