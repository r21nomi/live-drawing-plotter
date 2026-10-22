"""Optional on-screen preview: camera | edges | what is on the paper."""

from __future__ import annotations

import logging
import os
import sys

import cv2
import numpy as np

from .ink_canvas import InkCanvas

log = logging.getLogger(__name__)

_PANEL_WIDTH = 420
_WINDOW = "live-drawing-plotter"
_QUIT_KEYS = {ord("q"), 27}  # q or Esc


def display_available(override: bool | None) -> bool:
    if override is not None:
        return override
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return True
    # OpenCV's bundled Qt only speaks X11 (xcb); a Wayland-only session would abort, so
    # require DISPLAY (Xwayland sets it on Raspberry Pi OS desktops).
    return bool(os.environ.get("DISPLAY"))


def open_preview(enabled: bool) -> Preview | NullPreview:
    """A window if one can be created, otherwise a silent stand-in."""
    if not enabled:
        return NullPreview()
    try:
        return Preview()
    except cv2.error as error:
        log.warning("preview window unavailable, continuing without it: %s", error)
        return NullPreview()


class NullPreview:
    def show(self, frame: np.ndarray, edges: np.ndarray, canvas: InkCanvas, status: list[str]) -> bool:
        return False

    def close(self) -> None:
        pass


class Preview:
    """Shows a composite window. `show` returns True when the user asks to quit."""

    def __init__(self) -> None:
        cv2.namedWindow(_WINDOW, cv2.WINDOW_AUTOSIZE)

    def show(self, frame: np.ndarray, edges: np.ndarray, canvas: InkCanvas, status: list[str]) -> bool:
        cv2.imshow(_WINDOW, compose(frame, edges, canvas, status))
        return cv2.waitKey(1) & 0xFF in _QUIT_KEYS

    def close(self) -> None:
        cv2.destroyAllWindows()
        cv2.waitKey(1)


def compose(frame: np.ndarray, edges: np.ndarray, canvas: InkCanvas, status: list[str]) -> np.ndarray:
    """Build the preview image: camera | edges | paper (black ink on white), with status text."""
    panels = [
        _fit(frame),
        _fit(cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)),
        _fit(cv2.cvtColor(255 - canvas.pixels, cv2.COLOR_GRAY2BGR)),
    ]
    height = max(p.shape[0] for p in panels)
    composite = np.hstack([_pad_to_height(p, height) for p in panels])
    for i, line in enumerate(status):
        cv2.putText(composite, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    return composite


def _fit(image: np.ndarray) -> np.ndarray:
    scale = _PANEL_WIDTH / image.shape[1]
    size = (_PANEL_WIDTH, max(1, int(round(image.shape[0] * scale))))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _pad_to_height(image: np.ndarray, height: int) -> np.ndarray:
    extra = height - image.shape[0]
    if extra <= 0:
        return image
    return cv2.copyMakeBorder(image, 0, extra, 0, 0, cv2.BORDER_CONSTANT, value=(40, 40, 40))
