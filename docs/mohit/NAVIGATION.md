# Max phase 1: hardware-free navigation

## Scope

Phase 1 is a supervised indoor, pickup-and-return prototype:

- RTAB-Map visual SLAM using one RGB camera and wheel odometry.
- AprilTag checkpoints.
- Teach-and-repeat waypoint following.
- Camera-only, fail-closed obstruction stopping.
- A local web page for start, stop, resume, pickup confirmation, cancellation,
  and emergency stop.

Voice, cloud models, payment, Linq, item recognition, lidar costmaps, unknown
environment navigation, and public-space operation are deferred.

No neural model is required in this phase. RTAB-Map, AprilTag, reference-image
comparison, and optical flow are classical computer-vision algorithms.

## Current hardware boundary

The physical stack requires a measured `nav_msgs/Odometry` source on
`/wheel/odom`; timed PWM is not accepted as odometry. The autonomous demo
assumes that source has been installed and calibrated. Without it, the safety
gate remains stopped and only simulation or supervised teleoperation may run.

Two motors and two BTS7960 bridges are supported by `max-motors`. Each motor
needs four distinct BCM GPIO assignments. The shipped configuration uses `-1`
for every pin and therefore fails closed until a private hardware YAML is
provided. The driver caps duty at 25%, stops after 250 ms without `/cmd_vel`,
and disables both bridges on shutdown.

## Architecture

```text
camera ─┬─> RTAB-Map ─────────────┐
        ├─> AprilTag ─────────────┤
        └─> obstruction detector ─┤
                                  v
wheel odometry ────────────> safety gate
                                  v
web UI ─> mission state ─> waypoint controller ─> /cmd_vel
```

Only the local waypoint controller publishes velocity. Any stale camera,
odometry, localization, obstruction, or controller heartbeat; lost
localization; detected obstruction; or emergency stop forces a zero command.

## Implemented components

- `apps/robot/max_robot/core.py`: mission state machine and movement safety gate.
- `apps/robot/max_robot/navigation.py`: differential-drive waypoint follower.
- `apps/robot/max_robot/obstruction.py`: obstruction hysteresis, reference
  comparison, and optical-flow time-to-collision.
- `apps/robot/max_robot/web.py`: PIN-protected local control API and page.
- `apps/robot/max_robot/ros_node.py`: ROS integration, route execution, and
  zero-command watchdog.
- `apps/robot/max_robot/vision_node.py`: live obstruction node and reference-frame
  recorder.
- `apps/robot/launch/`: simulation, mapping, and localization/navigation launches.
- `apps/robot/models/` and `apps/robot/worlds/`: differential-drive robot and
  indoor Gazebo course.
- `apps/robot/config/`: RTAB-Map, AprilTag, Gazebo bridge, route, and safety thresholds.

## Development environment

Use Ubuntu 26.04, ROS 2 Lyrical, and Gazebo Jetty. Jetty is the supported
Gazebo pairing for Lyrical.

The ROS package lives in `apps/robot`. Install the packages required by
`apps/robot/package.xml`, then put this repository
inside a ROS workspace:

```bash
mkdir -p ~/max_ws/src
cd ~/max_ws/src
git clone <repository-url> max_robot
cd ..
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select max_robot
source install/setup.bash
```

Run the remaining package-local commands below from `apps/robot` in the cloned
repository unless a command says otherwise.

The pure core tests do not require ROS, Gazebo, or OpenCV:

```bash
python3 -m unittest discover -s tests -v
```

## Hardware-free workflow

### 1. Start the simulator

```bash
ros2 launch max_robot simulation.launch.py
```

The simulator publishes the virtual camera, camera calibration, wheel
odometry, TF, and clock. Ground truth stays inside Gazebo and must never be
connected to production navigation.

### 2. Build a visual map

```bash
ros2 launch max_robot mapping.launch.py database:=/tmp/max_rtabmap.db
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

Drive the outbound and return path slowly. Confirm that RTAB-Map produces
stable loop closures before using the database for navigation.

### 3. Record clear-route reference frames

Start the recorder:

```bash
ros2 run max_robot max-record-reference --ros-args \
  -p output_dir:="$PWD/references"
