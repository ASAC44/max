# Physical autonomous robot demo

This path assumes measured `nav_msgs/Odometry` is already published on
`/wheel/odom`. Autonomous motion remains fail-closed until the camera,
odometry, localization, obstruction detector, controller, motors, and
normally-closed emergency stop all report healthy.

## Commission the route

Install ROS 2 Lyrical and the dependencies in `apps/robot/package.xml`, build
the package, and source the workspace. Copy a private motor configuration from
`apps/robot/config/max.yaml`; configure eight distinct BTS7960 pins and the
`max_estop.gpio` input.

With wheels raised, validate motor polarity and the emergency stop. Build the
map by starting sensor-only mapping mode and slowly pushing the unpowered robot
along the route so measured encoder odometry remains available:

```bash
ros2 launch max_robot hardware.launch.py \
  database:=/var/lib/max-robot/navigation/max_rtabmap.db \
  motor_config:=/etc/max-robot/motors.yaml \
  mapping:=true

```

In a second terminal, start the recorder:

```bash
ros2 run max_robot max-record-reference --ros-args \
  -p output_dir:=/var/lib/max-robot/navigation/references
```

Publish waypoint indices `0` through `8` while the pushed robot is at the
matching positions. Place AprilTag `0` at home and AprilTag `2` at pickup.
Validate the finished artifacts and live inputs with the normal navigation
stack running:

```bash
sudo -u pi -E infra/pi/verify-navigation.sh
```

## Install autonomous services

Set the backend and Pi environment to `MAX_ROBOT_MODE=pi_poll` and
`MAX_ROBOT_DRY_RUN=false`. Configure `MAX_OPERATOR_PIN` identically for the
local controller and Pi agent, then install:

```bash
sudo /tmp/max-robot-source/infra/pi/install-agent.sh autonomous
```

`max-navigation.service` conflicts with the teleoperation services so only one
motor command path can run. Verify both services before placing wheels down:

```bash
sudo systemctl status max-navigation.service max-robot-agent.service
curl -H "Authorization: Bearer $MAX_ADMIN_TOKEN" \
  https://max.example.com/api/robot/v1/status
```

The dashboard must show `PHYSICAL AUTONOMOUS MOTION ENABLED` before dispatch.
At pickup, confirm the package through the local PIN-protected control page.
After an obstruction, remove it, wait five clear seconds, and press Resume.
Emergency-stop release is separate and never resumes motion automatically.

## Acceptance

- Camera calibration and at least 15 fps pass `max-hardware-check`.
- Odometry scale and direction match measured travel.
- Ten supervised pickup-and-return runs complete.
- Thirty obstruction approaches stop without collision.
- Stop commands appear within 250 ms of safety faults.
- Network loss, localization loss, and emergency stop never advance lifecycle.
