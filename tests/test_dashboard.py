import json
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

from live_plotter.camera import StillImageSource
from live_plotter.config import PaperConfig
from live_plotter.controls import Phase, RunControl
from live_plotter.dashboard import Dashboard
from live_plotter.ink_canvas import InkCanvas
from live_plotter.status import StatusInfo


@pytest.fixture
def scene(tmp_path):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (40, 30), (120, 90), (255, 255, 255), thickness=-1)
    path = tmp_path / "scene.png"
    cv2.imwrite(str(path), frame)
    return path


@pytest.fixture
def dashboard(scene):
    control = RunControl()
    with StillImageSource(str(scene)) as camera:
        board = Dashboard(control, port=0)
        board.start(camera)
        try:
            yield board, control
        finally:
            board.stop()


def _get(board, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{board.port}{path}", timeout=5) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def _post(board, path, body):
    request = urllib.request.Request(
        f"http://127.0.0.1:{board.port}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_serves_the_page(dashboard):
    board, _ = dashboard
    status, content_type, body = _get(board, "/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert "一時停止".encode() in body


def test_status_json_reflects_control_and_last_update(dashboard):
    board, control = dashboard
    control.set_phase(Phase.IDLE)
    canvas = InkCanvas.empty(PaperConfig(), px_per_mm=2.0)
    edges = np.zeros((120, 160), dtype=np.uint8)
    status_in = StatusInfo(cycle=3, candidates=10, strokes=2, coverage=0.25, drawn_mm=1234.0, dry_run=True)
    board.update(edges, canvas, status_in)
    _, content_type, body = _get(board, "/status.json")
    assert content_type.startswith("application/json")
    status = json.loads(body)
    assert status["phase"] == "idle"
    assert status["paused"] is False
    assert status["cycle"] == 3
    assert status["coverage"] == 0.25
    assert status["updated"] >= 1


def test_paper_and_edges_images_are_jpeg(dashboard):
    board, _ = dashboard
    canvas = InkCanvas.empty(PaperConfig(), px_per_mm=2.0)
    board.update(np.zeros((120, 160), dtype=np.uint8), canvas, StatusInfo())
    for path in ("/paper.jpg", "/edges.jpg"):
        status, content_type, body = _get(board, path)
        assert status == 200
        assert content_type == "image/jpeg"
        assert body[:2] == b"\xff\xd8"


def test_camera_stream_sends_mjpeg_frames(dashboard):
    board, _ = dashboard
    deadline = time.time() + 5
    while time.time() < deadline and board.camera_frames == 0:
        time.sleep(0.05)
    request = urllib.request.urlopen(f"http://127.0.0.1:{board.port}/camera.mjpg", timeout=5)
    assert request.headers.get("Content-Type", "").startswith("multipart/x-mixed-replace")
    chunk = request.read(64)
    assert b"--frame" in chunk
    request.close()


def test_control_endpoint_pauses_resumes_and_requests_new_paper(dashboard):
    board, control = dashboard
    status, body = _post(board, "/control", {"action": "pause"})
    assert status == 200
    assert body["ok"] is True
    assert control.paused is True
    _post(board, "/control", {"action": "resume"})
    assert control.paused is False
    _post(board, "/control", {"action": "new_paper"})
    assert control.paused is True
    assert control.take_new_paper_request() is True


def test_control_rejects_unknown_actions_and_get(dashboard):
    board, _ = dashboard
    with pytest.raises(urllib.error.HTTPError) as error:
        _post(board, "/control", {"action": "explode"})
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(board, "/control")
    assert error.value.code == 405


def test_unknown_path_is_404(dashboard):
    board, _ = dashboard
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(board, "/nope")
    assert error.value.code == 404
