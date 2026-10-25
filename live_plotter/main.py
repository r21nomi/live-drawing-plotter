"""Entry point: capture -> vectorize -> pick novel strokes -> plot, forever."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import dataclass, replace

import numpy as np

from .camera import CameraError, FrameSource, open_source
from .config import AppConfig, DrawingConfig, PaperConfig
from .controls import Phase, RunControl
from .dashboard import Dashboard
from .geometry import Point, polyline_length
from .ink_canvas import InkCanvas
from .path_planning import order_strokes, select_strokes
from .persistence import SavedState, StateStore
from .plotter import AxiDrawPlotter, DryRunPlotter, Plotter, PlotterError, PlotterStopped
from .preview import NullPreview, Preview, display_available, open_preview
from .status import StatusInfo
from .vectorize import detect_edges, vectorize_edges

log = logging.getLogger("live_plotter")

PAPER_PRESETS: dict[str, tuple[float, float, int]] = {
    # name: (width_mm, height_mm, axidraw model)
    "a4": (297.0, 210.0, 1),
    "a3": (420.0, 297.0, 2),
}

EXIT_OK = 0
EXIT_RETRY = 1  # camera / plotter not available: systemd restarts us
EXIT_NEEDS_HOMING = 75  # AxiDraw stopped mid-run: position unknown, do NOT restart automatically

_NO_FRAME_SLEEP_S = 0.2
_PAUSE_POLL_S = 0.2
_CYCLE_FAILURE_SLEEP_S = 1.0
_MAX_CONSECUTIVE_CYCLE_FAILURES = 10


class CycleError(RuntimeError):
    """Image processing kept failing; something is wrong with the frames."""


@dataclass(frozen=True)
class LoopState:
    canvas: InkCanvas
    pen: Point
    cycle: int
    drawn_mm: float
    saturated: bool


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return run(cfg)


def run(cfg: AppConfig, plotter: Plotter | None = None, control: RunControl | None = None) -> int:
    """Run until stopped. Returns a process exit code (see EXIT_* constants)."""
    stop = threading.Event()
    _install_signal_handlers(stop)
    if plotter is None:
        plotter = DryRunPlotter(cfg.axidraw, cfg.paper) if cfg.dry_run else AxiDrawPlotter(cfg.axidraw, cfg.paper)
    control = control or RunControl()
    dashboard = Dashboard(control, port=cfg.web_port) if cfg.web_port else None
    preview = open_preview(display_available(cfg.preview))
    store = StateStore(cfg.state_dir) if cfg.state_dir else None
    state = _initial_state(cfg, store)
    log.info("paper %.0fx%.0f mm, budget %.0f mm/cycle, saturation policy=%s",
             cfg.paper.width_mm, cfg.paper.height_mm, cfg.drawing.length_budget_mm, cfg.drawing.saturation_policy)
    exit_code = EXIT_OK
    try:
        # Camera first: if it is not ready yet we exit without ever energising the plotter.
        with open_source(cfg.camera) as camera:
            if dashboard is not None:
                dashboard.start(camera)
            plotter.connect()
            try:
                state = _run_loop(camera, plotter, preview, cfg, stop, state, store, control, dashboard)
            finally:
                plotter.finish()
    except PlotterStopped as error:
        log.error("%s", error)
        log.error("the carriage position is unknown: move it to the home corner by hand before restarting")
        exit_code = EXIT_NEEDS_HOMING
    except (CameraError, PlotterError, CycleError) as error:
        log.error("%s", error)
        exit_code = EXIT_RETRY
    finally:
        if dashboard is not None:
            dashboard.stop()
        preview.close()
        log.info("stopped after %d cycles, %.1f m drawn (exit %d)", state.cycle, state.drawn_mm / 1000, exit_code)
    return exit_code


def _initial_state(cfg: AppConfig, store: StateStore | None) -> LoopState:
    empty = LoopState(InkCanvas.empty(cfg.paper, cfg.drawing.ink_px_per_mm), (0.0, 0.0), 0, 0.0, False)
    if store is None:
        return empty
    if cfg.fresh_start:
        store.clear()
        log.info("fresh start: saved ink memory discarded")
        return empty
    saved = store.load(cfg.paper, cfg.drawing.ink_px_per_mm)
    if saved is None:
        return empty
    log.info("resuming: %.1f%% of the paper already drawn (%.1f m over %d cycles)",
             saved.canvas.coverage() * 100, saved.drawn_mm / 1000, saved.cycle)
    return LoopState(saved.canvas, (0.0, 0.0), saved.cycle, saved.drawn_mm, False)


def _persist(store: StateStore | None, state: LoopState) -> None:
    """Best effort: a full disk must not stop the drawing."""
    if store is None:
        return
    try:
        store.save(SavedState(canvas=state.canvas, drawn_mm=state.drawn_mm, cycle=state.cycle))
    except Exception as error:  # noqa: BLE001
        log.warning("could not save ink memory: %s", error)


def _run_loop(
    camera: FrameSource,
    plotter: Plotter,
    preview: Preview | NullPreview,
    cfg: AppConfig,
    stop: threading.Event,
    state: LoopState,
    store: StateStore | None = None,
    control: RunControl | None = None,
    dashboard: Dashboard | None = None,
) -> LoopState:
    control = control or RunControl()
    last_frame_at = time.monotonic()
    failures = 0
    while not stop.is_set():
        if control.take_new_paper_request():
            state = _new_paper(cfg, state, store, dashboard)
        if control.paused:
            control.set_phase(Phase.PAUSED)
            stop.wait(_PAUSE_POLL_S)
            continue
        frame = camera.read()
        if frame is None:
            control.set_phase(Phase.WAITING_CAMERA)
            if time.monotonic() - last_frame_at > cfg.camera.timeout_s:
                raise CameraError(f"no camera frame for {cfg.camera.timeout_s:.0f} s")
            stop.wait(_NO_FRAME_SLEEP_S)
            continue
        last_frame_at = time.monotonic()
        try:
            state = run_cycle(frame, state, cfg, plotter, preview, stop, store, control, dashboard)
            failures = 0
        except PlotterError:
            raise
        except Exception:  # noqa: BLE001 - a bad frame must not kill an unattended piece
            failures += 1
            log.exception("cycle %d failed (%d in a row)", state.cycle, failures)
            if failures >= _MAX_CONSECUTIVE_CYCLE_FAILURES:
                raise CycleError(f"{failures} consecutive cycles failed; giving up") from None
            stop.wait(_CYCLE_FAILURE_SLEEP_S)
    return state


def _new_paper(cfg: AppConfig, state: LoopState, store: StateStore | None, dashboard: Dashboard | None) -> LoopState:
    log.info("new paper: ink memory cleared after %.1f m; waiting for the operator to resume", state.drawn_mm / 1000)
    fresh = LoopState(InkCanvas.empty(cfg.paper, cfg.drawing.ink_px_per_mm), (0.0, 0.0), 0, 0.0, False)
    _persist(store, fresh)
    if dashboard is not None:
        dashboard.update(np.zeros((1, 1), dtype=np.uint8), fresh.canvas, _status(cfg, fresh, 0, 0))
    return fresh


def run_cycle(
    frame: np.ndarray,
    state: LoopState,
    cfg: AppConfig,
    plotter: Plotter,
    preview: Preview | NullPreview,
    stop: threading.Event,
    store: StateStore | None = None,
    control: RunControl | None = None,
    dashboard: Dashboard | None = None,
) -> LoopState:
    control = control or RunControl()
    edges = detect_edges(frame, cfg.vectorize)
    candidates = vectorize_edges(edges, cfg.vectorize, cfg.paper, cfg.camera.mirror)
    selected = select_strokes(
        candidates, state.canvas, cfg.drawing.length_budget_mm, cfg.drawing.min_novelty, cfg.drawing.ink_radius_mm
    )
    ordered = order_strokes(selected, state.pen)
    log.info("cycle %d: %d candidates, %d strokes to draw, coverage %.1f%%",
             state.cycle, len(candidates), len(ordered), state.canvas.coverage() * 100)

    canvas, pen, drawn = state.canvas, state.pen, state.drawn_mm
    control.set_phase(Phase.DRAWING if ordered else Phase.IDLE)
    for stroke in ordered:
        if stop.is_set() or control.paused:
            break  # the pen is up between strokes; remaining strokes are re-planned on resume
        plotter.draw_stroke(stroke)
        canvas = canvas.with_strokes([stroke], cfg.drawing.ink_radius_mm)
        pen = stroke[-1]
        drawn += polyline_length(stroke)
        progress = LoopState(canvas, pen, state.cycle, drawn, state.saturated)
        _persist(store, progress)  # survive a crash mid-cycle
        if _publish(preview, dashboard, frame, edges, canvas, _status(cfg, progress, len(candidates), len(ordered))):
            log.info("quit requested from preview window")
            stop.set()

    if not ordered:
        idle = LoopState(canvas, pen, state.cycle, drawn, state.saturated)
        if _publish(preview, dashboard, frame, edges, canvas, _status(cfg, idle, len(candidates), 0)):
            stop.set()
        stop.wait(cfg.drawing.idle_sleep_s)

    advanced = LoopState(canvas, pen, state.cycle + 1, drawn, state.saturated)
    next_state = _apply_saturation_policy(advanced, cfg.drawing, stop)
    if ordered or next_state.canvas is not state.canvas:
        _persist(store, next_state)
    return next_state


def _publish(
    preview: Preview | NullPreview,
    dashboard: Dashboard | None,
    frame: np.ndarray,
    edges: np.ndarray,
    canvas: InkCanvas,
    status: StatusInfo,
) -> bool:
    """Preview and dashboard are cosmetic: a failure there must never lose track of drawn strokes."""
    quit_requested = False
    try:
        quit_requested = preview.show(frame, edges, canvas, status)
    except Exception as error:  # noqa: BLE001
        log.warning("preview failed: %s", error)
    if dashboard is not None:
        try:
            dashboard.update(edges, canvas, status)
        except Exception as error:  # noqa: BLE001
            log.warning("dashboard update failed: %s", error)
    return quit_requested


def _apply_saturation_policy(state: LoopState, cfg: DrawingConfig, stop: threading.Event) -> LoopState:
    coverage = state.canvas.coverage()
    if coverage < cfg.saturation_threshold:
        return replace(state, saturated=False)
    if cfg.saturation_policy == "clear":
        log.info("paper is %.0f%% covered; clearing ink memory (change the paper now)", coverage * 100)
        return replace(state, canvas=state.canvas.cleared(), saturated=False)
    if cfg.saturation_policy == "stop":
        log.info("paper is %.0f%% covered; stopping", coverage * 100)
        stop.set()
        return replace(state, saturated=True)
    if not state.saturated:
        log.info("paper is %.0f%% covered; continuing, only novel strokes will be drawn", coverage * 100)
    return replace(state, saturated=True)


def _status(cfg: AppConfig, state: LoopState, candidates: int, strokes: int) -> StatusInfo:
    return StatusInfo(cycle=state.cycle, candidates=candidates, strokes=strokes, coverage=state.canvas.coverage(),
                      drawn_mm=state.drawn_mm, dry_run=cfg.dry_run, saturated=state.saturated)


def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(signum: int, _frame: object) -> None:
        log.info("signal %d received; finishing current stroke and stopping", signum)
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def parse_args(argv: list[str] | None = None) -> AppConfig:
    defaults = AppConfig()
    parser = argparse.ArgumentParser(description="Draw what the webcam sees, continuously, on an AxiDraw.")
    parser.add_argument("--dry-run", action="store_true", help="simulate the plotter (no hardware needed)")
    parser.add_argument("--dry-run-speed", type=float, default=defaults.axidraw.dry_run_speed_mm_s,
                        help="simulated pen speed in mm/s for --dry-run")
    parser.add_argument("--state-dir", default=defaults.state_dir,
                        help="directory where the ink memory is saved so a restart continues on the same paper")
    parser.add_argument("--no-persist", action="store_true", help="do not save the ink memory")
    parser.add_argument("--fresh", action="store_true", help="discard the saved ink memory (new sheet of paper)")
    parser.add_argument("--web-port", type=int, default=defaults.web_port,
                        help="port of the dashboard (camera view and pause/resume controls)")
    parser.add_argument("--no-web", action="store_true", help="do not serve the dashboard")
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument("--preview", dest="preview", action="store_true", default=None)
    preview.add_argument("--no-preview", dest="preview", action="store_false")

    cam = parser.add_argument_group("camera")
    source = cam.add_mutually_exclusive_group()
    source.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    source.add_argument("--source", default=None,
                        help="device path (/dev/video0, /dev/v4l/by-id/...), or a video / image file for testing")
    cam.add_argument("--width", type=int, default=defaults.camera.width)
    cam.add_argument("--height", type=int, default=defaults.camera.height)
    cam.add_argument("--mirror", action="store_true", help="flip left/right, like a mirror")
    cam.add_argument("--warmup", type=float, default=defaults.camera.warmup_s,
                     help="seconds of frames to discard at start while exposure settles")

    paper = parser.add_argument_group("paper")
    paper.add_argument("--paper", choices=sorted(PAPER_PRESETS), default="a4")
    paper.add_argument("--margin", type=float, default=defaults.paper.margin_mm, help="margin in mm")

    vec = parser.add_argument_group("vectorize")
    vec.add_argument("--canny", type=int, nargs=2, metavar=("LOW", "HIGH"),
                     default=(defaults.vectorize.canny_low, defaults.vectorize.canny_high))
    vec.add_argument("--blur", type=int, default=defaults.vectorize.blur_kernel, help="gaussian blur kernel (odd)")
    vec.add_argument("--min-length", type=float, default=defaults.vectorize.min_length_mm,
                     help="drop strokes shorter than this (mm)")

    draw = parser.add_argument_group("drawing")
    draw.add_argument("--budget", type=float, default=defaults.drawing.length_budget_mm,
                      help="mm of line per cycle")
    draw.add_argument("--min-novelty", type=float, default=defaults.drawing.min_novelty,
                      help="0..1; skip strokes mostly already drawn")
    draw.add_argument("--ink-radius", type=float, default=defaults.drawing.ink_radius_mm,
                      help="mm; how wide a drawn line 'claims' the paper")
    draw.add_argument("--saturation-threshold", type=float, default=defaults.drawing.saturation_threshold)
    draw.add_argument("--saturation-policy", choices=("continue", "stop", "clear"),
                      default=defaults.drawing.saturation_policy)
    draw.add_argument("--idle-sleep", type=float, default=defaults.drawing.idle_sleep_s,
                      help="seconds to wait when nothing new to draw")

    axi = parser.add_argument_group("axidraw")
    axi.add_argument("--speed", type=int, default=defaults.axidraw.speed_pendown, help="pen-down speed, percent")
    axi.add_argument("--pen-up", type=int, default=defaults.axidraw.pen_pos_up, help="pen-up height, percent")
    axi.add_argument("--pen-down", type=int, default=defaults.axidraw.pen_pos_down,
                     help="pen-down height, percent")
    axi.add_argument("--port", default=None, help="serial port, e.g. /dev/ttyACM0 (default: auto)")

    args = parser.parse_args(argv)
    width_mm, height_mm, model = PAPER_PRESETS[args.paper]
    _validate(parser, args, width_mm, height_mm)
    return AppConfig(
        paper=PaperConfig(width_mm=width_mm, height_mm=height_mm, margin_mm=args.margin),
        camera=replace(defaults.camera, source=args.source if args.source is not None else args.camera,
                       width=args.width, height=args.height, mirror=args.mirror, warmup_s=args.warmup),
        vectorize=replace(defaults.vectorize, blur_kernel=args.blur, canny_low=args.canny[0],
                          canny_high=args.canny[1], min_length_mm=args.min_length),
        drawing=replace(defaults.drawing, length_budget_mm=args.budget, ink_radius_mm=args.ink_radius,
                        min_novelty=args.min_novelty, saturation_threshold=args.saturation_threshold,
                        saturation_policy=args.saturation_policy, idle_sleep_s=args.idle_sleep),
        axidraw=replace(defaults.axidraw, model=model, speed_pendown=args.speed, pen_pos_up=args.pen_up,
                        pen_pos_down=args.pen_down, port=args.port, dry_run_speed_mm_s=args.dry_run_speed),
        dry_run=args.dry_run,
        preview=args.preview,
        state_dir=None if args.no_persist else args.state_dir,
        fresh_start=args.fresh,
        web_port=None if args.no_web else args.web_port,
    )


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace, width_mm: float, height_mm: float) -> None:
    checks = [
        (0 <= args.margin < min(width_mm, height_mm) / 2, "--margin must leave a drawable area"),
        (args.width > 0 and args.height > 0, "--width and --height must be positive"),
        (args.warmup >= 0, "--warmup must be >= 0"),
        (0 < args.canny[0] < args.canny[1], "--canny needs 0 < LOW < HIGH"),
        (args.blur > 0, "--blur must be positive"),
        (args.min_length >= 0, "--min-length must be >= 0"),
        (args.budget > 0, "--budget must be positive"),
        (0.0 <= args.min_novelty <= 1.0, "--min-novelty must be within 0..1"),
        (args.ink_radius > 0, "--ink-radius must be positive"),
        (0.0 < args.saturation_threshold <= 1.0, "--saturation-threshold must be within 0..1"),
        (args.idle_sleep >= 0, "--idle-sleep must be >= 0"),
        (1 <= args.speed <= 100, "--speed must be within 1..100"),
        (0 <= args.pen_down < args.pen_up <= 100, "--pen-down must be below --pen-up, both within 0..100"),
        (args.dry_run_speed > 0, "--dry-run-speed must be positive"),
        (1 <= args.web_port <= 65535, "--web-port must be within 1..65535"),
    ]
    for ok, message in checks:
        if not ok:
            parser.error(message)


if __name__ == "__main__":
    raise SystemExit(main())
