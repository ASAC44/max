#!/bin/sh
set -eu

mode=${1:-teleop}
if [ "$mode" != teleop ] && [ "$mode" != autonomous ]; then
  echo "usage: $0 [teleop|autonomous]" >&2
  exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "run this installer with sudo" >&2
  exit 1
fi
if [ ! -f /tmp/max-robot-agent.env ]; then
  echo "/tmp/max-robot-agent.env is required" >&2
  exit 1
fi
if [ ! -d /tmp/max-robot-source/apps/robot ]; then
  echo "/tmp/max-robot-source/apps/robot is required" >&2
  exit 1
fi
if [ "$mode" = autonomous ] && ! grep -qx 'MAX_ROBOT_DRY_RUN=false' /tmp/max-robot-agent.env; then
  echo "autonomous mode requires MAX_ROBOT_DRY_RUN=false" >&2
  exit 1
fi
if [ "$mode" = autonomous ]; then
  test -x /opt/ros/lyrical/bin/ros2 || {
    echo "ROS 2 Lyrical must be installed before autonomous mode" >&2
    exit 1
  }
fi

apt-get update
apt-get install -y python3-venv python3-evdev python3-lgpio kmod ffmpeg pipewire-bin
getent group input >/dev/null || groupadd --system input
usermod -a -G input,dialout pi
printf '%s\n' uinput >/etc/modules-load.d/max-uinput.conf
printf '%s\n' 'KERNEL=="uinput", MODE="0660", GROUP="input"' >/etc/udev/rules.d/90-max-uinput.rules
modprobe uinput
udevadm control --reload-rules
udevadm trigger --name-match=uinput
install -d -m 0755 /opt/max-robot
python3 -m venv --system-site-packages /opt/max-robot/venv
/opt/max-robot/venv/bin/pip install --no-cache-dir /tmp/max-robot-source/apps/robot

install -d -m 0750 /etc/max-robot
install -m 0600 /tmp/max-robot-agent.env /etc/max-robot/agent.env
install -m 0644 \
  /tmp/max-robot-source/apps/robot/systemd/max-robot-agent.service \
  /etc/systemd/system/max-robot-agent.service
install -m 0644 \
  /tmp/max-robot-source/apps/robot/systemd/max-teleop-agent.service \
  /etc/systemd/system/max-teleop-agent.service
install -m 0644 \
  /tmp/max-robot-source/apps/robot/systemd/max-drive-controller.service \
  /etc/systemd/system/max-drive-controller.service
if [ "$mode" = autonomous ]; then
  install -m 0644 \
    /tmp/max-robot-source/apps/robot/systemd/max-navigation.service \
    /etc/systemd/system/max-navigation.service
fi

systemctl disable --now max-robot-bridge.service 2>/dev/null || true
systemctl disable --now max-robot-poller.service 2>/dev/null || true
if [ -d /run/user/1000 ]; then
  su -s /bin/sh pi -c \
    'XDG_RUNTIME_DIR=/run/user/1000 systemctl --user disable --now prava-drive.service max-robot-bridge.service' \
    2>/dev/null || true
fi
systemctl daemon-reload
if [ "$mode" = autonomous ]; then
  systemctl disable --now max-teleop-agent.service max-drive-controller.service 2>/dev/null || true
  systemctl enable --now max-navigation.service
  systemctl enable --now max-robot-agent.service
else
  systemctl disable --now max-navigation.service 2>/dev/null || true
  systemctl enable --now max-robot-agent.service
  systemctl enable --now max-teleop-agent.service
  systemctl enable --now max-drive-controller.service
fi
systemctl --no-pager --full status max-robot-agent.service
if [ "$mode" = autonomous ]; then
  systemctl --no-pager --full status max-navigation.service
else
  systemctl --no-pager --full status max-teleop-agent.service
  systemctl --no-pager --full status max-drive-controller.service
fi
