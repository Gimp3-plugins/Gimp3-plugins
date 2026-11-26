#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Time the full-resolution tiled warps at the sizes named in the brief.

Measures the warp kernels and the tiling overhead with in-memory tiles; GEGL
read/write time inside GIMP comes on top.

    python tools/benchmark.py [--sizes 1000 4000 8000] [--mesh 8] [--pins 30]
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from warpforge.mesh import Mesh
from warpforge.puppet import PuppetRig
from warpforge.render import (
    TILE_SIZE,
    plan_tiles,
    puppet_tiles,
    render_mesh_tiled,
    render_puppet_tiled,
    select_backend,
)
from warpforge.state import PixelBuffer, Rect

log = logging.getLogger("benchmark")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 4000, 8000])
    parser.add_argument("--mesh", type=int, default=8)
    parser.add_argument("--pins", type=int, default=30)
    args = parser.parse_args()
    backend = select_backend()
    log.info("backend: %s", backend.name)
    rng = random.Random(1)
    for size in args.sizes:
        mesh = Mesh(args.mesh, args.mesh, size, size)
        for i in range(len(mesh.vertices)):
            x, y = mesh.vertices[i]
            jitter = size / args.mesh / 3
            dx, dy = rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter)
            mesh.move_vertex(i, (x + dx, y + dy))
        cache: dict[tuple[int, int], PixelBuffer] = {}

        def read(rect: Rect, cache: dict[tuple[int, int], PixelBuffer] = cache) -> PixelBuffer:
            key = (rect.width, rect.height)
            if key not in cache:
                cache[key] = PixelBuffer(rect.width, rect.height,
                                         bytes(rect.width * rect.height * 16), dtype="f32")
            return cache[key]

        tiles = len(plan_tiles(mesh, TILE_SIZE))
        start = time.perf_counter()
        render_mesh_tiled(backend, mesh, read, lambda rect, px: None)
        elapsed = time.perf_counter() - start
        log.info("mesh %dx%d  %5d x %-5d  %3d tiles  %6.2f s  (%.1f Mpx/s)", args.mesh,
                 args.mesh, size, size, tiles, elapsed, size * size / elapsed / 1e6)

        rig = PuppetRig(size, size)
        for _ in range(args.pins):
            rig.add_pin((rng.uniform(0.05, 0.95) * size, rng.uniform(0.05, 0.95) * size),
                        size * 0.09, 0.55)
        for pin in rig.pins[: args.pins // 3]:
            rig.move_pin(pin.id, (pin.target[0] + rng.uniform(-0.04, 0.04) * size,
                                  pin.target[1] + rng.uniform(-0.04, 0.04) * size), True)
        tiles = len(puppet_tiles(size, size, TILE_SIZE))
        start = time.perf_counter()
        render_puppet_tiled(backend, rig, 0.55, read, lambda rect, px: None)
        elapsed = time.perf_counter() - start
        log.info("puppet %d pins %5d x %-5d  %3d tiles  %6.2f s  (%.1f Mpx/s)", args.pins,
                 size, size, tiles, elapsed, size * size / elapsed / 1e6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
