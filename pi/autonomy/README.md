# Max VSLAM integration boundary

This directory prepares the Prava Raspberry Pi hardware for the navigation
prototype in [`ASAC44/max`](https://github.com/ASAC44/max), inspected at commit
`984f949a525d1f44bcd6efa73d3416b9a4b27a7c`.

It does **not** enable autonomous motor output. The upstream mission state
machine may be retained, but RTAB-Map navigation can be replaced by
`prava_route_replay.py` for a single taught route. The route controller produces
drive intents from coarse GPS progress, IMU heading, camera path alignment and
camera obstruction status. `prava_autonomy_guard.py` remains the required
fail-closed boundary before a future GPIO bridge may consume those intents.

## Why motor output remains disabled

The physical robot currently has no physical motor-power emergency stop or
depth/lidar obstacle sensor. Header I2C is disabled, the GPS currently has no
fix, and thermal throttling was observed above 85°C. The MPU6050 can improve
orientation estimation but cannot measure reliable travel distance by itself.
ROS 2 is optional in this direct Python route-replay design; it is needed only
if the original Max ROS navigation interfaces are retained.

For the defined 150m route, wheel encoders are no longer a hard software
dependency. They may be substituted experimentally by a manually taught
camera/GPS/IMU route, but only while a supervisor maintains a live stop link.
The NEO-6M GPS is a coarse progress signal; camera path lock is responsible for
lateral alignment.

The public Camera Module 3 stream is also not a ROS camera pipeline. VSLAM needs
calibrated, timestamped image and camera-info topics without the public tunnel or
1080p software encoder.

## Intended architecture

```text
Camera Module 3 -> path alignment + obstruction state ---┐
NEO-6M GPS -----> coarse route progress -----------------┤
MPU6050 --------> filtered short-term heading -----------┤
                                                         v
Taught route ----> Prava route-replay controller -> safety guard
                                                         v
Live supervisor + physical E-stop ------------> future BTS7960 bridge
```

The MPU6050 has a gyroscope and accelerometer but no magnetometer. Its yaw must
be corrected using camera route alignment and GPS course while moving; raw gyro
integration must not be treated as an absolute compass heading.

## Readiness audit

Update `hardware.json` only after each item has been physically installed and
validated. Then run:

```bash
python3 prava_autonomy_readiness.py --mode route-replay
```

The audit always reports `autonomous_motor_output_enabled: false`; passing the
audit is necessary but does not itself authorize motor output.

## Required implementation stages

1. Add active cooling and keep the Pi below 75°C without current throttle flags.
2. Restore a stable GPS fix and record its HDOP along the complete route.
3. Wire and calibrate the MPU6050 on GPIO2/GPIO3 after enabling header I2C.
4. Calibrate the camera and record a manually driven teach pass with route
   points every 2-5m and visual references continuously along the path.
5. Add a physical latching emergency stop that disconnects motor battery power.
6. Shadow-replay the route without GPIO output and validate GPS progress,
   camera steering, obstruction stops and supervisor-link loss.
7. Perform supervised, wheels-raised GPIO bridge tests at the lowest power.
8. Validate at least 30 obstruction approaches and ten pickup-return routes in a
   closed private test area before considering higher speeds.

Wheel encoders and depth/lidar remain strongly recommended. They are mandatory
before general navigation outside the one validated route.

Outdoor roads, footpaths, and unsupervised food pickup remain out of scope for
the camera-only prototype.
