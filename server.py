"""
Joy-Car web controller — Flask + WebSocket + MJPEG camera stream.
Run with:  python server.py
Then open: http://localhost:5000
"""

import time
import json
import os
from datetime import datetime

os.makedirs("logs", exist_ok=True)
run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"logs/robot_log_{run_timestamp}.jsonl"

log_file = open(log_filename, "a")
print(f"Logging to {log_filename}")


import threading
import json
import cv2
import mediapipe as mp
from flask import Flask, render_template, Response, request, jsonify
from flask_sock import Sock

import config
from joycar import SerialLink, Odometry, Navigator

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
sock = Sock(app)

# ---------------------------------------------------------------------------
# Hardware init (deferred so import works without device connected)
# ---------------------------------------------------------------------------
link: SerialLink = None
odom: Odometry   = None
nav:  Navigator  = None
_current_speed   = config.DEFAULT_SPEED

_last_command = None
_command_lock = threading.Lock()

# Last byte sent over serial — tracked for time-based odometry fallback
_last_serial_cmd      = None
_last_serial_cmd_lock = threading.Lock()

points = []

def _init_hardware():
    global link, odom, nav, _current_speed
    try:
        print(f"[hw] Opening serial port {config.SERIAL_PORT} ...")
        link = SerialLink()
        # Monkey-patch link.send() so every command is visible to the odom updater
        _orig_send = link.send
        def _tracked_send(b):
            global _last_serial_cmd
            _orig_send(b)
            with _last_serial_cmd_lock:
                _last_serial_cmd = b
        link.send = _tracked_send
        print(f"[hw] Serial OK. Initialising odometry + navigator ...")
        odom = Odometry()
        nav  = Navigator(link, odom)
        _current_speed = config.DEFAULT_SPEED
        link.set_speed(_current_speed)
        print(f"[hw] Hardware ready. Speed={_current_speed}")
        # Encoder polling thread: update odometry from device ticks
        threading.Thread(target=_odom_updater, daemon=True).start()
        # Command repeater: re-send active drive command every 150ms so the
        # device's 400ms safety timeout never fires while a key is held
        threading.Thread(target=_cmd_repeater, daemon=True).start()
    except Exception as e:
        print(f"[hw] WARNING: Hardware not available ({e}). Running in web-only mode.")
        link = odom = nav = None

def _odom_updater():
    import time

    global log_filename
    last_log_time   = 0
    last_ticks      = (0, 0)
    last_status_t   = 0   # for periodic heartbeat every 5 s
    encoder_online  = False  # flips True the first time ticks actually change

    print("[odom] updater thread started")

    while True:
        try:
            now = time.time()

            if not link or not odom:
                # Print once every 5 s so it's clear hardware is missing
                if now - last_status_t >= 5:
                    print("[odom] WARNING: link or odom is None — hardware not connected")
                    last_status_t = now
                time.sleep(0.5)
                continue

            ticks = link.get_ticks()
            odom.update(*ticks)

            # Always print status every 5 s so you can see the thread is alive
            if now - last_status_t >= 5:
                mode = 'encoder' if encoder_online else 'TIME-BASED fallback'
                print(f"[odom] heartbeat ({mode}) ticks L={ticks[0]} R={ticks[1]}  pose={odom.pose()}")
                last_status_t = now

            # Also print immediately whenever ticks change
            if ticks != last_ticks:
                if not encoder_online:
                    print("[odom] encoder online — switching from time-based to encoder odometry")
                encoder_online = True
                last_ticks = ticks
                print(f"[odom] tick change L={ticks[0]} R={ticks[1]}  pose={odom.pose()}")

            # ----------------------------------------------------------------
            # Time-based dead reckoning fallback (encoder disc not in sensor)
            # When encoder ticks never move, estimate pose from commanded motion.
            # Switch back automatically the moment real ticks appear.
            # ----------------------------------------------------------------
            if not encoder_online:
                with _last_serial_cmd_lock:
                    cmd = _last_serial_cmd
                if cmd and cmd != b' ':
                    speed_mmps = config.SPEED_MMPS_AT_MAX * (_current_speed / config.MAX_SPEED)
                    dist = speed_mmps * 0.05   # 50 ms per loop iteration
                    half_track = config.TRACK_WIDTH_MM / 2.0
                    if   cmd == b'w': odom.push_delta( dist,  0.0)
                    elif cmd == b's': odom.push_delta(-dist,  0.0)
                    elif cmd == b'd': odom.push_delta( 0.0,  -dist / half_track)
                    elif cmd == b'a': odom.push_delta( 0.0,   dist / half_track)

            with _human_lock:
                human = _human_detected

            with _command_lock:
                cmd = _last_command

            if human: # and (now - last_log_time >= 0.5):
                points.append([speed, int(human)])
                #log_entry = {
                #    "ticks": ticks,
                #    "human_detected": 1,
                #    "command": cmd,
                #}
                #log_file.write(json.dumps(log_entry) + "\n")
                #log_file.flush()
            
            if now - last_log_time >= 0.5:
                #points.append([int(speed), int(human)])
                with open(log_filename, "w") as f:
                    json.dump({"points": points}, f, indent=2)
                last_log_time = now
    
                #last_log_time = now

        except Exception as e:
            print(f"[odom] updater error: {e}")

        time.sleep(0.05)

