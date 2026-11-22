"""BIMP 3 settings and path planning, independent of GIMP.

SPDX-License-Identifier: GPL-2.0-or-later
Original BIMP: Alessandro Francesconi. GIMP 3 rewrite: 2026.
"""

import configparser
import copy
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


FORMATS = ["bmp", "gif", "ico", "jpg", "png", "tga", "tiff", "heif", "webp", "avif", "exr", "xcf"]
RATIOS = [(1, 1), (3, 2), (4, 3), (16, 9), (16, 10), (7, 9), (2, 3), (40, 71), (3, 4)]
POSITIONS = [
    "Lewy górny",
    "Środek górny",
    "Prawy górny",
    "Lewy środek",
    "Środek",
    "Prawy środek",
    "Lewy dolny",
    "Środek dolny",
    "Prawy dolny",
]
# field: label, default, optional range or choices. Integers in choices store indices.
SCHEMAS = {
    "resize": (
        "Zmiana rozmiaru",
        {
            "resize_mode_width": ("Szerokość: jednostka", 0, ["Procenty", "Piksele", "Bez zmiany"]),
            "new_w_pc": ("Szerokość (%)", 100.0, (0.01, 10000)),
            "new_w_px": ("Szerokość (px)", 640, (1, 524288)),
            "resize_mode_height": ("Wysokość: jednostka", 0, ["Procenty", "Piksele", "Bez zmiany"]),
            "new_h_pc": ("Wysokość (%)", 100.0, (0.01, 10000)),
            "new_h_px": ("Wysokość (px)", 480, (1, 524288)),
            "stretch_mode": ("Proporcje", 1, ["Rozciągnij", "Zachowaj proporcje", "Dopasuj i dodaj tło"]),
            "padding_color": ("Kolor tła", "#000000"),
            "padding_color_alpha": ("Krycie tła (0–65535)", 65535, (0, 65535)),
            "interpolation": ("Interpolacja", 2, ["Brak", "Liniowa", "Sześcienna", "NoHalo", "LoHalo"]),
            "change_res": ("Zmień rozdzielczość druku", False),
            "new_res_x": ("Rozdzielczość X (ppi)", 72.0, (0.01, 100000)),
            "new_res_y": ("Rozdzielczość Y (ppi)", 72.0, (0.01, 100000)),
        },
    ),
    "crop": (
        "Kadrowanie",
        {
            "manual": ("Użyj wymiarów w pikselach", False),
            "new_w": ("Szerokość (px)", 640, (1, 524288)),
            "new_h": ("Wysokość (px)", 480, (1, 524288)),
            "ratio": ("Proporcje", 0, ["1:1", "3:2", "4:3", "16:9", "16:10", "7:9", "2:3", "40:71", "3:4", "Własne"]),
            "custom_ratio1": ("Własne proporcje: szerokość", 1.0, (0.001, 10000)),
            "custom_ratio2": ("Własne proporcje: wysokość", 1.0, (0.001, 10000)),
            "start_pos": ("Położenie", 0, ["Środek", "Lewy górny", "Prawy górny", "Lewy dolny", "Prawy dolny"]),
        },
    ),
    "fliprotate": (
        "Odbicie i obrót",
        {
            "flip_h": ("Odbij poziomo", False),
            "flip_v": ("Odbij pionowo", False),
            "rotate": ("Obróć", False),
            "rotation_type": ("Kąt", 0, ["90°", "180°", "270°"]),
        },
    ),
    "color": (
        "Korekcja kolorów",
        {
            "brightness": ("Jasność", 0.0, (-0.5, 0.5)),
            "contrast": ("Kontrast", 0.0, (-0.5, 0.5)),
            "levels_auto": ("Automatyczne poziomy", False),
            "grayscale": ("Skala szarości", False),
            "curve_file": ("Plik krzywych GIMP (opcjonalny)", ""),
        },
    ),
    "sharpblur": (
        "Wyostrzenie / rozmycie",
        {
            "amount": ("Wartość: ujemna wyostrza, dodatnia rozmywa", 0, (-100, 100)),
        },
    ),
    "watermark": (
        "Znak wodny",
        {
            "mode": ("Tekst (wyłącz dla obrazu)", True),
            "text": ("Tekst", ""),
            "font": ("Czcionka i rozmiar", "Sans 16px"),
            "color": ("Kolor", "#000000"),
            "image_file": ("Plik obrazu", ""),
            "image_sizemode": (
                "Skalowanie obrazu znaku",
                0,
                ["Bez skalowania", "% szerokości zdjęcia", "% wysokości zdjęcia"],
            ),
            "image_size_percent": ("Rozmiar obrazu znaku (%)", 25.0, (0.01, 1000)),
            "opacity": ("Krycie (%)", 100.0, (0, 100)),
            "edge_distance": ("Odstęp od krawędzi (px)", 0, (0, 524288)),
            "position": ("Położenie", 8, POSITIONS),
        },
    ),
    "changeformat": (
        "Format i kompresja",
        {
            "format": ("Format", 3, FORMATS),
        },
    ),
    "rename": ("Zmiana nazwy", {"pattern": ("Wzorzec: $$ nazwa, ## numer, @@ data", "$$")}),
    "userdef": ("Inna procedura GIMP 3", {"procedure": ("Nazwa procedury", "")}),
    "lut": (
        "Kolory z LUT (.cube)",
        {
            "file": ("Plik LUT (.cube)", ""),
            "strength": ("Siła LUT (%)", 100.0, (0, 100)),
        },
    ),
}


