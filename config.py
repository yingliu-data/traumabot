"""
Central configuration for the Joy-Car controller.
Edit values here; all other modules import from this file.
"""

# --- Serial ---
import sys as _sys, glob as _glob

def _find_serial_port():
    if _sys.platform == 'darwin':
        candidates = _glob.glob('/dev/cu.usbmodem*')
    else:
        candidates = _glob.glob('/dev/ttyACM*') or _glob.glob('/dev/ttyUSB*')
    return candidates[0] if candidates else '/dev/ttyACM0'

SERIAL_PORT = _find_serial_port()
BAUD_RATE   = 115200

# --- Odometry (calibrate after build) ---
# TICKS_PER_REV: confirmed from enkoder.py (both edges, 20-slot disc = 40 ticks/rev)
TICKS_PER_REV  = 40
WHEEL_DIAM_MM  = 65     # measure your wheel; typical Joy-Car = ~65 mm
TRACK_WIDTH_MM = 160    # axle-to-axle distance; measure on your chassis

# --- Drive control ---
DEFAULT_SPEED  = 120    # PWM value sent on startup (0–180)
MIN_SPEED      = 40     # slowest speed used by navigator
MAX_SPEED      = 180    # fastest allowed PWM

# --- Navigator ---
STOP_RADIUS_CM    = 5   # declare waypoint reached when within this distance
HEADING_THRESH_DEG = 15  # turn in place if heading error exceeds this angle

# --- Web server ---
SERVER_HOST  = '0.0.0.0'
SERVER_PORT  = 8080
CAMERA_INDEX = 0        # OpenCV webcam device index (0 = first webcam)
MJPEG_QUALITY = 70      # JPEG quality for video stream (1–100)
