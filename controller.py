"""
Joy-Car keyboard controller.
Run on Mac after uploading code.py to the device.

  Arrow keys: drive
  Space:      stop
  Q:          quit
"""

import curses
import serial
import time
import sys

PORT = '/dev/cu.usbmodem21101'
BAUD = 115200
SEND_INTERVAL = 0.08      # Re-send command every 80ms while key held
KEY_RELEASE_TIMEOUT = 0.15  # Stop after 150ms of no key events (> OS repeat interval)

KEY_MAP = {
    curses.KEY_UP:    (b'w', 'FORWARD  '),
    curses.KEY_DOWN:  (b's', 'BACKWARD '),
    curses.KEY_LEFT:  (b'a', 'LEFT     '),
    curses.KEY_RIGHT: (b'd', 'RIGHT    '),
    ord(' '):         (b' ', 'STOP     '),
}

def draw_ui(win):
    win.clear()
    win.addstr(0, 0, "=== Joy-Car Controller ===")
    win.addstr(1, 0, "UP    Forward")
    win.addstr(2, 0, "DOWN  Backward")
    win.addstr(3, 0, "LEFT  Turn left")
    win.addstr(4, 0, "RIGHT Turn right")
    win.addstr(5, 0, "SPC   Stop")
    win.addstr(6, 0, "Q     Quit")
    win.addstr(7, 0, "-" * 26)

def main(stdscr):
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.05)
    except serial.SerialException as e:
        stdscr.addstr(0, 0, f"Error: {e}")
        stdscr.addstr(1, 0, "Press any key to exit.")
        stdscr.getch()
        return

    # Interrupt any running code (Ctrl+C), then soft-reset (Ctrl+D) to restart code.py
    ser.write(b'\x03')  # Ctrl+C
    time.sleep(0.3)
    ser.write(b'\x04')  # Ctrl+D — soft reset, relaunches code.py
    ser.reset_input_buffer()

    curses.cbreak()
    curses.noecho()
    stdscr.keypad(True)
    stdscr.nodelay(True)
    curses.curs_set(0)

    draw_ui(stdscr)
    stdscr.addstr(8, 0, f"Port: {PORT}")
    stdscr.addstr(9, 0, "Status: Booting...        ")
    stdscr.refresh()

    time.sleep(3.0)  # Wait for code.py to fully start

    stdscr.addstr(9, 0, "Status: READY             ")
    stdscr.refresh()

    current_cmd = None
    last_send = 0.0
    last_key_time = 0.0

    try:
        while True:
            key = stdscr.getch()
            now = time.time()

            if key == ord('q') or key == ord('Q'):
                ser.write(b' ')
                break

            if key in KEY_MAP:
                cmd, label = KEY_MAP[key]
                last_key_time = now
                if cmd != current_cmd:
                    current_cmd = cmd
                    ser.write(cmd)
                    last_send = now
                    stdscr.addstr(9, 0, f"Status: {label}")
                    stdscr.refresh()
            elif current_cmd is not None and (now - last_key_time) > KEY_RELEASE_TIMEOUT:
                # No key event for 150ms — key released, stop
                ser.write(b' ')
                current_cmd = None
                last_send = 0.0
                stdscr.addstr(9, 0, "Status: STOP             ")
                stdscr.refresh()

            # Re-send while key held (keeps device's watchdog alive)
            if current_cmd is not None and (now - last_send) >= SEND_INTERVAL:
                ser.write(current_cmd)
                last_send = now

            time.sleep(0.02)

    finally:
        ser.write(b' ')
        ser.close()

if __name__ == '__main__':
    curses.wrapper(main)
