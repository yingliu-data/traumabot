"""
Dead-reckoning odometry for a differential-drive robot.

Uses cumulative encoder tick counts from SerialLink to estimate
the robot's pose (x, y, heading) relative to its start position.

Calibration constants live in config.py:
  TICKS_PER_REV  = 40    (both edges, 20-slot disc — confirmed from enkoder.py)
  WHEEL_DIAM_MM  = 65
  TRACK_WIDTH_MM = 160
"""

import math
import threading
import config


class Odometry:
    def __init__(self):
        self._lock = threading.Lock()
        self._dist_per_tick = (math.pi * config.WHEEL_DIAM_MM) / config.TICKS_PER_REV  # mm
        self._track_mm = config.TRACK_WIDTH_MM

        # State
        self._x   = 0.0   # mm
        self._y   = 0.0   # mm
        self._theta = 0.0  # radians, 0 = initial forward direction

        self._prev_left  = 0
        self._prev_right = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, left_ticks: int, right_ticks: int) -> None:
        """Call with the latest cumulative tick counts from the device."""
        dl = (left_ticks  - self._prev_left)  * self._dist_per_tick  # mm
        dr = (right_ticks - self._prev_right) * self._dist_per_tick  # mm
        self._prev_left  = left_ticks
        self._prev_right = right_ticks

        d_center = (dl + dr) / 2.0
        d_theta  = (dr - dl) / self._track_mm  # radians

        with self._lock:
            self._theta += d_theta
            self._x += d_center * math.cos(self._theta)
            self._y += d_center * math.sin(self._theta)

    def pose(self) -> dict:
        """Return current pose: x_cm, y_cm, theta_deg."""
        with self._lock:
            return {
                'x':     round(self._x / 10.0, 1),          # cm
                'y':     round(self._y / 10.0, 1),          # cm
                'theta': round(math.degrees(self._theta), 1),
            }

    def push_delta(self, dist_mm: float, d_theta_rad: float) -> None:
        """Inject a motion delta directly — used for time-based dead reckoning
        when encoder ticks are not available."""
        with self._lock:
            self._theta += d_theta_rad
            self._x += dist_mm * math.cos(self._theta)
            self._y += dist_mm * math.sin(self._theta)

    def reset(self, left_baseline: int = 0, right_baseline: int = 0) -> None:
        """Zero the pose.  Pass the device's current tick counts so the first
        update after reset computes a delta of zero instead of a large jump."""
        with self._lock:
            self._x = self._y = self._theta = 0.0
            self._prev_left  = left_baseline
            self._prev_right = right_baseline