def new_step(kind):
    result = {"type": kind, "settings": {k: copy.deepcopy(v[1]) for k, v in SCHEMAS[kind][1].items()}}
    if kind in ("changeformat", "userdef"):
        result["settings"]["arguments"] = {}
    return result


def validate_steps(steps):
    if not isinstance(steps, list):
        raise ValueError("Lista operacji musi być tablicą.")
    counts = {}
    for step in steps:
        if not isinstance(step, dict) or step.get("type") not in SCHEMAS:
            raise ValueError("Nieznany typ operacji.")
        kind = step["type"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("rename", "changeformat") and counts[kind] > 1:
            raise ValueError("Można dodać tylko jedną zmianę nazwy i jedną zmianę formatu.")
        values = step.get("settings")
        if not isinstance(values, dict):
            raise ValueError("Nieprawidłowe ustawienia operacji.")
        allowed = set(SCHEMAS[kind][1]) | ({"arguments"} if kind in ("changeformat", "userdef") else set())
        if set(values) - allowed:
            raise ValueError(f"Nieznane ustawienia: {set(values) - allowed}")
        for key, field in SCHEMAS[kind][1].items():
            value = values.get(key, field[1])
            default = field[1]
            if isinstance(default, bool):
                valid = type(value) is bool
            elif isinstance(default, (int, float)):
                valid = type(value) in (int, float) and math.isfinite(value)
                if isinstance(default, int):
                    valid = valid and type(value) is int
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError(f"Nieprawidłowa wartość: {key}")
            if len(field) == 3:
                limits = field[2]
                if isinstance(limits, list):
                    valid = 0 <= value < len(limits)
                else:
                    valid = limits[0] <= value <= limits[1]
                if not valid:
                    raise ValueError(f"Wartość poza zakresem: {key}")
            values[key] = value
        if "arguments" in allowed and not isinstance(values.setdefault("arguments", {}), dict):
            raise ValueError("Argumenty procedury muszą być obiektem JSON.")
        if kind == "rename":
            safe_name(values["pattern"])
        if kind == "watermark" and not values["mode"] and not values["image_file"]:
            raise ValueError("Wybierz plik obrazu znaku wodnego.")
        if kind == "userdef" and not values["procedure"]:
            raise ValueError("Wybierz procedurę GIMP 3.")
        if kind == "lut" and not values["file"]:
            raise ValueError("Wybierz plik LUT .cube.")
    return steps


def safe_name(name):
    if not name or name in (".", "..") or any(c in name for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in name):
        raise ValueError(f"Nieprawidłowa nazwa pliku: {name!r}")
    if name.endswith((" ", ".")) or name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)),
    }:
        raise ValueError(f"Zastrzeżona nazwa pliku: {name!r}")
    return name


