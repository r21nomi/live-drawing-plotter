import threading

import cv2
import numpy as np

from live_plotter.config import AppConfig, DrawingConfig
from live_plotter.ink_canvas import InkCanvas
from live_plotter.main import LoopState, _apply_saturation_policy, parse_args, run_cycle
from live_plotter.preview import NullPreview


class RecordingPlotter:
    def __init__(self):
        self.strokes = []

    def connect(self):
        pass

    def draw_stroke(self, stroke):
        self.strokes.append(stroke)

    def finish(self):
        pass


def _frame_with_rectangle():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (80, 60), (240, 180), (255, 255, 255), thickness=-1)
    return frame


def _state(cfg):
    return LoopState(InkCanvas.empty(cfg.paper, cfg.drawing.ink_px_per_mm), (0.0, 0.0), 0, 0.0, False)


def test_parse_args_defaults_and_overrides():
    cfg = parse_args(["--dry-run", "--paper", "a3", "--budget", "123", "--mirror", "--no-preview"])
    assert cfg.dry_run is True
    assert cfg.paper.width_mm == 420.0
    assert cfg.axidraw.model == 2
    assert cfg.drawing.length_budget_mm == 123.0
    assert cfg.camera.mirror is True
    assert cfg.preview is False
    assert parse_args([]).preview is None


def test_run_cycle_draws_then_second_cycle_draws_nothing_new():
    cfg = AppConfig(dry_run=True, drawing=DrawingConfig(length_budget_mm=10_000.0, idle_sleep_s=0.0))
    plotter = RecordingPlotter()
    stop = threading.Event()
    frame = _frame_with_rectangle()

    first = run_cycle(frame, _state(cfg), cfg, plotter, NullPreview(), stop)
    assert plotter.strokes
    assert first.cycle == 1
    assert first.drawn_mm > 0
    assert first.canvas.coverage() > 0

    drawn_before = len(plotter.strokes)
    second = run_cycle(frame, first, cfg, plotter, NullPreview(), stop)
    assert len(plotter.strokes) == drawn_before
    assert second.cycle == 2


def test_run_cycle_stops_between_strokes_when_stop_is_set():
    cfg = AppConfig(dry_run=True, drawing=DrawingConfig(length_budget_mm=10_000.0, idle_sleep_s=0.0))
    plotter = RecordingPlotter()
    stop = threading.Event()
    stop.set()
    run_cycle(_frame_with_rectangle(), _state(cfg), cfg, plotter, NullPreview(), stop)
    assert plotter.strokes == []


def _saturated_state(cfg):
    canvas = InkCanvas.empty(cfg.paper, cfg.drawing.ink_px_per_mm)
    full = canvas.with_strokes([((0.0, 0.0), (1000.0, 1000.0))], radius_mm=1000.0)
    return LoopState(full, (0.0, 0.0), 1, 0.0, False)


def test_saturation_policy_continue_keeps_canvas():
    cfg = DrawingConfig(saturation_policy="continue")
    stop = threading.Event()
    state = _apply_saturation_policy(_saturated_state(AppConfig(drawing=cfg)), cfg, stop)
    assert state.saturated is True
    assert state.canvas.coverage() > 0.9
    assert not stop.is_set()


def test_saturation_policy_stop_sets_stop():
    cfg = DrawingConfig(saturation_policy="stop")
    stop = threading.Event()
    _apply_saturation_policy(_saturated_state(AppConfig(drawing=cfg)), cfg, stop)
    assert stop.is_set()


def test_saturation_policy_clear_resets_canvas():
    cfg = DrawingConfig(saturation_policy="clear")
    state = _apply_saturation_policy(_saturated_state(AppConfig(drawing=cfg)), cfg, threading.Event())
    assert state.canvas.coverage() == 0.0


def test_parse_args_rejects_invalid_values():
    import pytest

    invalid = (["--margin", "200"], ["--canny", "150", "50"], ["--speed", "0"],
               ["--pen-up", "20", "--pen-down", "40"], ["--min-novelty", "2"], ["--budget", "0"], ["--blur", "0"])
    for argv in invalid:
        with pytest.raises(SystemExit):
            parse_args(argv)


def _scene_file(tmp_path):
    path = tmp_path / "scene.png"
    cv2.imwrite(str(path), _frame_with_rectangle())
    return str(path)


def _cfg(tmp_path, **drawing):
    from live_plotter.config import CameraConfig

    # state_dir=None: tests must never touch the project's real ./state directory.
    return AppConfig(dry_run=True, preview=False, state_dir=None, web_port=None, autostart=True,
                     camera=CameraConfig(source=_scene_file(tmp_path)),
                     drawing=DrawingConfig(length_budget_mm=10_000.0, idle_sleep_s=0.0, **drawing))


def test_run_exits_0_on_saturation_stop(tmp_path):
    from live_plotter.main import EXIT_OK, run

    cfg = _cfg(tmp_path, saturation_policy="stop", saturation_threshold=0.001)
    plotter = RecordingPlotter()
    assert run(cfg, plotter=plotter) == EXIT_OK
    assert plotter.strokes


