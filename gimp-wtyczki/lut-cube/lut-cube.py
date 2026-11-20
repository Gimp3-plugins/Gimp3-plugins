#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LUT-y (.cube) – wtyczka GIMP 3.x (darmowa, GPL-3.0).

Nakłada kolorystyczne tablice LUT (.cube, .3dl, Hald CLUT .png), ma własną
bibliotekę LUT-ów, podgląd przed/po i suwak siły efektu. Działa offline.

Procedury:
  python-fu-lut-cube-apply     – Filtry → LUT → Zastosuj LUT (.cube)…
  python-fu-lut-cube-library   – Filtry → LUT → Zarządzaj biblioteką…
  python-fu-lut-cube-batch     – Filtry → LUT → Wsadowo (folder zdjęć)…
  python-fu-lut-cube-hald-new  – Filtry → LUT → Utwórz obraz Hald (własny look)…
  python-fu-lut-cube-hald-save – Filtry → LUT → Zapisz look jako .cube…

Kod obliczeniowy jest w modułach obok (cube_parser, lut_formats, lut_apply,
library, batch), które działają bez GIMP-a – testy: tests/test_lut_cube.py.
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

import gi  # noqa: E402
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio, GLib, GObject  # noqa: E402

PLUG_IN_BINARY = "lut-cube"
PROC_APPLY = "python-fu-lut-cube-apply"
PROC_LIBRARY = "python-fu-lut-cube-library"
PROC_BATCH = "python-fu-lut-cube-batch"
PROC_HALD_NEW = "python-fu-lut-cube-hald-new"
PROC_HALD_SAVE = "python-fu-lut-cube-hald-save"
MENU_PATH = "<Image>/Filters/LUT"


def _choice(items):
    choice = Gimp.Choice.new()
    for i, (nick, label) in enumerate(items):
        choice.add(nick, i, label, "")
    return choice


def _error(procedure, message):
    # GIMP sam pokazuje komunikat z GLib.Error.
    return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                       GLib.Error(message))


def _success(procedure):
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def _cancel(procedure):
    return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)


# --- wspólne argumenty LUT-a ----------------------------------------------------------

def _add_lut_arguments(p, rw):
    p.add_file_argument("lut-file", "Plik LUT", "LUT do nałożenia (.cube, .3dl, "
                        "Hald .png)", Gimp.FileChooserAction.OPEN, True, None, rw)
    p.add_string_argument("preset", "Preset z biblioteki",
                          "Nazwa presetu (LUT + ustawienia); gdy podany, "
                          "zastępuje plik LUT i ustawienia poniżej", "", rw)
    p.add_double_argument("strength", "Siła (%)", "Siła efektu 0–100 %",
                          0.0, 100.0, 100.0, rw)
    p.add_choice_argument(
        "interpolation", "Interpolacja", "Interpolacja w siatce LUT-a",
        _choice([("tetrahedral", "Tetraedralna"), ("trilinear", "Trójliniowa")]),
        "tetrahedral", rw)
    p.add_double_argument("color", "Kolor (%)", "Ile zmiany koloru (barwy) "
                          "przenieść", 0.0, 100.0, 100.0, rw)
    p.add_double_argument("luminance", "Jasność (%)", "Ile zmiany jasności/"
                          "kontrastu przenieść", 0.0, 100.0, 100.0, rw)
    for name, label in (("shadows", "Cienie (%)"), ("midtones", "Półtony (%)"),
                        ("highlights", "Światła (%)")):
        p.add_double_argument(name, label, "Siła efektu w tym zakresie tonalnym",
                              0.0, 100.0, 100.0, rw)


