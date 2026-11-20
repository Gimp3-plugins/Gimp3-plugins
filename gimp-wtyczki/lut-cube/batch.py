# -*- coding: utf-8 -*-
"""
Tryb wsadowy: ten sam LUT na wszystkich zdjęciach z folderu, zapis do
drugiego folderu. Część bez GIMP-a (lista plików, ścieżki) jest na górze
i ma testy; nakładanie i zapis używają GIMP-a (run_batch).
"""

import os
from lut_i18n import tr  # noqa: E402

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
FORMATS = {"jpg": ".jpg", "png": ".png", "tif": ".tif", "webp": ".webp"}


class BatchError(Exception):
    """Błąd ustawień trybu wsadowego (po polsku)."""


def list_images(folder, recursive=False, exclude=None):
    """Zdjęcia w folderze (posortowane); exclude – folder pomijany (wyjście)."""
    exclude = os.path.normcase(os.path.abspath(exclude)) if exclude else None
    found = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(
                d for d in dirnames
                if os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) != exclude)
            for name in sorted(filenames):
                if name.lower().endswith(IMAGE_EXTENSIONS):
                    found.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(IMAGE_EXTENSIONS):
                found.append(path)
    return found


def output_path(src, in_root, out_root, fmt, suffix):
    """
    Ścieżka wyniku: ta sama struktura podfolderów co na wejściu, nazwa
    z przyrostkiem, rozszerzenie wg formatu ("same" = jak oryginał).
    """
    rel = os.path.relpath(src, in_root)
    stem, ext = os.path.splitext(rel)
    ext = ext.lower() if fmt == "same" else FORMATS[fmt]
    if ext == ".jpeg":
        ext = ".jpg"
    if ext == ".tiff":
        ext = ".tif"
    return os.path.join(out_root, stem + suffix + ext)


def check_settings(in_root, out_root, fmt, suffix):
    """Rzuca BatchError, gdy ustawienia groziłyby nadpisaniem oryginałów."""
    if not in_root or not os.path.isdir(in_root):
        raise BatchError(tr("Wybierz istniejący folder ze zdjęciami."))
    if not out_root:
        raise BatchError(tr("Wybierz folder, do którego trafią wyniki."))
    same = os.path.normcase(os.path.abspath(in_root)) == \
        os.path.normcase(os.path.abspath(out_root))
    if same and not suffix and fmt == "same":
        raise BatchError(tr("Folder wynikowy jest taki sam jak folder zdjęć, a nie "
                         "ma przyrostka nazwy – oryginały zostałyby nadpisane. "
                         "Wybierz inny folder albo podaj przyrostek (np. -lut)."))


# --- część GIMP-owa ------------------------------------------------------------------

def _export(image, path, fmt_ext, quality):
    import gi
    gi.require_version("Gimp", "3.0")
    from gi.repository import Gimp, Gio
    gfile = Gio.File.new_for_path(path)
    proc_name = {".jpg": "file-jpeg-export", ".png": "file-png-export",
                 ".tif": "file-tiff-export", ".webp": "file-webp-export"}.get(fmt_ext)
    if proc_name is None:
        if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, gfile, None):
            raise BatchError(tr("nie udało się zapisać"))
        return
    if fmt_ext == ".jpg":
        image.flatten()                    # JPG nie ma przezroczystości
    proc = Gimp.get_pdb().lookup_procedure(proc_name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", image)
    cfg.set_property("file", gfile)
    if fmt_ext == ".jpg":
        cfg.set_property("quality", quality / 100.0)
    elif fmt_ext == ".webp":
        cfg.set_property("quality", float(quality))
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        raise BatchError(tr("eksport się nie powiódł"))


def run_batch(files, in_root, out_root, fmt, suffix, quality, lut, params,
              convert_srgb=True, progress=None):
    """
    Przetwarza listę plików. progress(i, n, nazwa) -> False przerywa.
    Zwraca (zapisane, błędy[(plik, komunikat)]).
    """
    import gi
    gi.require_version("Gimp", "3.0")
    from gi.repository import Gimp, Gio
    import gimp_ops

    saved, errors = [], []
    for i, src in enumerate(files):
        if progress is not None and progress(i, len(files), os.path.basename(src)) is False:
            break
        dest = output_path(src, in_root, out_root, fmt, suffix)
        image = None
        try:
            image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
            if image is None:
                raise BatchError(tr("nie udało się wczytać"))
            image.undo_disable()           # kopia robocza – cofanie zbędne
            if gimp_ops.needs_rgb_conversion(image):
                image.convert_rgb()
            if convert_srgb and not gimp_ops.profile_info(image)[0]:
                gimp_ops.convert_to_srgb(image)
            layer = image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            gimp_ops.apply_to_layer(image, layer, lut, params, "in-place")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            _export(image, dest, os.path.splitext(dest)[1].lower(), quality)
            saved.append(dest)
        except Exception as e:  # noqa – błąd jednego pliku nie przerywa całości
            msg = getattr(e, "message", None) or str(e) or type(e).__name__
            errors.append((src, msg))
        finally:
            if image is not None:
                image.delete()
    if progress is not None:
        progress(len(files), len(files), "")
    return saved, errors
