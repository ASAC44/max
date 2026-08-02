#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
output=${1:-/tmp/max-robot-agent-bundle.tar.gz}

COPYFILE_DISABLE=1 tar \
  --no-xattrs \
  --exclude='*/__pycache__' \
  --exclude='*/.pytest_cache' \
  --exclude='apps/robot/tests' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.DS_Store' \
  -C "$root" -czf "$output" \
  apps/robot \
  infra/pi/install-agent.sh \
  infra/pi/max-robot-agent.env.example

echo "$output"
