import cv2
import numpy as np
import pytest

from live_plotter.camera import CameraError, LatestFrameCamera, StillImageSource, open_source
from live_plotter.config import CameraConfig


def _scene(color):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 60), 30, color, thickness=-1)
    return frame


def test_open_source_picks_still_image_for_image_paths(tmp_path):
    path = tmp_path / "scene.png"
    cv2.imwrite(str(path), _scene((255, 255, 255)))
    source = open_source(CameraConfig(source=str(path)))
    assert isinstance(source, StillImageSource)
    with source:
        first, second = source.read(), source.read()
    assert first.shape == (120, 160, 3)
    assert first is not second  # copies, never the shared buffer


def test_open_source_picks_camera_for_indices():
    assert isinstance(open_source(CameraConfig(source=0)), LatestFrameCamera)


def test_still_image_missing_file_raises():
    with pytest.raises(CameraError):
        StillImageSource("/nonexistent/scene.png").start()


def test_video_file_loops_and_serves_frames(tmp_path):
    path = tmp_path / "scene.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (160, 120))
    for _ in range(3):
        writer.write(_scene((255, 255, 255)))
    writer.release()
    with LatestFrameCamera(CameraConfig(source=str(path))) as camera:
        import time

        time.sleep(0.5)  # longer than the 3-frame clip; the reader must have looped
        frame = camera.read()
    assert frame is not None
    assert frame.shape == (120, 160, 3)


def test_device_paths_are_not_files():
    assert LatestFrameCamera(CameraConfig(source="/dev/video99")).is_file is False
    assert LatestFrameCamera(CameraConfig(source=0)).is_file is False


def test_video_files_are_files(tmp_path):
    path = tmp_path / "clip.avi"
    path.write_bytes(b"")
    assert LatestFrameCamera(CameraConfig(source=str(path))).is_file is True


def test_read_returns_none_for_stale_frames():
    import time

    camera = LatestFrameCamera(CameraConfig(source=0, max_age_s=5.0))
    assert camera.read() is None
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    camera._store(frame, timestamp=time.monotonic() - 10.0)
    assert camera.read() is None
    camera._store(frame)
    fresh = camera.read()
    assert fresh is not None
    assert fresh is not frame
