/* Joy-Car browser controller */

'use strict';

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

const wsUrl = `ws://${location.host}/ws`;
let ws;
const badge = document.getElementById('status-badge');

function connect() {
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    badge.textContent = 'Connected';
    badge.className = 'badge connected';
  };

  ws.onclose = () => {
    badge.textContent = 'Disconnected';
    badge.className = 'badge disconnected';
    setTimeout(connect, 2000);  // auto-reconnect
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'pose') {
        document.getElementById('t-x').textContent     = msg.x + ' cm';
        document.getElementById('t-y').textContent     = msg.y + ' cm';
        document.getElementById('t-theta').textContent = msg.theta + '°';
        document.getElementById('t-speed').textContent = msg.speed;
        document.getElementById('speed-slider').value  = msg.speed;
        mapDraw(msg.x, msg.y);

        // Human detection warning
        const warn = document.getElementById('human-warning');
        if (msg.human) {
          warn.classList.remove('hidden');
        } else {
          warn.classList.add('hidden');
        }
      }
    } catch (_) {}
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

connect();

// ---------------------------------------------------------------------------
// Keyboard control
// ---------------------------------------------------------------------------

const DRIVE_KEYS = new Set([
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Space', 'KeyW', 'KeyS', 'KeyA', 'KeyD'
]);
const SPEED_KEYS = new Set(['Digit1','Digit2','Digit3','Digit4','Digit5',
                             'Digit6','Digit7','Digit8','Digit9']);

const heldKeys = new Set();

document.addEventListener('keydown', (e) => {
  if (e.repeat) return;

  if (SPEED_KEYS.has(e.code)) {
    const digit = e.code.replace('Digit', '');
    send({ type: 'key', key: digit, down: true });
    return;
  }

  const key = e.code === 'Space' ? 'Space' : e.key.startsWith('Arrow') ? e.key : e.code;
  if (!DRIVE_KEYS.has(key)) return;

  e.preventDefault();
  if (heldKeys.has(key)) return;
  heldKeys.add(key);
  send({ type: 'key', key, down: true });

  // D-pad button highlight
  const btn = document.querySelector(`.dpad-btn[data-key="${e.key === ' ' ? 'Space' : e.key}"]`);
  if (btn) btn.classList.add('pressed');
});

document.addEventListener('keyup', (e) => {
  const key = e.code === 'Space' ? 'Space' : e.key.startsWith('Arrow') ? e.key : e.code;
  if (!DRIVE_KEYS.has(key)) return;
  e.preventDefault();
  heldKeys.delete(key);
  send({ type: 'key', key, down: false });

  const btn = document.querySelector(`.dpad-btn[data-key="${e.key === ' ' ? 'Space' : e.key}"]`);
  if (btn) btn.classList.remove('pressed');
});

// ---------------------------------------------------------------------------
// D-pad buttons (touch / mouse)
// ---------------------------------------------------------------------------

document.querySelectorAll('.dpad-btn').forEach(btn => {
  const key = btn.dataset.key;

  function press()   { btn.classList.add('pressed');    send({ type: 'key', key, down: true }); }
  function release() { btn.classList.remove('pressed'); send({ type: 'key', key, down: false }); }

  btn.addEventListener('mousedown',  press);
  btn.addEventListener('mouseup',    release);
  btn.addEventListener('mouseleave', release);
  btn.addEventListener('touchstart', (e) => { e.preventDefault(); press(); });
  btn.addEventListener('touchend',   (e) => { e.preventDefault(); release(); });
});

// ---------------------------------------------------------------------------
// Speed slider
// ---------------------------------------------------------------------------

const slider = document.getElementById('speed-slider');
slider.addEventListener('input', () => {
  send({ type: 'speed', value: parseInt(slider.value) });
});

// ---------------------------------------------------------------------------
// Go To form
// ---------------------------------------------------------------------------

document.getElementById('btn-goto').addEventListener('click', () => {
  const x = parseFloat(document.getElementById('goto-x').value) || 0;
  const y = parseFloat(document.getElementById('goto-y').value) || 0;
  fetch('/goto', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, y }),
  });
});

