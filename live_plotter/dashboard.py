"""Dashboard served by the running piece: live camera, paper state, and operator controls.

Standard library only. Runs in daemon threads next to the drawing loop:
- an HTTP server (one thread per request) for the page, images, status and controls
- a camera thread encoding the newest frame to JPEG for the MJPEG stream
The drawing loop pushes edges / paper / status with `update()`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from .camera import FrameSource
from .controls import RunControl
from .dashboard_page import PAGE
from .ink_canvas import InkCanvas
from .status import StatusInfo

log = logging.getLogger(__name__)

_CAMERA_FPS = 10
_JPEG_QUALITY = 80
_STREAM_BOUNDARY = b"--frame"
_ACTIONS = ("pause", "resume", "new_paper")
_BLANK_JPEG_SIZE = (120, 160)


@dataclass(frozen=True)
class _Snapshot:
    edges_jpeg: bytes
    paper_jpeg: bytes
    status: StatusInfo
    updated: int


def _encode_jpeg(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buffer.tobytes()


def _blank_jpeg() -> bytes:
    return _encode_jpeg(np.full((*_BLANK_JPEG_SIZE, 3), 28, dtype=np.uint8))


def _no_camera_jpeg() -> bytes:
    image = np.full((240, 320, 3), 28, dtype=np.uint8)
    cv2.putText(image, "NO CAMERA", (70, 128), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (90, 90, 200), 2, cv2.LINE_AA)
    return _encode_jpeg(image)


class Dashboard:
    def __init__(self, control: RunControl, port: int = 8080, host: str = "0.0.0.0") -> None:
        self._control = control
        self._host = host
        self._requested_port = port
        self._lock = threading.Lock()
        blank = _blank_jpeg()
        self._snapshot = _Snapshot(blank, blank, StatusInfo(), 0)
        self._camera_jpeg: bytes = _no_camera_jpeg()
        self._camera_seq = 0
        self._stop = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._threads: list[threading.Thread] = []
        self._camera: FrameSource | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._requested_port

    @property
    def camera_frames(self) -> int:
        with self._lock:
            return self._camera_seq

    def start(self, camera: FrameSource | None = None) -> None:
        """Serve immediately; the camera can be attached later with set_camera()."""
        self._camera = camera
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((self._host, self._requested_port), handler)
        self._server.daemon_threads = True
        self._threads = [
            threading.Thread(target=self._server.serve_forever, name="dashboard-http", daemon=True),
            threading.Thread(target=self._camera_loop, name="dashboard-camera", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        log.info("dashboard at http://%s:%d/", "localhost" if self._host == "0.0.0.0" else self._host, self.port)

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        for thread in self._threads:
            thread.join(timeout=2.0)

    def set_camera(self, camera: FrameSource | None) -> None:
        """Attach (or detach, with None) the frame source behind the live stream."""
        with self._lock:
            self._camera = camera
            if camera is None:
                self._camera_jpeg = _no_camera_jpeg()
                self._camera_seq += 1

    def update(self, edges: np.ndarray, canvas: InkCanvas, status: StatusInfo) -> None:
        edges_jpeg = _encode_jpeg(edges)
        paper_jpeg = _encode_jpeg(255 - canvas.pixels)
        with self._lock:
            self._snapshot = _Snapshot(edges_jpeg, paper_jpeg, status, self._snapshot.updated + 1)

    # --- used by the request handler -------------------------------------------------

    def snapshot(self) -> _Snapshot:
        with self._lock:
            return self._snapshot

    def camera_jpeg(self) -> tuple[bytes, int]:
        with self._lock:
            return self._camera_jpeg, self._camera_seq

    def status_json(self) -> bytes:
        snapshot = self.snapshot()
        payload = {**snapshot.status.as_dict(), **self._control.snapshot(), "updated": snapshot.updated}
        return json.dumps(payload).encode()

    def apply_action(self, action: str) -> None:
        if action == "pause":
            self._control.request_pause()
        elif action == "resume":
            self._control.request_resume()
        elif action == "new_paper":
            self._control.request_new_paper()
        else:
            raise ValueError(f"unknown action {action!r}")
        log.info("dashboard: %s", action)

    def stopped(self) -> bool:
        return self._stop.is_set()

    def _camera_loop(self) -> None:
        interval = 1.0 / _CAMERA_FPS
        while not self._stop.is_set():
            started = time.monotonic()
            with self._lock:
                camera = self._camera
            try:
                frame = None if camera is None else camera.read()
                if frame is not None:
                    jpeg = _encode_jpeg(frame)
                    with self._lock:
                        self._camera_jpeg = jpeg
                        self._camera_seq += 1
            except Exception as error:  # noqa: BLE001 - cosmetic; never take the piece down
                log.warning("dashboard camera encode failed: %s", error)
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))


def _make_handler(board: Dashboard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:  # quiet by default
            log.debug("http: " + fmt, *args)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", PAGE.encode())
            elif path == "/status.json":
                self._send(HTTPStatus.OK, "application/json", board.status_json())
            elif path == "/paper.jpg":
                self._send(HTTPStatus.OK, "image/jpeg", board.snapshot().paper_jpeg)
            elif path == "/edges.jpg":
                self._send(HTTPStatus.OK, "image/jpeg", board.snapshot().edges_jpeg)
            elif path == "/camera.mjpg":
                self._stream_camera()
            elif path == "/control":
                self._send(HTTPStatus.METHOD_NOT_ALLOWED, "text/plain", b"POST only")
            else:
                self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/control":
                self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                action = body.get("action")
                if action not in _ACTIONS:
                    raise ValueError(f"action must be one of {_ACTIONS}")
                board.apply_action(action)
            except (ValueError, AttributeError) as error:
                self._send(HTTPStatus.BAD_REQUEST, "application/json",
                           json.dumps({"ok": False, "error": str(error)}).encode())
                return
            self._send(HTTPStatus.OK, "application/json",
                       json.dumps({"ok": True, **json.loads(board.status_json())}).encode())

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream_camera(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_STREAM_BOUNDARY.decode()}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last_seq = -1
            try:
                while not board.stopped():
                    jpeg, seq = board.camera_jpeg()
                    if seq != last_seq:
                        last_seq = seq
                        self.wfile.write(_STREAM_BOUNDARY + b"\r\nContent-Type: image/jpeg\r\n"
                                         + f"Content-Length: {len(jpeg)}\r\n\r\n".encode() + jpeg + b"\r\n")
                        self.wfile.flush()
                    time.sleep(1.0 / (_CAMERA_FPS * 2))
            except (BrokenPipeError, ConnectionResetError):
                pass  # viewer went away

    return Handler
