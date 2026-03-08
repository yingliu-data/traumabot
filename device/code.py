"""
Joy-Car serial command receiver — runs on PICO:ED (CircuitPython).
Upload via:  ./scripts/upload.sh

Commands received from host (Mac):
  w         forward
  s         backward
  a         left turn
  d         right turn
  ' '       stop
  S{nnn}\n  set speed (0-180 PWM), e.g. b'S120\n'

Telemetry sent to host every 100ms:
  E:{left_ticks},{right_ticks}\n
"""

import sys
import supervisor
import digitalio
import board
from picoed import i2c
from time import sleep, monotonic_ns
from motor import Motor
from konstanty import Konstanty
from neopixel import NeoPixel
from board import P0

# -- Init motors --
if i2c.try_lock():
    i2c.writeto(0x70, b'\x00\x01')
    i2c.writeto(0x70, b'\xE8\xAA')
    i2c.unlock()

levy = Motor(Konstanty.levy)
pravy = Motor(Konstanty.pravy)

# Motors are mounted in reverse — swap directions to compensate
DOPREDU = Konstanty.dozadu
DOZADU  = Konstanty.dopredu

# -- Init NeoPixels --
pixels = NeoPixel(P0, 8, auto_write=True)

HEADLIGHTS  = (0, 3)
BRAKELIGHTS = (5, 6)
LEFT_IND    = (1, 4)
RIGHT_IND   = (2, 7)

WHITE  = (60, 60, 60)
RED    = (80, 0, 0)
ORANGE = (80, 30, 0)
OFF    = (0, 0, 0)

def set_leds(headlights=False, brake=False, left=False, right=False):
    for i in range(8):
        pixels[i] = OFF
    if headlights:
        for i in HEADLIGHTS:
            pixels[i] = WHITE
    if brake:
        for i in BRAKELIGHTS:
            pixels[i] = RED
    if left:
        for i in LEFT_IND:
            pixels[i] = ORANGE
    if right:
        for i in RIGHT_IND:
            pixels[i] = ORANGE

# -- Init encoders (P14=left, P15=right, count both edges) --
enc_left  = digitalio.DigitalInOut(board.P14)
enc_right = digitalio.DigitalInOut(board.P15)
enc_left.direction  = digitalio.Direction.INPUT
enc_right.direction = digitalio.Direction.INPUT

left_ticks  = 0
right_ticks = 0
prev_left   = enc_left.value
prev_right  = enc_right.value

# -- Motor state --
SPEED         = 120
TIMEOUT_NS    = 400_000_000   # 400ms: stop if no command received
TELEMETRY_NS  = 100_000_000   # 100ms between encoder reports

dir_l        = None
dir_r        = None
last_cmd_ns  = 0
last_telem_ns = 0

# Serial command buffer for multi-char speed commands (S{nnn}\n)
serial_buf = []

def stop_all():
    global dir_l, dir_r
    levy.zastav()
    pravy.zastav()
    dir_l = None
    dir_r = None
    set_leds()

def drive(new_l, new_r, led_kw):
    global dir_l, dir_r
    if new_l != dir_l or new_r != dir_r:
        levy.zastav()
        pravy.zastav()
        dir_l = new_l
        dir_r = new_r
    if new_l:
        levy.jed_pwm(new_l, SPEED)
    if new_r:
        pravy.jed_pwm(new_r, SPEED)
    set_leds(**led_kw)

print("Joy-Car ready. Waiting for commands...")

while True:
    now = monotonic_ns()

    # -- Update encoder tick counts (both edges) --
    cur_left  = enc_left.value
    cur_right = enc_right.value
    if cur_left != prev_left:
        left_ticks += 1
        prev_left = cur_left
    if cur_right != prev_right:
        right_ticks += 1
        prev_right = cur_right

    # -- Read serial input --
    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        last_cmd_ns = now

        if ch == '\n':
            # Process buffered multi-char command (e.g. "S120")
            line = ''.join(serial_buf)
            serial_buf.clear()
            if line.startswith('S'):
                try:
                    SPEED = max(0, min(180, int(line[1:])))
                except ValueError:
                    pass
        elif ch in ('w', 's', 'a', 'd', ' '):
            serial_buf.clear()  # discard any partial buffer
            if ch == 'w':
                drive(DOPREDU, DOPREDU, {"headlights": True})
            elif ch == 's':
                drive(DOZADU, DOZADU, {"brake": True})
            elif ch == 'a':
                drive(DOZADU, DOPREDU, {"left": True})
            elif ch == 'd':
                drive(DOPREDU, DOZADU, {"right": True})
            elif ch == ' ':
                stop_all()
        else:
            serial_buf.append(ch)

    # -- Safety: stop if no command for TIMEOUT_NS --
    if last_cmd_ns > 0 and (now - last_cmd_ns) > TIMEOUT_NS:
        stop_all()
        last_cmd_ns = 0

    # -- Encoder telemetry every 100ms --
    if (now - last_telem_ns) >= TELEMETRY_NS:
        print(f"E:{left_ticks},{right_ticks}")
        last_telem_ns = now

    sleep(0.005)  # 5ms loop — fast enough for encoder edge detection
