# SPDX-License-Identifier: GPL-3.0-or-later
"""Background preview rendering.

The GTK main loop must never wait for a warp. A single worker thread renders
the *newest* request only: while it works, newer requests replace older
pending ones, so a fast drag never builds a backlog. Results are handed back
through ``schedule`` (``GLib.idle_add`` in the dialog), i.e. on the main thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Generic, TypeVar

log = logging.getLogger(__name__)

J = TypeVar("J")
R = TypeVar("R")


class PreviewWorker(Generic[J, R]):
    def __init__(
        self,
        render: Callable[[J], R],
        deliver: Callable[[int, R | None, Exception | None, float], None],
        schedule: Callable[[Callable[[], Any]], Any],
    ) -> None:
        self._render = render
        self._deliver = deliver
        self._schedule = schedule
        self._cond = threading.Condition()
        self._pending: tuple[int, J] | None = None
        self._generation = 0
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="warpforge-preview", daemon=True)
        self._thread.start()

    def submit(self, job: J) -> int:
        """Queue a render; returns its generation number."""
        with self._cond:
            self._generation += 1
            self._pending = (self._generation, job)
            self._cond.notify()
            return self._generation

    @property
    def latest(self) -> int:
        return self._generation

    def close(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._closed = True
            self._pending = None
            self._cond.notify()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                assert self._pending is not None
                generation, job = self._pending
                self._pending = None
            start = time.perf_counter()
            result: R | None = None
            error: Exception | None = None
            try:
                result = self._render(job)
            except Exception as exc:  # reported to the UI, never kills the worker
                log.exception("Preview render failed")
                error = exc
            elapsed = time.perf_counter() - start

            def deliver_on_main(g: int = generation, r: R | None = result,
                                e: Exception | None = error, t: float = elapsed) -> bool:
                self._deliver(g, r, e, t)
                return False  # one-shot idle callback

            self._schedule(deliver_on_main)
