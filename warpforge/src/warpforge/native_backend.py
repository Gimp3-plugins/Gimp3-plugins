# SPDX-License-Identifier: GPL-3.0-or-later
"""ctypes binding for the Rust kernels in ``native/``.

The library exports a plain C ABI, so it works with any Python build -
including GIMP's MSYS2/UCRT Python on Windows, where PyO3 modules would not
load. ctypes releases the GIL during the call, so preview rendering in a
worker thread keeps the GTK main loop responsive.

Search order for the library:

1. ``$WARPFORGE_NATIVE_LIB``
2. ``warpforge/native/<libname>`` (installed plug-in)
3. ``warpforge/native/target/release/<libname>`` (source checkout)
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from array import array
from collections.abc import Sequence
from pathlib import Path

from warpforge.errors import WarpForgeError, _
from warpforge.puppet import Handle, MapGrid, SourceMap
from warpforge.render import PREVIEW_MAX_SIDE
from warpforge.state import PixelBuffer, Rect

log = logging.getLogger(__name__)

ABI_VERSION = 3
_FORMATS = {"u8": 0, "f32": 1}
_ERRORS = {-1: "null pointer", -2: "bad size", -3: "bad format", -4: "misaligned buffer",
           -5: "internal error"}


def library_name() -> str:
    if sys.platform == "win32":
        return "warpforge_native.dll"
    if sys.platform == "darwin":
        return "libwarpforge_native.dylib"
    return "libwarpforge_native.so"


def candidate_paths() -> list[Path]:
    here = Path(__file__).resolve().parent / "native"
    paths = []
    env = os.environ.get("WARPFORGE_NATIVE_LIB")
    if env:
        paths.append(Path(env))
    paths += [here / library_name(), here / "target" / "release" / library_name()]
    return paths


class _WfImage(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
    ]


class _WfHandle(ctypes.Structure):
    _fields_ = [(name, ctypes.c_double) for name in
                ("source_x", "source_y", "target_x", "target_y", "radius", "weight")]


class _WfGrid(ctypes.Structure):
    _fields_ = [
        ("x0", ctypes.c_double),
        ("y0", ctypes.c_double),
        ("step", ctypes.c_double),
        ("columns", ctypes.c_uint32),
        ("rows", ctypes.c_uint32),
    ]


def _grid(grid: MapGrid) -> _WfGrid:
    return _WfGrid(grid.x0, grid.y0, grid.step, grid.columns, grid.rows)


def _check(code: int) -> None:
    if code != 0:
        raise WarpForgeError(_("Native warp failed: {reason}.").format(
            reason=_ERRORS.get(code, str(code))))


class NativeBackend:
    name = "native"
    preview_max_side = PREVIEW_MAX_SIDE

    def __init__(self, lib: ctypes.CDLL, path: Path) -> None:
        self.path = path
        self._fn = lib.warpforge_mesh_warp
        self._fn.restype = ctypes.c_int32
        self._fn.argtypes = [
            ctypes.POINTER(_WfImage), ctypes.POINTER(_WfImage), ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ctypes.c_uint32, ctypes.c_uint32,
        ]
        self._puppet_map = lib.warpforge_puppet_map
        self._puppet_map.restype = ctypes.c_int32
        self._puppet_map.argtypes = [
            ctypes.POINTER(_WfHandle), ctypes.c_uint32, ctypes.c_double,
            ctypes.POINTER(_WfGrid), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._map_warp = lib.warpforge_map_warp
        self._map_warp.restype = ctypes.c_int32
        self._map_warp.argtypes = [
            ctypes.POINTER(_WfImage), ctypes.POINTER(_WfImage), ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(_WfGrid),
        ]
        # Re-copying the same preview source for every frame is wasted work.
        self._cached_src: PixelBuffer | None = None
        self._cached_buf: ctypes.Array[ctypes.c_char] | None = None

    def _source_buffer(self, src: PixelBuffer) -> ctypes.Array[ctypes.c_char]:
        if self._cached_src is not src or self._cached_buf is None:
            self._cached_buf = ctypes.create_string_buffer(src.data, len(src.data))
            self._cached_src = src
        return self._cached_buf

    def mesh_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                  src_vertices: Sequence[float], dst_vertices: Sequence[float],
                  columns: int, rows: int) -> PixelBuffer:
        count = 2 * (columns + 1) * (rows + 1)
        if len(src_vertices) != count or len(dst_vertices) != count:
            raise ValueError("vertex arrays do not match the mesh size")
        src_buf = self._source_buffer(src)
        out_size = dst_rect.width * dst_rect.height * 4 * src.bytes_per_sample
        out_buf = ctypes.create_string_buffer(out_size)
        src_img = _WfImage(ctypes.addressof(src_buf), src.width, src.height, *src_origin)
        dst_img = _WfImage(ctypes.addressof(out_buf), dst_rect.width, dst_rect.height,
                           dst_rect.x, dst_rect.y)
        sv = (ctypes.c_double * count)(*src_vertices)
        dv = (ctypes.c_double * count)(*dst_vertices)
        _check(self._fn(ctypes.byref(src_img), ctypes.byref(dst_img), _FORMATS[src.dtype],
                        sv, dv, columns, rows))
        return PixelBuffer(dst_rect.width, dst_rect.height, ctypes.string_at(out_buf, out_size),
                           dtype=src.dtype)

    def source_map(self, handles: Sequence[Handle], stiffness: float,
                   grid: MapGrid) -> SourceMap:
        hs = (_WfHandle * max(1, len(handles)))(*[
            _WfHandle(h.source[0], h.source[1], h.target[0], h.target[1], h.radius, h.weight)
            for h in handles])
        data = array("d", bytes(16 * grid.nodes))
        address, _length = data.buffer_info()
        out = ctypes.cast(address, ctypes.POINTER(ctypes.c_double))
        bounds = (ctypes.c_double * 4)()
        wf_grid = _grid(grid)
        _check(self._puppet_map(hs, len(handles), stiffness, ctypes.byref(wf_grid), out, bounds))
        return SourceMap(grid, data, (bounds[0], bounds[1], bounds[2], bounds[3]))

    def map_warp(self, src: PixelBuffer, src_origin: tuple[int, int], dst_rect: Rect,
                 smap: SourceMap) -> PixelBuffer:
        if len(smap.data) != 2 * smap.grid.nodes:
            raise ValueError("source map does not match its grid")
        src_buf = self._source_buffer(src)
        out_size = dst_rect.width * dst_rect.height * 4 * src.bytes_per_sample
        out_buf = ctypes.create_string_buffer(out_size)
        src_img = _WfImage(ctypes.addressof(src_buf), src.width, src.height, *src_origin)
        dst_img = _WfImage(ctypes.addressof(out_buf), dst_rect.width, dst_rect.height,
                           dst_rect.x, dst_rect.y)
        address, _length = smap.data.buffer_info()
        map_ptr = ctypes.cast(address, ctypes.POINTER(ctypes.c_double))
        wf_grid = _grid(smap.grid)
        _check(self._map_warp(ctypes.byref(src_img), ctypes.byref(dst_img), _FORMATS[src.dtype],
                              map_ptr, ctypes.byref(wf_grid)))
        return PixelBuffer(dst_rect.width, dst_rect.height, ctypes.string_at(out_buf, out_size),
                           dtype=src.dtype)


def load_native_backend() -> NativeBackend | None:
    """Load the first compatible library found, or ``None``."""
    for path in candidate_paths():
        if not path.is_file():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            lib.warpforge_abi_version.restype = ctypes.c_uint32
            version = lib.warpforge_abi_version()
        except (OSError, AttributeError) as exc:
            log.warning("Cannot load %s: %s", path, exc)
            continue
        if version != ABI_VERSION:
            log.warning("Ignoring %s: ABI %s, need %s", path, version, ABI_VERSION)
            continue
        log.info("Using native warp library %s", path)
        return NativeBackend(lib, path)
    return None
