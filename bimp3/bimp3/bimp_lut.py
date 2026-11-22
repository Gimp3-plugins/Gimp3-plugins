"""Strict Iridas/Resolve .cube reader and RGB interpolation.

SPDX-License-Identifier: GPL-2.0-or-later
Ordering verified against OpenColorIO's IridasCube reader: red index fastest.
A bundled C accelerator is optional; the scalar reference path uses Python only.
"""

from array import array
from functools import lru_cache
import math
from pathlib import Path
import shlex
import ctypes


@lru_cache(maxsize=1)
def native_module():
    try:
        lib = ctypes.CDLL(str(Path(__file__).with_name("bimp_lut_native.dll")))
        pointer = ctypes.POINTER(ctypes.c_float)
        lib.bimp_lut.argtypes = [
            pointer,
            ctypes.c_size_t,
            pointer,
            ctypes.c_int,
            ctypes.c_int,
            pointer,
            pointer,
            ctypes.c_float,
        ]
        lib.bimp_lut.restype = None
        return lib
    except OSError:
        return None


class Cube:
    def __init__(self, size, dimension, table, low, high, title=""):
        self.size, self.dimension, self.table = size, dimension, table
        self.low, self.high, self.title = tuple(low), tuple(high), title

    def rgb(self, rgb):
        coords = [
            max(0.0, min(1.0, (rgb[i] - self.low[i]) / (self.high[i] - self.low[i]))) * (self.size - 1)
            for i in range(3)
        ]
        base = [min(self.size - 2, int(c)) for c in coords]
        frac = [coords[i] - base[i] for i in range(3)]
        if self.dimension == 1:
            return tuple(
                self.table[base[i] * 3 + i] * (1 - frac[i]) + self.table[(base[i] + 1) * 3 + i] * frac[i]
                for i in range(3)
            )
        output = [0.0, 0.0, 0.0]
        for b in (0, 1):
            for g in (0, 1):
                for r in (0, 1):
                    weight = (
                        (frac[0] if r else 1 - frac[0])
                        * (frac[1] if g else 1 - frac[1])
                        * (frac[2] if b else 1 - frac[2])
                    )
                    offset = ((base[2] + b) * self.size**2 + (base[1] + g) * self.size + base[0] + r) * 3
                    for channel in range(3):
                        output[channel] += self.table[offset + channel] * weight
        return tuple(output)

    def transform(self, pixels, strength=100, accelerated=True):
        """RGBA float32 bytes in/out, alpha untouched; LUT samples stay unclipped."""
        if not 0 <= strength <= 100:
            raise ValueError("Siła LUT musi mieścić się w zakresie 0–100%.")
        if len(pixels) % 16:
            raise ValueError("Nieprawidłowy bufor RGBA float.")
        if strength == 0:
            return bytes(pixels)
        mix = strength / 100.0
        native = native_module() if accelerated else None
        if native is not None:
            values = array("f")
            values.frombytes(bytes(pixels))
            vector = ctypes.c_float * 3
            native.bimp_lut(
                (ctypes.c_float * len(values)).from_buffer(values),
                len(values) // 4,
                (ctypes.c_float * len(self.table)).from_buffer(self.table),
                self.size,
                self.dimension,
                vector(*self.low),
                vector(*self.high),
                mix,
            )
            return values.tobytes()
        values = array("f")
        values.frombytes(bytes(pixels))
        for index in range(0, len(values), 4):
            original = values[index : index + 3]
            mapped = self.rgb(original)
            for channel in range(3):
                values[index + channel] = original[channel] + mix * (mapped[channel] - original[channel])
        return values.tobytes()


def read_cube(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    if stat.st_size > 128 * 1024 * 1024:
        raise ValueError("Plik LUT przekracza limit 128 MB.")
    return _read_cube(str(path), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=4)
def _read_cube(path, _size, _mtime):
    size, dimension, title = None, None, ""
    low, high = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    table = array("f")
    data_started = False
    seen = set()
    with open(path, encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                tokens = shlex.split(line, comments=True)
                if not tokens:
                    continue
                key = tokens[0].upper()
                if key in (
                    "TITLE",
                    "LUT_1D_SIZE",
                    "LUT_3D_SIZE",
                    "DOMAIN_MIN",
                    "DOMAIN_MAX",
                    "LUT_1D_INPUT_RANGE",
                    "LUT_3D_INPUT_RANGE",
                ):
                    if data_started or key in seen:
                        raise ValueError("Powtórzony nagłówek lub nagłówek po danych.")
                    seen.add(key)
                    if key == "TITLE":
                        if len(tokens) != 2:
                            raise ValueError("Nieprawidłowy TITLE.")
                        title = tokens[1]
                    elif key.endswith("_SIZE"):
                        if size is not None or len(tokens) != 2:
                            raise ValueError("Wybierz pojedynczą tablicę 1D albo 3D, bez połączonego shaper LUT.")
                        size = int(tokens[1])
                        dimension = 1 if key == "LUT_1D_SIZE" else 3
                        if not 2 <= size <= (65536 if dimension == 1 else 129):
                            raise ValueError("Rozmiar LUT poza zakresem (1D: 2–65536; 3D: 2–129).")
                    elif key in ("DOMAIN_MIN", "DOMAIN_MAX"):
                        if len(tokens) != 4:
                            raise ValueError("DOMAIN wymaga trzech liczb.")
                        values = list(map(float, tokens[1:]))
                        if key == "DOMAIN_MIN":
                            low = values
                        else:
                            high = values
                    else:
                        if len(tokens) != 3 or any(k in seen for k in ("DOMAIN_MIN", "DOMAIN_MAX")):
                            raise ValueError("Niejednoznaczny zakres wejściowy LUT.")
                        a, b = map(float, tokens[1:])
                        low, high = [a] * 3, [b] * 3
                    continue
                if size is None or len(tokens) != 3:
                    raise ValueError("Oczekiwano nagłówka LUT_SIZE i trzech wartości RGB na wiersz.")
                values = list(map(float, tokens))
                if any(not math.isfinite(v) or abs(v) > 1e20 for v in values):
                    raise ValueError("Nieprawidłowe wartości RGB.")
                data_started = True
                table.extend(values)
                if len(table) > (size if dimension == 1 else size**3) * 3:
                    raise ValueError("Za dużo wierszy danych LUT.")
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"LUT: wiersz {line_number}: {exc}") from exc
    if size is None or len(table) != (size if dimension == 1 else size**3) * 3:
        raise ValueError("Niepełna tablica LUT.")
    if any(not math.isfinite(v) for v in low + high) or any(a >= b for a, b in zip(low, high)):
        raise ValueError("Nieprawidłowy zakres DOMAIN_MIN / DOMAIN_MAX.")
    return Cube(size, dimension, table, low, high, title)