def _lut_and_params(config):
    """(CubeLUT, Params, etykieta) z argumentów albo z presetu biblioteki."""
    import gimp_ops
    import library
    import lut_apply
    import lut_formats

    values = {k: config.get_property(k) for k in
              ("strength", "color", "luminance", "interpolation", "shadows",
               "midtones", "highlights")}
    preset_name = (config.get_property("preset") or "").strip()
    if preset_name:
        lib = library.Library(gimp_ops.library_root())
        preset = next((v for k, v in lib.presets.items()
                       if k.lower() == preset_name.lower()), None)
        if preset is None:
            raise gimp_ops.PluginError(
                "Nie ma presetu „%s”. Dostępne: %s" % (
                    preset_name, ", ".join(sorted(lib.presets)) or "brak"))
        values.update({k: v for k, v in preset.items() if k in values})
        key = preset.get("lut", "")
        if key.startswith("file:"):
            path = key[5:]
            lut, label = lut_formats.load_lut_file(path), \
                os.path.splitext(os.path.basename(path))[0]
        elif key in lib.entries:
            lut, label = lib.load_lut(key), lib.display_name(key)
        else:
            raise gimp_ops.PluginError("LUT presetu „%s” nie jest już w bibliotece."
                                       % preset_name)
    else:
        gfile = config.get_property("lut-file")
        path = gfile.get_path() if gfile is not None else None
        if not path or not os.path.isfile(path):
            raise gimp_ops.PluginError("Nie podano pliku LUT albo plik nie "
                                       "istnieje: %s" % (path or "(brak)"))
        lut = lut_formats.load_lut_file(path)
        label = os.path.splitext(os.path.basename(path))[0]
    params = lut_apply.Params(values["strength"] / 100.0, values["color"] / 100.0,
                              values["luminance"] / 100.0, values["interpolation"],
                              values["shadows"] / 100.0, values["midtones"] / 100.0,
                              values["highlights"] / 100.0)
    return lut, params, label


# --- Zastosuj LUT ----------------------------------------------------------------------

def _apply_noninteractive(image, drawables, config):
    """Wywołanie ze skryptu / „Powtórz”: wszystko z parametrów procedury."""
    import gimp_ops

    if gimp_ops.needs_rgb_conversion(image):
        raise gimp_ops.PluginError(
            "Obraz jest %s – LUT działa na obrazach RGB. Zmień tryb: "
            "Obraz → Tryb → RGB." % gimp_ops.base_type_name(image))
    lut, params, label = _lut_and_params(config)
    layers = gimp_ops.target_layers(image, drawables)

    Gimp.progress_init("Nakładanie LUT-a %s…" % label)
    image.undo_group_start()
    try:
        for k, layer in enumerate(layers):
            def progress(f, k=k):
                Gimp.progress_update((k + f) / len(layers))
                return True
            gimp_ops.apply_to_layer(
                image, layer, lut, params, config.get_property("output"),
                config.get_property("strength-as-opacity"), label, progress)
    finally:
        image.undo_group_end()
        Gimp.progress_end()


def _run_apply(procedure, run_mode, image, drawables, config, data):
    import cube_parser
    import gimp_ops

    if image is None:
        return _error(procedure, "Brak otwartego obrazu – otwórz zdjęcie "
                                 "i spróbuj ponownie.")
    try:
        if run_mode == Gimp.RunMode.INTERACTIVE:
            import ui
            result = ui.run_apply_dialog(PLUG_IN_BINARY, PLUGIN_DIR, image,
                                         drawables, config)
            if result is None:
                return _cancel(procedure)
        else:
            _apply_noninteractive(image, drawables, config)
    except (gimp_ops.PluginError, cube_parser.CubeError) as e:
        return _error(procedure, str(e))
    except Exception as e:  # noqa – żadnych niezłapanych wyjątków
        return _error(procedure, "Nieoczekiwany błąd wtyczki LUT: %s" % e)
    Gimp.displays_flush()
    return _success(procedure)


# --- Biblioteka ------------------------------------------------------------------------

def _run_library(procedure, config, data):
    if config.get_property("run-mode") != Gimp.RunMode.INTERACTIVE:
        return _error(procedure, "Zarządzanie biblioteką wymaga okna "
                                 "(tryb interaktywny).")
    try:
        import ui
        ui.run_library_dialog(PLUG_IN_BINARY, PLUGIN_DIR)
    except Exception as e:  # noqa
        return _error(procedure, "Nieoczekiwany błąd biblioteki LUT: %s" % e)
    return _success(procedure)


# --- Tryb wsadowy ----------------------------------------------------------------------

def _dialog(procedure, config, title, order):
    gi.require_version("GimpUi", "3.0")
    from gi.repository import GimpUi
    GimpUi.init(PLUG_IN_BINARY)
    dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config, title=title)
    dialog.fill(order)
    ok = dialog.run()
    dialog.destroy()
    return ok


