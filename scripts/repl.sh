#!/bin/bash
# Open an interactive MicroPython/CircuitPython REPL on the Joy-Car.
# Usage: ./scripts/repl.sh
# Exit with Ctrl+X

PORT="${JOYCAR_PORT:-/dev/cu.usbmodem21101}"
mpremote connect "$PORT" repl