def test_run_persists_ink_and_resumes_after_restart(tmp_path):
    from dataclasses import replace

    from live_plotter.main import EXIT_OK, run
    from live_plotter.persistence import StateStore

    state_dir = tmp_path / "state"
    cfg = replace(_cfg(tmp_path, saturation_policy="stop", saturation_threshold=0.001), state_dir=str(state_dir))

    first = RecordingPlotter()
    assert run(cfg, plotter=first) == EXIT_OK
    assert first.strokes
    saved = StateStore(state_dir).load(cfg.paper, cfg.drawing.ink_px_per_mm)
    assert saved is not None
    assert saved.canvas.coverage() > 0
    assert saved.cycle >= 1

    # Same scene after a "restart": everything is already on the paper, so nothing is drawn.
    second = RecordingPlotter()
    assert run(cfg, plotter=second) == EXIT_OK
    assert second.strokes == []


def test_run_fresh_discards_saved_state(tmp_path):
    from dataclasses import replace

    from live_plotter.main import run

    state_dir = tmp_path / "state"
    cfg = replace(_cfg(tmp_path, saturation_policy="stop", saturation_threshold=0.001), state_dir=str(state_dir))
    run(cfg, plotter=RecordingPlotter())
    fresh = RecordingPlotter()
    run(replace(cfg, fresh_start=True), plotter=fresh)
    assert fresh.strokes


def test_run_without_state_dir_does_not_persist(tmp_path, monkeypatch):
    from dataclasses import replace

    from live_plotter.main import run

    monkeypatch.chdir(tmp_path)
    cfg = replace(_cfg(tmp_path, saturation_policy="stop", saturation_threshold=0.001), state_dir=None)
    run(cfg, plotter=RecordingPlotter())
    assert not (tmp_path / "state").exists()


def test_parse_args_state_options():
    assert parse_args([]).state_dir == "state"
    assert parse_args(["--state-dir", "/tmp/x"]).state_dir == "/tmp/x"
    assert parse_args(["--no-persist"]).state_dir is None
    assert parse_args(["--fresh"]).fresh_start is True


def test_run_loop_pauses_between_strokes_and_resumes(tmp_path):
    import threading

    from live_plotter.camera import StillImageSource
    from live_plotter.controls import Phase, RunControl
    from live_plotter.main import _run_loop

    cfg = _cfg(tmp_path)
    control = RunControl()
    control.request_pause()
    plotter = RecordingPlotter()
    stop = threading.Event()
    with StillImageSource(cfg.camera.source) as camera:
        threading.Timer(0.3, control.request_resume).start()
        threading.Timer(1.2, stop.set).start()
        state = _run_loop(camera, plotter, NullPreview(), cfg, stop, _state(cfg), None, control)
    assert plotter.strokes  # drew after resume
    assert state.cycle >= 1
    assert control.phase in (Phase.IDLE, Phase.DRAWING)


def test_run_loop_new_paper_clears_canvas_and_saved_state(tmp_path):
    import threading

    from live_plotter.camera import StillImageSource
    from live_plotter.controls import RunControl
    from live_plotter.main import _run_loop
    from live_plotter.persistence import StateStore

    cfg = _cfg(tmp_path)
    store = StateStore(tmp_path / "state")
    inked = _state(cfg)
    inked = LoopState(inked.canvas.with_strokes([((20.0, 20.0), (200.0, 20.0))], 1.0), (0.0, 0.0), 5, 180.0, False)
    control = RunControl()
    control.request_new_paper()
    stop = threading.Event()
    with StillImageSource(cfg.camera.source) as camera:
        threading.Timer(0.3, stop.set).start()
        state = _run_loop(camera, RecordingPlotter(), NullPreview(), cfg, stop, inked, store, control)
    assert state.canvas.coverage() == 0.0
    assert state.drawn_mm == 0.0
    assert control.paused is True  # waits for the operator to put the paper in and resume
    saved = store.load(cfg.paper, cfg.drawing.ink_px_per_mm)
    assert saved is not None and saved.canvas.coverage() == 0.0


def test_parse_args_web_options():
    assert parse_args([]).web_port == 8080
    assert parse_args(["--web-port", "9000"]).web_port == 9000
    assert parse_args(["--no-web"]).web_port is None


def test_run_waits_for_the_start_button_by_default(tmp_path):
    import threading
    from dataclasses import replace

    from live_plotter.controls import Phase, RunControl
    from live_plotter.main import EXIT_OK, run

    cfg = replace(_cfg(tmp_path), autostart=False)
    control = RunControl(paused=True)
    plotter = RecordingPlotter()
    seen_phase = []

    def observe_then_start():
        seen_phase.append(control.phase)
        control.request_resume()

    threading.Timer(0.5, observe_then_start).start()
    threading.Timer(1.5, _stop_via_signal).start()
    assert run(cfg, plotter=plotter, control=control) == EXIT_OK
    assert seen_phase == [Phase.READY]
    assert plotter.strokes  # drew only after the start button


