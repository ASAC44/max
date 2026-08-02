#!/bin/sh
set -eu

. /opt/ros/lyrical/setup.sh
AMENT_PREFIX_PATH=/opt/max-robot/venv:${AMENT_PREFIX_PATH:-}
export AMENT_PREFIX_PATH

database=${MAX_NAVIGATION_DATABASE:-/var/lib/max-robot/navigation/max_rtabmap.db}
references=${MAX_NAVIGATION_REFERENCE_DIR:-/var/lib/max-robot/navigation/references}
motors=${MAX_NAVIGATION_MOTOR_CONFIG:-/etc/max-robot/motors.yaml}

test -s "$database" || { echo "missing RTAB-Map database: $database" >&2; exit 1; }
test -s "$motors" || { echo "missing motor/emergency-stop config: $motors" >&2; exit 1; }
for index in 0 1 2 3 4 5 6 7 8; do
  test -s "$references/$index.png" || {
    echo "missing obstruction reference: $references/$index.png" >&2
    exit 1
  }
done

exec ros2 run max_robot max-hardware-check --seconds 30
