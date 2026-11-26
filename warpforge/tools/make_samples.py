#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the sample images used for manual tests (no third-party packages).

    python tools/make_samples.py                 # data/samples/*.png (committed, 1000 px)
    python tools/make_samples.py --large         # also 4000 and 8000 px grids into dist/samples

* ``grid-<n>.png`` - checkerboard with a labelled-looking line grid: warps show
  clearly, straight lines reveal any kink. Opaque RGB.
* ``figure-1000.png`` - a simple jointed figure on a transparent background,
  the typical Puppet Warp subject (pins on joints, alpha edges).
"""

from __future__ import annotations

import argparse
import logging
import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("samples")


def write_png(path: Path, width: int, height: int, rows: list[bytes], alpha: bool) -> None:
    """Minimal PNG writer: 8-bit RGB or RGBA, filter 0 on every row."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    log.info("wrote %s (%dx%d)", path.relative_to(ROOT), width, height)


def grid_image(size: int) -> list[bytes]:
    """Checker squares of size/16, thin dark lines every size/32. Built row-wise (fast)."""
    cell = max(2, size // 16)
    line_every = max(2, size // 32)
    line_width = max(1, size // 500)
    light, dark, ink = bytes((235, 225, 200)), bytes((120, 160, 210)), bytes((30, 30, 40))

    def row(y: int) -> bytes:
        if y % line_every < line_width:
            return ink * size
        pixels = bytearray()
        band = (y // cell) % 2
        for x0 in range(0, size, cell):
            colour = light if ((x0 // cell) % 2) == band else dark
            pixels += colour * min(cell, size - x0)
        for x in range(0, size, line_every):  # vertical lines
            for k in range(line_width):
                if x + k < size:
                    pixels[3 * (x + k):3 * (x + k) + 3] = ink
        return bytes(pixels)

    cache: dict[tuple[int, bool], bytes] = {}
    rows = []
    for y in range(size):
        key = ((y // cell) % 2, y % line_every < line_width)
        if key not in cache:
            cache[key] = row(y)
        rows.append(cache[key])
    return rows


def figure_image(size: int) -> list[bytes]:
    """A jointed figure: capsules between joints, a round head, soft 1 px edges."""
    s = size / 1000
    joints = {
        "head": (500, 170), "neck": (500, 260), "hip": (500, 560),
        "l_elbow": (370, 380), "l_hand": (280, 520), "r_elbow": (630, 370), "r_hand": (740, 250),
        "l_knee": (420, 740), "l_foot": (380, 930), "r_knee": (585, 745), "r_foot": (640, 930),
    }
    joints = {k: (x * s, y * s) for k, (x, y) in joints.items()}
    bones = [("neck", "hip", 70), ("neck", "l_elbow", 34), ("l_elbow", "l_hand", 30),
             ("neck", "r_elbow", 34), ("r_elbow", "r_hand", 30), ("hip", "l_knee", 42),
             ("l_knee", "l_foot", 36), ("hip", "r_knee", 42), ("r_knee", "r_foot", 36)]
    shapes = [(joints[a], joints[b], r * s) for a, b, r in bones]
    head = (joints["head"], 85 * s)

    def coverage(x: float, y: float) -> tuple[float, tuple[int, int, int]]:
        hx, hy = head[0]
        d = math.hypot(x - hx, y - hy) - head[1]
        if d < 1:
            return min(1.0, 1 - d) if d > 0 else 1.0, (240, 190, 150)
        best = 2.0
        for (ax, ay), (bx, by), r in shapes:
            vx, vy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / (vx * vx + vy * vy)))
            best = min(best, math.hypot(x - ax - t * vx, y - ay - t * vy) - r)
        if best < 1:
            # stripes across the body make bending visible
            stripe = int((y / s) // 40) % 2
            colour = (200, 70, 60) if stripe else (230, 120, 60)
            return (1.0 if best <= 0 else 1 - best), colour
        return 0.0, (0, 0, 0)

    rows = []
    for py in range(size):
        out = bytearray()
        for px in range(size):
            a, (r, g, b) = coverage(px + 0.5, py + 0.5)
            out += bytes((r, g, b, round(255 * a))) if a > 0 else b"\x00\x00\x00\x00"
        rows.append(bytes(out))
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true",
                        help="also 4000 and 8000 px grids (into dist/samples, not committed)")
    args = parser.parse_args()
    samples = ROOT / "data" / "samples"
    write_png(samples / "grid-1000.png", 1000, 1000, grid_image(1000), alpha=False)
    write_png(samples / "figure-1000.png", 1000, 1000, figure_image(1000), alpha=True)
    if args.large:
        for size in (4000, 8000):
            write_png(ROOT / "dist" / "samples" / f"grid-{size}.png", size, size,
                      grid_image(size), alpha=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