def _stop_via_signal():
    import os
    import signal

    os.kill(os.getpid(), signal.SIGINT)


def test_parse_args_autostart():
    assert parse_args([]).autostart is False
    assert parse_args(["--autostart"]).autostart is True


class FlakyPlotter(RecordingPlotter):
    """Fails to connect a few times, then works; can also stop once mid-run."""

    def __init__(self, connect_failures=0, stop_once=False):
        super().__init__()
        self.connect_calls = 0
        self.connected = False
        self._connect_failures = connect_failures
        self._stop_once = stop_once

    def connect(self):
        from live_plotter.plotter import PlotterError

        self.connect_calls += 1
        if self.connect_calls <= self._connect_failures:
            raise PlotterError("could not connect to AxiDraw (check USB cable and power)")
        self.connected = True

    def draw_stroke(self, stroke):
        from live_plotter.plotter import PlotterStopped

        if self._stop_once:
            self._stop_once = False
            raise PlotterStopped("Stopped by pause button press")
        super().draw_stroke(stroke)

    def finish(self):
        self.connected = False


def _fast_retries(monkeypatch):
    monkeypatch.setattr("live_plotter.main._RETRY_S", 0.05)
    monkeypatch.setattr("live_plotter.main._CYCLE_FAILURE_SLEEP_S", 0.0)


def test_run_waits_for_the_camera_and_reports_the_problem(tmp_path, monkeypatch):
    import shutil
    import threading
    from dataclasses import replace

    from live_plotter.config import CameraConfig
    from live_plotter.controls import Phase, ProblemKind, RunControl
    from live_plotter.main import EXIT_OK, run

    _fast_retries(monkeypatch)
    missing = tmp_path / "later.png"
    cfg = replace(_cfg(tmp_path), camera=CameraConfig(source=str(missing)))
    control = RunControl()
    plotter = RecordingPlotter()
    observed = []

    def observe_then_plug_in():
        observed.append((control.phase, control.problem.kind if control.problem else None))
        shutil.copy(_scene_file(tmp_path), missing)  # "plug the camera in"

    threading.Timer(0.4, observe_then_plug_in).start()
    threading.Timer(1.5, _stop_via_signal).start()
    assert run(cfg, plotter=plotter, control=control) == EXIT_OK
    assert observed == [(Phase.WAITING_CAMERA, ProblemKind.CAMERA)]
    assert plotter.strokes  # drew once the camera appeared
    assert control.problem is None


def test_run_retries_plotter_connection(tmp_path, monkeypatch):
    import threading

    from live_plotter.controls import RunControl
    from live_plotter.main import EXIT_OK, run

    _fast_retries(monkeypatch)
    plotter = FlakyPlotter(connect_failures=2)
    control = RunControl()
    threading.Timer(1.0, _stop_via_signal).start()
    assert run(_cfg(tmp_path), plotter=plotter, control=control) == EXIT_OK
    assert plotter.connect_calls == 3
    assert plotter.strokes
    assert control.problem is None


def test_run_recovers_from_plotter_stop_after_operator_resumes(tmp_path, monkeypatch):
    import threading

    from live_plotter.controls import ProblemKind, RunControl
    from live_plotter.main import EXIT_OK, run

    _fast_retries(monkeypatch)
    plotter = FlakyPlotter(stop_once=True)
    control = RunControl()
    observed = []

    def observe_then_resume():
        observed.append((control.paused, control.problem.kind if control.problem else None))
        control.request_resume()  # operator re-homed the carriage and pressed start

    threading.Timer(0.5, observe_then_resume).start()
    threading.Timer(1.5, _stop_via_signal).start()
    assert run(_cfg(tmp_path), plotter=plotter, control=control) == EXIT_OK
    assert observed == [(True, ProblemKind.PLOTTER_STOPPED)]
    assert plotter.connect_calls == 2  # reconnected after the stop
    assert plotter.strokes  # drew after the operator resumed
    assert control.problem is None


def test_run_reports_repeated_cycle_failures_and_keeps_running(tmp_path, monkeypatch):
    import threading

    from live_plotter.controls import ProblemKind, RunControl
    from live_plotter.main import EXIT_OK, run

    _fast_retries(monkeypatch)

    def broken(*_args, **_kwargs):
        raise ValueError("bad frame")

    monkeypatch.setattr("live_plotter.main.detect_edges", broken)
    control = RunControl()
    observed = []
    threading.Timer(0.6, lambda: observed.append(control.problem.kind if control.problem else None)).start()
    threading.Timer(0.9, _stop_via_signal).start()
    assert run(_cfg(tmp_path), plotter=RecordingPlotter(), control=control) == EXIT_OK
    assert observed == [ProblemKind.CYCLES]
