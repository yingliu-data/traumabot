# Joy-Car Controller

Web-based keyboard + trajectory controller for the Joy-It Joy-Car robot.
Control the car from your browser with arrow keys, a live webcam feed,
speed control, autonomous Go-To navigation, and human-detection safety stop.

```
Laptop (browser)  ──SSH tunnel──▶  Raspberry Pi 5  ──USB serial──▶  PICO:ED (CircuitPython)
                                         │                                    │
                                   webcam MJPEG +                    encoder tick telemetry
                                   MediaPipe pose detection
```

---

## Hardware

| Component | Detail |
|-----------|--------|
| Robot | Joy-It Joy-Car |
| Controller | ELECFREAKS PICO:ED (RP2040, CircuitPython 9.x) |
| Server | Raspberry Pi 5 (8 GB), Raspberry Pi OS Bookworm 64-bit |
| USB serial | `/dev/ttyACM0` on Pi (auto-detected; `/dev/cu.usbmodem*` on Mac) |
| Camera | USB webcam connected to the Pi (index 0) |
| Encoders | Optical speed sensors on P14 (left) and P15 (right) |

---

## Quick Start

### Run on Raspberry Pi 5

**Step 1 — Deploy files from your Mac:**
```bash
chmod +x scripts/deploy_pi.sh
./scripts/deploy_pi.sh pi@raspberrypi.local
```

**Step 2 — First-time Pi setup** (SSH in, run once):
```bash
ssh pi@raspberrypi.local

sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev \
                   libatlas-base-dev libopenblas-dev

# Grant serial + camera access (log out and back in after this)
sudo usermod -aG dialout,video $USER
exit && ssh pi@raspberrypi.local

cd ~/joyit
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 3 — Upload firmware to the robot** (from Pi, PICO:ED plugged in):
```bash
cd ~/joyit && source .venv/bin/activate
./scripts/upload.sh
```

**Step 4 — Start the server on the Pi:**
```bash
python server.py
```
On first run it downloads the MediaPipe pose model (~5 MB). The server prints:
```
 * Running on http://0.0.0.0:8080
```

**Step 5 — Open SSH tunnel on your Mac** (keep this terminal open):
```bash
ssh -L 8080:localhost:8080 pi@raspberrypi.local
```

**Step 6 — Open in browser on your Mac:**
```
http://127.0.0.1:8080
```

---

### Run locally on Mac (development)

```bash
cd joyit
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/upload.sh   # deploy firmware (PICO:ED plugged into Mac)
python server.py
```

Open **http://127.0.0.1:8080** in your browser.

---

## Controls

| Input | Action |
|-------|--------|
| Arrow keys / WASD | Drive (hold to keep moving) |
| Space | Stop |
| Keys 1–9 | Set speed (slow → fast) |
| Speed slider | Fine-tune PWM speed (40–180) |
| Go To form | Enter X, Y in cm → autonomous navigation |
| STOP ALL button | Immediately halt and cancel navigation |
| Reset button | Zero the odometry position |

### Human Detection

When the camera detects a person, a red banner appears and all robot movement is immediately paused. Movement resumes automatically once no person is visible.

---

## Configuration

All tuneable values are in **`config.py`**:

```python
# Serial port is auto-detected (macOS: /dev/cu.usbmodem*, Linux: /dev/ttyACM*)
TICKS_PER_REV  = 40     # encoder: 20-slot disc × 2 edges
WHEEL_DIAM_MM  = 65     # measure your wheel
TRACK_WIDTH_MM = 160    # axle-to-axle distance
DEFAULT_SPEED  = 120    # PWM 0–180
CAMERA_INDEX   = 0      # OpenCV camera device index
SERVER_PORT    = 8080
```

---

## Calibration

Dead-reckoning accuracy depends on two constants.

### 1. Distance calibration (`WHEEL_DIAM_MM`)

1. Mark the robot's start position on the floor.
2. Drive forward exactly **100 cm**, then stop.
3. In the browser, read the displayed X value.
4. Adjust `WHEEL_DIAM_MM` until the reading matches 100 cm.
   - Reading too small → increase `WHEEL_DIAM_MM`
   - Reading too large → decrease `WHEEL_DIAM_MM`

### 2. Turning calibration (`TRACK_WIDTH_MM`)

1. Click **Reset** to zero the pose.
2. Drive a full 360° spin (hold left/right arrow).
3. The heading display should return to 0°.
4. Adjust `TRACK_WIDTH_MM` until it does:
   - Heading overshoots 360° → increase `TRACK_WIDTH_MM`
   - Heading undershoots 360° → decrease `TRACK_WIDTH_MM`

---

## Re-deploying after code changes

```bash
# On your Mac — sync updated files to Pi
./scripts/deploy_pi.sh

# On the Pi — restart server
pkill -f server.py
cd ~/joyit && source .venv/bin/activate && python server.py
```

---

## Architecture

See [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for a full breakdown.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `CIRCUITPY not mounted` | Connect USB cable; turn on battery pack |
| `SerialException: [Errno 16] Resource busy` | Close any other app using the serial port (e.g. mpremote REPL) |
| `No such file or directory: /dev/ttyACM0` | PICO:ED not plugged in, or wrong index — check `ls /dev/ttyACM*` |
| Camera shows "No camera" | Check `CAMERA_INDEX` in `config.py` (try 0, 1, 2); ensure user is in `video` group |
| Robot moves but odometry stays at 0 | Encoder wiring issue — check P14/P15 connections |
| Robot doesn't move | Battery pack off, or firmware not uploaded (`./scripts/upload.sh`) |
| Arrow keys not working in browser | Click anywhere on the page first to give it keyboard focus |
| SSH tunnel drops | Re-run `ssh -L 8080:localhost:8080 pi@raspberrypi.local` |
| `mediapipe` install fails on Pi | Ensure you're using 64-bit Pi OS and Python 3.9+ |