def _cmd_repeater():
    """Re-send the current drive command every 150ms to prevent the device's
    400ms safety timeout from stopping the motors while a key is held down."""
    import time
    while True:
        time.sleep(0.15)
        if link:
            with _last_serial_cmd_lock:
                cmd = _last_serial_cmd
            # Only repeat actual drive commands — not stop (b' ')
            if cmd and cmd != b' ':
                link.send(cmd)

# ---------------------------------------------------------------------------
# Camera (MJPEG)
# ---------------------------------------------------------------------------

_camera_lock  = threading.Lock()
_camera_frame = None

# Human detection state (updated by camera reader thread)
_human_detected = False
_human_lock     = threading.Lock()

def _make_placeholder_jpg(text='No camera'):
    """Return a JPEG bytes of a black 640x480 frame with centred text."""
    import numpy as np
    img = np.zeros((480, 640, 3), dtype='uint8')
    cv2.putText(img, text, (180, 250), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, (80, 80, 80), 2, cv2.LINE_AA)
    _, jpg = cv2.imencode('.jpg', img)
    return jpg.tobytes()

def _ensure_object_model():
    """Download the MediaPipe EfficientDet Lite-2 object detection model if not present."""
    import os, urllib.request
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'efficientdet_lite2.tflite')
    if not os.path.exists(path):
        url = ('https://storage.googleapis.com/mediapipe-models/object_detector/'
               'efficientdet_lite2/int8/latest/efficientdet_lite2.tflite')
        print('Downloading MediaPipe object detection model (~7 MB)...')
        urllib.request.urlretrieve(url, path)
        print('Object detection model ready.')
    return path

# Colours for bounding boxes — person gets red, everything else gets cyan/green
_BOX_PERSON_COLOUR = (0,   0,   220)   # BGR red
_BOX_OTHER_COLOUR  = (0,   200,  80)   # BGR green

