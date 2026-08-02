#!/bin/sh
set -eu

env_file=${1:-/opt/max/.env}
web_origin=${2:-}

if [ -z "$web_origin" ]; then
  echo "usage: $0 ENV_FILE WEB_ORIGIN" >&2
  exit 2
fi
case "$web_origin" in
  http://*|https://*) ;;
  *)
    echo "WEB_ORIGIN must start with http:// or https://" >&2
    exit 2
    ;;
esac
if [ ! -f "$env_file" ]; then
  echo "$env_file does not exist" >&2
  exit 1
fi

temporary=$(mktemp "${env_file}.teleop.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM

awk -v origin="$web_origin" '
BEGIN {
  values["MAX_TELEOP_ENABLED"] = "true"
  values["MAX_TELEOP_DEADMAN_MS"] = "350"
  values["MAX_TELEOP_MAX_CLIENT_AGE_MS"] = "1000"
  values["MAX_TELEOP_CONTROLLER_IDLE_SECONDS"] = "6"
  values["MAX_TELEOP_AGENT_IDLE_SECONDS"] = "10"
  values["MAX_WEB_ORIGIN"] = origin
}
{
  separator = index($0, "=")
  key = separator > 0 ? substr($0, 1, separator - 1) : ""
  if (key in values) {
    print key "=" values[key]
    seen[key] = 1
    next
  }
  print
}
END {
  for (key in values) {
    if (!(key in seen)) {
      print key "=" values[key]
    }
  }
}
' "$env_file" >"$temporary"

mode=$(stat -c '%a' "$env_file" 2>/dev/null || stat -f '%Lp' "$env_file")
owner=$(stat -c '%u:%g' "$env_file" 2>/dev/null || stat -f '%u:%g' "$env_file")
chmod "$mode" "$temporary"
chown "$owner" "$temporary"
mv "$temporary" "$env_file"

echo "teleoperation environment enabled; emergency-stop state remains independently latched"
