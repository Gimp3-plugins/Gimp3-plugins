# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from warpforge.geometry import (
    affine_from_triangles,
    barycentric,
    bounding_box,
    clamp,
    contains,
    signed_area,
)

TRI = ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0))


def test_signed_area_orientation() -> None:
    assert signed_area(*TRI) == 100.0
    assert signed_area(TRI[0], TRI[2], TRI[1]) == -100.0


def test_barycentric_of_vertices_and_centroid() -> None:
    assert barycentric((0.0, 0.0), *TRI) == pytest.approx((1, 0, 0))
    assert barycentric((10.0, 0.0), *TRI) == pytest.approx((0, 1, 0))
    centroid = (10 / 3, 10 / 3)
    assert barycentric(centroid, *TRI) == pytest.approx((1 / 3, 1 / 3, 1 / 3))


def test_degenerate_triangle() -> None:
    line = ((0.0, 0.0), (1.0, 1.0), (2.0, 2.0))
    assert barycentric((1.0, 0.0), *line) is None
    assert affine_from_triangles(line, line) is None


def test_contains() -> None:
    assert contains((1.0, 1.0), *TRI)
    assert contains((5.0, 5.0), *TRI)  # on the hypotenuse
    assert not contains((6.0, 6.0), *TRI)


def test_affine_maps_vertices_and_midpoints() -> None:
    src = ((5.0, 5.0), (25.0, 1.0), (2.0, 40.0))
    mapping = affine_from_triangles(TRI, src)
    assert mapping is not None
    fx, fy = mapping

    def apply(p: tuple[float, float]) -> tuple[float, float]:
        return (fx[0] * p[0] + fx[1] * p[1] + fx[2], fy[0] * p[0] + fy[1] * p[1] + fy[2])

    for d, s in zip(TRI, src, strict=True):
        assert apply(d) == pytest.approx(s)
    assert apply((5.0, 0.0)) == pytest.approx((15.0, 3.0))  # midpoint -> midpoint


def test_bounding_box_and_clamp() -> None:
    assert bounding_box([(1, 5), (-2, 3), (4, -1)]) == (-2, -1, 4, 5)
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 0, 3) == 2
