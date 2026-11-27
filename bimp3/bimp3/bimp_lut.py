"""Strict Iridas/Resolve .cube reader and RGB interpolation.

SPDX-License-Identifier: GPL-2.0-or-later
Ordering verified against OpenColorIO's IridasCube reader: red index fastest.
A bundled C accelerator is optional; the scalar reference path uses Python only.
"""

from array import array
from functools import lru_cache
from hashlib import sha256
import math
import os
from pathlib import Path
import shlex
import sys
import ctypes

NATIVE_NAMES = {"nt": "bimp_lut_native.dll", "darwin": "bimp_lut_native.dylib"}
native_problem = None


def native_library_path():
    name = NATIVE_NAMES["nt"] if os.name == "nt" else NATIVE_NAMES.get(sys.platform, "bimp_lut_native.so")
    return Path(__file__).with_name(name)


def verify_native(path):
    """The accelerator runs inside GIMP: load only the exact reviewed build."""
    digest_file = path.with_name(path.name + ".sha256")
    if not path.is_file():
        return "brak biblioteki " + path.name
    if not digest_file.is_file():
        return "brak sumy kontrolnej " + digest_file.name
    expected = digest_file.read_text(encoding="ascii").split()[0].lower()
    if sha256(path.read_bytes()).hexdigest() != expected:
        return "suma kontrolna " + path.name + " nie zgadza się"
    return None


@lru_cache(maxsize=1)
def native_module():
    global native_problem
    path = native_library_path()
    native_problem = verify_native(path)
    if native_problem:
        return None
    try:
        lib = ctypes.CDLL(str(path))
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
    except OSError as exc:
        native_problem = str(exc)
        return None


class Cube:
    def __init__(self, size, dimension, table, low, high, title=""):
        self.size, self.dimension, self.table = size, dimension, table
        self.low, self.high, self.title = tuple(low), tuple(high), title

    def rgb(self, rgb):
        size, low, high, table = self.size, self.low, self.high, self.table
        scale = size - 1
        base, frac = [0, 0, 0], [0.0, 0.0, 0.0]
        for i in range(3):
            x = (rgb[i] - low[i]) / (high[i] - low[i])
            # Same clamping as the C accelerator; NaN becomes 0.
            x = 0.0 if not x >= 0.0 else 1.0 if x > 1.0 else x
            x *= scale
            index = int(x)
            if index > size - 2:
                index = size - 2
            base[i], frac[i] = index, x - index
        if self.dimension == 1:
            return tuple(
                table[base[i] * 3 + i] * (1 - frac[i]) + table[(base[i] + 1) * 3 + i] * frac[i] for i in range(3)
            )
        fr, fg, fb = frac
        row, plane = size * 3, size * size * 3
        origin = base[2] * plane + base[1] * row + base[0] * 3
        out_r = out_g = out_b = 0.0
        for offset, weight in (
            (0, (1 - fr) * (1 - fg) * (1 - fb)),
            (3, fr * (1 - fg) * (1 - fb)),
            (row, (1 - fr) * fg * (1 - fb)),
            (row + 3, fr * fg * (1 - fb)),
            (plane, (1 - fr) * (1 - fg) * fb),
            (plane + 3, fr * (1 - fg) * fb),
            (plane + row, (1 - fr) * fg * fb),
            (plane + row + 3, fr * fg * fb),
        ):
            position = origin + offset
            out_r += table[position] * weight
            out_g += table[position + 1] * weight
            out_b += table[position + 2] * weight
        return (out_r, out_g, out_b)

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
        rgb = self.rgb
        for index in range(0, len(values), 4):
            r, g, b = values[index], values[index + 1], values[index + 2]
            mr, mg, mb = rgb((r, g, b))
            values[index] = r + mix * (mr - r)
            values[index + 1] = g + mix * (mg - g)
            values[index + 2] = b + mix * (mb - b)
        return values.tobytes()


def read_cube(path):
    try:
        path = Path(path).resolve(strict=True)
    except OSError:
        raise ValueError(f"Nie znaleziono pliku LUT: {path}") from None
    stat = path.stat()
    if stat.st_size > 128 * 1024 * 1024:
        raise ValueError("Plik LUT przekracza limit 128 MB.")
    return _read_cube(str(path), stat.st_size, stat.st_mtime_ns)


NUMERIC_START = frozenset("0123456789+-.")


@lru_cache(maxsize=4)
def _read_cube(path, _size, _mtime):
    size, dimension, title = None, None, ""
    low, high = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    table = array("f")
    data_started = False
    seen = set()
    with open(path, encoding="utf-8-sig") as stream:
        expected = None
        for line_number, line in enumerate(stream, 1):
            try:
                stripped = line.lstrip()
                if data_started and stripped[:1] in NUMERIC_START:
                    # Fast path for the (up to 2 million) data rows; keywords keep shlex.
                    tokens = stripped.split("#", 1)[0].split()
                    if len(tokens) != 3:
                        raise ValueError("Oczekiwano trzech wartości RGB na wiersz.")
                    r, g, b = float(tokens[0]), float(tokens[1]), float(tokens[2])
                    # Also rejects NaN, because every comparison with NaN is false.
                    if not (abs(r) <= 1e20 and abs(g) <= 1e20 and abs(b) <= 1e20):
                        raise ValueError("Nieprawidłowe wartości RGB.")
                    table.append(r)
                    table.append(g)
                    table.append(b)
                    if len(table) > expected:
                        raise ValueError("Za dużo wierszy danych LUT.")
                    continue
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
                expected = (size if dimension == 1 else size**3) * 3
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
