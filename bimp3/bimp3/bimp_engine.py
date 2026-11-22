"""GIMP 3 batch engine. SPDX-License-Identifier: GPL-2.0-or-later."""

import math
import os
import re
import tempfile
from pathlib import Path

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio, GObject, Pango

from bimp_model import (
    FORMATS,
    resize_geometry,
    crop_geometry,
    watermark_xy,
    read_curves,
    validate_steps,
    dependency_paths,
    path_key,
)
from bimp_lut import read_cube

EXPORTERS = {
    "bmp": "file-bmp-export",
    "gif": "file-gif-export",
    "ico": "file-ico-export",
    "jpg": "file-jpeg-export",
    "jpeg": "file-jpeg-export",
    "png": "file-png-export",
    "tga": "file-tga-export",
    "tif": "file-tiff-export",
    "tiff": "file-tiff-export",
    "heif": "file-heif-export",
    "heic": "file-heif-export",
    "webp": "file-webp-export",
    "avif": "file-heif-av1-export",
    "exr": "file-exr-export",
    "xcf": "gimp-xcf-save",
}
AUTOMATIC = {"procedure", "run-mode", "image", "drawable", "drawables", "options", "file"}

# Only native image/drawable transforms are accepted. Global procedures and
# arbitrary third-party plug-ins are not executable through imported presets.
SAFE_USER_PROCEDURES = {
    "gimp-image-flip",
    "gimp-image-rotate",
    "gimp-image-scale",
    "gimp-image-crop",
    "gimp-image-convert-rgb",
    "gimp-image-convert-grayscale",
    "gimp-drawable-invert",
    "gimp-drawable-desaturate",
    "gimp-drawable-equalize",
    "gimp-drawable-brightness-contrast",
    "gimp-drawable-hue-saturation",
    "gimp-drawable-color-balance",
    "gimp-drawable-colorize-hsl",
    "gimp-drawable-levels-stretch",
    "gimp-drawable-threshold",
}


def watermark_font(description):
    # GIMP resource names are not Pango descriptions. Pango can reinterpret
    # words such as Bold in a family name, and GTK can invent missing styles.
    resource_name = re.sub(r"\s+\d+(?:\.\d+)?(?:px|pt)?$", "", description.strip(), flags=re.I)
    font = Gimp.Font.get_by_name(resource_name)
    if font is not None:
        return font
    desc = Pango.FontDescription.from_string(description)
    desc.unset_fields(Pango.FontMask.SIZE)
    font = Gimp.Font.get_by_name(desc.to_string())
    if font is not None:
        return font
    normalize = lambda name: re.sub(r"[^\w]+", " ", name.casefold()).strip()
    requested = normalize(resource_name)
    candidates = Gimp.fonts_get_list(None)
    # Prefer exact names, including GIMP's explicit "Regular" suffix.
    for candidate in candidates:
        name = normalize(candidate.get_name())
        if name == requested or name == requested + " regular":
            return candidate
    # Existing GTK presets may request a synthetic italic/oblique style. Use
    # the actual family present in GIMP, without matching unrelated families.
    for suffix in (" italic", " oblique"):
        if requested.endswith(suffix):
            base = requested[: -len(suffix)]
            for candidate in candidates:
                name = normalize(candidate.get_name())
                if name in (base, base + " regular"):
                    return candidate
    raise ValueError(f"Czcionka „{resource_name}” nie jest dostępna w GIMP. Wybierz czcionkę z listy GIMP.")


def require(value, action):
    if value is False or value is None:
        raise RuntimeError(f"GIMP: nie powiodło się: {action}")
    return value


def procedure(name):
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc is None:
        raise ValueError(f"Ta instalacja GIMP nie zawiera procedury: {name}")
    return proc


def run_checked(proc, config):
    result = proc.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS:
        message = result.index(1) if result.length() > 1 else "brak szczegółów"
        raise RuntimeError(f"{proc.get_name()}: {message}")
    return result


