"""Pen plotter backends: the real AxiDraw and a dry-run stand-in."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from .config import AxiDrawConfig, PaperConfig
from .geometry import Point, Polyline, distance, polyline_length

log = logging.getLogger(__name__)

_UNITS_MM = 2
_HOME: Point = (0.0, 0.0)


class PlotterError(RuntimeError):
    """The plotter is unusable (not connected, not found). Safe to retry after a restart."""


class PlotterStopped(PlotterError):
    """The AxiDraw stopped mid-run (pause button, lost USB).

    The carriage position is now unknown to the firmware, so the piece must not simply
    restart: a human has to re-home the carriage first.
    """


class Plotter(Protocol):
    def connect(self) -> None: ...

    def draw_stroke(self, stroke: Polyline) -> None: ...

    def finish(self) -> None: ...


def _clamped(stroke: Polyline, paper: PaperConfig) -> Polyline:
    """Never send the pen outside the paper, whatever the planner produced."""
    return tuple(
        (min(max(x, 0.0), paper.width_mm), min(max(y, 0.0), paper.height_mm)) for x, y in stroke
    )


def _make_axidraw() -> Any:
    try:
        from pyaxidraw import axidraw
    except ImportError as error:
        raise PlotterError(
            "pyaxidraw is not installed; run `uv sync --extra axidraw` (or use --dry-run)"
        ) from error
    return axidraw.AxiDraw()


class AxiDrawPlotter:
    """Drives an AxiDraw through the official pyaxidraw interactive API, in mm."""

    def __init__(
        self,
        cfg: AxiDrawConfig,
        paper: PaperConfig,
        factory: Callable[[], Any] = _make_axidraw,
    ) -> None:
        self._cfg = cfg
        self._paper = paper
        self._factory = factory
        self._ad: Any = None

    def connect(self) -> None:
        ad = self._factory()
        ad.interactive()
        ad.options.units = _UNITS_MM
        ad.options.model = self._cfg.model
        ad.options.speed_pendown = self._cfg.speed_pendown
        ad.options.speed_penup = self._cfg.speed_penup
        ad.options.pen_pos_up = self._cfg.pen_pos_up
        ad.options.pen_pos_down = self._cfg.pen_pos_down
        if self._cfg.port:
            ad.options.port = self._cfg.port
        # Make pyaxidraw raise instead of silently entering a "stopped" state in which
        # draw_path returns without moving anything.
        ad.errors.connect = True
        ad.errors.button = True  # the pause button on the AxiDraw stops the piece
        ad.errors.keyboard = True
        ad.errors.disconnect = True
        try:
            connected = ad.connect()
        except RuntimeError as error:
            raise PlotterError(f"could not connect to AxiDraw: {error}") from error
        if not connected:
            raise PlotterError("could not connect to AxiDraw (check USB cable and power)")
        self._ad = ad
        log.info("AxiDraw connected (model %d, pen-down speed %d%%)", self._cfg.model, self._cfg.speed_pendown)

    def draw_stroke(self, stroke: Polyline) -> None:
        if self._ad is None:
            raise PlotterError("draw_stroke called before connect")
        points = [[x, y] for x, y in _clamped(stroke, self._paper)]
        if len(points) < 2:
            return
        try:
            self._ad.draw_path(points)
        except RuntimeError as error:
            raise PlotterStopped(f"AxiDraw stopped: {error}") from error
        code = getattr(self._ad.errors, "code", 0)
        if code or getattr(self._ad.plot_status, "stopped", False):
            raise PlotterStopped(f"AxiDraw stopped (error code {code}); re-home the carriage before restarting")

    def finish(self) -> None:
        if self._ad is None:
            return
        ad, self._ad = self._ad, None
        try:
            ad.penup()
            ad.moveto(*_HOME)
        except Exception as error:  # noqa: BLE001 - anything here must not block disconnect
            log.warning("could not return home cleanly: %s", error)
        try:
            ad.disconnect()
            log.info("AxiDraw disconnected")
        except Exception as error:  # noqa: BLE001
            log.warning("disconnect failed: %s", error)


class DryRunPlotter:
    """No hardware: sleeps for roughly the time the pen would take and logs each stroke."""

    def __init__(self, cfg: AxiDrawConfig, paper: PaperConfig) -> None:
        self._speed = cfg.dry_run_speed_mm_s
        self._paper = paper
        self._position: Point = _HOME

    def connect(self) -> None:
        log.info("dry run: no AxiDraw connected, simulating %.0f mm/s", self._speed)

    def draw_stroke(self, stroke: Polyline) -> None:
        clamped = _clamped(stroke, self._paper)
        if len(clamped) < 2:
            return
        travel = distance(self._position, clamped[0]) + polyline_length(clamped)
        time.sleep(travel / self._speed)
        self._position = clamped[-1]

    def finish(self) -> None:
        self._position = _HOME
        log.info("dry run: finished")
