import numpy as np

from live_plotter.config import PaperConfig
from live_plotter.ink_canvas import InkCanvas
from live_plotter.preview import NullPreview, compose, display_available


def test_compose_puts_three_panels_side_by_side():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    edges = np.zeros((480, 640), dtype=np.uint8)
    canvas = InkCanvas.empty(PaperConfig(), px_per_mm=2.0)
    image = compose(frame, edges, canvas, ["status"])
    assert image.ndim == 3
    assert image.shape[1] == 3 * 420
    assert image.shape[0] >= 315


def test_display_override_wins():
    assert display_available(True) is True
    assert display_available(False) is False


def test_null_preview_never_quits():
    assert NullPreview().show(None, None, None, None) is False
