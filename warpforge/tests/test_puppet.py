# SPDX-License-Identifier: GPL-3.0-or-later
"""Puppet Warp: pin model, the MLS deformation and its rendering on every backend."""

from __future__ import annotations

import math
import random
import time
import tracemalloc

import pytest

from tests.test_warp import (
    BACKENDS,
    NATIVE,
    TIMING_FACTOR,
    coordinate_image,
    needs_native,
    noise_image,
)
from warpforge.native_backend import NativeBackend
from warpforge.puppet import (
    FOLD_GUARD,
    MAX_SEGMENT_HANDLES,
    MapGrid,
    PuppetRig,
    compute_source_map,
    inverse_point,
    prepare,
)
from warpforge.render import (
    PythonBackend,
    WarpBackend,
    puppet_tiles,
    render_puppet_preview,
    render_puppet_tiled,
    source_footprint,
)
from warpforge.state import PixelBuffer, Rect


def rig_with(pins: list[tuple[tuple[float, float], tuple[float, float], float]],
             width: float = 200, height: float = 200) -> PuppetRig:
    """A rig whose pins go from source to target: [(source, target, radius), ...]."""
    rig = PuppetRig(width, height)
    added = [rig.add_pin(source, radius, 0.5) for source, _target, radius in pins]
    for pin, (_source, target, _radius) in zip(added, pins, strict=True):
        rig.move_pin(pin.id, target, clamp_to_bounds=False)
    return rig


def full_map(backend: WarpBackend, rig: PuppetRig, stiffness: float = 0.5,
             step: int = 4) -> PixelBuffer:
    w, h = round(rig.width), round(rig.height)
    smap = backend.source_map(rig.handles(), stiffness, MapGrid.covering(0, 0, w, h, step))
    return backend.map_warp(coordinate_image(w, h), (0, 0), Rect(0, 0, w, h), smap)


# -- the deformation -----------------------------------------------------------


class TestDeformation:
    def test_pin_target_maps_exactly_to_its_source(self) -> None:
        rig = rig_with([((50, 60), (70, 52), 40), ((140, 120), (150, 130), 50),
                        ((60, 150), (60, 150), 30)])
        prepared = prepare(rig.handles())
        for pin in rig.pins:
            assert inverse_point(prepared, 0.7, *pin.target) == pytest.approx(pin.source)

    def test_far_from_every_pin_nothing_moves(self) -> None:
        rig = rig_with([((50, 50), (65, 45), 30)])
        prepared = prepare(rig.handles())
        assert inverse_point(prepared, 0.5, 150.0, 150.0) == (150.0, 150.0)
        # falloff radius: max(30, FOLD_GUARD * |(15, -5)|) = 31.6
        assert inverse_point(prepared, 0.5, 65.0 + 32.0, 45.0) == (97.0, 45.0)
        assert inverse_point(prepared, 0.5, 65.0 + 31.0, 45.0) != (96.0, 45.0)

    def test_without_pins_the_map_is_identity(self) -> None:
        smap = compute_source_map([], 0.5, MapGrid.covering(0, 0, 20, 10, 4))
        g = smap.grid
        expected = [v for j in range(g.rows) for i in range(g.columns)
                    for v in (g.x0 + i * g.step, g.y0 + j * g.step)]
        assert list(smap.data) == expected

    def test_restored_pins_are_identity(self) -> None:
        rig = rig_with([((50, 50), (80, 40), 60), ((120, 100), (100, 120), 60)])
        assert not rig.is_identity()
        rig.restore()
        assert rig.is_identity()
        prepared = prepare(rig.handles())
        for x, y in [(10.0, 10.0), (55.0, 47.0), (118.0, 103.0)]:
            assert inverse_point(prepared, 0.5, x, y) == pytest.approx((x, y))

    @pytest.mark.parametrize("stiffness, expected_y", [(0.0, 55.0), (1.0, 60.0)])
    def test_stiffness_blends_scaling_and_rigid(self, stiffness: float,
                                                expected_y: float) -> None:
        """Two pins pulled apart 2x: 'similarity' scales the region, 'rigid' does not."""
        rig = rig_with([((40, 50), (30, 50), 5000), ((60, 50), (70, 50), 5000)])
        sx, sy = inverse_point(prepare(rig.handles()), stiffness, 50.0, 60.0)
        assert sx == pytest.approx(50.0, abs=1e-6)
        assert sy == pytest.approx(expected_y, abs=0.05)

    def test_fold_guard_widens_the_falloff_of_far_dragged_pins(self) -> None:
        rig = rig_with([((50, 50), (130, 50), 10)])
        ((_qx, _qy, _px, _py, _w, inv_r2),) = prepare(rig.handles())
        assert 1 / math.sqrt(inv_r2) == pytest.approx(FOLD_GUARD * 80)

    @pytest.mark.parametrize("seed", range(6))
    @pytest.mark.parametrize("stiffness", [0.0, 0.55, 1.0])
    def test_typical_edits_do_not_fold(self, seed: int, stiffness: float) -> None:
        """Jacobian of the source map stays positive: no self-overlapping image.

        "Typical" = no pin is dragged across another one. (Swapping two pins'
        order folds the image under any warp that puts pins exactly where
        they are dragged.) Here each move is under a third of the distance
        to the nearest other pin.
        """
        rng = random.Random(seed)
        rig = PuppetRig(240, 240)
        for _ in range(rng.randint(3, 6)):
            rig.add_pin((rng.uniform(30, 210), rng.uniform(30, 210)), rng.uniform(40, 120),
                        stiffness)
        for pin in rig.pins:
            if rng.random() < 0.3:
                continue
            nearest = min((math.dist(pin.source, other.source) for other in rig.pins
                           if other is not pin), default=100.0)
            reach = min(40.0, nearest / 3)
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(0.3, 1.0) * reach
            rig.move_pin(pin.id, (pin.source[0] + dist * math.cos(angle),
                                  pin.source[1] + dist * math.sin(angle)), True)
        smap = compute_source_map(rig.handles(), stiffness, MapGrid.covering(0, 0, 240, 240, 3))
        g, d = smap.grid, smap.data
        worst = math.inf
        for j in range(g.rows - 1):
            for i in range(g.columns - 1):
                o = 2 * (j * g.columns + i)
                right, down = o + 2, o + 2 * g.columns
                ax, ay = d[right] - d[o], d[right + 1] - d[o + 1]
                bx, by = d[down] - d[o], d[down + 1] - d[o + 1]
                worst = min(worst, (ax * by - ay * bx) / (g.step * g.step))
        assert worst > 0.05, worst


