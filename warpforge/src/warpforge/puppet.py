# SPDX-License-Identifier: GPL-3.0-or-later
"""Puppet Warp model and the reference deformation (pure Python).

Pins
----
A pin has a ``source`` (where it was put on the original layer) and a
``target`` (where the user dragged it). Pins can be linked into a *rigid
group*: dragging one pin moves the whole group, so linked pins keep their
relative distance and orientation, and the segments between them are held
rigid in the warp (see :meth:`PuppetRig.handles`).

Deformation
-----------
The warp is computed backwards, as the renderer needs it: for every output
point ``v`` it finds the source point to sample.

1. **Moving Least Squares** (Schaefer, McPhail, Warren 2006) with the roles of
   source and target swapped, i.e. fitted from targets to sources. For each
   ``v`` the best similarity (scale + rotation) and the best rigid (rotation
   only) transform of the handles around ``v`` are found in closed form with
   weights ``weight_i / |q_i - v|^2``. ``stiffness`` blends them: 0 lets
   regions scale, 1 keeps them as rigid as possible. MLS interpolates: at a
   pin's target the result is exactly the pin's source.
2. **Falloff.** Plain MLS moves the whole image when one pin moves. The MLS
   displacement is therefore multiplied by ``g(v) = 1 - prod_i (1 - k_i(v))``
   where ``k_i`` is a smooth bump ``(1 - d^2/r^2)^2`` of radius ``r`` around
   pin ``i``. ``g`` is 1 at every pin (exactness kept) and 0 farther than
   every pin's radius (the image stays put there).
3. **Fold guard.** The bump's slope is at most ``1.54 / r``; a pin moved by
   ``D`` with ``r < 1.54 D`` could fold the image over itself. The radius
   used for the falloff is therefore at least ``FOLD_GUARD * D``.

Backends compute this on a coarse grid of output points (a *source map*) and
interpolate it bilinearly per pixel; see :mod:`warpforge.render`.
"""

from __future__ import annotations

import copy
import itertools
import math
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from warpforge.geometry import Point, clamp

MIN_PIN_RADIUS = 4.0
MIN_PIN_WEIGHT = 0.1
MAX_PIN_WEIGHT = 10.0
FOLD_GUARD = 2.0
"""The falloff radius is at least this many times the pin's displacement."""
SEGMENT_SPACING = 12.0
"""Distance (layer px) between the extra handles that hold a rigid segment."""
MAX_SEGMENT_HANDLES = 32
_COINCIDENT = 1e-12  # squared distance below which v is on a handle


@dataclass
class Pin:
    id: str
    source: Point
    target: Point
    radius: float
    weight: float = 1.0
    pinned_rotation: bool = False
    """Reserved by the preset schema; not used by the warp yet."""
    pinned_scale: bool = False
    """Reserved by the preset schema; not used by the warp yet."""
    group: str | None = None
    """Rigid group id; pins sharing it move together."""

    @property
    def displacement(self) -> float:
        return math.hypot(self.target[0] - self.source[0], self.target[1] - self.source[1])

    @property
    def is_moved(self) -> bool:
        return self.displacement > 1e-9


@dataclass(frozen=True)
class Handle:
    """One MLS constraint: a pin, or a point on a rigid segment."""

    source: Point
    target: Point
    radius: float
    weight: float