def resize_geometry(width, height, s):
    modes = s["resize_mode_width"], s["resize_mode_height"]
    factors = [
        s["new_w_pc"] / 100 if modes[0] == 0 else s["new_w_px"] / width if modes[0] == 1 else 1,
        s["new_h_pc"] / 100 if modes[1] == 0 else s["new_h_px"] / height if modes[1] == 1 else 1,
    ]
    if modes == (2, 2):
        return width, height, width, height
    canvas = [max(1, round(width * factors[0])), max(1, round(height * factors[1]))]
    if s["stretch_mode"]:
        factor = min(f for f, mode in zip(factors, modes) if mode != 2)
        scaled = [max(1, round(width * factor)), max(1, round(height * factor))]
        if s["stretch_mode"] == 1:
            canvas = scaled[:]
        else:
            canvas = [scaled[i] if modes[i] == 2 else canvas[i] for i in range(2)]
    else:
        scaled = canvas[:]
    return (*scaled, *canvas)


def crop_geometry(width, height, s):
    if s["manual"]:
        w, h = min(width, s["new_w"]), min(height, s["new_h"])
    else:
        a, b = RATIOS[s["ratio"]] if s["ratio"] < len(RATIOS) else (s["custom_ratio1"], s["custom_ratio2"])
        w, h = (
            (max(1, round(height * a / b)), height) if width / height > a / b else (width, max(1, round(width * b / a)))
        )
    pos = s["start_pos"]
    x = (width - w) // 2 if pos == 0 else width - w if pos in (2, 4) else 0
    y = (height - h) // 2 if pos == 0 else height - h if pos in (3, 4) else 0
    return w, h, x, y


