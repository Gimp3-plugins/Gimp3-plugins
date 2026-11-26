# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh warp tests, run against every available backend."""

from __future__ import annotations

import os
import random
import struct
import time
import tracemalloc

import pytest

from warpforge.mesh import Mesh
from warpforge.native_backend import NativeBackend, load_native_backend
from warpforge.render import (
    PythonBackend,
    WarpBackend,
    plan_tiles,
    render_mesh_preview,
    render_mesh_tiled,
)
from warpforge.state import PixelBuffer, Rect

# Shared CI runners are slow and noisy; there the timing budgets only catch
# gross regressions. Locally the brief's budgets apply as written.
TIMING_FACTOR = 10.0 if os.environ.get("CI") else 1.0

NATIVE = load_native_backend()
needs_native = pytest.mark.skipif(
    NATIVE is None, reason="native library not built (cargo build --release)")
BACKENDS = [pytest.param(PythonBackend(), id="python"),
            pytest.param(NATIVE, id="native", marks=needs_native)]


def coordinate_image(width: int, height: int) -> PixelBuffer:
    """f32 image with R = x + 0.5, G = y + 0.5 (pixel centre), B = 0, A = 1.

    Bilinear sampling of a linear function is exact, so each output pixel's
    R/G reveal precisely which source point the warp sampled.
    """
    values = []
    for y in range(height):
        for x in range(width):
            values += [x + 0.5, y + 0.5, 0.0, 1.0]
    return PixelBuffer(width, height, struct.pack(f"{len(values)}f", *values), dtype="f32")


def noise_image(width: int, height: int, seed: int = 1) -> PixelBuffer:
    rng = random.Random(seed)
    data = bytearray(rng.randrange(256) for _ in range(width * height * 4))
    data[3::4] = bytes([255]) * (width * height)
    return PixelBuffer(width, height, bytes(data))


def warp_full(backend: WarpBackend, src: PixelBuffer, mesh: Mesh) -> PixelBuffer:
    return backend.mesh_warp(src, (0, 0), Rect(0, 0, src.width, src.height),
                             mesh.flat_source_vertices(), mesh.flat_vertices(),
                             mesh.columns, mesh.rows)


@pytest.mark.parametrize("backend", BACKENDS)
def test_identity_mesh_is_lossless(backend: WarpBackend) -> None:
    src = noise_image(41, 29)
    out = warp_full(backend, src, Mesh(4, 4, 41, 29))
    assert out.data == src.data


@pytest.mark.parametrize("backend", BACKENDS)
def test_2x2_mesh_applies_expected_affine_transform(backend: WarpBackend) -> None:
    """All vertices moved by one affine map -> output samples through its inverse."""
    w, h = 64, 48
    mesh = Mesh(2, 2, w, h)
    mesh.vertices = [(0.8 * x + 6.0, 0.8 * y + 4.0) for x, y in mesh.source_vertices()]
    out = warp_full(backend, coordinate_image(w, h), mesh)
    for px, py in [(30, 20), (10, 10), (45, 35), (7, 40)]:
        r, g, _b, a = out.pixel(px, py)
        assert a == pytest.approx(1.0)
        assert r == pytest.approx(((px + 0.5) - 6.0) / 0.8, abs=1e-3)
        assert g == pytest.approx(((py + 0.5) - 4.0) / 0.8, abs=1e-3)
    assert out.pixel(1, 1)[3] == 0.0  # outside the shrunken mesh


@pytest.mark.parametrize("backend", BACKENDS)
def test_moving_centre_vertex_is_piecewise_affine(backend: WarpBackend) -> None:
    w, h = 80, 80
    mesh = Mesh(4, 4, w, h)  # 20 px cells
    centre = mesh.index(2, 2)
    mesh.move_vertex(centre, (52.0, 44.0))
    out = warp_full(backend, coordinate_image(w, h), mesh)
    # The moved vertex's neighbourhood samples near the original centre...
    r, g, *_ = out.pixel(51, 43)
    assert abs(r - 40.0) < 1.5 and abs(g - 40.0) < 1.5
    # ...while cells that do not touch the vertex are untouched.
    assert out.pixel(2, 2)[:2] == pytest.approx((2.5, 2.5), abs=1e-3)
    assert out.pixel(77, 5)[:2] == pytest.approx((77.5, 5.5), abs=1e-3)