def set_argument(config, key, value):
    spec = config.find_property(key)
    if spec is None or key in AUTOMATIC:
        raise ValueError(f"Nieobsługiwany parametr procedury: {key}")
    # Reading the default materializes lazy GI enum bindings. Without this,
    # ParamSpec.value_type.pytype can still be None for native PDB arguments.
    current = config.get_property(key)
    if GObject.type_is_a(spec.value_type, GObject.TYPE_ENUM):
        enum = spec.value_type.pytype or type(current)
        if isinstance(value, str):
            matches = [v for v in enum.__enum_values__.values() if value in (v.value_nick, v.value_name)]
            if not matches:
                raise ValueError(f"Nieznana wartość {key}: {value}")
            value = matches[0]
        else:
            value = enum(value)
    elif spec.value_type.name == "GeglColor":
        value = Gegl.Color.new(value)
    elif spec.value_type.name == "GFile":
        value = Gio.File.new_for_path(str(value))
    elif spec.value_type.name == "GimpFont":
        value = require(Gimp.Font.get_by_name(value), "wybór fontu")
    elif spec.value_type.name == "GimpParamChoice":
        pass
    elif spec.value_type.name == "gboolean":
        if type(value) is not bool:
            raise ValueError(f"{key}: wymagana wartość true/false")
    elif spec.value_type.name in ("gint", "guint", "gint64", "guint64", "gdouble", "gfloat"):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{key}: wymagana liczba")
        if spec.value_type.name not in ("gdouble", "gfloat") and int(value) != value:
            raise ValueError(f"{key}: wymagana liczba całkowita")
        if not spec.minimum <= value <= spec.maximum:
            raise ValueError(f"{key}: zakres {spec.minimum}–{spec.maximum}")
    elif spec.value_type.name == "gchararray":
        if not isinstance(value, str):
            raise ValueError(f"{key}: wymagany tekst")
        if GObject.type_name(spec.__gtype__) == "GimpParamChoice":
            choice = Gimp.param_spec_choice_get_choice(spec)
            if value not in choice.list_nicks():
                raise ValueError(f"{key}: nieznany wybór {value}")
    else:
        raise ValueError(f"Parametr {key} ({spec.value_type.name}) wymaga nieobsługiwanego obiektu.")
    config.set_property(key, value)
    # GObject may clamp invalid properties with a warning instead of raising.
    actual = config.get_property(key)
    if isinstance(value, (str, int, float, bool)) and actual != value:
        raise ValueError(f"GIMP odrzucił wartość parametru {key}: {value}")


def config_for(proc, image=None, file=None, arguments=None):
    config = proc.create_config()
    if config.find_property("run-mode"):
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    if image is not None:
        if config.find_property("image"):
            config.set_property("image", image)
        layers = image.get_selected_layers() or image.get_layers()
        if config.find_property("drawables"):
            config.set_core_object_array("drawables", layers)
        if config.find_property("drawable"):
            config.set_property("drawable", layers[0])
    if file is not None:
        config.set_property("file", Gio.File.new_for_path(str(file)))
    for key, value in (arguments or {}).items():
        set_argument(config, key, value)
    return config


def validate_runtime(steps):
    validate_steps(steps)
    for step in steps:
        kind, s = step["type"], step["settings"]
        if kind == "changeformat":
            config_for(procedure(EXPORTERS[FORMATS[s["format"]]]), arguments=s["arguments"])
        elif kind == "userdef":
            name = s["procedure"]
            if name not in SAFE_USER_PROCEDURES:
                raise ValueError(f"Procedura nie znajduje się na liście dozwolonych operacji obrazowych: {name}")
            proc = procedure(name)
            if any(p.name == "file" for p in proc.get_arguments()):
                raise ValueError("Procedury plikowe wybierz przez operację „Format i kompresja”.")
            config_for(proc, arguments=s["arguments"])
        elif kind == "color" and s["curve_file"]:
            read_curves(s["curve_file"])
        elif kind == "lut":
            read_cube(s["file"])
        elif kind == "watermark":
            if s["mode"]:
                desc = Pango.FontDescription.from_string(s["font"])
                watermark_font(s["font"])
            elif not Path(s["image_file"]).is_file():
                raise ValueError(f"Brak obrazu znaku wodnego: {s['image_file']}")


def leaf_layers(image):
    def walk(layers):
        for layer in layers:
            if layer.is_group():
                yield from walk(layer.get_children())
            else:
                yield layer

    return list(walk(image.get_layers()))