def _camera_reader():
    import time
    global _camera_frame, _human_detected, _last_command

    model_path      = _ensure_object_model()
    ObjectDetector  = mp.tasks.vision.ObjectDetector
    DetectorOptions = mp.tasks.vision.ObjectDetectorOptions
    RunningMode     = mp.tasks.vision.RunningMode

    options = DetectorOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        score_threshold=0.45,   # raise to reduce false positives
        max_results=20,
    )

    # Serve placeholder until a camera is available
    with _camera_lock:
        _camera_frame = _make_placeholder_jpg()

    cap        = None
    frame_n    = 0
    t_start    = time.time()
    # Keep the last detection result so we can draw boxes on skipped frames too
    last_detections = []

    with ObjectDetector.create_from_options(options) as detector:
        while True:
            # (Re)open camera if needed
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(config.CAMERA_INDEX)
                if not cap.isOpened():
                    with _camera_lock:
                        _camera_frame = _make_placeholder_jpg('No camera — retrying…')
                    time.sleep(2)
                    continue
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            ok, frame = cap.read()
            if not ok:
                cap.release()
                cap = None
                continue

            frame_n += 1
            # Run detection every 3 frames to keep CPU usage low
            if frame_n % 3 == 0:
                rgb          = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image     = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int((time.time() - t_start) * 1000)
                results      = detector.detect_for_video(mp_image, timestamp_ms)
                last_detections = results.detections  # list of Detection objects

                detected = any(
                    d.categories[0].category_name == 'person'
                    for d in last_detections
                    if d.categories
                )

                with _human_lock:
                    prev            = _human_detected
                    _human_detected = detected

                # On rising edge: stop forward/back + cancel navigator, but allow turning
                if detected and not prev:
                    if link:
                        with _command_lock:
                            _last_command = "stop"
                        link.send(b' ')
                    if nav:
                        nav.stop()
                    with _active_lock:
                        # Only clear forward/back keys; keep turn keys so driver can steer
                        _active_keys.discard('ArrowUp')
                        _active_keys.discard('ArrowDown')
                        _active_keys.discard('KeyW')
                        _active_keys.discard('KeyS')

            # Draw bounding boxes for every detected object
            h, w = frame.shape[:2]
            for det in last_detections:
                if not det.categories:
                    continue
                cat   = det.categories[0]
                label = cat.category_name
                score = cat.score
                bb    = det.bounding_box   # origin_x/y, width, height — pixel coords

                x1 = max(0,     int(bb.origin_x))
                y1 = max(0,     int(bb.origin_y))
                x2 = min(w - 1, int(bb.origin_x + bb.width))
                y2 = min(h - 1, int(bb.origin_y + bb.height))

                colour = _BOX_PERSON_COLOUR if label == 'person' else _BOX_OTHER_COLOUR
                cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)

                caption = f'{label} {score:.0%}'
                # Black background behind text for readability
                (tw, th), baseline = cv2.getTextSize(
                    caption, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                ty = max(y1 - 4, th + 4)
                cv2.rectangle(frame,
                              (x1, ty - th - baseline - 2),
                              (x1 + tw + 4, ty + baseline - 2),
                              colour, cv2.FILLED)
                cv2.putText(frame, caption, (x1 + 2, ty - 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

            _, jpg = cv2.imencode('.jpg', frame,
                                  [cv2.IMWRITE_JPEG_QUALITY, config.MJPEG_QUALITY])
            with _camera_lock:
                _camera_frame = jpg.tobytes()

def _mjpeg_generator():
    import time
    while True:
        with _camera_lock:
            frame = _camera_frame
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(1 / 30)  # cap at 30 fps; prevents CPU starvation of other threads

# ---------------------------------------------------------------------------
# Key → command mapping
# ---------------------------------------------------------------------------

_KEY_CMD = {
    'ArrowUp':    b'w',
    'ArrowDown':  b's',
    'ArrowLeft':  b'a',
    'ArrowRight': b'd',
    'Space':      b' ',
    'KeyW':       b'w',
    'KeyS':       b's',
    'KeyA':       b'a',
    'KeyD':       b'd',
}

_SPEED_KEYS = {str(i): config.MIN_SPEED + (config.MAX_SPEED - config.MIN_SPEED) * (i - 1) // 8
               for i in range(1, 10)}

_active_keys: set = set()
_active_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html',
                           host=request.host.split(':')[0],
                           port=config.SERVER_PORT)

@app.route('/video_feed')
def video_feed():
    return Response(_mjpeg_generator(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/goto', methods=['POST'])
def goto():
    if nav is None:
        return jsonify(status='error', msg='Hardware not connected'), 503
    data = request.get_json(force=True)
    x = float(data.get('x', 0))
    y = float(data.get('y', 0))
    nav.go_to(x, y)
    return jsonify(status='ok', x=x, y=y)

@app.route('/stop', methods=['POST'])
def stop_all():
    if nav:
        nav.stop()
    elif link:
        link.send(b' ')
    return jsonify(status='ok')

@app.route('/reset_pose', methods=['POST'])
def reset_pose():
    if odom is None:
        return jsonify(status='error', msg='Hardware not connected'), 503
    # Pass current device tick counts as baseline so the first delta is zero
    current_ticks = link.get_ticks() if link else (0, 0)
    odom.reset(*current_ticks)
    return jsonify(status='ok')

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@sock.route('/ws')
def ws_handler(ws):
    global _current_speed
    import time

    # Push pose telemetry to this client in a background thread
    def _push_telemetry():
        while True:
            try:
                pose = odom.pose() if odom else {'x': 0, 'y': 0, 'theta': 0}
                with _human_lock:
                    human = _human_detected
                ws.send(json.dumps({'type': 'pose', **pose,
                                    'speed': _current_speed,
                                    'busy': nav.is_busy() if nav else False,
                                    'human': human}))
                time.sleep(0.2)
            except Exception:
                break

    t = threading.Thread(target=_push_telemetry, daemon=True)
    t.start()

    while True:
        try:
            msg = ws.receive()
        except Exception:
            break
        if msg is None:
            break

        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            continue

        mtype = data.get('type')

        if mtype == 'key':
            key  = data.get('key', '')
            down = data.get('down', False)

            # When a human is detected, block only forward/backward — turning still allowed
            with _human_lock:
                blocked = _human_detected
            if blocked and key in ('ArrowUp', 'ArrowDown', 'KeyW', 'KeyS'):
                continue

            # Speed key (digit 1–9)
            if key in _SPEED_KEYS:
                if down:
                    _current_speed = int(_SPEED_KEYS[key])
                    if link:
                        link.set_speed(_current_speed)
                continue

            cmd = _KEY_CMD.get(key)
            if cmd is None or link is None:
                continue

            with _active_lock:
                if down:
                    _active_keys.add(key)
                    link.send(cmd)
                else:
                    _active_keys.discard(key)
                    if not _active_keys:
                        link.send(b' ')

        elif mtype == 'speed':
            _current_speed = max(config.MIN_SPEED,
                                 min(config.MAX_SPEED, int(data.get('value', config.DEFAULT_SPEED))))
            if link:
                link.set_speed(_current_speed)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    _init_hardware()
    threading.Thread(target=_camera_reader, daemon=True).start()
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT,
            debug=False, threaded=True)