@needs_native
def test_native_matches_python_reference() -> None:
    rng = random.Random(7)
    src = noise_image(60, 45, seed=3)
    mesh = Mesh(4, 3, 60, 45)
    for _ in range(40):
        i = rng.randrange(len(mesh.vertices))
        x, y = mesh.vertices[i]
        mesh.move_vertex(i, (x + rng.uniform(-12, 12), y + rng.uniform(-12, 12)))
    assert NATIVE is not None
    a = warp_full(NATIVE, src, mesh).data
    b = warp_full(PythonBackend(), src, mesh).data
    diff = [abs(x - y) for x, y in zip(a, b, strict=True)]
    # Pixel centres exactly on a shared triangle edge may pick either neighbour.
    assert max(diff) <= 2
    assert sum(d > 1 for d in diff) <= len(diff) * 0.002


@pytest.mark.parametrize("backend", BACKENDS)
def test_tiled_render_equals_single_pass(backend: WarpBackend) -> None:
    w, h = 70, 50
    src = coordinate_image(w, h)
    mesh = Mesh(3, 3, w, h)
    mesh.move_vertex(5, (35.0, 10.0))
    mesh.move_vertex(10, (40.0, 40.0))
    expected = warp_full(backend, src, mesh)

    canvas = bytearray(len(expected.data))
    row_bytes = w * 16

    def read(rect: Rect) -> PixelBuffer:
        rows = [src.data[(rect.y + j) * row_bytes + rect.x * 16:
                         (rect.y + j) * row_bytes + (rect.x + rect.width) * 16]
                for j in range(rect.height)]
        return PixelBuffer(rect.width, rect.height, b"".join(rows), dtype="f32")

    def write(rect: Rect, pixels: PixelBuffer) -> None:
        for j in range(rect.height):
            start = (rect.y + j) * row_bytes + rect.x * 16
            canvas[start:start + rect.width * 16] = pixels.data[
                j * rect.width * 16:(j + 1) * rect.width * 16]

    fractions: list[float] = []
    render_mesh_tiled(backend, mesh, read, write, progress=fractions.append, tile_size=16)
    assert bytes(canvas) == expected.data
    assert fractions[-1] == 1.0
    assert len(fractions) == len(plan_tiles(mesh, 16))


def test_tiles_read_only_their_footprint() -> None:
    mesh = Mesh(8, 8, 4096, 4096)
    jobs = plan_tiles(mesh, 512)
    assert len(jobs) == 64
    # Undeformed and aligned: each tile needs just itself plus padding.
    assert all(job.src.width <= 512 + 4 and job.src.height <= 512 + 4 for job in jobs)


def test_preview_render_uses_scaled_mesh() -> None:
    src = coordinate_image(50, 25)
    mesh = Mesh(2, 2, 1000, 500)  # layer is 20x larger than the preview
    out = render_mesh_preview(PythonBackend(), src, mesh)
    assert out.data == src.data


@needs_native
def test_native_preview_is_fast_enough() -> None:
    """Brief: < 50 ms per preview frame for a 2000x2000 layer (1024 px preview)."""
    assert NATIVE is not None
    src = noise_image(1024, 1024)
    mesh = Mesh(8, 8, 2000, 2000)
    rng = random.Random(5)
    for i in range(len(mesh.vertices)):
        x, y = mesh.vertices[i]
        mesh.move_vertex(i, (x + rng.uniform(-60, 60), y + rng.uniform(-60, 60)))
    render_mesh_preview(NATIVE, src, mesh)  # warm-up, fills the source cache
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        render_mesh_preview(NATIVE, src, mesh)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.050 * TIMING_FACTOR, timings


@needs_native
def test_repeated_rendering_does_not_leak() -> None:
    assert isinstance(NATIVE, NativeBackend)
    src = noise_image(256, 256)
    mesh = Mesh(6, 6, 256, 256)
    for _ in range(20):
        render_mesh_preview(NATIVE, src, mesh)
    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    for i in range(200):
        mesh.move_vertex(8, (50.0 + i % 20, 45.0))
        render_mesh_preview(NATIVE, src, mesh)
    grown = tracemalloc.get_traced_memory()[0] - baseline
    tracemalloc.stop()
    assert grown < 1_000_000, grown


def test_python_backend_handles_small_preview_in_time() -> None:
    src = noise_image(160, 120)
    mesh = Mesh(4, 4, 160, 120)
    mesh.move_vertex(6, (50.0, 40.0))
    start = time.perf_counter()
    render_mesh_preview(PythonBackend(), src, mesh)
    assert time.perf_counter() - start < 5.0 * TIMING_FACTOR
