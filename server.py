"""
Joy-Car web controller — Flask + WebSocket + MJPEG camera stream.
Run with:  python server.py
Then open: http://localhost:5000
"""

import time
import json

log_file = open("robot_log.jsonl", "a")


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

def _init_hardware():
    global link, odom, nav, _current_speed
    link = SerialLink()
    odom = Odometry()
    nav  = Navigator(link, odom)
    _current_speed = config.DEFAULT_SPEED
    link.set_speed(_current_speed)
    # Encoder polling thread: update odometry from device ticks
    threading.Thread(target=_odom_updater, daemon=True).start()

def _odom_updater():
    import time
    
    last_log_time = 0
    
    while True:
        if link:
            odom.update(*link.get_ticks())

            with _human_lock:
                human = _human_detected

            now = time.time()
            
            with _command_lock:
                cmd = _last_command

            # Log only every 0.5 seconds AND only if a human is detected
            if human and (now - last_log_time >= 0.5):

                speed = getattr(odom, "v", 0)

                log_entry = {
                    "speed": speed,
                    "human_detected": 1,
                    "command": cmd
                }

                log_file.write(json.dumps(log_entry) + "\n")
                log_file.flush()

                last_log_time = now

        time.sleep(0.05)

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

def _ensure_pose_model():
    """Download the MediaPipe pose landmarker model if not already present."""
    import os, urllib.request
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pose_landmarker_lite.task')
    if not os.path.exists(path):
        url = ('https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
               'pose_landmarker_lite/float16/latest/pose_landmarker_lite.task')
        print('Downloading MediaPipe pose model (~5 MB)...')
        urllib.request.urlretrieve(url, path)
        print('Pose model ready.')
    return path

def _camera_reader():
    import time, os
    global _camera_frame, _human_detected, _last_command

    # Tasks API — works with mediapipe 0.10.x
    model_path = _ensure_pose_model()
    PoseLandmarker        = mp.tasks.vision.PoseLandmarker
    PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
    RunningMode           = mp.tasks.vision.RunningMode

    options = PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    # Serve placeholder until a camera is available
    with _camera_lock:
        _camera_frame = _make_placeholder_jpg()

    cap     = None
    frame_n = 0
    t_start = time.time()

    with PoseLandmarker.create_from_options(options) as detector:
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
            # Run pose detection every 3 frames to keep CPU usage low
            if frame_n % 3 == 0:
                rgb          = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image     = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int((time.time() - t_start) * 1000)
                results      = detector.detect_for_video(mp_image, timestamp_ms)
                detected     = len(results.pose_landmarks) > 0

                with _human_lock:
                    prev            = _human_detected
                    _human_detected = detected

                # On rising edge: immediately stop robot + cancel navigator + clear held keys
                if detected and not prev:
                    if link:
                    	with _command_lock:
                    		_last_command = "stop"
                    	link.send(b' ')
                    if nav:
                        nav.stop()
                    with _active_lock:
                        _active_keys.clear()

                # Annotate frame with landmark dots + red border
                if results.pose_landmarks:
                    h, w = frame.shape[:2]
                    for landmark_list in results.pose_landmarks:
                        for lm in landmark_list:
                            cx, cy = int(lm.x * w), int(lm.y * h)
                            cv2.circle(frame, (cx, cy), 3, (0, 255, 0), -1)
                    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 220), 8)

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
    data = request.get_json(force=True)
    x = float(data.get('x', 0))
    y = float(data.get('y', 0))
    nav.go_to(x, y)
    return jsonify(status='ok', x=x, y=y)

@app.route('/stop', methods=['POST'])
def stop_all():
    nav.stop()
    return jsonify(status='ok')

@app.route('/reset_pose', methods=['POST'])
def reset_pose():
    odom.reset()
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
            with _human_lock:
                blocked = _human_detected
            if blocked:
                continue  # Ignore all movement commands while human is present

            key  = data.get('key', '')
            down = data.get('down', False)

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
