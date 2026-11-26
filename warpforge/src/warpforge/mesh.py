# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh Warp model: a regular grid whose vertices the user moves.

``columns``/``rows`` count cells, so a 4x4 mesh has 5x5 vertices. Vertices are
stored row-major in layer pixel coordinates. Each cell is split into two
triangles; the warp maps every target triangle affinely back onto its source
triangle.

Constraints keep the result well-behaved:

* corners never move, other border vertices slide along their border, so the
  warped image always covers the whole layer;
* "clamp to bounds" keeps interior vertices inside the layer;
* a move that would flip or collapse a triangle is shortened to the furthest
  valid position along the drag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from warpforge.geometry import Point, clamp, signed_area

# A triangle may shrink to this fraction of its original area, no further.
MIN_AREA_RATIO = 0.02
_SEARCH_STEPS = 24


@lru_cache(maxsize=64)
def triangulate(columns: int, rows: int) -> tuple[tuple[int, int, int], ...]:
    """Vertex-index triangles, two per cell, all with positive orientation."""
    stride = columns + 1
    tris: list[tuple[int, int, int]] = []
    for r in range(rows):
        for c in range(columns):
            a = r * stride + c
            b, d = a + 1, a + stride
            tris.append((a, b, d + 1))
            tris.append((a, d + 1, d))
    return tuple(tris)


@lru_cache(maxsize=64)
def _vertex_triangles(columns: int, rows: int) -> tuple[tuple[int, ...], ...]:
    """For each vertex, the indices of the triangles that use it."""
    result: list[list[int]] = [[] for _ in range((columns + 1) * (rows + 1))]
    for t, tri in enumerate(triangulate(columns, rows)):
        for v in tri:
            result[v].append(t)
    return tuple(tuple(ts) for ts in result)


def regular_grid(columns: int, rows: int, width: float, height: float) -> list[Point]:
    return [
        (width * c / columns, height * r / rows)
        for r in range(rows + 1)
        for c in range(columns + 1)
    ]


@dataclass
class Mesh:
    columns: int
    rows: int
    width: float
    height: float
    vertices: list[Point] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.columns < 1 or self.rows < 1:
            raise ValueError("a mesh needs at least one cell in each direction")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("mesh size must be positive")
        if not self.vertices:
            self.vertices = self.source_vertices()
        expected = (self.columns + 1) * (self.rows + 1)
        if len(self.vertices) != expected:
            raise ValueError(f"mesh needs {expected} vertices, got {len(self.vertices)}")

    # -- structure --------------------------------------------------------

    @property
    def stride(self) -> int:
        return self.columns + 1

    def index(self, row: int, column: int) -> int:
        return row * self.stride + column

    def position(self, index: int) -> tuple[int, int]:
        """(row, column) of a vertex index."""
        return divmod(index, self.stride)

    def source_vertices(self) -> list[Point]:
        return regular_grid(self.columns, self.rows, self.width, self.height)

    def triangles(self) -> tuple[tuple[int, int, int], ...]:
        return triangulate(self.columns, self.rows)

    def copy(self) -> Mesh:
        return Mesh(self.columns, self.rows, self.width, self.height, list(self.vertices))

    def scaled(self, width: float, height: float) -> Mesh:
        """The same deformation for a layer of a different size."""
        sx, sy = width / self.width, height / self.height
        return Mesh(self.columns, self.rows, width, height,
                    [(x * sx, y * sy) for x, y in self.vertices])

    def is_identity(self, tolerance: float = 1e-6) -> bool:
        return all(
            abs(x - sx) <= tolerance and abs(y - sy) <= tolerance
            for (x, y), (sx, sy) in zip(self.vertices, self.source_vertices(), strict=True)
        )

    # -- validity ---------------------------------------------------------

    def _min_area(self) -> float:
        # signed_area() returns twice the area; a source triangle is half a cell,
        # so twice its area equals the cell area.
        cell_area = (self.width / self.columns) * (self.height / self.rows)
        return cell_area * MIN_AREA_RATIO

    def triangle_ok(self, tri: tuple[int, int, int], vertices: list[Point] | None = None) -> bool:
        v = self.vertices if vertices is None else vertices
        return signed_area(v[tri[0]], v[tri[1]], v[tri[2]]) >= self._min_area()

    def inverted_triangles(self) -> list[int]:
        """Indices of triangles that are flipped or collapsed."""
        return [t for t, tri in enumerate(self.triangles()) if not self.triangle_ok(tri)]

    def is_valid(self) -> bool:
        return not self.inverted_triangles()

    def _valid_around(self, index: int, point: Point) -> bool:
        trial = list(self.vertices)
        trial[index] = point
        tris = self.triangles()
        return all(
            self.triangle_ok(tris[t], trial)
            for t in _vertex_triangles(self.columns, self.rows)[index]
        )

    # -- editing ----------------------------------------------------------

    def constrain(self, index: int, point: Point, clamp_to_bounds: bool = True) -> Point:
        """Apply the border rules (and optionally the layer bounds) to a position."""
        row, col = self.position(index)
        x, y = point
        on_left, on_right = col == 0, col == self.columns
        on_top, on_bottom = row == 0, row == self.rows
        if (on_left or on_right) and (on_top or on_bottom):
            return self.source_vertices()[index]
        if on_left or on_right:
            return (0.0 if on_left else self.width, clamp(y, 0.0, self.height))
        if on_top or on_bottom:
            return (clamp(x, 0.0, self.width), 0.0 if on_top else self.height)
        if clamp_to_bounds:
            return clamp(x, 0.0, self.width), clamp(y, 0.0, self.height)
        return x, y

    def move_vertex(self, index: int, target: Point, clamp_to_bounds: bool = True) -> Point:
        """Move a vertex as close to ``target`` as the rules allow; return where it went."""
        target = self.constrain(index, target, clamp_to_bounds)
        start = self.vertices[index]
        if self._valid_around(index, target) or not self._valid_around(index, start):
            # Either fine, or the mesh was already broken here (e.g. from a preset):
            # do not trap the vertex.
            self.vertices[index] = target
            return target
        lo, hi = 0.0, 1.0
        for _ in range(_SEARCH_STEPS):
            mid = (lo + hi) / 2
            if self._valid_around(index, _lerp(start, target, mid)):
                lo = mid
            else:
                hi = mid
        result = _lerp(start, target, lo)
        self.vertices[index] = result
        return result

    def nearest_vertex(self, point: Point, max_distance: float) -> int | None:
        best, best_d2 = None, max_distance * max_distance
        for i, (x, y) in enumerate(self.vertices):
            d2 = (x - point[0]) ** 2 + (y - point[1]) ** 2
            if d2 <= best_d2:
                best, best_d2 = i, d2
        return best

    def reset(self) -> None:
        self.vertices = self.source_vertices()

    def flat_vertices(self) -> list[float]:
        return [coord for vertex in self.vertices for coord in vertex]

    def flat_source_vertices(self) -> list[float]:
        return [coord for vertex in self.source_vertices() for coord in vertex]


def _lerp(a: Point, b: Point, t: float) -> Point:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
