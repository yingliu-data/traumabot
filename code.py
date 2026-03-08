"""
Joy-Car serial command receiver.
Upload this to the device, then run controller.py on the Mac.

Commands (single char over USB serial):
  w = forward
  s = backward
  a = left
  d = right
  ' ' = stop
"""

import sys
import supervisor
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

# -- Motor state --
SPEED = 120
TIMEOUT_NS = 400_000_000  # 400ms: stop if no command received

dir_l = None
dir_r = None
last_cmd_ns = 0

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

print("Joy-Car ready. Waiting for commands (w/a/s/d/space)...")

while True:
    now = monotonic_ns()

    if supervisor.runtime.serial_bytes_available:
        cmd = sys.stdin.read(1)
        last_cmd_ns = now

        if cmd == 'w':
            drive(DOPREDU, DOPREDU, {"headlights": True})
        elif cmd == 's':
            drive(DOZADU, DOZADU, {"brake": True})
        elif cmd == 'a':
            drive(DOZADU, DOPREDU, {"left": True})
        elif cmd == 'd':
            drive(DOPREDU, DOZADU, {"right": True})
        elif cmd == ' ':
            stop_all()

    # Safety: stop if no command for TIMEOUT_NS
    if last_cmd_ns > 0 and (now - last_cmd_ns) > TIMEOUT_NS:
        stop_all()
        last_cmd_ns = 0

    sleep(0.01)
