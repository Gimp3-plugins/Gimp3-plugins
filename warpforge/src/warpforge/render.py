# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering: preview sizing, warp backends and tiled full-resolution rendering.

Two interchangeable backends implement :class:`WarpBackend`:

* :class:`warpforge.native_backend.NativeBackend` - Rust kernel via ctypes (fast);
* :class:`PythonBackend` - pure Python, same algorithm, used when the native
  library is missing. Slow, so it gets a smaller preview.

Mesh warp: both rasterise each target triangle of the mesh, map pixel centres
back to the source with the triangle's affine map and sample bilinearly with
premultiplied alpha. Pixels covered by no triangle are transparent.

Puppet warp: the deformation (:mod:`warpforge.puppet`) is evaluated on a
coarse grid of output points, a *source map*; each pixel interpolates its
source position from the map and samples there. Positions outside the layer
are transparent. The same map is what a GEGL ``map-absolute`` filter would
need, which is the route to a non-destructive effect (stage 4).
"""

from __future__ import annotations

import logging
import math
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from warpforge.errors import OperationCancelledError
from warpforge.geometry import affine_from_triangles, barycentric_functions
from warpforge.mesh import Mesh, triangulate
from warpforge.puppet import (
    Handle,
    MapGrid,
    PuppetRig,
    SourceMap,
    compute_source_map,
    scale_handles,
)
from warpforge.state import PixelBuffer, Rect

log = logging.getLogger(__name__)

PREVIEW_MAX_SIDE = 1024
PYTHON_PREVIEW_MAX_SIDE = 320
TILE_SIZE = 512
PREVIEW_MAP_STEP = 4
"""Source-map grid spacing in preview pixels."""
FULL_MAP_STEP = 4
"""Source-map grid spacing in layer pixels for the full-resolution render."""
_TILE_PADDING = 2  # source pixels around each tile's footprint (bilinear needs 1)
_EPS = 1e-7


def preview_scale(width: int, height: int, max_side: int = PREVIEW_MAX_SIDE) -> float:
    """Scale factor that fits the longer side into ``max_side``; never upscales."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    longest = max(width, height)
    return 1.0 if longest <= max_side else max_side / longest


def preview_size(width: int, height: int, max_side: int = PREVIEW_MAX_SIDE) -> tuple[int, int]:
    """Integer preview dimensions matching :func:`preview_scale` (each at least 1 px)."""
    scale = preview_scale(width, height, max_side)
    return max(1, round(width * scale)), max(1, round(height * scale))


class WarpBackend(Protocol):
    name: str
    preview_max_side: int

    def mesh_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                  src_vertices: Sequence[float], dst_vertices: Sequence[float],
                  columns: int, rows: int) -> PixelBuffer:
        """Warp ``src`` (a region at ``src_origin`` of the layer) into ``dst_rect``.

        Vertex lists are flat ``[x0, y0, x1, y1, ...]`` in layer coordinates.
        """
        ...

    def source_map(self, handles: Sequence[Handle], stiffness: float,
                   grid: MapGrid) -> SourceMap:
        """Evaluate the puppet deformation at every node of ``grid``."""
        ...

    def map_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                 smap: SourceMap) -> PixelBuffer:
        """Warp ``src`` into ``dst_rect`` through a source map (layer coordinates)."""
        ...