def _folder(config, name):
    gfile = config.get_property(name)
    return gfile.get_path() if gfile is not None else ""


def _run_batch(procedure, config, data):
    import batch
    import cube_parser
    import gimp_ops

    run_mode = config.get_property("run-mode")
    if run_mode == Gimp.RunMode.INTERACTIVE:
        if not _dialog(procedure, config, "LUT wsadowo (folder zdjęć)",
                       ["input-folder", "recursive", "output-folder", "suffix",
                        "format", "quality", "lut-file", "preset", "strength",
                        "interpolation", "color", "luminance", "shadows",
                        "midtones", "highlights", "convert-srgb"]):
            return _cancel(procedure)
    try:
        in_root, out_root = _folder(config, "input-folder"), _folder(config, "output-folder")
        fmt = config.get_property("format")
        suffix = config.get_property("suffix") or ""
        batch.check_settings(in_root, out_root, fmt, suffix)
        lut, params, label = _lut_and_params(config)
        files = batch.list_images(in_root, config.get_property("recursive"),
                                  exclude=out_root)
        if not files:
            raise batch.BatchError("W folderze %s nie ma zdjęć (JPG, PNG, TIFF, "
                                   "WebP)." % in_root)
        Gimp.progress_init("LUT %s: %d zdjęć…" % (label, len(files)))

        def progress(i, n, name):
            Gimp.progress_set_text("LUT %s: %d/%d %s" % (label, min(i + 1, n), n, name))
            Gimp.progress_update(i / float(n))
            return True

        saved, errors = batch.run_batch(
            files, in_root, out_root, fmt, suffix, config.get_property("quality"),
            lut, params, config.get_property("convert-srgb"), progress)
        Gimp.progress_end()
    except (batch.BatchError, gimp_ops.PluginError, cube_parser.CubeError) as e:
        return _error(procedure, str(e))
    except Exception as e:  # noqa
        return _error(procedure, "Nieoczekiwany błąd trybu wsadowego: %s" % e)
    if not saved and errors:
        return _error(procedure, "Żadne zdjęcie nie zostało zapisane. Pierwszy "
                                 "błąd: %s – %s" % (os.path.basename(errors[0][0]),
                                                    errors[0][1]))
    lines = ["LUT %s: zapisano %d z %d zdjęć do:\n%s"
             % (label, len(saved), len(files), out_root)]
    for path, msg in errors[:10]:
        lines.append("  • %s – %s" % (os.path.basename(path), msg))
    if len(errors) > 10:
        lines.append("  • … i %d więcej błędów" % (len(errors) - 10))
    if run_mode == Gimp.RunMode.INTERACTIVE or errors:
        Gimp.message("\n".join(lines))
    return _success(procedure)


# --- Własny look: obraz Hald ------------------------------------------------------------

def _run_hald_new(procedure, config, data):
    import gimp_ops

    run_mode = config.get_property("run-mode")
    if run_mode == Gimp.RunMode.INTERACTIVE:
        if not _dialog(procedure, config, "Utwórz obraz Hald (własny look)",
                       ["level"]):
            return _cancel(procedure)
    level = int(config.get_property("level")[1:])
    image = gimp_ops.new_hald_image(level)
    if run_mode == Gimp.RunMode.INTERACTIVE:
        Gimp.Display.new(image)
        Gimp.displays_flush()
        Gimp.message(
            "To jest obraz Hald CLUT (siatka %d). Popraw na nim kolory tak jak "
            "na zdjęciu: Kolory → Krzywe, Poziomy, Balans kolorów, "
            "Barwa-Nasycenie… (bez kadrowania, skalowania i filtrów "
            "przestrzennych, np. rozmycia).\n\nPotem: Filtry → LUT → Zapisz look "
            "jako .cube…" % (level * level))
    # Wartości zwracane: [status, obraz] – podmieniamy domyślny obraz (None).
    retval = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    retval.remove(1)
    retval.append(GObject.Value(Gimp.Image, image))
    return retval