def watermark_xy(w, h, ww, wh, position, edge):
    col, row = position % 3, position // 3
    return ([edge, (w - ww) // 2, w - ww - edge][col], [edge, (h - wh) // 2, h - wh - edge][row])


def dependency_paths(steps):
    paths = []
    for step in steps:
        s = step["settings"]
        if step["type"] == "watermark" and not s["mode"]:
            paths.append(Path(s["image_file"]).resolve(strict=True))
        elif step["type"] == "color" and s["curve_file"]:
            paths.append(Path(s["curve_file"]).resolve(strict=True))
        elif step["type"] == "lut" and s.get("file"):
            paths.append(Path(s["file"]).resolve(strict=True))
        elif step["type"] == "userdef":
            # File arguments supplied to approved procedures are dependencies too.
            for value in s.get("arguments", {}).values():
                if isinstance(value, str) and Path(value).is_file():
                    paths.append(Path(value).resolve(strict=True))
    return paths


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def hierarchy_parts(paths):
    """Compute a common parent per drive; disambiguate different Windows drives."""
    groups = {}
    for path in paths:
        groups.setdefault(path.anchor.casefold(), []).append(path)
    result = {}
    for anchor, group in groups.items():
        common = Path(os.path.commonpath([str(p.parent) for p in group]))
        prefix = Path()
        if len(groups) > 1:
            drive = group[0].drive.replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
            prefix = Path(safe_name(drive or "root"))
        for path in group:
            result[path] = prefix / path.parent.relative_to(common)
    return result


def plan_outputs(inputs, folder, steps, hierarchy=False, timestamp=None, collision="error"):
    paths = [Path(p).resolve(strict=True) for p in inputs]
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError("Wybierz istniejące pliki wejściowe.")
    if len(set(paths)) != len(paths):
        raise ValueError("Lista wejściowa zawiera duplikaty.")
    root = Path(folder).resolve()
    subfolders = hierarchy_parts(paths) if hierarchy else {}
    pattern = next((s["settings"]["pattern"] for s in steps if s["type"] == "rename"), "$$")
    fmt = next((FORMATS[s["settings"]["format"]] for s in steps if s["type"] == "changeformat"), None)
    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M")
    outputs = []
    input_keys = {path_key(p) for p in paths + dependency_paths(steps)}
    output_keys = set()
    for index, path in enumerate(paths, 1):
        substitutions = {"$$": path.stem, "##": str(index), "@@": timestamp}
        name = safe_name(re.sub(r"\$\$|##|@@", lambda m: substitutions[m[0]], pattern))
        suffix = "." + fmt if fmt else path.suffix.lower()
        if not suffix:
            raise ValueError(f"Plik {path.name} nie ma rozszerzenia. Dodaj zmianę formatu.")
        target = root / subfolders.get(path, Path()) / (name + suffix)
        target = target.resolve()
        if not target.is_relative_to(root):
            raise ValueError("Plik wynikowy musi znajdować się w katalogu wyjściowym.")
        key = os.path.normcase(str(target))
        if key in input_keys:
            raise ValueError(f"Plik wynikowy nadpisałby plik wejściowy lub zależność: {target}")
        if collision == "suffix":
            original = target
            number = 2
            while path_key(target) in output_keys or target.exists():
                target = original.with_name(f"{original.stem}_{number}{original.suffix}")
                number += 1
            key = path_key(target)
        if key in output_keys:
            raise ValueError(f"Dwie pozycje mają tę samą nazwę wynikową: {target}")
        output_keys.add(key)
        outputs.append((path, target))
    return outputs


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bimp-json-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_settings(path, steps):
    validate_steps(steps)
    atomic_json(path, {"bimp3": 1, "steps": steps})


def load_settings(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        if data.get("bimp3") != 1:
            raise ValueError("Nieobsługiwana wersja zestawu BIMP 3.")
        return validate_steps(data["steps"])
    return import_legacy(text)


def import_legacy(text):
    """Read BIMP 2 GLib key files; reject positional PDB calls and unmapped options."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_string(text)
    version = re.search(r"#\s*BIMP\s+(\d+)\.(\d+)", text)
    if not version or int(version[1]) < 2:
        raise ValueError("Import obsługuje zestawy BIMP 2.x. Zestawy starsze wymagają odtworzenia ustawień.")
    steps = []
    for group in cfg.sections():
        kind = re.sub(r"\d+$", "", group).lower()
        if kind == "userdef":
            raise ValueError(
                "Zestaw zawiera procedurę GIMP 2. Odtwórz ją przez „Inna procedura GIMP 3”; stare argumenty pozycyjne nie są zgodne z API 3."
            )
        if kind not in SCHEMAS:
            raise ValueError(f"Nieznana sekcja BIMP: {group}")
        step = new_step(kind)
        for key, value in cfg[group].items():
            if key in step["settings"]:
                default = step["settings"][key]
                step["settings"][key] = (
                    cfg.getboolean(group, key)
                    if isinstance(default, bool)
                    else int(float(value))
                    if isinstance(default, int)
                    else float(value)
                    if isinstance(default, float)
                    else re.sub(
                        r"\\([snrt\\])", lambda m: {"s": " ", "n": "\n", "r": "\r", "t": "\t", "\\": "\\"}[m[1]], value
                    )
                )
            elif kind == "changeformat":
                step["settings"]["arguments"][key] = value
            else:
                raise ValueError(f"Nieobsługiwane ustawienie: {group}.{key}")
        if kind == "changeformat":
            step["settings"]["arguments"] = legacy_export_args(
                step["settings"]["format"], step["settings"]["arguments"]
            )
        steps.append(step)
    return validate_steps(steps)


def legacy_export_args(fmt, args):
    """Explicit mappings verified against local GIMP 3.2 PDB; no positional calls."""
    mappings = {
        1: {"interlace": "interlace"},
        3: {
            "quality": "quality",
            "smoothing": "smoothing",
            "entropy": "optimize",
            "progressive": "progressive",
            "baseline": "baseline",
            "subsampling": "sub-sampling",
            "dct": "dct",
        },
        4: {
            "interlace": "interlaced",
            "compression": "compression",
            "savebgc": "bkgd",
            "saveoff": "offs",
            "savephys": "phys",
            "savetime": "time",
            "savecomm": "include-comment",
            "savetrans": "save-transparent",
        },
        5: {"rle": "rle", "origin": "origin"},
        6: {"compression": "compression"},
        7: {"lossless": "lossless", "quality": "quality"},
        8: {
            "preset": "preset",
            "lossless": "lossless",
            "quality": "quality",
            "alpha_quality": "alpha-quality",
            "animation": "animation",
            "anim_loop": "animation-loop",
            "minimize_size": "minimize-size",
            "kf_distance": "keyframe-distance",
            "exif": "include-exif",
            "iptc": "include-iptc",
            "xmp": "include-xmp",
            "delay": "default-delay",
            "force_delay": "force-delay",
        },
        9: {"lossless": "lossless", "quality": "quality"},
    }
    result = {}
    for key, raw in args.items():
        if key == "savegamma" and raw.lower() == "false" or key in ("comment", "markers") and raw in ("", "0"):
            continue
        if key not in mappings.get(fmt, {}):
            raise ValueError(
                f"Ustawienie eksportu {key} nie ma potwierdzonego odpowiednika w GIMP 3. Odtwórz zmianę formatu ręcznie."
            )
        value = raw.lower() == "true" if raw.lower() in ("true", "false") else float(raw) if "." in raw else int(raw)
        if fmt == 3:
            if key == "quality":
                value /= 100
            elif key == "subsampling":
                value = ["sub-sampling-2x2", "sub-sampling-2x1", "sub-sampling-1x1", "sub-sampling-1x2"][value]
            elif key == "dct":
                value = ["integer", "fixed", "float"][value]
        if fmt == 5 and key == "origin":
            value = ["bottom-left", "top-left"][value]
        if fmt == 6 and key == "compression":
            value = ["none", "lzw", "pack-bits", "deflate", "jpeg", "ccitt-g3", "ccitt-g4"][value]
        if fmt == 8 and key == "preset":
            value = ["default", "picture", "photo", "drawing", "icon", "text"][value]
        if key == "force_delay":
            value = bool(value)
        result[mappings[fmt][key]] = value
    return result


def read_curves(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    if not text.startswith("# GIMP"):
        raise ValueError("To nie jest plik krzywych GIMP.")
    result = {}
    for match in re.finditer(r"\(channel\s+(value|red|green|blue|alpha)\)(.*?)(?=\(channel|# end|\Z)", text, re.S):
        points = re.search(r"\(points\s+(\d+)\s+([^)]*)\)", match[2], re.S)
        if not points:
            raise ValueError("Krzywe odręczne bez punktów kontrolnych nie są obsługiwane.")
        numbers = [float(n) for n in points[2].split()]
        if len(numbers) != int(points[1]) or len(numbers) % 2 or any(not math.isfinite(n) for n in numbers):
            raise ValueError("Nieprawidłowa liczba współrzędnych krzywej.")
        valid = [(x, y) for x, y in zip(numbers[::2], numbers[1::2]) if 0 <= x <= 1 and 0 <= y <= 1]
        if len(valid) < 2:
            raise ValueError("Krzywa wymaga co najmniej dwóch punktów.")
        if any(a[0] >= b[0] for a, b in zip(valid, valid[1:])):
            raise ValueError("Współrzędne X krzywej muszą być ściśle rosnące.")
        result[match[1]] = [v for pair in valid for v in pair]
    if not result:
        raise ValueError("Brak kanałów w pliku krzywych.")
    return result
