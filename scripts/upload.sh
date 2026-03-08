#!/bin/bash
# Deploy device/code.py to the Joy-Car (copies to CIRCUITPY volume, auto-reloads).
# Usage: ./scripts/upload.sh

set -e

CIRCUITPY="/Volumes/CIRCUITPY"
SRC="$(dirname "$0")/../device/code.py"

if [ ! -d "$CIRCUITPY" ]; then
  echo "Error: CIRCUITPY not mounted. Connect the Joy-Car via USB."
  exit 1
fi

echo "Uploading device/code.py..."
python3 -c "import shutil; shutil.copy('$SRC', '$CIRCUITPY/code.py')"
echo "Done. Device is reloading..."
echo ""
echo "Wait 3 seconds, then run:  python server.py"
