"""
Thread-safe serial interface to the Joy-Car PICO:ED.

- Opens the serial port and soft-resets the device (Ctrl+C + Ctrl+D).
- Background daemon thread reads all incoming lines and parses encoder
  telemetry: E:{left_ticks},{right_ticks}\n
- Public API is fully thread-safe (Lock-protected writes).
"""

import threading
import time
import serial
import config


class SerialLink:
    def __init__(self, port: str = config.SERIAL_PORT, baud: int = config.BAUD_RATE):
        self._ser = serial.Serial(port, baud, timeout=0.1)
        self._lock = threading.Lock()
        self._ticks = (0, 0)          # (left, right) cumulative ticks from device
        self._connected = False

        self._reset_device()
        self._connected = True

        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, cmd: bytes) -> None:
        with self._lock:
            self._ser.write(cmd)

    def set_speed(self, pwm: int) -> None:
        pwm = max(0, min(180, pwm))
        with self._lock:
            self._ser.write(f'S{pwm}\n'.encode())

    def get_ticks(self) -> tuple:
        return self._ticks

    def close(self) -> None:
        self.send(b' ')  # stop motors
        self._ser.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reset_device(self) -> None:
        self._ser.write(b'\x03')   # Ctrl+C — interrupt running code
        time.sleep(0.3)
        self._ser.write(b'\x04')   # Ctrl+D — soft reset, relaunches code.py
        self._ser.reset_input_buffer()
        time.sleep(3.0)            # wait for code.py to boot

    def _reader(self) -> None:
        buf = b''
        while True:
            try:
                chunk = self._ser.read(64)
                if not chunk:
                    continue
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    self._parse_line(line.decode('ascii', errors='ignore').strip())
            except Exception:
                time.sleep(0.05)

    def _parse_line(self, line: str) -> None:
        if line.startswith('E:'):
            try:
                parts = line[2:].split(',')
                self._ticks = (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
