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
  --exclude='efficientdet_lite2.tflite' \
  "${PROJECT_ROOT}/" "${DEST}:~/joyit/"

echo "Setting up autostart service..."
ssh "${DEST}" bash << 'REMOTE'
set -e
# Install systemd service
sudo cp ~/joyit/scripts/joyit.service /etc/systemd/system/joyit.service
sudo systemctl daemon-reload
sudo systemctl enable joyit
sudo systemctl restart joyit
echo "Service status:"
sudo systemctl status joyit --no-pager
REMOTE

echo ""
echo "Done! Server is running and will auto-start on boot."
echo ""
echo "Useful commands on the Pi:"
echo "  sudo systemctl status joyit   # check status"
echo "  sudo journalctl -u joyit -f   # live logs"
echo "  sudo systemctl restart joyit  # restart"
echo ""
echo "Access from your Mac:"
echo "  http://raspberrypi.local:8080"
