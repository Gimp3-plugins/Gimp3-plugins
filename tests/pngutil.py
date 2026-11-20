# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 PSHost contributors
"""Minimal PNG decoder (8-bit RGB/RGBA, all filter types) for the tests."""
import struct, zlib

def decode_png(path):
    d = open(path, "rb").read(); pos = 8; idat = b""
    while pos < len(d):
        ln, typ = struct.unpack(">I4s", d[pos:pos + 8]); body = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR": w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        if typ == b"IDAT": idat += body
        pos += 12 + ln
    bpp = {6: 4, 2: 3}[ct]; raw = zlib.decompress(idat); stride = w * bpp; rows = []; prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]; line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0; b = prev[i]; c = prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line); prev = line
    return w, h, bpp, rows
