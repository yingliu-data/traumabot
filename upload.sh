#!/bin/bash
# Upload code.py to the Joy-Car (copies to CIRCUITPY volume, device auto-reloads).
# Usage: ./upload.sh

CIRCUITPY="/Volumes/CIRCUITPY"

if [ ! -d "$CIRCUITPY" ]; then
    echo "Error: CIRCUITPY not mounted. Make sure the Joy-Car is connected via USB."
    exit 1
fi

echo "Uploading code.py..."
python3 -c "import shutil; shutil.copy('code.py', '$CIRCUITPY/code.py')"
echo "Done! Device is reloading..."
echo ""
echo "Wait 2-3 seconds, then run:  python3 controller.py"