class PythonBackend:
    """Reference implementation in pure Python (no NumPy: GIMP's Python lacks it)."""

    name = "python"
    preview_max_side = PYTHON_PREVIEW_MAX_SIDE

    def mesh_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                  src_vertices: Sequence[float], dst_vertices: Sequence[float],
                  columns: int, rows: int) -> PixelBuffer:
        s = src.samples()
        sw, sh = src.width, src.height
        sx0, sy0 = src_origin
        norm = 1.0 / 255.0 if src.dtype == "u8" else 1.0
        dw, dh = dst_rect.width, dst_rect.height
        out = _zeros(src.dtype, dw * dh * 4)
        to_u8 = src.dtype == "u8"
        max_u, max_v = sw - 1.0, sh - 1.0
        dx0, dy0 = dst_rect.x, dst_rect.y
        dx1, dy1 = dx0 + dw, dy0 + dh

        def vertex(flat: Sequence[float], i: int) -> tuple[float, float]:
            return flat[2 * i], flat[2 * i + 1]

        for tri in triangulate(columns, rows):
            d = (vertex(dst_vertices, tri[0]), vertex(dst_vertices, tri[1]),
                 vertex(dst_vertices, tri[2]))
            st = (vertex(src_vertices, tri[0]), vertex(src_vertices, tri[1]),
                  vertex(src_vertices, tri[2]))
            weights = barycentric_functions(*d)
            mapping = affine_from_triangles(d, st)
            if weights is None or mapping is None:
                continue
            (ax, bx, cx), (ay, by, cy) = mapping
            xs = [p[0] for p in d]
            ys = [p[1] for p in d]
            py_start = max(dy0, math.ceil(max(min(ys), dy0) - 0.5))
            py_end = min(dy1 - 1, math.floor(min(max(ys), dy1) - 0.5))
            x_lo_tri = max(min(xs), dx0)
            x_hi_tri = min(max(xs), dx1)
            if x_lo_tri >= x_hi_tri:
                continue
            for py in range(py_start, py_end + 1):
                fy = py + 0.5
                lo, hi = x_lo_tri, x_hi_tri
                empty = False
                for wa, wb, wc in weights:  # weight(x) = wa*x + k >= -eps
                    k = wb * fy + wc
                    if wa > 0:
                        lo = max(lo, (-_EPS - k) / wa)
                    elif wa < 0:
                        hi = min(hi, (-_EPS - k) / wa)
                    elif k < -_EPS:
                        empty = True
                if empty:
                    continue
                px_start = max(dx0, math.ceil(lo - 0.5))
                px_end = min(dx1 - 1, math.floor(hi - 0.5))
                row = (py - dy0) * dw
                for px in range(px_start, px_end + 1):
                    fx = px + 0.5
                    u = ax * fx + bx * fy + cx - 0.5 - sx0
                    v = ay * fx + by * fy + cy - 0.5 - sy0
                    u = 0.0 if u < 0.0 else max_u if u > max_u else u
                    v = 0.0 if v < 0.0 else max_v if v > max_v else v
                    x0, y0 = int(u), int(v)
                    x1 = x0 + 1 if x0 + 1 < sw else x0
                    y1 = y0 + 1 if y0 + 1 < sh else y0
                    tx, ty = u - x0, v - y0
                    r = g = b = a = 0.0
                    for qx, qy, w in ((x0, y0, (1 - tx) * (1 - ty)), (x1, y0, tx * (1 - ty)),
                                      (x0, y1, (1 - tx) * ty), (x1, y1, tx * ty)):
                        if w == 0.0:
                            continue
                        i = (qy * sw + qx) * 4
                        wa_ = s[i + 3] * norm * w
                        r += s[i] * norm * wa_
                        g += s[i + 1] * norm * wa_
                        b += s[i + 2] * norm * wa_
                        a += wa_
                    o = (row + px - dx0) * 4
                    if a <= 1e-12:
                        out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0
                        continue
                    r, g, b = r / a, g / a, b / a
                    if to_u8:
                        out[o] = _to_u8(r)
                        out[o + 1] = _to_u8(g)
                        out[o + 2] = _to_u8(b)
                        out[o + 3] = _to_u8(a)
                    else:
                        out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, a
        return PixelBuffer(dw, dh, out.tobytes(), dtype=src.dtype)

    def source_map(self, handles: Sequence[Handle], stiffness: float,
                   grid: MapGrid) -> SourceMap:
        return compute_source_map(handles, stiffness, grid)

    def map_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                 smap: SourceMap) -> PixelBuffer:
        s = src.samples()
        sw, sh = src.width, src.height
        sx0, sy0 = src_origin
        sx1, sy1 = sx0 + sw, sy0 + sh
        norm = 1.0 / 255.0 if src.dtype == "u8" else 1.0
        to_u8 = src.dtype == "u8"
        dw, dh = dst_rect.width, dst_rect.height
        out = _zeros(src.dtype, dw * dh * 4)
        grid, m = smap.grid, smap.data
        cols, rows, step = grid.columns, grid.rows, grid.step
        max_u, max_v = sw - 1.0, sh - 1.0

        def cell(pos: float, origin: float, nodes: int) -> tuple[int, float]:
            if nodes < 2:
                return 0, 0.0
            u = (pos - origin) / step
            i = min(max(math.floor(u), 0), nodes - 2)
            f = u - i
            return i, 0.0 if f < 0.0 else 1.0 if f > 1.0 else f

        columns = [cell(dst_rect.x + px + 0.5, grid.x0, cols) for px in range(dw)]
        for py in range(dh):
            j, fy = cell(dst_rect.y + py + 0.5, grid.y0, rows)
            j1 = j + 1 if rows > 1 else j
            # this output row's source positions at every map column
            top, bot = 2 * j * cols, 2 * j1 * cols
            row_nodes = [m[top + k] + (m[bot + k] - m[top + k]) * fy for k in range(2 * cols)]
            o = py * dw * 4
            for i, fx in columns:
                i1 = i + 1 if cols > 1 else i
                ax, ay = row_nodes[2 * i], row_nodes[2 * i + 1]
                sx = ax + (row_nodes[2 * i1] - ax) * fx
                sy = ay + (row_nodes[2 * i1 + 1] - ay) * fx
                if not (sx0 <= sx <= sx1 and sy0 <= sy <= sy1):
                    o += 4  # transparent (already zero)
                    continue
                u = sx - 0.5 - sx0
                v = sy - 0.5 - sy0
                u = 0.0 if u < 0.0 else max_u if u > max_u else u
                v = 0.0 if v < 0.0 else max_v if v > max_v else v
                r, g, b, a = _bilinear(s, sw, sh, u, v, norm)
                if a > 1e-12:
                    if to_u8:
                        out[o] = _to_u8(r)
                        out[o + 1] = _to_u8(g)
                        out[o + 2] = _to_u8(b)
                        out[o + 3] = _to_u8(a)
                    else:
                        out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, a
                o += 4
        return PixelBuffer(dw, dh, out.tobytes(), dtype=src.dtype)


