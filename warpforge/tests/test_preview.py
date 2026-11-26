# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from warpforge.preview import PreviewWorker


def make_worker(render: Callable[[int], int]) -> tuple[PreviewWorker[int, int], queue.Queue[Any]]:
    """Worker whose 'main loop' is a queue we drain by hand."""
    main_loop: queue.Queue[Callable[[], Any]] = queue.Queue()
    results: queue.Queue[Any] = queue.Queue()
    worker = PreviewWorker(render, lambda g, r, e, t: results.put((g, r, e)), main_loop.put)

    def pump() -> None:
        while True:
            callback = main_loop.get()
            if callback is None:
                return
            callback()

    threading.Thread(target=pump, daemon=True).start()
    return worker, results


def test_renders_and_delivers_on_main_loop() -> None:
    worker, results = make_worker(lambda job: job * 2)
    generation = worker.submit(21)
    assert results.get(timeout=2) == (generation, 42, None)
    worker.close()


def test_only_newest_pending_job_is_rendered() -> None:
    gate = threading.Event()
    started = threading.Event()
    rendered: list[int] = []

    def render(job: int) -> int:
        if job == 0:
            started.set()
            gate.wait(2)  # hold the worker busy while more jobs arrive
        rendered.append(job)
        return job

    worker, results = make_worker(render)
    worker.submit(0)
    assert started.wait(2)
    for job in range(1, 6):
        worker.submit(job)
    gate.set()
    assert results.get(timeout=2)[1] == 0
    assert results.get(timeout=2)[1] == 5
    assert rendered == [0, 5]  # jobs 1-4 were superseded, never rendered
    worker.close()


def test_errors_are_reported_not_raised() -> None:
    def render(job: int) -> int:
        raise RuntimeError("boom")

    worker, results = make_worker(render)
    worker.submit(1)
    _generation, result, error = results.get(timeout=2)
    assert result is None and isinstance(error, RuntimeError)
    worker.submit(2)  # still alive
    assert results.get(timeout=2)[2] is not None
    worker.close()
