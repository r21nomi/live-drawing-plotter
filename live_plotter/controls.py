"""Operator controls shared between the main loop and the dashboard thread.

This is deliberately the one piece of mutable shared state: a few flags behind a lock.
The main loop polls it between strokes; the dashboard sets it from HTTP requests.
"""

from __future__ import annotations

import threading
from enum import Enum


class Phase(str, Enum):
    STARTING = "starting"
    WAITING_CAMERA = "waiting_camera"
    DRAWING = "drawing"
    IDLE = "idle"  # nothing new to draw
    PAUSED = "paused"


class RunControl:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._new_paper = False
        self._phase = Phase.STARTING

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

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"phase": self._phase.value, "paused": self._paused}
