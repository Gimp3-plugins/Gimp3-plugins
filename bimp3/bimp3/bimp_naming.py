"""Output name patterns and the image facts they use (EXIF date, size, orientation).

SPDX-License-Identifier: GPL-2.0-or-later
Pure Python, without GIMP: names are planned before any image is opened.

Tokens (besides the classic $$ name, ## number, @@ date/time):
  {name} {name:lower} {name:upper}  source file name without extension
  {n} {n:03}                        number, optionally zero-padded
  {date} {date:%Y%m%d}              time of the run
  {mtime:%Y-%m-%d}                  file modification time
  {exif:%Y-%m-%d}                   EXIF DateTimeOriginal, else modification time
  {w} {h}                           original width / height (after EXIF rotation)
  {ext} {folder}                    source extension and parent folder name
"""

from datetime import datetime
import re
import struct
from pathlib import Path

TOKEN = re.compile(r"\{(\w+)(?::([^{}]*))?\}|\$\$|##|@@")
TOKENS = {"name", "n", "date", "mtime", "exif", "w", "h", "ext", "folder"}


def parse_tiff(data, want_size=False):
    """Orientation, DateTimeOriginal and (optionally) size from a TIFF/EXIF block."""
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        return {}
    order = "<" if data[:2] == b"II" else ">"
    facts = {}

    def entries(offset):
        if offset <= 0 or offset + 2 > len(data):
            return
        count = struct.unpack_from(order + "H", data, offset)[0]
        for index in range(min(count, 512)):
            position = offset + 2 + index * 12
            if position + 12 > len(data):
                return
            tag, kind, number = struct.unpack_from(order + "HHI", data, position)
            yield tag, kind, number, position + 8

    def value(kind, number, position):
        if kind == 3:
            return struct.unpack_from(order + "H", data, position)[0]
        if kind == 4:
            return struct.unpack_from(order + "I", data, position)[0]
        if kind == 2:
            start = position if number <= 4 else struct.unpack_from(order + "I", data, position)[0]
            return data[start : start + number].split(b"\0", 1)[0].decode("ascii", "replace")
        return None

    try:
        ifd0 = struct.unpack_from(order + "I", data, 4)[0]
        exif_ifd = None
        for tag, kind, number, position in entries(ifd0):
            if tag == 0x0112:
                facts["orientation"] = value(kind, number, position)
            elif tag == 0x0132:
                facts.setdefault("datetime", value(kind, number, position))
            elif tag == 0x8769:
                exif_ifd = value(kind, number, position)
            elif want_size and tag in (0x0100, 0x0101):
                facts["width" if tag == 0x0100 else "height"] = value(kind, number, position)
        for tag, kind, number, position in entries(exif_ifd or 0):
            if tag == 0x9003:
                facts["datetime"] = value(kind, number, position)
    except struct.error:
        pass
    return facts


