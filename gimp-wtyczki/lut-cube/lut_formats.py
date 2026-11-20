# -*- coding: utf-8 -*-
"""
Inne formaty LUT-ów niż .cube oraz zapis .cube. Bez GIMP-a i bez numpy.

  * .3dl (Autodesk Lustre / Flame): pierwszy wiersz to siatka wejścia
    (np. „0 64 128 … 1023”), potem N³ wierszy liczb całkowitych
    (zwykle 10-, 12- albo 16-bitowych). Niebieski zmienia się najszybciej.
  * Hald CLUT (PNG): obraz poziomu L ma L³ × L³ pikseli i koduje siatkę
    N = L² węzłów; kolejność pikseli jak w .cube (R najszybciej).

Obraz Hald służy też do zrobienia własnego looku: generujesz obraz
tożsamościowy, poprawiasz go w GIMP-ie (krzywe, poziomy, barwa…) i zapisujesz
wynik jako .cube (hald_to_lut + write_cube).
"""

import os
import struct
import zlib
from array import array

from cube_parser import CubeError, CubeLUT, parse_cube_file
from lut_i18n import tr  # noqa: E402

LUT_EXTENSIONS = (".cube", ".3dl", ".png")
HALD_LEVELS = (4, 5, 6, 7, 8)        # siatka 16, 25, 36, 49, 64


# --- .3dl -------------------------------------------------------------------------

def parse_3dl_text(text, source=""):
    name = os.path.basename(source) if source else tr("plik")
    shaper = None
    out_bits = None
    rows = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        head = parts[0].lower()
        if head == "3dmesh":
            continue
        if head == "mesh" and len(parts) == 3:
            try:
                out_bits = int(parts[2])
            except ValueError:
                raise CubeError(tr("%s, wiersz %d: niepoprawny nagłówek Mesh.") % (name, lineno))
            continue
        if head[0].isalpha():
            continue                      # inne słowa kluczowe (np. LUT8, gamma)
        try:
            values = [int(p) for p in parts]
        except ValueError:
            raise CubeError(tr("%s, wiersz %d: oczekiwano liczb całkowitych: %s")
                            % (name, lineno, line))
        if shaper is None:
            shaper = values
            continue
        if len(values) != 3:
            raise CubeError(tr("%s, wiersz %d: wiersz danych musi mieć 3 liczby.")
                            % (name, lineno))
        rows.append(values)
    if not shaper or len(shaper) < 2:
        raise CubeError(tr("%s: brak siatki wejścia – to nie wygląda na plik .3dl.") % name)
    n = len(shaper)
    if len(rows) != n ** 3:
        raise CubeError(tr("%s: zła liczba wierszy danych – jest %d, a powinno być "
                        "%d³ = %d.") % (name, len(rows), n, n ** 3))
    if out_bits:
        out_max = float((1 << out_bits) - 1)
    else:
        top = max(max(r) for r in rows)
        out_max = float(next((m for m in (1023, 4095, 16383, 65535) if top <= m),
                             top))
    # .3dl: B najszybciej (pętla r, g, b) → .cube: R najszybciej.
    table = array("f", bytes(4 * 3 * n ** 3))
    i = 0
    for r in range(n):
        for g in range(n):
            for b in range(n):
                o = 3 * (r + n * g + n * n * b)
                vr, vg, vb = rows[i]
                table[o] = vr / out_max
                table[o + 1] = vg / out_max
                table[o + 2] = vb / out_max
                i += 1
    title = os.path.splitext(os.path.basename(source))[0] if source else ""
    return CubeLUT(title, 0, None, n, table)


# --- minimalny PNG (zapis i odczyt RGB/RGBA, 8 i 16 bitów) ------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def write_png_rgb16(path, width, height, rgb):
    """Zapisuje PNG RGB 16 bitów; rgb – płaska lista wartości 0–1."""
    raw = bytearray()
    row_len = width * 3
    for y in range(height):
        raw.append(0)                     # filtr: brak
        vals = rgb[y * row_len:(y + 1) * row_len]
        raw += struct.pack(">%dH" % row_len,
                           *[0 if v <= 0 else (65535 if v >= 1 else int(v * 65535 + 0.5))
                             for v in vals])
    with open(path, "wb") as f:
        f.write(_PNG_SIG)
        f.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 2, 0, 0, 0)))
        f.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(_chunk(b"IEND", b""))