def _run_hald_save(procedure, run_mode, image, drawables, config, data):
    import gimp_ops
    import library
    import lut_formats

    if image is None:
        return _error(procedure, "Brak otwartego obrazu Hald.")
    if run_mode == Gimp.RunMode.INTERACTIVE:
        if config.get_property("file") is None:
            src = image.get_file()
            base = os.path.splitext(src.get_basename())[0] if src else "Mój look"
            folder = os.path.dirname(src.get_path()) if src and src.get_path() \
                else os.path.expanduser("~")
            config.set_property("file", Gio.File.new_for_path(
                os.path.join(folder, base + ".cube")))
        if not _dialog(procedure, config, "Zapisz look jako .cube",
                       ["file", "title", "add-to-library"]):
            return _cancel(procedure)
    try:
        gfile = config.get_property("file")
        path = gfile.get_path() if gfile is not None else None
        if not path:
            raise gimp_ops.PluginError("Nie wybrano pliku docelowego.")
        if not path.lower().endswith(".cube"):
            path += ".cube"
        title = (config.get_property("title") or "").strip() or \
            os.path.splitext(os.path.basename(path))[0]
        lut = gimp_ops.image_to_lut(image, title)
        lut_formats.write_cube(lut, path, title)
        note = ""
        if config.get_property("add-to-library"):
            res = library.Library(gimp_ops.library_root()).add_files([path])
            note = ("\nDodano do biblioteki LUT-ów." if res.added else
                    "\nTen look już jest w bibliotece." if res.duplicates else
                    "\nNie udało się dodać do biblioteki: %s"
                    % (res.errors[0][1] if res.errors else ""))
    except gimp_ops.PluginError as e:
        return _error(procedure, str(e))
    except (OSError, library.LibraryError) as e:
        return _error(procedure, "Nie udało się zapisać pliku: %s" % e)
    if run_mode == Gimp.RunMode.INTERACTIVE:
        Gimp.message("Zapisano look (siatka %d) do:\n%s%s" % (lut.size_3d, path, note))
    return _success(procedure)


# --- rejestracja ----------------------------------------------------------------------