document.getElementById('btn-stop-all').addEventListener('click', () => {
  fetch('/stop', { method: 'POST' });
  send({ type: 'key', key: 'Space', down: true });
  setTimeout(() => send({ type: 'key', key: 'Space', down: false }), 100);
});

document.getElementById('btn-reset-pose').addEventListener('click', () => {
  fetch('/reset_pose', { method: 'POST' });
  trailPoints = [];
  mapCtx.clearRect(0, 0, mapCanvas.width, mapCanvas.height);
});

// ---------------------------------------------------------------------------
// Odometry map (canvas)
// ---------------------------------------------------------------------------

const mapCanvas = document.getElementById('map');
const mapCtx    = mapCanvas.getContext('2d');
const W = mapCanvas.width;
const H = mapCanvas.height;

let trailPoints = [];   // [{x, y}] in cm
const SCALE_CM  = 2;    // pixels per cm

function mapDraw(x_cm, y_cm) {
  trailPoints.push({ x: x_cm, y: y_cm });

  mapCtx.clearRect(0, 0, W, H);

  // Grid
  mapCtx.strokeStyle = '#1c2630';
  mapCtx.lineWidth = 1;
  const gridStep = 20 * SCALE_CM;  // every 20cm
  const cx = W / 2, cy = H / 2;

  for (let gx = cx % gridStep; gx < W; gx += gridStep) {
    mapCtx.beginPath(); mapCtx.moveTo(gx, 0); mapCtx.lineTo(gx, H); mapCtx.stroke();
  }
  for (let gy = cy % gridStep; gy < H; gy += gridStep) {
    mapCtx.beginPath(); mapCtx.moveTo(0, gy); mapCtx.lineTo(W, gy); mapCtx.stroke();
  }

  // Origin
  mapCtx.strokeStyle = '#30363d';
  mapCtx.beginPath(); mapCtx.moveTo(cx, 0); mapCtx.lineTo(cx, H); mapCtx.stroke();
  mapCtx.beginPath(); mapCtx.moveTo(0, cy); mapCtx.lineTo(W, cy);  mapCtx.stroke();

  // Trail
  if (trailPoints.length < 2) {
    drawDot(cx, cy);
    return;
  }
  mapCtx.beginPath();
  mapCtx.strokeStyle = '#388bfd';
  mapCtx.lineWidth   = 2;
  trailPoints.forEach((p, i) => {
    const px = cx + p.x * SCALE_CM;
    const py = cy - p.y * SCALE_CM;
    i === 0 ? mapCtx.moveTo(px, py) : mapCtx.lineTo(px, py);
  });
  mapCtx.stroke();

  // Current robot dot
  const last = trailPoints[trailPoints.length - 1];
  drawDot(cx + last.x * SCALE_CM, cy - last.y * SCALE_CM);
}

function drawDot(px, py) {
  mapCtx.beginPath();
  mapCtx.arc(px, py, 5, 0, 2 * Math.PI);
  mapCtx.fillStyle = '#58a6ff';
  mapCtx.fill();
  mapCtx.strokeStyle = '#fff';
  mapCtx.lineWidth = 1.5;
  mapCtx.stroke();
}

// Draw initial state
mapDraw(0, 0);

// ---------------------------------------------------------------------------
// Camera: snapshot polling (works on Safari + always shows latest frame,
// avoiding MJPEG TCP-buffer lag)
// ---------------------------------------------------------------------------

const camImg = document.getElementById('cam');
let _camPending = false;

function _pollCamera() {
  if (_camPending) return;
  _camPending = true;
  const img = new Image();
  img.onload = () => {
    camImg.src = img.src;
    _camPending = false;
    setTimeout(_pollCamera, 66);   // ~15 fps — tune lower if still laggy
  };
  img.onerror = () => {
    _camPending = false;
    setTimeout(_pollCamera, 500);  // back off on error
  };
  img.src = '/snapshot?t=' + Date.now();
}

_pollCamera();