def apply_resize(image, s):
    if s["change_res"]:
        require(image.set_resolution(s["new_res_x"], s["new_res_y"]), "rozdzielczość")
    w, h, cw, ch = resize_geometry(image.get_width(), image.get_height(), s)
    require(Gimp.context_set_interpolation(Gimp.InterpolationType(s["interpolation"])), "interpolacja")
    require(image.scale(w, h), "skalowanie")
    if (cw, ch) != (w, h):
        if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
            require(image.convert_rgb(), "RGB")
        require(image.resize(cw, ch, (cw - w) // 2, (ch - h) // 2), "płótno")
        layer_type = (
            Gimp.ImageType.GRAYA_IMAGE
            if image.get_base_type() == Gimp.ImageBaseType.GRAY
            else Gimp.ImageType.RGBA_IMAGE
        )
        layer = require(
            Gimp.Layer.new(
                image, "BIMP: tło", cw, ch, layer_type, s["padding_color_alpha"] / 65535 * 100, Gimp.LayerMode.NORMAL
            ),
            "warstwa tła",
        )
        require(image.insert_layer(layer, None, len(image.get_layers())), "wstawienie tła")
        require(Gimp.context_set_background(Gegl.Color.new(s["padding_color"])), "kolor tła")
        require(layer.fill(Gimp.FillType.BACKGROUND), "wypełnienie tła")


def apply_color(image, s):
    if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
        require(image.convert_rgb(), "RGB")
    if s["grayscale"] and image.get_base_type() != Gimp.ImageBaseType.GRAY:
        require(image.convert_grayscale(), "skala szarości")
    curves = read_curves(s["curve_file"]) if s["curve_file"] else {}
    for layer in leaf_layers(image):
        if s["brightness"] or s["contrast"]:
            require(layer.brightness_contrast(s["brightness"], s["contrast"]), "jasność i kontrast")
        if s["levels_auto"]:
            require(layer.levels_stretch(), "poziomy automatyczne")
        for channel, points in curves.items():
            if layer.is_gray() and channel in ("red", "green", "blue") or channel == "alpha" and not layer.has_alpha():
                continue
            require(layer.curves_spline(getattr(Gimp.HistogramChannel, channel.upper()), points), "krzywe")


def apply_sharpblur(image, s):
    if s["amount"] == 0:
        return
    amount = s["amount"]
    if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
        require(image.convert_rgb(), "RGB")
    for layer in leaf_layers(image):
        op = "gegl:gaussian-blur" if amount > 0 else "gegl:unsharp-mask"
        effect = require(Gimp.DrawableFilter.new(layer, op, "BIMP"), op)
        config = effect.get_config()
        # GEGL Gaussian uses standard deviation, rather than GIMP 2's blur radius.
        values = (
            {"std-dev-x": amount / 10, "std-dev-y": amount / 10}
            if amount > 0
            else {"std-dev": 3.0, "scale": abs(amount) / 50, "threshold": 0.0}
        )
        for key, value in values.items():
            set_argument(config, key, value)
        effect.update()
        layer.merge_filter(effect)


def apply_watermark(image, s):
    if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
        require(image.convert_rgb(), "RGB")
    if s["mode"]:
        if not s["text"]:
            return
        desc = Pango.FontDescription.from_string(s["font"])
        font = watermark_font(s["font"])
        size = desc.get_size() / Pango.SCALE or 16
        unit = Gimp.Unit.pixel() if desc.get_size_is_absolute() else Gimp.Unit.point()
        layer = require(Gimp.TextLayer.new(image, s["text"], font, size, unit), "tekst znaku wodnego")
        require(image.insert_layer(layer, None, 0), "wstawienie tekstu")
        require(layer.set_color(Gegl.Color.new(s["color"])), "kolor tekstu")
    else:
        layer = require(
            Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(s["image_file"])),
            "wczytanie znaku wodnego",
        )
        require(image.insert_layer(layer, None, 0), "wstawienie znaku wodnego")
        if s["image_sizemode"]:
            factor = (
                (
                    image.get_width() / layer.get_width()
                    if s["image_sizemode"] == 1
                    else image.get_height() / layer.get_height()
                )
                * s["image_size_percent"]
                / 100
            )
            require(
                layer.scale(
                    max(1, round(layer.get_width() * factor)), max(1, round(layer.get_height() * factor)), True
                ),
                "skalowanie znaku wodnego",
            )
    require(layer.set_opacity(s["opacity"]), "krycie znaku wodnego")
    x, y = watermark_xy(
        image.get_width(), image.get_height(), layer.get_width(), layer.get_height(), s["position"], s["edge_distance"]
    )
    require(layer.set_offsets(x, y), "pozycja znaku wodnego")


class Cancelled(Exception):
    pass


def apply_lut(image, settings, checkpoint=lambda: None):
    if settings["strength"] == 0:
        return
    cube = read_cube(settings["file"])
    if image.get_base_type() != Gimp.ImageBaseType.RGB:
        require(image.convert_rgb(), "RGB dla LUT")
    require(
        image.convert_color_profile(
            Gimp.ColorProfile.new_rgb_srgb(), Gimp.ColorRenderingIntent.RELATIVE_COLORIMETRIC, True
        ),
        "sRGB dla LUT",
    )
    for layer in leaf_layers(image):
        width, height = layer.get_width(), layer.get_height()
        source, shadow = layer.get_buffer(), layer.get_shadow_buffer()
        try:
            rows = max(1, min(64, 131072 // max(width, 1)))
            for y in range(0, height, rows):
                checkpoint()
                rect = Gegl.Rectangle.new(0, y, width, min(rows, height - y))
                raw = source.get(rect, 1.0, "R'G'B'A float", Gegl.AbyssPolicy.NONE)
                shadow.set(rect, "R'G'B'A float", cube.transform(bytes(raw), settings["strength"]))
            shadow.flush()
        finally:
            source = shadow = None
        require(layer.merge_shadow(True), "zapis LUT")
        require(layer.update(0, 0, width, height), "odświeżenie LUT")


def apply_step(image, step, checkpoint=lambda: None):
    kind, s = step["type"], step["settings"]
    if kind == "resize":
        apply_resize(image, s)
    elif kind == "crop":
        require(image.crop(*crop_geometry(image.get_width(), image.get_height(), s)), "kadrowanie")
    elif kind == "fliprotate":
        if s["flip_h"]:
            require(image.flip(Gimp.OrientationType.HORIZONTAL), "odbicie poziome")
        if s["flip_v"]:
            require(image.flip(Gimp.OrientationType.VERTICAL), "odbicie pionowe")
        if s["rotate"]:
            require(image.rotate(Gimp.RotationType(s["rotation_type"])), "obrót")
    elif kind == "color":
        apply_color(image, s)
    elif kind == "sharpblur":
        apply_sharpblur(image, s)
    elif kind == "watermark":
        apply_watermark(image, s)
    elif kind == "lut":
        apply_lut(image, s, checkpoint)
    elif kind == "userdef":
        if s["procedure"] not in SAFE_USER_PROCEDURES:
            raise ValueError("Niedozwolona procedura użytkownika.")
        proc = procedure(s["procedure"])
        run_checked(proc, config_for(proc, image=image, arguments=s["arguments"]))


def prepare_metadata(image, policy):
    if policy == "strip":
        # The local GI typelib rejects None despite the C API's nullable contract.
        require(image.set_metadata(Gimp.Metadata.new()), "usunięcie metadanych")
    elif policy == "strip-gps":
        metadata = image.get_metadata()
        if metadata:
            metadata.try_delete_gps_info()
            for tag in (
                list(metadata.get_exif_tags() or [])
                + list(metadata.get_xmp_tags() or [])
                + list(metadata.get_iptc_tags() or [])
            ):
                if any(
                    key in tag.casefold()
                    for key in ("gps", "latitude", "longitude", "geolocation", "locationcreated", "locationshown")
                ):
                    metadata.try_clear_tag(tag)
            require(image.set_metadata(metadata), "usunięcie GPS")
    elif policy != "preserve":
        raise ValueError("Nieznana polityka metadanych.")


def export_image(image, target, arguments, options=None):
    if options and options.get("output_color") == "srgb":
        if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
            require(image.convert_rgb(), "RGB eksportu")
        if image.get_base_type() == Gimp.ImageBaseType.RGB:
            require(
                image.convert_color_profile(
                    Gimp.ColorProfile.new_rgb_srgb(), Gimp.ColorRenderingIntent.RELATIVE_COLORIMETRIC, True
                ),
                "sRGB eksportu",
            )
    ext = target.suffix.lower().lstrip(".")
    if ext in EXPORTERS:
        proc = procedure(EXPORTERS[ext])
        arguments = dict(arguments)
        if options is not None:
            policy = options.get("metadata", "strip-gps")
            prepare_metadata(image, policy)
            config = proc.create_config()
            for flag in ("include-exif", "include-iptc", "include-xmp", "include-comment"):
                if config.find_property(flag):
                    arguments[flag] = policy != "strip"
            if config.find_property("include-color-profile"):
                arguments["include-color-profile"] = options.get("color_profile", True)
        # GIMP 3.2.6's TIFF loader may import the embedded thumbnail as a page.
        # Batch output should round-trip at its original canvas dimensions.
        if ext in ("tif", "tiff"):
            arguments.setdefault("include-thumbnail", False)
        if ext == "gif" and image.get_base_type() != Gimp.ImageBaseType.INDEXED:
            require(
                image.convert_indexed(
                    Gimp.ConvertDitherType.FS, Gimp.ConvertPaletteType.GENERATE, 256, False, False, ""
                ),
                "paleta GIF",
            )
        run_checked(proc, config_for(proc, image=image, file=target, arguments=arguments))
    elif arguments:
        raise ValueError(f"Brak skonfigurowanego eksportera dla {ext}")
    else:
        if options:
            prepare_metadata(image, options.get("metadata", "strip-gps"))
        require(
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(str(target)), None),
            "eksport " + ext,
        )


def process_one(source, target, steps, overwrite=False, keep_dates=False, options=None, checkpoint=lambda: None):
    """Export to a sibling temporary file, then publish only a successful result."""
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError("Plik wynikowy nie może nadpisywać źródła.")
    if path_key(target) in {path_key(p) for p in dependency_paths(steps)}:
        raise ValueError("Plik wynikowy nie może nadpisywać zależności zadania.")
    automatic_suffix = options is not None and options.get("collision") == "suffix"
    reserved = set((options or {}).get("reserved_targets", []))

    def next_target(original):
        counter = 2
        while True:
            candidate = original.with_name(f"{original.stem}_{counter}{original.suffix}")
            if not candidate.exists() and path_key(candidate) not in reserved:
                return candidate
            counter += 1

    if target.exists() and not overwrite and automatic_suffix:
        target = next_target(target)
    if target.exists() and not overwrite:
        return {"source": str(source), "target": str(target), "status": "skipped"}
    target.parent.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    image, temporary = None, None
    require(Gimp.context_push(), "kontekst")
    try:
        image = require(
            Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source))), "otwarcie obrazu"
        )
        image.undo_disable()
        for step in steps:
            checkpoint()
            apply_step(image, step, checkpoint)
        arguments = next((s["settings"]["arguments"] for s in steps if s["type"] == "changeformat"), {})
        fd, name = tempfile.mkstemp(prefix=".bimp-", suffix=target.suffix, dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        checkpoint()
        if options is None:
            export_image(image, temporary, arguments)
        else:
            export_image(image, temporary, arguments, options)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("Eksporter nie zapisał pliku.")
        if keep_dates:
            os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        checkpoint()
        if overwrite:
            os.replace(temporary, target)
        else:
            original_target = target
            while True:
                try:
                    if os.name == "nt":
                        os.rename(temporary, target)
                    else:
                        os.link(temporary, target)
                    break
                except FileExistsError:
                    if automatic_suffix:
                        target = next_target(original_target)
                    else:
                        return {"source": str(source), "target": str(target), "status": "skipped"}
        return {"source": str(source), "target": str(target), "status": "success"}
    finally:
        # Cleanup failures must never mask an export error or skip context_pop.
        for action in (
            lambda: image.delete() if image is not None else None,
            lambda: temporary.unlink(missing_ok=True) if temporary is not None else None,
        ):
            try:
                action()
            except Exception as exc:
                import warnings

                try:
                    warnings.warn(f"BIMP: problem ze sprzątaniem: {exc}", RuntimeWarning)
                except Exception:
                    # Warning filters must not turn a cleanup warning into an
                    # exception which skips restoring the GIMP context.
                    pass
        Gimp.context_pop()


def render_preview(source, steps, before, after, checkpoint=lambda: None, max_edge=1000):
    """Full-resolution operations followed by display-size PNGs; source untouched."""
    validate_runtime(steps)
    Gimp.context_push()
    image = None
    try:
        image = require(Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source))), "podgląd")
        image.undo_disable()

        def thumbnail(destination):
            checkpoint()
            image.get_thumbnail(max_edge, max_edge, Gimp.PixbufTransparency.SMALL_CHECKS).savev(
                str(destination), "png", [], []
            )

        thumbnail(before)
        for step in steps:
            checkpoint()
            apply_step(image, step, checkpoint)
        thumbnail(after)
        return {"width": image.get_width(), "height": image.get_height()}
    finally:
        try:
            if image is not None:
                image.delete()
        finally:
            Gimp.context_pop()