def png_size(path):
    """(szerokość, wysokość) z nagłówka PNG albo None, gdy to nie PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png_rgb(path):
    """Czyta PNG RGB/RGBA 8/16 bitów bez przeplotu. Zwraca (w, h, rgb 0–1)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != _PNG_SIG:
        raise CubeError(tr("%s: to nie jest plik PNG.") % os.path.basename(path))
    pos, idat, ihdr = 8, bytearray(), None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise CubeError(tr("%s: uszkodzony PNG (brak IHDR).") % os.path.basename(path))
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if ctype not in (2, 6) or depth not in (8, 16) or interlace:
        raise CubeError(tr("%s: obsługiwany jest PNG RGB/RGBA 8 lub 16 bitów bez "
                        "przeplotu (zapisz obraz Hald ponownie z GIMP-a).")
                        % os.path.basename(path))
    channels = 3 if ctype == 2 else 4
    bpp = channels * depth // 8
    stride = w * bpp
    raw = zlib.decompress(bytes(idat))
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ftype = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if depth == 16:
        vals = struct.unpack(">%dH" % (w * h * channels), bytes(out))
        scale = 65535.0
    else:
        vals = out
        scale = 255.0
    rgb = []
    for i in range(0, len(vals), channels):
        rgb += (vals[i] / scale, vals[i + 1] / scale, vals[i + 2] / scale)
    return w, h, rgb


# --- Hald CLUT -----------------------------------------------------------------------

def hald_level(width, height):
    """Poziom L obrazu Hald (L³ × L³) albo None."""
    if width != height:
        return None
    for level in range(2, 17):
        if level ** 3 == width:
            return level
    return None


def hald_identity(level):
    """Tożsamościowy Hald: (bok, rgb 0–1) – każdy piksel to węzeł siatki."""
    n = level * level
    side = level ** 3
    rgb = []
    for b in range(n):
        for g in range(n):
            for r in range(n):
                rgb += (r / (n - 1), g / (n - 1), b / (n - 1))
    return side, rgb


def hald_to_lut(width, height, rgb, title=""):
    """Obraz Hald (rgb 0–1) → CubeLUT 3D."""
    level = hald_level(width, height)
    if level is None:
        raise CubeError(tr("To nie jest obraz Hald CLUT: wymiary %d×%d (oczekiwano "
                        "kwadratu L³×L³, np. 512×512).") % (width, height))
    n = level * level
    return CubeLUT(title, 0, None, n, array("f", rgb[:3 * n ** 3]))


def parse_hald_png(path):
    w, h, rgb = read_png_rgb(path)
    return hald_to_lut(w, h, rgb, os.path.splitext(os.path.basename(path))[0])


def is_hald_png(path):
    size = png_size(path)
    return size is not None and hald_level(*size) is not None


# --- zapis .cube --------------------------------------------------------------------

def write_cube(lut, path, title=None):
    """Zapisuje LUT (część 1D i/lub 3D) w formacie .cube."""
    lines = ['TITLE "%s"' % (title if title is not None else lut.title or "LUT")]
    if lut.size_1d:
        lines.append("LUT_1D_SIZE %d" % lut.size_1d)
    if lut.size_3d:
        lines.append("LUT_3D_SIZE %d" % lut.size_3d)
    lo, hi = lut.domain_min_3d, lut.domain_max_3d
    if (lo, hi) != ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)):
        lines.append("DOMAIN_MIN %g %g %g" % lo)
        lines.append("DOMAIN_MAX %g %g %g" % hi)
    for table in (lut.table_1d, lut.table_3d):
        if table is not None:
            for i in range(0, len(table), 3):
                lines.append("%.6f %.6f %.6f" % (table[i], table[i + 1], table[i + 2]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


# --- wczytanie dowolnego obsługiwanego pliku ----------------------------------------

def is_lut_file(path, check_png=True):
    """Czy plik wygląda na LUT (dla .png: tylko obraz Hald)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return not check_png or is_hald_png(path)
    return ext in (".cube", ".3dl")


def load_lut_file(path):
    """Wczytuje .cube, .3dl albo Hald PNG. Rzuca CubeError."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cube":
        return parse_cube_file(path)
    try:
        if ext == ".3dl":
            from cube_parser import read_text
            return parse_3dl_text(read_text(path), path)
        if ext == ".png":
            return parse_hald_png(path)
    except OSError as e:
        raise CubeError(tr("Nie można odczytać pliku %s: %s")
                        % (os.path.basename(path), e.strerror or e))
    except (zlib.error, struct.error) as e:
        raise CubeError(tr("Uszkodzony plik %s: %s") % (os.path.basename(path), e))
    raise CubeError(tr("Nieobsługiwany format pliku: %s (obsługiwane: .cube, .3dl, "
                    "Hald CLUT .png).") % os.path.basename(path))
