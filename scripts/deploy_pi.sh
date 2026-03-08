#!/usr/bin/env bash
# Deploy project files to Raspberry Pi 5.
# Usage:  ./scripts/deploy_pi.sh [user@host]
#         ./scripts/deploy_pi.sh pi@192.168.1.42
# Default host: pi@raspberrypi.local

set -e

DEST=${1:-pi@raspberrypi.local}
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Syncing to ${DEST}:~/joyit/ ..."
rsync -avz \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='pose_landmarker_lite.task' \
  "${PROJECT_ROOT}/" "${DEST}:~/joyit/"

echo ""
echo "Done. On the Pi, run:"
echo "  cd ~/joyit && source .venv/bin/activate && python server.py"
echo ""
echo "Then on your Mac, open an SSH tunnel:"
echo "  ssh -L 8080:localhost:8080 ${DEST}"
echo "  Open: http://127.0.0.1:8080"
