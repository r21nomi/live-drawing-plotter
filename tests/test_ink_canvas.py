import pytest

from live_plotter.config import PaperConfig
from live_plotter.ink_canvas import InkCanvas

PAPER = PaperConfig(width_mm=100.0, height_mm=80.0, margin_mm=10.0)


def test_empty_canvas_is_fully_novel():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0)
    assert canvas.coverage() == 0.0
    assert canvas.novelty(((20.0, 20.0), (60.0, 20.0))) == 1.0


def test_stroke_removes_novelty_of_itself():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0)
    line = ((20.0, 20.0), (60.0, 20.0))
    inked = canvas.with_strokes([line], radius_mm=1.0)
    assert inked.novelty(line) < 0.05
    assert inked.coverage() > 0.0


def test_nearby_parallel_stroke_counts_as_already_drawn():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0).with_strokes(
        [((20.0, 20.0), (60.0, 20.0))], radius_mm=1.0
    )
    assert canvas.novelty(((20.0, 20.5), (60.0, 20.5))) < 0.05
    assert canvas.novelty(((20.0, 40.0), (60.0, 40.0))) == 1.0


def test_partially_overlapping_stroke_has_partial_novelty():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0).with_strokes(
        [((20.0, 20.0), (40.0, 20.0))], radius_mm=1.0
    )
    assert canvas.novelty(((20.0, 20.0), (60.0, 20.0))) == pytest.approx(0.5, abs=0.1)


def test_with_strokes_does_not_mutate_original():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0)
    inked = canvas.with_strokes([((20.0, 20.0), (60.0, 20.0))], radius_mm=1.0)
    assert canvas.coverage() == 0.0
    assert inked.pixels is not canvas.pixels


def test_points_outside_paper_are_clamped_not_crashing():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0)
    inked = canvas.with_strokes([((-50.0, -50.0), (500.0, 500.0))], radius_mm=1.0)
    assert 0.0 < inked.novelty(((-50.0, -50.0), (500.0, 20.0))) <= 1.0


def test_cleared_canvas_is_empty():
    canvas = InkCanvas.empty(PAPER, px_per_mm=2.0).with_strokes(
        [((20.0, 20.0), (60.0, 20.0))], radius_mm=1.0
    )
    assert canvas.cleared().coverage() == 0.0