def read_image_facts(path):
    """Best effort: width, height, orientation and datetime of common formats."""
    path = Path(path)
    facts = {}
    try:
        with path.open("rb") as stream:
            head = stream.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                facts["width"], facts["height"] = struct.unpack(">II", head[16:24])
                stream.seek(8)
                while True:
                    header = stream.read(8)
                    if len(header) < 8:
                        break
                    length, kind = struct.unpack(">I4s", header)
                    if kind == b"eXIf":
                        facts.update({k: v for k, v in parse_tiff(stream.read(length)).items() if v is not None})
                        break
                    if kind == b"IDAT":
                        break
                    stream.seek(length + 4, 1)
            elif head[:2] == b"\xff\xd8":
                stream.seek(2)
                while True:
                    marker = stream.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        break
                    if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    length = struct.unpack(">H", stream.read(2))[0]
                    body = stream.read(length - 2)
                    if marker[1] == 0xE1 and body.startswith(b"Exif\0\0"):
                        facts.update({k: v for k, v in parse_tiff(body[6:]).items() if v is not None})
                    elif 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        facts["height"], facts["width"] = struct.unpack(">HH", body[1:5])
                        break
                    elif marker[1] == 0xDA:
                        break
            elif head[:6] in (b"GIF87a", b"GIF89a"):
                facts["width"], facts["height"] = struct.unpack("<HH", head[6:10])
            elif head[:2] == b"BM":
                width, height = struct.unpack("<ii", head[18:26])
                facts["width"], facts["height"] = width, abs(height)
            elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                chunk = head[12:16]
                stream.seek(12)
                body = stream.read(64)
                if chunk == b"VP8X":
                    facts["width"] = 1 + int.from_bytes(body[12:15], "little")
                    facts["height"] = 1 + int.from_bytes(body[15:18], "little")
                elif chunk == b"VP8 ":
                    facts["width"], facts["height"] = (v & 0x3FFF for v in struct.unpack("<HH", body[14:18]))
                elif chunk == b"VP8L":
                    bits = int.from_bytes(body[9:13], "little")
                    facts["width"], facts["height"] = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            elif head[:4] in (b"II*\0", b"MM\0*"):
                stream.seek(0)
                facts.update({k: v for k, v in parse_tiff(stream.read(4 * 1024 * 1024), True).items() if v})
    except (OSError, struct.error, ValueError):
        pass
    if facts.get("orientation") in (5, 6, 7, 8) and "width" in facts and "height" in facts:
        facts["width"], facts["height"] = facts["height"], facts["width"]
    return facts


def exif_datetime(text):
    try:
        return datetime.strptime(str(text).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def pattern_tokens(pattern):
    """Validate the pattern; returns the set of tokens it uses."""
    used = set()
    stripped = TOKEN.sub("", pattern)
    if "{" in stripped or "}" in stripped:
        raise ValueError(f"Niezamknięty lub nieznany znacznik we wzorcu nazwy: {pattern!r}")
    for match in TOKEN.finditer(pattern):
        if match[1] is None:
            continue
        name, spec = match[1], match[2]
        if name not in TOKENS:
            raise ValueError(f"Nieznany znacznik {{{name}}} we wzorcu nazwy.")
        if name == "name" and spec not in (None, "lower", "upper"):
            raise ValueError("{name} przyjmuje tylko :lower albo :upper.")
        if name == "n" and spec not in (None, "") and not re.fullmatch(r"0?\d", spec):
            raise ValueError("{n} przyjmuje szerokość, np. {n:03}.")
        if name in ("w", "h", "ext", "folder") and spec:
            raise ValueError(f"{{{name}}} nie przyjmuje formatu.")
        used.add(name)
    return used


def needs_facts(pattern):
    return bool(pattern_tokens(pattern) & {"exif", "w", "h"})


def render_name(pattern, path, number, now, facts=None, stamp=None):
    """Substitute every token exactly once; text from file names is never re-parsed."""
    path = Path(path)
    facts = facts or {}

    def moment(kind, spec):
        if kind == "date":
            value = now
        else:
            value = None
            if kind == "exif":
                value = exif_datetime(facts.get("datetime", ""))
            if value is None:
                value = datetime.fromtimestamp(path.stat().st_mtime)
        try:
            return value.strftime(spec or "%Y-%m-%d_%H-%M")
        except ValueError as exc:
            raise ValueError(f"Nieprawidłowy format daty {spec!r}: {exc}") from None

    def replace(match):
        token = match[0]
        if token == "$$":
            return path.stem
        if token == "##":
            return str(number)
        if token == "@@":
            return stamp or now.strftime("%Y-%m-%d_%H-%M")
        name, spec = match[1], match[2]
        if name == "name":
            return path.stem.lower() if spec == "lower" else path.stem.upper() if spec == "upper" else path.stem
        if name == "n":
            return format(number, spec) if spec else str(number)
        if name in ("date", "mtime", "exif"):
            return moment(name, spec)
        if name in ("w", "h"):
            key = "width" if name == "w" else "height"
            if not facts.get(key):
                raise ValueError(f"Nie udało się odczytać rozmiaru zdjęcia {path.name} dla {{{name}}}.")
            return str(facts[key])
        if name == "ext":
            return path.suffix.lstrip(".").lower()
        return path.parent.name

    return TOKEN.sub(replace, pattern)
