"""
Heading-based waypoint navigator for the Joy-Car.

Algorithm (runs in a background thread at 10 Hz):
  1. Compute distance and angle to the next waypoint.
  2. If within STOP_RADIUS_CM: waypoint reached — pop and continue.
  3. If heading error > HEADING_THRESH_DEG: turn in place (no forward movement).
  4. Otherwise: drive forward at a speed proportional to distance (clamped to
     MIN_SPEED–MAX_SPEED).  This gives smooth deceleration as the robot approaches.
"""

import math
import threading
import time
import config


class Navigator:
    def __init__(self, serial_link, odometry):
        self._link  = serial_link
        self._odom  = odometry
        self._queue = []          # list of (x_cm, y_cm)
        self._lock  = threading.Lock()
        self._running = True

        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def go_to(self, x_cm: float, y_cm: float) -> None:
        with self._lock:
            self._queue.append((x_cm, y_cm))

    def stop(self) -> None:
        with self._lock:
            self._queue.clear()
        self._link.send(b' ')

    def is_busy(self) -> bool:
        with self._lock:
            return len(self._queue) > 0

    def shutdown(self) -> None:
        self._running = False
        self.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                target = self._queue[0] if self._queue else None

            if target is None:
                time.sleep(0.1)
                continue

            pose = self._odom.pose()
            tx, ty = target
            dx = tx - pose['x']
            dy = ty - pose['y']
            dist = math.sqrt(dx * dx + dy * dy)

            if dist < config.STOP_RADIUS_CM:
                self._link.send(b' ')
                with self._lock:
                    if self._queue:
                        self._queue.pop(0)
                time.sleep(0.1)
                continue

            target_angle_deg = math.degrees(math.atan2(dy, dx))
            heading_error = target_angle_deg - pose['theta']

            # Normalise to [-180, 180]
            while heading_error >  180: heading_error -= 360
            while heading_error < -180: heading_error += 360

            if abs(heading_error) > config.HEADING_THRESH_DEG:
                # Turn in place
                cmd = b'd' if heading_error > 0 else b'a'
                turn_speed = config.MIN_SPEED
                self._link.set_speed(turn_speed)
                self._link.send(cmd)
            else:
                # Drive forward — decelerate as we approach
                speed = int(config.MIN_SPEED + (config.MAX_SPEED - config.MIN_SPEED) *
                            min(1.0, dist / 50.0))
                self._link.set_speed(speed)
                self._link.send(b'w')

            time.sleep(0.1)
