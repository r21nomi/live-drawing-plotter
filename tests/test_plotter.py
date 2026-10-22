import pytest

from live_plotter.config import AxiDrawConfig, PaperConfig
from live_plotter.plotter import AxiDrawPlotter, DryRunPlotter, PlotterError, PlotterStopped, _clamped

PAPER = PaperConfig(width_mm=100.0, height_mm=80.0, margin_mm=10.0)


class _Namespace:
    pass


class FakeAxiDraw:
    """Mimics the parts of pyaxidraw's interactive API that AxiDrawPlotter touches."""

    def __init__(self, connect_result=True, connect_raises=False, stop_after_draw=False, penup_raises=False):
        self.options = _Namespace()
        self.errors = _Namespace()
        self.errors.code = 0
        self.plot_status = _Namespace()
        self.plot_status.stopped = False
        self.calls = []
        self._connect_result = connect_result
        self._connect_raises = connect_raises
        self._stop_after_draw = stop_after_draw
        self._penup_raises = penup_raises

    def interactive(self):
        self.calls.append("interactive")

    def connect(self):
        self.calls.append("connect")
        if self._connect_raises:
            raise RuntimeError("Failed to connected to AxiDraw")
        return self._connect_result

    def draw_path(self, points):
        self.calls.append(("draw_path", points))
        if self._stop_after_draw:
            self.plot_status.stopped = 104
            self.errors.code = 104

    def penup(self):
        self.calls.append("penup")
        if self._penup_raises:
            raise RuntimeError("not connected")

    def moveto(self, x, y):
        self.calls.append(("moveto", x, y))

    def disconnect(self):
        self.calls.append("disconnect")


def _plotter(fake):
    return AxiDrawPlotter(AxiDrawConfig(), PAPER, factory=lambda: fake)


def test_clamped_keeps_points_on_paper():
    assert _clamped(((-5.0, 10.0), (500.0, 500.0)), PAPER) == ((0.0, 10.0), (100.0, 80.0))


def test_connect_configures_units_errors_and_options():
    fake = FakeAxiDraw()
    _plotter(fake).connect()
    assert fake.options.units == 2  # millimetres
    assert fake.options.model == 1
    assert (fake.errors.connect, fake.errors.button, fake.errors.keyboard, fake.errors.disconnect) == (True,) * 4
    assert fake.calls[:2] == ["interactive", "connect"]


def test_connect_failure_is_a_plotter_error_not_a_raw_runtime_error():
    with pytest.raises(PlotterError, match="could not connect"):
        _plotter(FakeAxiDraw(connect_raises=True)).connect()
    with pytest.raises(PlotterError):
        _plotter(FakeAxiDraw(connect_result=False)).connect()


def test_draw_stroke_sends_clamped_points_in_mm():
    fake = FakeAxiDraw()
    plotter = _plotter(fake)
    plotter.connect()
    plotter.draw_stroke(((20.0, 20.0), (150.0, 30.0)))
    assert ("draw_path", [[20.0, 20.0], [100.0, 30.0]]) in fake.calls


def test_draw_stroke_before_connect_raises():
    with pytest.raises(PlotterError):
        _plotter(FakeAxiDraw()).draw_stroke(((0.0, 0.0), (1.0, 1.0)))


def test_silent_stop_after_draw_is_detected():
    plotter = _plotter(FakeAxiDraw(stop_after_draw=True))
    plotter.connect()
    with pytest.raises(PlotterStopped):
        plotter.draw_stroke(((20.0, 20.0), (30.0, 20.0)))


def test_runtime_error_during_draw_becomes_plotter_stopped():
    fake = FakeAxiDraw()

    def boom(points):
        raise RuntimeError("Lost USB connectivity")

    fake.draw_path = boom
    plotter = _plotter(fake)
    plotter.connect()
    with pytest.raises(PlotterStopped, match="Lost USB"):
        plotter.draw_stroke(((20.0, 20.0), (30.0, 20.0)))


def test_finish_lifts_pen_goes_home_and_disconnects():
    fake = FakeAxiDraw()
    plotter = _plotter(fake)
    plotter.connect()
    plotter.finish()
    assert fake.calls[-3:] == ["penup", ("moveto", 0.0, 0.0), "disconnect"]
    plotter.finish()  # idempotent
    assert fake.calls.count("disconnect") == 1


def test_finish_still_disconnects_when_homing_fails():
    fake = FakeAxiDraw(penup_raises=True)
    plotter = _plotter(fake)
    plotter.connect()
    plotter.finish()
    assert "disconnect" in fake.calls


def test_dry_run_plotter_sleeps_proportionally(monkeypatch):
    slept = []
    monkeypatch.setattr("live_plotter.plotter.time.sleep", lambda s: slept.append(s))
    plotter = DryRunPlotter(AxiDrawConfig(dry_run_speed_mm_s=100.0), PAPER)
    plotter.connect()
    plotter.draw_stroke(((0.0, 0.0), (50.0, 0.0)))
    plotter.draw_stroke(((50.0, 0.0), (50.0, 30.0)))
    assert slept == pytest.approx([0.5, 0.3])
