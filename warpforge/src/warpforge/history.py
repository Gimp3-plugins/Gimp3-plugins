# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo/redo inside the dialog.

One entry per finished gesture (a whole drag, a reset), never per mouse
motion. GIMP's own undo stack only sees the final commit.
"""

from __future__ import annotations

import copy
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_LIMIT = 100


class EditHistory(Generic[T]):
    def __init__(self, limit: int = DEFAULT_LIMIT) -> None:
        self._undo: list[T] = []
        self._redo: list[T] = []
        self._limit = limit

    def record(self, state_before: T) -> None:
        """Remember the state as it was before a gesture."""
        self._undo.append(copy.deepcopy(state_before))
        if len(self._undo) > self._limit:
            del self._undo[0]
        self._redo.clear()

    def undo(self, current: T) -> T | None:
        if not self._undo:
            return None
        self._redo.append(copy.deepcopy(current))
        return self._undo.pop()

    def redo(self, current: T) -> T | None:
        if not self._redo:
            return None
        self._undo.append(copy.deepcopy(current))
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
