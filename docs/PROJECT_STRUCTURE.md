# Project Structure

## File Map

```
joyit/
├── device/
│   └── code.py              CircuitPython firmware — runs on the PICO:ED
├── joycar/                  Host Python package (runs on Raspberry Pi)
│   ├── __init__.py          Package exports (SerialLink, Odometry, Navigator)
│   ├── serial_link.py       Thread-safe serial interface + background reader
│   ├── odometry.py          Dead-reckoning pose estimation
│   └── navigator.py         Autonomous waypoint follower
├── web/
│   ├── templates/
│   │   └── index.html       Browser UI layout
│   └── static/
│       ├── style.css        Dark theme stylesheet
│       └── app.js           WebSocket client, d-pad, canvas trail
├── scripts/
│   ├── deploy_pi.sh         Rsync project to Pi + install/restart systemd service
│   ├── joyit.service        systemd unit file (auto-start on boot)
│   ├── upload.sh            Deploy firmware to /Volumes/CIRCUITPY/
│   └── repl.sh              Open interactive REPL via mpremote
├── docs/
│   └── PROJECT_STRUCTURE.md  This file
├── server.py                Flask + WebSocket + MJPEG + MediaPipe entry point
├── config.py                All tuneable constants
├── requirements.txt         Python dependencies
└── README.md                Setup and usage guide
```

---

## Deployment

The project runs on **Raspberry Pi 5** with Python 3.12 via Miniforge:
- Environment: `~/miniforge3/envs/joyit`
- Service: `/etc/systemd/system/joyit.service` (auto-start on boot)
- Deploy command (from Mac): `./scripts/deploy_pi.sh sota@<PI_IP>`

Access via SSH tunnel: `ssh -L 8080:localhost:8080 sota@<PI_IP>` → `http://localhost:8080`

---

## Data Flow

```
Browser (arrow keys / Go To form)
        │  WebSocket JSON {"type":"key"/"speed"/"goto"}
        ▼
server.py  (Flask + flask-sock)
        │  bytes: b'w' / b'a' / b'S120\n' ...
        ▼
joycar/serial_link.py  (pyserial, background read thread)
        │  USB serial (115200 baud)
        ▼
device/code.py  (CircuitPython on PICO:ED)
        │  drives motors via I2C motor controller (0x70)
        │  drives NeoPixels via P0
        │  reads encoders on P14 / P15
        │
        │  every 100ms prints: E:{left},{right}\n
        ▼
joycar/serial_link.py  (background thread parses telemetry)
        ▼
joycar/odometry.py  (differential drive dead reckoning)
        ▼
server.py  (WebSocket push: {"type":"pose","x":…,"y":…,"theta":…})
        ▼
Browser  (canvas trail + telemetry display)
```

Camera + human detection (separate path):
```
USB webcam
  → cv2.VideoCapture
  → MediaPipe PoseLandmarker (every 3rd frame)
      → bounding box + landmark dots drawn on frame
      → human flag → stops robot on rising edge
  → MJPEG /video_feed route
  → <img> in browser
```

---

## Serial Protocol

### Pi → Device

| Bytes | Meaning |
|-------|---------|
| `w` | Drive forward |
| `s` | Drive backward |
| `a` | Turn left |
| `d` | Turn right |
| ` ` (space) | Stop |
| `S{nnn}\n` | Set speed (0–180 PWM), e.g. `S120\n` |
| `\x03` | Ctrl+C — interrupt running code (sent on connect) |
| `\x04` | Ctrl+D — soft reset, relaunch code.py (sent on connect) |

### Device → Pi

| Format | Meaning |
|--------|---------|
| `E:{left},{right}\n` | Cumulative encoder ticks, sent every 100 ms |

---

## Odometry Math

The robot is a **differential drive**: two independently driven wheels, separated by `TRACK_WIDTH_MM`.

Encoders produce **40 ticks per wheel revolution** (20-slot optical disc, both edges counted).

Each tick corresponds to:
```
dist_per_tick = π × WHEEL_DIAM_MM / TICKS_PER_REV  ≈ 5.1 mm
```

At each update step, given `dl` and `dr` (new ticks × dist_per_tick for left/right):
```
d_center = (dl + dr) / 2          # distance travelled by midpoint
d_theta  = (dr - dl) / TRACK_WIDTH  # change in heading (radians)

theta += d_theta
x     += d_center × cos(theta)
y     += d_center × sin(theta)
```

The pose is stored in mm internally and exposed in cm via `Odometry.pose()`.

---

## Navigator Algorithm

`Navigator` runs a background thread at 10 Hz. For each waypoint `(tx, ty)`:

1. **Check arrival**: if `dist < STOP_RADIUS_CM` → stop, pop waypoint.
2. **Compute heading error**: `target_angle = atan2(ty - y, tx - x)`, then `error = target_angle - theta`, normalised to `[-180°, 180°]`.
3. **Turn phase**: if `|error| > HEADING_THRESH_DEG` → send turn command at `MIN_SPEED`.
4. **Drive phase**: send forward command; speed = `MIN_SPEED + (MAX_SPEED - MIN_SPEED) × min(1, dist / 50cm)` — decelerates in the last 50 cm.

---

## Human Detection

MediaPipe `PoseLandmarkerOptions` runs in `VIDEO` mode on every 3rd frame to limit CPU usage.

When a person is detected:
- A **bounding box** is drawn around each person (min/max of landmark coordinates ± 10 px padding) with a "Person" label
- Green **landmark dots** are drawn at each body keypoint
- On the **rising edge** (first frame a person appears): robot stops, navigator cancelled, active keys cleared
- All movement commands are blocked while a person is in frame

---

## How to Extend

### Add a sensor readout (e.g. ultrasonic distance)
1. Add reading code in `device/code.py` (e.g. `print(f"U:{dist_cm}")` every 500ms).
2. In `joycar/serial_link.py → _parse_line()`, add an `elif line.startswith('U:'):` branch.
3. Expose a `get_distance()` method on `SerialLink`.
4. Forward to browser via the WebSocket telemetry push in `server.py`.

### Add servo control
1. In `device/code.py`, handle a new command `V{angle}\n` using `pwmio`.
2. Add a `set_servo(angle)` method to `SerialLink`.
3. Add a slider in `index.html` and a `ws.send({"type":"servo",…})` call in `app.js`.
4. Handle `mtype == 'servo'` in the `ws_handler` in `server.py`.
