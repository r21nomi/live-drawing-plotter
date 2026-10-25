"""Operator controls shared between the main loop and the dashboard thread.

This is deliberately the one piece of mutable shared state: a few flags behind a lock.
The main loop polls it between strokes; the dashboard sets it from HTTP requests.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from enum import Enum


class Phase(str, Enum):
    STARTING = "starting"
    WAITING_CAMERA = "waiting_camera"
    WAITING_PLOTTER = "waiting_plotter"
    DRAWING = "drawing"
    IDLE = "idle"  # nothing new to draw
    PAUSED = "paused"
    READY = "ready"  # waiting for the start button; nothing drawn on this sheet yet


class ProblemKind(str, Enum):
    CAMERA = "camera"  # cannot open / lost the camera; retrying
    PLOTTER = "plotter"  # cannot connect to the AxiDraw; retrying
    PLOTTER_STOPPED = "plotter_stopped"  # pause button / USB loss: re-home by hand, then press start
    CYCLES = "cycles"  # image processing keeps failing


@dataclass(frozen=True)
class Problem:
    kind: ProblemKind
    detail: str


class RunControl:
    def __init__(self, paused: bool = False) -> None:
        self._lock = threading.Lock()
        self._paused = paused
        self._new_paper = False
        self._phase = Phase.STARTING
        self._problem: Problem | None = None

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def phase(self) -> Phase:
        with self._lock:
            return self._phase

    def request_pause(self) -> None:
        with self._lock:
            self._paused = True

    def request_resume(self) -> None:
        with self._lock:
            self._paused = False

    def request_new_paper(self) -> None:
        """Pause and ask the main loop to forget what was drawn. Resume starts the new sheet."""
        with self._lock:
            self._paused = True
            self._new_paper = True

    def take_new_paper_request(self) -> bool:
        """True once per request; the caller then clears the ink memory."""
        with self._lock:
            requested, self._new_paper = self._new_paper, False
            return requested

    def set_phase(self, phase: Phase) -> None:
        with self._lock:
            self._phase = phase

    @property
    def problem(self) -> Problem | None:
        with self._lock:
            return self._problem

    def set_problem(self, kind: ProblemKind, detail: str) -> None:
        with self._lock:
            self._problem = Problem(kind, detail)

    def clear_problem(self) -> None:
        with self._lock:
            self._problem = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            problem = None if self._problem is None else {**asdict(self._problem), "kind": self._problem.kind.value}
            return {"phase": self._phase.value, "paused": self._paused, "problem": problem}
