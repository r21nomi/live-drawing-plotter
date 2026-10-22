import json

import numpy as np

from live_plotter.config import PaperConfig
from live_plotter.ink_canvas import InkCanvas
from live_plotter.persistence import SavedState, StateStore

PAPER = PaperConfig(width_mm=100.0, height_mm=80.0, margin_mm=10.0)


def _inked():
    return InkCanvas.empty(PAPER, px_per_mm=2.0).with_strokes([((20.0, 20.0), (60.0, 20.0))], radius_mm=1.0)


def test_load_returns_none_when_nothing_saved(tmp_path):
    assert StateStore(tmp_path / "state").load(PAPER, px_per_mm=2.0) is None


def test_save_then_load_round_trips_canvas_and_counters(tmp_path):
    store = StateStore(tmp_path / "state")
    canvas = _inked()
    store.save(SavedState(canvas=canvas, drawn_mm=123.5, cycle=7))

    loaded = store.load(PAPER, px_per_mm=2.0)
    assert loaded is not None
    assert np.array_equal(loaded.canvas.pixels, canvas.pixels)
    assert loaded.canvas.px_per_mm == 2.0
    assert loaded.canvas.origin_mm == (10.0, 10.0)
    assert loaded.drawn_mm == 123.5
    assert loaded.cycle == 7


def test_save_creates_directory_and_viewable_png(tmp_path):
    store = StateStore(tmp_path / "nested" / "state")
    store.save(SavedState(canvas=_inked(), drawn_mm=0.0, cycle=0))
    assert (tmp_path / "nested" / "state" / "ink_canvas.png").exists()
    meta = json.loads((tmp_path / "nested" / "state" / "state.json").read_text())
    assert meta["paper"]["width_mm"] == 100.0
    assert "saved_at" in meta


def test_load_ignores_state_saved_for_a_different_paper(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(SavedState(canvas=_inked(), drawn_mm=1.0, cycle=1))
    other_paper = PaperConfig(width_mm=200.0, height_mm=80.0, margin_mm=10.0)
    assert store.load(other_paper, px_per_mm=2.0) is None
    assert store.load(PAPER, px_per_mm=4.0) is None


def test_load_ignores_corrupt_metadata(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(SavedState(canvas=_inked(), drawn_mm=1.0, cycle=1))
    (tmp_path / "state" / "state.json").write_text("{not json")
    assert store.load(PAPER, px_per_mm=2.0) is None


def test_clear_removes_saved_state(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(SavedState(canvas=_inked(), drawn_mm=1.0, cycle=1))
    store.clear()
    assert store.load(PAPER, px_per_mm=2.0) is None
    store.clear()  # idempotent


def test_save_is_atomic_leaves_no_temp_files(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(SavedState(canvas=_inked(), drawn_mm=1.0, cycle=1))
    store.save(SavedState(canvas=_inked(), drawn_mm=2.0, cycle=2))
    names = sorted(p.name for p in (tmp_path / "state").iterdir())
    assert names == ["ink_canvas.png", "state.json"]