# -- the model -------------------------------------------------------------------


class TestRig:
    def test_adding_a_pin_on_a_warped_image_does_not_change_it(self) -> None:
        rig = rig_with([((60, 60), (80, 50), 80)])
        before = prepare(rig.handles())
        spot = (95.0, 70.0)
        expected = inverse_point(before, 0.5, *spot)
        pin = rig.add_pin(spot, 60, 0.5)
        assert pin.source == pytest.approx(expected)
        assert inverse_point(prepare(rig.handles()), 0.5, *spot) == pytest.approx(expected)

    def test_ids_are_unique_and_nearest_pin_respects_distance(self) -> None:
        rig = PuppetRig(100, 100)
        a = rig.add_pin((10, 10), 20, 0.5)
        b = rig.add_pin((50, 50), 20, 0.5)
        assert a.id != b.id
        assert rig.nearest_pin((48, 49), 5) is b
        assert rig.nearest_pin((30, 30), 5) is None

    def test_clamp_keeps_pins_inside_the_layer(self) -> None:
        rig = PuppetRig(100, 80)
        pin = rig.add_pin((90, 40), 20, 0.5)
        rig.move_pin(pin.id, (150, -20), clamp_to_bounds=True)
        assert pin.target == (100, 0)
        rig.move_pin(pin.id, (150, -20), clamp_to_bounds=False)
        assert pin.target == (150, -20)

    def test_linked_pins_move_together(self) -> None:
        rig = PuppetRig(200, 200)
        a = rig.add_pin((50, 50), 30, 0.5)
        b = rig.add_pin((90, 70), 30, 0.5)
        c = rig.add_pin((150, 150), 30, 0.5)
        group = rig.link([a.id, b.id])
        assert group is not None and a.group == b.group == group and c.group is None
        rig.move_pin(b.id, (100, 60), clamp_to_bounds=True)
        assert a.target == (60, 40)  # same offset: distance and angle kept
        assert c.target == (150, 150)

    def test_clamp_shrinks_the_whole_group_move(self) -> None:
        rig = PuppetRig(100, 100)
        a = rig.add_pin((10, 50), 30, 0.5)
        b = rig.add_pin((40, 50), 30, 0.5)
        rig.link([a.id, b.id])
        rig.move_pin(b.id, (0, 50), clamp_to_bounds=True)
        assert a.target == (0, 50) and b.target == (30, 50)

    def test_rigid_segment_holds_between_the_pins(self) -> None:
        rig = PuppetRig(300, 300)
        a = rig.add_pin((100, 150), 60, 0.5)
        b = rig.add_pin((200, 150), 60, 0.5)
        rig.link([a.id, b.id])
        handles = rig.handles()
        assert len(handles) == 2 + min(MAX_SEGMENT_HANDLES, 100 // 12)
        rig.move_pin(a.id, (110, 130), clamp_to_bounds=True)
        prepared = prepare(rig.handles())
        # the segment's midpoint shows its original midpoint
        assert inverse_point(prepared, 0.5, 160.0, 130.0) == pytest.approx((150.0, 150.0),
                                                                              abs=0.5)

    def test_removing_or_unlinking_dissolves_one_pin_groups(self) -> None:
        rig = PuppetRig(100, 100)
        a, b, c = (rig.add_pin((x, 50), 20, 0.5) for x in (20, 50, 80))
        rig.link([a.id, b.id, c.id])
        rig.remove([c.id])
        assert a.group is not None and a.group == b.group
        rig.unlink([a.id])
        assert a.group is None and b.group is None

    def test_linking_merges_existing_groups(self) -> None:
        rig = PuppetRig(100, 100)
        a, b, c, d = (rig.add_pin((x, 50), 20, 0.5) for x in (10, 30, 60, 90))
        rig.link([a.id, b.id])
        rig.link([c.id, d.id])
        rig.link([b.id, c.id])
        assert len({p.group for p in rig.pins}) == 1

    def test_weight_and_radius_are_clamped(self) -> None:
        rig = PuppetRig(100, 100)
        pin = rig.add_pin((10, 10), 0.5, 0.5)
        assert pin.radius >= 4
        rig.set_weight([pin.id], 99)
        rig.set_radius([pin.id], -3)
        assert pin.weight == 10.0 and pin.radius == 4.0

    def test_copy_is_independent(self) -> None:
        rig = rig_with([((50, 50), (60, 60), 30)])
        clone = rig.copy()
        rig.move_pin(rig.pins[0].id, (70, 70), clamp_to_bounds=True)
        assert clone.pins[0].target == (60, 60)
        assert clone != rig


# -- rendering ------------------------------------------------------------------


class TestGrid:
    def test_nodes_cover_every_pixel_centre(self) -> None:
        g = MapGrid.covering(13, 7, 30, 20, 4)
        assert g.x0 <= 13.5 and g.x0 + (g.columns - 1) * g.step >= 13 + 30 - 0.5
        assert g.y0 <= 7.5 and g.y0 + (g.rows - 1) * g.step >= 7 + 20 - 0.5

    def test_tiles_share_global_nodes(self) -> None:
        a = MapGrid.covering(0, 0, 16, 16, 4)
        b = MapGrid.covering(16, 0, 16, 16, 4)
        assert (b.x0 - a.x0) / 4 == int((b.x0 - a.x0) / 4)

    def test_one_pixel_rect_still_has_two_nodes(self) -> None:
        g = MapGrid.covering(8, 8, 1, 1, 4)
        assert g.columns >= 2 and g.rows >= 2

    def test_footprint_is_clipped_to_the_layer(self) -> None:
        smap = compute_source_map([], 0.5, MapGrid.covering(0, 0, 10, 10, 4))
        assert source_footprint(smap, 10, 10) == Rect(0, 0, 10, 10)


@pytest.mark.parametrize("backend", BACKENDS)
def test_single_pin_moves_pixels_within_its_radius(backend: WarpBackend) -> None:
    rig = rig_with([((40, 40), (50, 44), 30)], 96, 96)
    out = full_map(backend, rig)
    r, g, _b, a = out.pixel(49, 43)  # the pixel at the pin's target...
    assert a == pytest.approx(1.0)
    assert (r, g) == pytest.approx((39.5, 39.5), abs=0.75)  # ...shows the pin's source
    assert out.pixel(90, 90)[:2] == pytest.approx((90.5, 90.5), abs=1e-4)  # far: unchanged
    assert out.pixel(5, 80)[:2] == pytest.approx((5.5, 80.5), abs=1e-4)


@pytest.mark.parametrize("backend", BACKENDS)
def test_unedited_rig_is_lossless(backend: WarpBackend) -> None:
    src = noise_image(37, 29)
    rig = PuppetRig(37, 29)
    rig.add_pin((10, 10), 30, 0.5)
    smap = backend.source_map(rig.handles(), 0.5, MapGrid.covering(0, 0, 37, 29, 4))
    assert backend.map_warp(src, (0, 0), Rect(0, 0, 37, 29), smap).data == src.data


@pytest.mark.parametrize("backend", BACKENDS)
def test_content_pulled_from_outside_the_layer_is_transparent(backend: WarpBackend) -> None:
    rig = rig_with([((4, 40), (40, 40), 10)], 80, 80)  # left edge dragged far right
    out = full_map(backend, rig)
    assert out.pixel(20, 40)[3] == 0.0  # samples x < 0
    assert out.pixel(78, 78)[3] == pytest.approx(1.0)


@pytest.mark.parametrize("backend", BACKENDS)
def test_tiled_render_equals_single_pass(backend: WarpBackend) -> None:
    w, h = 60, 44
    src = coordinate_image(w, h)
    rig = rig_with([((20, 20), (28, 16), 25), ((40, 30), (38, 36), 20)], w, h)
    expected = backend.map_warp(src, (0, 0), Rect(0, 0, w, h), backend.source_map(
        rig.handles(), 0.4, MapGrid.covering(0, 0, w, h, 4)))
    canvas = bytearray(len(expected.data))
    row_bytes = w * 16
    reads: list[Rect] = []

    def read(rect: Rect) -> PixelBuffer:
        reads.append(rect)
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
    render_puppet_tiled(backend, rig, 0.4, read, write, progress=fractions.append,
                        tile_size=16)
    assert bytes(canvas) == expected.data
    assert len(fractions) == len(puppet_tiles(w, h, 16)) and fractions[-1] == 1.0
    # untouched corner tiles read little more than themselves
    assert reads[-1].width <= 16 + 4 and reads[-1].height <= 16 + 4


def test_preview_uses_pins_scaled_to_the_preview() -> None:
    src = coordinate_image(50, 25)
    rig = rig_with([((500, 250), (500, 250), 100)], 1000, 500)  # unmoved pin
    out = render_puppet_preview(PythonBackend(), src, rig, 0.5)
    assert out.data == src.data


@needs_native
@pytest.mark.parametrize("stiffness", [0.0, 0.55, 1.0])
def test_native_map_matches_python_reference(stiffness: float) -> None:
    assert NATIVE is not None
    rng = random.Random(11)
    rig = PuppetRig(300, 200)
    for _ in range(12):
        pin = rig.add_pin((rng.uniform(0, 300), rng.uniform(0, 200)), rng.uniform(20, 150),
                          stiffness)
        rig.move_pin(pin.id, (pin.target[0] + rng.uniform(-30, 30),
                              pin.target[1] + rng.uniform(-30, 30)), True)
    pins = rig.pins
    rig.link([pins[0].id, pins[1].id, pins[2].id])
    rig.set_weight([pins[3].id], 3.0)
    grid = MapGrid.covering(0, 0, 300, 200, 5)
    a = NATIVE.source_map(rig.handles(), stiffness, grid)
    b = PythonBackend().source_map(rig.handles(), stiffness, grid)
    assert max(abs(x - y) for x, y in zip(a.data, b.data, strict=True)) < 1e-6
    assert a.bounds == pytest.approx(b.bounds)
    src = noise_image(300, 200)
    rect = Rect(0, 0, 300, 200)
    pa = NATIVE.map_warp(src, (0, 0), rect, a).data
    pb = PythonBackend().map_warp(src, (0, 0), rect, b).data
    assert max(abs(x - y) for x, y in zip(pa, pb, strict=True)) <= 1


def busy_rig(size: int, pins: int) -> PuppetRig:
    rng = random.Random(3)
    rig = PuppetRig(size, size)
    for _ in range(pins):
        rig.add_pin((rng.uniform(0.05, 0.95) * size, rng.uniform(0.05, 0.95) * size),
                    size * 0.09, 0.55)
    for pin in rig.pins[: pins // 3]:
        rig.move_pin(pin.id, (pin.target[0] + rng.uniform(-0.04, 0.04) * size,
                              pin.target[1] + rng.uniform(-0.04, 0.04) * size), True)
    return rig


@needs_native
def test_native_puppet_preview_is_fast_enough() -> None:
    """Brief: smooth preview; same 50 ms budget as the mesh, with 30 pins on 2000x2000."""
    assert NATIVE is not None
    src = noise_image(1024, 1024)
    rig = busy_rig(2000, 30)
    render_puppet_preview(NATIVE, src, rig, 0.55)
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        render_puppet_preview(NATIVE, src, rig, 0.55)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.050 * TIMING_FACTOR, timings


@needs_native
def test_repeated_pin_dragging_does_not_leak() -> None:
    assert isinstance(NATIVE, NativeBackend)
    src = noise_image(256, 256)
    rig = busy_rig(256, 8)
    pin = rig.pins[-1]
    for _ in range(20):
        render_puppet_preview(NATIVE, src, rig, 0.5)
    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    for i in range(200):
        rig.move_pin(pin.id, (100.0 + i % 20, 120.0), True)
        render_puppet_preview(NATIVE, src, rig, 0.5)
    grown = tracemalloc.get_traced_memory()[0] - baseline
    tracemalloc.stop()
    assert grown < 1_000_000, grown


def test_python_backend_handles_small_preview_in_time() -> None:
    src = noise_image(200, 150)
    rig = busy_rig(200, 6)
    start = time.perf_counter()
    render_puppet_preview(PythonBackend(), src, rig, 0.5)
    assert time.perf_counter() - start < 5.0 * TIMING_FACTOR