def _bilinear(s: Any, sw: int, sh: int, u: float, v: float,
              norm: float) -> tuple[float, float, float, float]:
    """Premultiplied bilinear sample at (u, v) (pixel-centre coordinates, in range)."""
    x0, y0 = int(u), int(v)
    x1 = x0 + 1 if x0 + 1 < sw else x0
    y1 = y0 + 1 if y0 + 1 < sh else y0
    tx, ty = u - x0, v - y0
    r = g = b = a = 0.0
    for qx, qy, w in ((x0, y0, (1 - tx) * (1 - ty)), (x1, y0, tx * (1 - ty)),
                      (x0, y1, (1 - tx) * ty), (x1, y1, tx * ty)):
        if w == 0.0:
            continue
        i = (qy * sw + qx) * 4
        wa = s[i + 3] * norm * w
        r += s[i] * norm * wa
        g += s[i + 1] * norm * wa
        b += s[i + 2] * norm * wa
        a += wa
    if a <= 1e-12:
        return 0.0, 0.0, 0.0, 0.0
    return r / a, g / a, b / a, a


def _zeros(dtype: str, count: int) -> array[Any]:
    """A zero-filled sample array: bytes for u8, C floats for f32."""
    return array("B", bytes(count)) if dtype == "u8" else array("f", bytes(count * 4))


def _to_u8(v: float) -> int:
    n = int(v * 255.0 + 0.5)
    return 0 if n < 0 else 255 if n > 255 else n


def select_backend(prefer_native: bool = True) -> WarpBackend:
    if prefer_native:
        from warpforge.native_backend import load_native_backend

        native = load_native_backend()
        if native is not None:
            return native
    log.warning("Native warp library not available; using the slow Python backend.")
    return PythonBackend()


# --------------------------------------------------------------------------
# Preview and tiled full-resolution rendering
# --------------------------------------------------------------------------


def render_mesh_preview(backend: WarpBackend, preview: PixelBuffer, mesh: Mesh) -> PixelBuffer:
    """Warp the preview buffer with a mesh given in layer coordinates."""
    scaled = mesh.scaled(preview.width, preview.height)
    return backend.mesh_warp(preview, (0, 0), Rect(0, 0, preview.width, preview.height),
                             scaled.flat_source_vertices(), scaled.flat_vertices(),
                             mesh.columns, mesh.rows)


@dataclass(frozen=True)
class TileJob:
    dst: Rect
    src: Rect
    """Source region whose pixels the ``dst`` tile samples."""


def plan_tiles(mesh: Mesh, tile_size: int = TILE_SIZE) -> list[TileJob]:
    """Split the output into tiles and find the source footprint of each one."""
    width, height = round(mesh.width), round(mesh.height)
    src_pts = mesh.source_vertices()
    dst_pts = mesh.vertices
    tri_boxes = []
    for tri in mesh.triangles():
        dxs = [dst_pts[i][0] for i in tri]
        dys = [dst_pts[i][1] for i in tri]
        sxs = [src_pts[i][0] for i in tri]
        sys_ = [src_pts[i][1] for i in tri]
        tri_boxes.append(((min(dxs), min(dys), max(dxs), max(dys)),
                          (min(sxs), min(sys_), max(sxs), max(sys_))))
    jobs = []
    for ty in range(0, height, tile_size):
        for tx in range(0, width, tile_size):
            tw, th = min(tile_size, width - tx), min(tile_size, height - ty)
            sx0 = sy0 = math.inf
            sx1 = sy1 = -math.inf
            for (x0, y0, x1, y1), (a0, b0, a1, b1) in tri_boxes:
                # Strict: a triangle that only touches the tile border covers none
                # of its pixel centres.
                if x1 <= tx or x0 >= tx + tw or y1 <= ty or y0 >= ty + th:
                    continue
                sx0, sy0 = min(sx0, a0), min(sy0, b0)
                sx1, sy1 = max(sx1, a1), max(sy1, b1)
            if sx0 == math.inf:
                src = Rect(0, 0, 1, 1)  # nothing maps here; output stays transparent
            else:
                left = max(0, math.floor(sx0) - _TILE_PADDING)
                top = max(0, math.floor(sy0) - _TILE_PADDING)
                right = min(width, math.ceil(sx1) + _TILE_PADDING)
                bottom = min(height, math.ceil(sy1) + _TILE_PADDING)
                src = Rect(left, top, max(1, right - left), max(1, bottom - top))
            jobs.append(TileJob(Rect(tx, ty, tw, th), src))
    return jobs