@dataclass
class PuppetRig:
    """The pins of one layer, in layer pixel coordinates."""

    width: float
    height: float
    pins: list[Pin] = field(default_factory=list)
    _next_id: int = 1

    # -- queries -----------------------------------------------------------

    def pin(self, pin_id: str) -> Pin:
        for p in self.pins:
            if p.id == pin_id:
                return p
        raise KeyError(pin_id)

    def nearest_pin(self, point: Point, max_distance: float) -> Pin | None:
        """The pin whose target is closest to ``point``, within ``max_distance``."""
        best, best_d = None, max_distance
        for p in self.pins:
            d = math.hypot(p.target[0] - point[0], p.target[1] - point[1])
            if d <= best_d:
                best, best_d = p, d
        return best

    def group_members(self, pin: Pin) -> list[Pin]:
        if pin.group is None:
            return [pin]
        return [p for p in self.pins if p.group == pin.group]

    def is_identity(self) -> bool:
        return not any(p.is_moved for p in self.pins)

    def copy(self) -> PuppetRig:
        return copy.deepcopy(self)

    # -- editing ------------------------------------------------------------

    def add_pin(self, target: Point, radius: float, stiffness: float) -> Pin:
        """Add a pin where the user clicked on the *warped* image.

        Its source is what the current warp shows at that point, so adding a
        pin does not make the image jump.
        """
        source = inverse_point(prepare(self.handles()), stiffness, target[0], target[1])
        pin = Pin(id=f"pin-{self._next_id}", source=source, target=target,
                  radius=max(MIN_PIN_RADIUS, radius))
        self._next_id += 1
        self.pins.append(pin)
        return pin

    def remove(self, ids: Iterable[str]) -> None:
        doomed = set(ids)
        self.pins = [p for p in self.pins if p.id not in doomed]
        self._dissolve_small_groups()

    def move_pin(self, pin_id: str, target: Point, clamp_to_bounds: bool) -> None:
        """Move a pin (and its rigid group, by the same offset)."""
        pin = self.pin(pin_id)
        members = self.group_members(pin)
        dx, dy = target[0] - pin.target[0], target[1] - pin.target[1]
        if clamp_to_bounds:
            # Shrink the offset so that every member stays inside the layer.
            lo_x = max(-p.target[0] for p in members)
            hi_x = min(self.width - p.target[0] for p in members)
            lo_y = max(-p.target[1] for p in members)
            hi_y = min(self.height - p.target[1] for p in members)
            dx = clamp(dx, min(lo_x, 0.0), max(hi_x, 0.0))
            dy = clamp(dy, min(lo_y, 0.0), max(hi_y, 0.0))
        for p in members:
            p.target = (p.target[0] + dx, p.target[1] + dy)

    def restore(self, ids: Iterable[str] | None = None) -> None:
        """Put pins (all if ``ids`` is None) back where they were placed."""
        wanted = None if ids is None else set(ids)
        for p in self.pins:
            if wanted is None or p.id in wanted:
                p.target = p.source

    def set_radius(self, ids: Iterable[str], radius: float) -> None:
        wanted = set(ids)
        for p in self.pins:
            if p.id in wanted:
                p.radius = max(MIN_PIN_RADIUS, radius)

    def set_weight(self, ids: Iterable[str], weight: float) -> None:
        wanted = set(ids)
        for p in self.pins:
            if p.id in wanted:
                p.weight = clamp(weight, MIN_PIN_WEIGHT, MAX_PIN_WEIGHT)

    def link(self, ids: Iterable[str]) -> str | None:
        """Join the pins (and the groups they are in) into one rigid group."""
        wanted = set(ids)
        chosen = [p for p in self.pins if p.id in wanted]
        if len(chosen) < 2:
            return None
        old_groups = {p.group for p in chosen if p.group is not None}
        group = f"group-{self._next_id}"
        self._next_id += 1
        for p in self.pins:
            if p.id in wanted or (p.group is not None and p.group in old_groups):
                p.group = group
        return group

    def unlink(self, ids: Iterable[str]) -> None:
        wanted = set(ids)
        for p in self.pins:
            if p.id in wanted:
                p.group = None
        self._dissolve_small_groups()

    def _dissolve_small_groups(self) -> None:
        counts: dict[str, int] = {}
        for p in self.pins:
            if p.group is not None:
                counts[p.group] = counts.get(p.group, 0) + 1
        for p in self.pins:
            if p.group is not None and counts[p.group] < 2:
                p.group = None

    # -- warp input -----------------------------------------------------------

    def handles(self) -> list[Handle]:
        """MLS constraints: every pin, plus points along each rigid segment.

        Pins of a group are chained in creation order. Points between two
        linked pins get targets on the straight line between the pins'
        targets; since a group only moves rigidly, that is where they belong.
        """
        result = [Handle(p.source, p.target, p.radius, p.weight) for p in self.pins]
        groups: dict[str, list[Pin]] = {}
        for p in self.pins:
            if p.group is not None:
                groups.setdefault(p.group, []).append(p)
        for members in groups.values():
            for a, b in itertools.pairwise(members):
                length = math.hypot(b.source[0] - a.source[0], b.source[1] - a.source[1])
                n = min(MAX_SEGMENT_HANDLES, int(length // SEGMENT_SPACING))
                for k in range(1, n + 1):
                    t = k / (n + 1)
                    result.append(Handle(
                        _lerp(a.source, b.source, t), _lerp(a.target, b.target, t),
                        a.radius + (b.radius - a.radius) * t,
                        a.weight + (b.weight - a.weight) * t,
                    ))
        return result


def _lerp(a: Point, b: Point, t: float) -> Point:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def scale_handles(handles: Sequence[Handle], fx: float, fy: float) -> list[Handle]:
    """Handles in another pixel space (the preview), radius scaled by the mean factor."""
    fr = math.sqrt(fx * fy)
    return [Handle((h.source[0] * fx, h.source[1] * fy), (h.target[0] * fx, h.target[1] * fy),
                   h.radius * fr, h.weight) for h in handles]


# ---------------------------------------------------------------------------
# The deformation (reference implementation; the Rust kernel mirrors it)
# ---------------------------------------------------------------------------

Prepared = tuple[float, float, float, float, float, float]
"""(qx, qy, px, py, weight, 1 / falloff_radius^2) per handle."""


def prepare(handles: Sequence[Handle]) -> list[Prepared]:
    out = []
    for h in handles:
        moved = math.hypot(h.target[0] - h.source[0], h.target[1] - h.source[1])
        radius = max(h.radius, FOLD_GUARD * moved, 1e-6)
        out.append((h.target[0], h.target[1], h.source[0], h.source[1], h.weight,
                    1.0 / (radius * radius)))
    return out


def inverse_point(prepared: Sequence[Prepared], stiffness: float, x: float, y: float) -> Point:
    """The source point that the warped image shows at (x, y)."""
    if not prepared:
        return x, y
    # falloff g = 1 - prod(1 - k_i)
    rest = 1.0
    for qx, qy, _px, _py, _w, inv_r2 in prepared:
        d2 = (qx - x) ** 2 + (qy - y) ** 2
        t = d2 * inv_r2
        if t < 1.0:
            k = (1.0 - t) * (1.0 - t)
            rest *= 1.0 - k
    g = 1.0 - rest
    if g <= 0.0:
        return x, y

    # MLS, coordinates relative to (x, y) for numerical stability
    sw = swqx = swqy = swpx = swpy = 0.0
    sqp = sqxp = sqq = 0.0  # sum w q.p, sum w (q x p), sum w |q|^2
    for qx, qy, px, py, weight, _inv_r2 in prepared:
        qx -= x
        qy -= y
        px -= x
        py -= y
        d2 = qx * qx + qy * qy
        if d2 < _COINCIDENT:
            # on a handle: exact. g == 1 there, so the falloff changes nothing.
            return px + x, py + y
        w = weight / d2
        sw += w
        swqx += w * qx
        swqy += w * qy
        swpx += w * px
        swpy += w * py
        sqp += w * (qx * px + qy * py)
        sqxp += w * (qx * py - qy * px)
        sqq += w * (qx * qx + qy * qy)
    cqx, cqy = swqx / sw, swqy / sw  # weighted centroids
    cpx, cpy = swpx / sw, swpy / sw
    a_sum = sqp - sw * (cqx * cpx + cqy * cpy)  # sum w qhat.phat
    b_sum = sqxp - sw * (cqx * cpy - cqy * cpx)  # sum w qhat x phat
    mu = sqq - sw * (cqx * cqx + cqy * cqy)  # sum w |qhat|^2
    norm = math.hypot(a_sum, b_sum)
    if mu <= 1e-12 or norm <= 1e-12:
        a, b = 1.0, 0.0  # one handle (or all on one spot): pure translation
    else:
        a = (1.0 - stiffness) * a_sum / mu + stiffness * a_sum / norm
        b = (1.0 - stiffness) * b_sum / mu + stiffness * b_sum / norm
    ux, uy = -cqx, -cqy  # v - q*, with v at the origin
    fx = ux * a - uy * b + cpx
    fy = ux * b + uy * a + cpy
    return x + g * fx, y + g * fy


@dataclass(frozen=True)
class MapGrid:
    """A regular grid of output points: node (i, j) is at (x0 + i*step, y0 + j*step)."""

    x0: float
    y0: float
    step: float
    columns: int
    rows: int

    @classmethod
    def covering(cls, x: int, y: int, width: int, height: int, step: int) -> MapGrid:
        """Nodes covering the pixel centres of a rectangle.

        Nodes sit at ``0.5 + k * step`` globally, so adjacent tiles share
        them and a tiled render matches a single pass exactly.
        """
        i0 = x // step
        j0 = y // step
        i1 = max(i0 + 1, -(-(x + width - 1) // step))
        j1 = max(j0 + 1, -(-(y + height - 1) // step))
        return cls(0.5 + i0 * step, 0.5 + j0 * step, float(step), i1 - i0 + 1, j1 - j0 + 1)

    @property
    def nodes(self) -> int:
        return self.columns * self.rows


@dataclass(frozen=True)
class SourceMap:
    """Source positions for the nodes of a :class:`MapGrid`, plus their bounding box."""

    grid: MapGrid
    data: array[float]
    """Flat ``[sx, sy, ...]`` per node, row-major (C doubles)."""
    bounds: tuple[float, float, float, float]
    """(min_x, min_y, max_x, max_y) of all source positions."""


def compute_source_map(handles: Sequence[Handle], stiffness: float, grid: MapGrid) -> SourceMap:
    prepared = prepare(handles)
    data = array("d", bytes(16 * grid.nodes))
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    o = 0
    for j in range(grid.rows):
        y = grid.y0 + j * grid.step
        for i in range(grid.columns):
            sx, sy = inverse_point(prepared, stiffness, grid.x0 + i * grid.step, y)
            data[o] = sx
            data[o + 1] = sy
            o += 2
            min_x, max_x = min(min_x, sx), max(max_x, sx)
            min_y, max_y = min(min_y, sy), max(max_y, sy)
    return SourceMap(grid, data, (min_x, min_y, max_x, max_y))