```

At each waypoint, request the corresponding index:

```bash
ros2 topic pub --once /route/waypoint_index std_msgs/msg/Int32 "{data: 0}"
```

Repeat for every index in `apps/robot/config/route.json`. Each request saves one
rectified frame as `apps/robot/references/<index>.png`. Missing frames cause the
obstruction node to stop, not continue blindly.

### 4. Run localization and route control

Set a non-default operator PIN and start the stack:

```bash
export MAX_OPERATOR_PIN=change-me
ros2 launch max_robot navigation.launch.py \
  database:=/tmp/max_rtabmap.db \
  reference_dir:="$PWD/references"
```

On Raspberry Pi 5 with Camera Module 3, use Ubuntu 26.04 arm64 and ROS 2
Lyrical, verify `rpicam-hello --list-cameras` reports `imx708`, install
`camera_ros` with Raspberry Pi's libcamera fork, calibrate the mounted camera,
then launch the physical stack with a private motor configuration:

```bash
ros2 launch max_robot hardware.launch.py \
  database:=/tmp/max_rtabmap.db \
  reference_dir:="$PWD/references" \
  motor_config:=/path/to/private-motors.yaml
```

Do the first motor-direction test with the wheels raised. Autonomous start is
still rejected until measured `/wheel/odom`, localization, camera, obstruction,
and controller heartbeats are healthy.

With the physical stack running, verify the minimum camera/odometry contract:

```bash
ros2 run max_robot max-hardware-check --seconds 30
```

It exits non-zero unless the rectified camera sustains at least 15 fps, camera
intrinsics are calibrated, and measured wheel odometry is present.

Open `http://<workstation-ip>:8080` from the phone on the same trusted local
network. The prototype UI does not provide TLS. Start is rejected until
camera, odometry, localization, obstruction, and controller heartbeats are
healthy.

### 5. Test obstructions

Move `movable_obstruction` into the taught path using the Gazebo UI. Verify:

- the first suspicious frame removes movement permission;
- three suspicious frames produce `STOPPED`;
- the detector requires five clear seconds;
- the mission remains stopped until the operator presses Resume;
- failed image alignment or too few optical-flow tracks also stops the robot.

## Automated verification

### Core behavior

The standard-library test suite covers:

- complete outbound, pickup, and return transitions;
- stale heartbeat rejection;
- obstruction stop and guarded resume;
- emergency-stop behavior;
- waypoint completion and turn-in-place behavior;
- obstruction confirmation and clear timing;
- web PIN validation and unauthenticated emergency stop.

### Simulator scenarios

Record ROS bags for these fixed regressions:

1. Clear pickup-and-return route.
2. Box in route.
3. Low-texture localization loss.
4. Wrong or missing AprilTag.
5. Camera timeout.
6. Encoder timeout.

Score the estimated pose against Gazebo ground truth only in the test harness:

- median checkpoint error no more than `0.15 m`;
- maximum accepted checkpoint error `0.30 m`;
- ten of ten clean simulated missions complete;
- nine of ten complete with camera and encoder noise;
- stop command appears within `250 ms` of a safety fault;
- at least 95% of staged opaque obstructions are detected;
- no collisions in 30 staged approaches at `0.15 m/s`;
- fewer than one false stop per clear route.

Phone or webcam videos may exercise the obstruction detector before the
Camera Module 3 arrives. They validate logic, not final thresholds.

## Required physical validation

Simulation cannot validate:

- Camera Module 3 intrinsics, autofocus lock, exposure, rolling shutter, glare,
  vibration, or real frame timing;
- real wheel radius, axle separation, encoder noise, slip, motor dead zone, or
  braking distance;
- Pi 5 frame rate, memory, temperature, or thermal throttling;
- physical emergency-stop wiring;
- real obstruction thresholds and stopping distance.

When hardware arrives:

1. Calibrate the camera at `640x480`.
2. Lock focus and exposure after startup.
3. Add and validate a measured odometry source; wheel encoders are recommended.
4. Calibrate wheel radius and axle separation.
5. Validate motor direction with wheels raised.
6. Start at `0.05 m/s`.
7. Rebuild the map and reference images.
8. Recalibrate obstruction thresholds.
9. Repeat 30 supervised obstruction approaches.
10. Measure stop latency and stopping distance.
11. Complete ten supervised pickup-and-return missions.

Do not raise speed, remove supervision, or claim general collision avoidance
until a depth camera or lidar is added.
