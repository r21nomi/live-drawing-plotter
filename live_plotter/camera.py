"""Frame sources: a webcam that always hands out the newest frame, or a file for testing.

Drawing a batch of strokes blocks for seconds, during which OpenCV would otherwise
queue up stale frames. A background thread keeps reading and only the latest frame
is kept, so each drawing cycle starts from what the camera sees *now*.
The thread owns the VideoCapture: it is opened on the main thread (so start-up errors
surface there) and released only by the thread itself.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import CameraConfig

log = logging.getLogger(__name__)

_REOPEN_AFTER_FAILURES = 30
_FAILURE_SLEEP_S = 0.1
_FILE_FRAME_INTERVAL_S = 1 / 30
_JOIN_TIMEOUT_S = 5.0
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


class CameraError(RuntimeError):
    pass


class FrameSource(Protocol):
    def start(self) -> None: ...

    def read(self) -> np.ndarray | None: ...

    def stop(self) -> None: ...

    def __enter__(self) -> FrameSource: ...

    def __exit__(self, *exc: object) -> None: ...


def open_source(cfg: CameraConfig) -> FrameSource:
    """A webcam (index or device path), or for testing a looping video or a still image."""
    if isinstance(cfg.source, str) and Path(cfg.source).suffix.lower() in _IMAGE_EXTENSIONS:
        return StillImageSource(cfg.source)
    return LatestFrameCamera(cfg)


class StillImageSource:
    """Serves one image forever. Useful for dry runs and for tuning edge parameters."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._image: np.ndarray | None = None

    def start(self) -> None:
        image = cv2.imread(self._path, cv2.IMREAD_COLOR)
        if image is None:
            raise CameraError(f"could not read image {self._path}")
        self._image = image
        log.info("still image %s loaded at %dx%d", self._path, image.shape[1], image.shape[0])

    def read(self) -> np.ndarray | None:
        return None if self._image is None else self._image.copy()

    def stop(self) -> None:
        self._image = None

    def __enter__(self) -> StillImageSource:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class LatestFrameCamera:
    def __init__(self, cfg: CameraConfig) -> None:
        self._cfg = cfg
        self._latest: tuple[np.ndarray, float] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_file(self) -> bool:
        """A regular file (video) is looped; anything else is treated as a live device."""
        return isinstance(self._cfg.source, str) and Path(self._cfg.source).is_file()

    def start(self) -> None:
        capture = self._open()
        self._thread = threading.Thread(target=self._loop, args=(capture,), name="camera", daemon=True)
        self._thread.start()

    def _open(self) -> cv2.VideoCapture:
        source = self._cfg.source
        if not self.is_file and sys.platform.startswith("linux"):
            capture = cv2.VideoCapture(source, cv2.CAP_V4L2)
        else:
            capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise CameraError(f"camera {source} could not be opened")
        if not self.is_file:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._cfg.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cfg.height)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise CameraError(f"camera {source} opened but returned no frame")
        log.info("camera %s opened at %dx%d", source, frame.shape[1], frame.shape[0])
        return capture

    def _loop(self, capture: cv2.VideoCapture) -> None:
        try:
            self._discard_warmup(capture)
            failures = 0
            while not self._stop.is_set():
                ok, frame = self._read(capture)
                if ok and frame is not None:
                    failures = 0
                    self._store(frame)
                    if self.is_file:
                        time.sleep(_FILE_FRAME_INTERVAL_S)  # play a video file at roughly real time
                    continue
                failures += 1
                if self.is_file:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the video
                elif failures == 1:
                    log.warning("camera read failed; retrying")
                if failures >= _REOPEN_AFTER_FAILURES:
                    failures = 0
                    capture = self._reopen(capture)
                time.sleep(_FAILURE_SLEEP_S)
        except Exception:  # noqa: BLE001 - keep the thread alive; main loop notices stale frames
            log.exception("camera thread crashed")
        finally:
            if capture is not None:
                capture.release()

    def _discard_warmup(self, capture: cv2.VideoCapture) -> None:
        """USB cameras return dark/noisy frames until auto-exposure settles; don't draw those."""
        if self.is_file or self._cfg.warmup_s <= 0:
            return
        deadline = time.monotonic() + self._cfg.warmup_s
        while time.monotonic() < deadline and not self._stop.is_set():
            self._read(capture)

    @staticmethod
    def _read(capture: cv2.VideoCapture | None) -> tuple[bool, np.ndarray | None]:
        if capture is None:
            return False, None
        try:
            return capture.read()
        except cv2.error as error:
            log.warning("camera read raised: %s", error)
            return False, None

    def _reopen(self, capture: cv2.VideoCapture | None) -> cv2.VideoCapture | None:
        log.warning("camera unresponsive; reopening")
        if capture is not None:
            capture.release()
        try:
            return self._open()
        except CameraError as error:
            log.error("camera reopen failed: %s", error)
            return None

    def _store(self, frame: np.ndarray, timestamp: float | None = None) -> None:
        with self._lock:
            self._latest = (frame, time.monotonic() if timestamp is None else timestamp)

    def read(self) -> np.ndarray | None:
        """A copy of the newest frame, or None if there is none or it is older than max_age_s."""
        with self._lock:
            latest = self._latest
        if latest is None:
            return None
        frame, timestamp = latest
        if time.monotonic() - timestamp > self._cfg.max_age_s:
            return None
        return frame.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                log.warning("camera thread did not stop in time; leaving it to exit with the process")

    def __enter__(self) -> LatestFrameCamera:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
