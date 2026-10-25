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


class StoppingPlotter(RecordingPlotter):
    def draw_stroke(self, stroke):
        from live_plotter.plotter import PlotterStopped

        raise PlotterStopped("Stopped by pause button press")


class FailingConnectPlotter(RecordingPlotter):
    def connect(self):
        from live_plotter.plotter import PlotterError

        raise PlotterError("could not connect")


def _scene_file(tmp_path):
    path = tmp_path / "scene.png"
    cv2.imwrite(str(path), _frame_with_rectangle())
    return str(path)


def _cfg(tmp_path, **drawing):
    from live_plotter.config import CameraConfig

    # state_dir=None: tests must never touch the project's real ./state directory.
    return AppConfig(dry_run=True, preview=False, state_dir=None, web_port=None,
                     camera=CameraConfig(source=_scene_file(tmp_path)),
                     drawing=DrawingConfig(length_budget_mm=10_000.0, idle_sleep_s=0.0, **drawing))


def test_run_exits_75_when_the_axidraw_stops_mid_run(tmp_path):
    from live_plotter.main import EXIT_NEEDS_HOMING, run

    plotter = StoppingPlotter()
    assert run(_cfg(tmp_path), plotter=plotter) == EXIT_NEEDS_HOMING


def test_run_exits_1_when_the_plotter_is_unavailable(tmp_path):
    from live_plotter.main import EXIT_RETRY, run

    assert run(_cfg(tmp_path), plotter=FailingConnectPlotter()) == EXIT_RETRY


def test_run_exits_1_when_the_camera_is_unavailable():
    from live_plotter.config import CameraConfig
    from live_plotter.main import EXIT_RETRY, run

    cfg = AppConfig(dry_run=True, preview=False, state_dir=None, web_port=None,
                    camera=CameraConfig(source="/nonexistent/scene.png"))
    plotter = RecordingPlotter()
    assert run(cfg, plotter=plotter) == EXIT_RETRY
    assert plotter.strokes == []  # the plotter was never energised


def test_run_exits_0_on_saturation_stop(tmp_path):
    from live_plotter.main import EXIT_OK, run

    cfg = _cfg(tmp_path, saturation_policy="stop", saturation_threshold=0.001)
    plotter = RecordingPlotter()
    assert run(cfg, plotter=plotter) == EXIT_OK
    assert plotter.strokes


def test_run_loop_gives_up_after_repeated_cycle_failures(tmp_path, monkeypatch):
    from live_plotter.main import EXIT_RETRY, run

    monkeypatch.setattr("live_plotter.main._CYCLE_FAILURE_SLEEP_S", 0.0)

    def broken(*_args, **_kwargs):
        raise ValueError("bad frame")

    monkeypatch.setattr("live_plotter.main.detect_edges", broken)
    assert run(_cfg(tmp_path), plotter=RecordingPlotter()) == EXIT_RETRY


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
