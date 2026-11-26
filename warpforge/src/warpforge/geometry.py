# SPDX-License-Identifier: GPL-3.0-or-later
"""Small 2-D geometry helpers shared by the mesh model and the Python backend.

Coordinates are layer pixels with y pointing down. A triangle whose vertices
are listed clockwise on screen has a positive :func:`signed_area`.
"""

from __future__ import annotations

from collections.abc import Iterable

Point = tuple[float, float]


def signed_area(a: Point, b: Point, c: Point) -> float:
    """Twice the signed area of triangle abc (positive = clockwise on screen)."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def barycentric(p: Point, a: Point, b: Point, c: Point) -> tuple[float, float, float] | None:
    """Barycentric weights of ``p`` in triangle abc, or ``None`` if degenerate."""
    area = signed_area(a, b, c)
    if area == 0.0:
        return None
    w0 = signed_area(p, b, c) / area
    w1 = signed_area(a, p, c) / area
    return w0, w1, 1.0 - w0 - w1


Linear = tuple[float, float, float]
"""Coefficients (a, b, c) of the affine function f(x, y) = a*x + b*y + c."""


def barycentric_functions(a: Point, b: Point, c: Point) -> tuple[Linear, Linear, Linear] | None:
    """The three barycentric weights of triangle abc as affine functions of (x, y)."""
    area = signed_area(a, b, c)
    if abs(area) < 1e-12:
        return None
    (x0, y0), (x1, y1), (x2, y2) = a, b, c
    return (
        ((y1 - y2) / area, (x2 - x1) / area, (x1 * y2 - x2 * y1) / area),
        ((y2 - y0) / area, (x0 - x2) / area, (x2 * y0 - x0 * y2) / area),
        ((y0 - y1) / area, (x1 - x0) / area, (x0 * y1 - x1 * y0) / area),
    )


def affine_from_triangles(dst: tuple[Point, Point, Point],
                          src: tuple[Point, Point, Point]) -> tuple[Linear, Linear] | None:
    """Affine map (fx, fy) sending each ``dst`` vertex onto the matching ``src`` vertex."""
    weights = barycentric_functions(*dst)
    if weights is None:
        return None
    fx = tuple(sum(w[k] * s[0] for w, s in zip(weights, src, strict=True)) for k in range(3))
    fy = tuple(sum(w[k] * s[1] for w, s in zip(weights, src, strict=True)) for k in range(3))
    return (fx[0], fx[1], fx[2]), (fy[0], fy[1], fy[2])


def contains(p: Point, a: Point, b: Point, c: Point, eps: float = 1e-9) -> bool:
    weights = barycentric(p, a, b, c)
    return weights is not None and min(weights) >= -eps


def bounding_box(points: Iterable[Point]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of the points."""
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value