class LutCube(Gimp.PlugIn):

    def do_query_procedures(self):
        return [PROC_APPLY, PROC_LIBRARY, PROC_BATCH, PROC_HALD_NEW, PROC_HALD_SAVE]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        Gegl.init(None)
        rw = GObject.ParamFlags.READWRITE

        if name == PROC_APPLY:
            p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                        _run_apply, None)
            p.set_menu_label("Zastosuj LUT (.cube)…")
            p.set_documentation(
                "Nakłada kolorystyczny LUT (.cube, .3dl, Hald .png).",
                "Okno z biblioteką LUT-ów, podglądem przed/po i siłą efektu. "
                "Wywołanie bez okna: lut-file albo preset, strength (0–100), "
                "output (new-layer / in-place), interpolation (tetrahedral / "
                "trilinear), color, luminance, shadows, midtones, highlights, "
                "strength-as-opacity.", None)
            p.set_image_types("*")
            p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                                   | Gimp.ProcedureSensitivityMask.DRAWABLES)
            _add_lut_arguments(p, rw)
            p.add_choice_argument(
                "output", "Wynik", "Gdzie zapisać wynik",
                _choice([("new-layer", "Nowa warstwa z efektem"),
                         ("in-place", "Na aktywnej warstwie")]),
                "new-layer", rw)
            p.add_boolean_argument(
                "strength-as-opacity", "Siła jako krycie warstwy",
                "Nowa warstwa ma pełny efekt, a siła trafia do krycia",
                False, rw)

        elif name == PROC_LIBRARY:
            p = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                   _run_library, None)
            p.set_menu_label("Zarządzaj biblioteką…")
            p.set_documentation(
                "Biblioteka LUT-ów: import, nazwy, kategorie, presety.",
                "Dodawanie, porządkowanie i podgląd LUT-ów bez obrazu, eksport "
                "i import biblioteki.", None)
            p.add_enum_argument("run-mode", "Tryb uruchomienia",
                                "Tryb uruchomienia", Gimp.RunMode,
                                Gimp.RunMode.INTERACTIVE, rw)

        elif name == PROC_BATCH:
            p = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                   _run_batch, None)
            p.set_menu_label("Wsadowo (folder zdjęć)…")
            p.set_documentation(
                "Nakłada LUT na wszystkie zdjęcia z folderu.",
                "Zdjęcia (JPG, PNG, TIFF, WebP) z folderu wejściowego są "
                "zapisywane z nałożonym LUT-em do folderu wynikowego. Oryginały "
                "zostają bez zmian.", None)
            p.add_enum_argument("run-mode", "Tryb uruchomienia",
                                "Tryb uruchomienia", Gimp.RunMode,
                                Gimp.RunMode.INTERACTIVE, rw)
            p.add_file_argument("input-folder", "Folder ze zdjęciami",
                                "Skąd brać zdjęcia",
                                Gimp.FileChooserAction.SELECT_FOLDER, True, None, rw)
            p.add_boolean_argument("recursive", "Z podfolderami",
                                   "Przetwarzaj też podfoldery (struktura "
                                   "zostaje zachowana)", False, rw)
            p.add_file_argument("output-folder", "Folder wynikowy",
                                "Dokąd zapisać wyniki",
                                Gimp.FileChooserAction.SELECT_FOLDER, True, None, rw)
            p.add_string_argument("suffix", "Przyrostek nazwy",
                                  "Dopisywany do nazwy pliku (np. -lut)", "-lut", rw)
            p.add_choice_argument(
                "format", "Format", "Format plików wynikowych",
                _choice([("jpg", "JPG"), ("png", "PNG"), ("tif", "TIFF"),
                         ("webp", "WebP"), ("same", "Jak oryginał")]),
                "jpg", rw)
            p.add_int_argument("quality", "Jakość JPG/WebP (%)", "Jakość 1–100",
                               1, 100, 92, rw)
            _add_lut_arguments(p, rw)
            p.add_boolean_argument(
                "convert-srgb", "Konwertuj do sRGB",
                "Zdjęcia w innych profilach (np. Adobe RGB) są konwertowane do "
                "sRGB przed nałożeniem LUT-a", True, rw)

        elif name == PROC_HALD_NEW:
            p = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                   _run_hald_new, None)
            p.set_menu_label("Utwórz obraz Hald (własny look)…")
            p.set_documentation(
                "Tworzy obraz Hald CLUT do zrobienia własnego LUT-a.",
                "Popraw kolory obrazu Hald (krzywe, poziomy, barwa…) i zapisz "
                "go przez „Zapisz look jako .cube…”.", None)
            p.add_enum_argument("run-mode", "Tryb uruchomienia",
                                "Tryb uruchomienia", Gimp.RunMode,
                                Gimp.RunMode.INTERACTIVE, rw)
            p.add_choice_argument(
                "level", "Dokładność", "Rozmiar siatki LUT-a",
                _choice([("l5", "Siatka 25 (125×125 px)"),
                         ("l6", "Siatka 36 (216×216 px)"),
                         ("l8", "Siatka 64 (512×512 px, najdokładniej)")]),
                "l6", rw)
            p.add_image_return_value("image", "Obraz", "Nowy obraz Hald", False, rw)

        elif name == PROC_HALD_SAVE:
            p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                        _run_hald_save, None)
            p.set_menu_label("Zapisz look jako .cube…")
            p.set_documentation(
                "Zapisuje poprawiony obraz Hald jako LUT .cube.",
                "Obraz musi mieć wymiary Hald (z „Utwórz obraz Hald…”). Plik "
                ".cube działa też w Lightroomie, Photoshopie i DaVinci.", None)
            p.set_image_types("RGB*")
            p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                                   | Gimp.ProcedureSensitivityMask.DRAWABLES
                                   | Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
            p.add_file_argument("file", "Plik .cube", "Gdzie zapisać LUT",
                                Gimp.FileChooserAction.SAVE, True, None, rw)
            p.add_string_argument("title", "Nazwa LUT-a (TITLE)",
                                  "Nazwa zapisana w pliku; puste = nazwa pliku",
                                  "", rw)
            p.add_boolean_argument("add-to-library", "Dodaj do biblioteki",
                                   "Od razu dodaj zapisany look do biblioteki "
                                   "LUT-ów", True, rw)
        else:
            return None

        p.add_menu_path(MENU_PATH)
        p.set_attribution("Marek Zettel", "Marek Zettel (GPL-3.0)", "2026")
        return p


if __name__ == "__main__":
    Gimp.main(LutCube.__gtype__, sys.argv)