def render_mesh_tiled(
    backend: WarpBackend,
    mesh: Mesh,
    read_region: Callable[[Rect], PixelBuffer],
    write_region: Callable[[Rect, PixelBuffer], None],
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    tile_size: int = TILE_SIZE,
) -> None:
    """Render a full-resolution mesh warp tile by tile, bounding memory use."""
    src_flat = mesh.flat_source_vertices()
    dst_flat = mesh.flat_vertices()
    jobs = plan_tiles(mesh, tile_size)
    for n, job in enumerate(jobs, start=1):
        if cancelled is not None and cancelled():
            raise OperationCancelledError()
        source = read_region(job.src)
        result = backend.mesh_warp(source, (job.src.x, job.src.y), job.dst, src_flat, dst_flat,
                                   mesh.columns, mesh.rows)
        write_region(job.dst, result)
        if progress is not None:
            progress(n / len(jobs))


def render_puppet_preview(backend: WarpBackend, preview: PixelBuffer, rig: PuppetRig,
                          stiffness: float, step: int = PREVIEW_MAP_STEP) -> PixelBuffer:
    """Warp the preview buffer with pins given in layer coordinates."""
    handles = scale_handles(rig.handles(), preview.width / rig.width,
                            preview.height / rig.height)
    rect = Rect(0, 0, preview.width, preview.height)
    smap = backend.source_map(handles, stiffness,
                              MapGrid.covering(0, 0, preview.width, preview.height, step))
    return backend.map_warp(preview, (0, 0), rect, smap)


def source_footprint(smap: SourceMap, width: int, height: int) -> Rect:
    """The layer region a tile with this source map samples (clipped to the layer)."""
    min_x, min_y, max_x, max_y = smap.bounds
    if not all(math.isfinite(v) for v in smap.bounds):
        return Rect(0, 0, width, height)
    left = max(0, math.floor(min_x) - _TILE_PADDING)
    top = max(0, math.floor(min_y) - _TILE_PADDING)
    right = min(width, math.ceil(max_x) + _TILE_PADDING)
    bottom = min(height, math.ceil(max_y) + _TILE_PADDING)
    if right <= left or bottom <= top:
        return Rect(0, 0, 1, 1)  # everything maps outside the layer: transparent
    return Rect(left, top, right - left, bottom - top)


def puppet_tiles(width: int, height: int, tile_size: int = TILE_SIZE) -> list[Rect]:
    return [Rect(tx, ty, min(tile_size, width - tx), min(tile_size, height - ty))
            for ty in range(0, height, tile_size) for tx in range(0, width, tile_size)]


def render_puppet_tiled(
    backend: WarpBackend,
    rig: PuppetRig,
    stiffness: float,
    read_region: Callable[[Rect], PixelBuffer],
    write_region: Callable[[Rect, PixelBuffer], None],
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    tile_size: int = TILE_SIZE,
    step: int = FULL_MAP_STEP,
) -> None:
    """Render a full-resolution puppet warp tile by tile, bounding memory use.

    Each tile's source footprint comes from the bounding box of its source
    map, so only the pixels it samples are read.
    """
    width, height = round(rig.width), round(rig.height)
    handles = rig.handles()
    tiles = puppet_tiles(width, height, tile_size)
    for n, dst in enumerate(tiles, start=1):
        if cancelled is not None and cancelled():
            raise OperationCancelledError()
        smap = backend.source_map(handles, stiffness,
                                  MapGrid.covering(dst.x, dst.y, dst.width, dst.height, step))
        src = source_footprint(smap, width, height)
        result = backend.map_warp(read_region(src), (src.x, src.y), dst, smap)
        write_region(dst, result)
        if progress is not None:
            progress(n / len(tiles))
