# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from warpforge.render import PREVIEW_MAX_SIDE, preview_scale, preview_size


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((800, 600), (800, 600)),  # small layers are never upscaled
        ((1024, 1024), (1024, 1024)),
        ((2048, 1024), (1024, 512)),
        ((1000, 4000), (256, 1024)),
        ((8000, 8000), (1024, 1024)),
        ((10000, 1), (1024, 1)),  # extreme aspect ratio keeps at least 1 px
    ],
)
def test_preview_size(size: tuple[int, int], expected: tuple[int, int]) -> None:
    assert preview_size(*size) == expected


def test_preview_longest_side_never_exceeds_limit() -> None:
    for w, h in [(1919, 1080), (4001, 3), (1025, 1025), (7777, 5555)]:
        pw, ph = preview_size(w, h)
        assert max(pw, ph) <= PREVIEW_MAX_SIDE


def test_preview_scale_custom_limit() -> None:
    assert preview_scale(2000, 1000, max_side=500) == 0.25


@pytest.mark.parametrize("args", [(0, 10), (10, 0), (10, 10, 0)])
def test_preview_scale_rejects_bad_input(args: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        preview_scale(*args)
