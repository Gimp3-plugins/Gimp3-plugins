#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zetmar Kolor – wtyczka GIMP 3.x: krzywe, czerń-biel, sepia, monochromia,
duotone i toning w jednym oknie z podglądem przed/po. Bez LUT-ów (do nich
służy osobna wtyczka lut-cube).

Procedura:
  python-fu-zetmar-kolor – Filtry → Zetmar → Kolor (krzywe, Cz-B, duotone, toning)…

Wywołanie bez okna (skrypt, „Filtry → Powtórz”): look (tekst .zklook) albo
look-file (plik .zklook), output (new-layer / in-place).
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

import gi  # noqa: E402
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, GLib, GObject  # noqa: E402
from zk_i18n import tr  # noqa: E402

PLUG_IN_BINARY = "zetmar-kolor"
PROC = "python-fu-zetmar-kolor"
MENU_PATH = "<Image>/Filters/Zetmar"


def _choice(items):
    choice = Gimp.Choice.new()
    for i, (nick, label) in enumerate(items):
        choice.add(nick, i, label, "")
    return choice


def _error(procedure, message):
    return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(message))


def _look_from_config(config):
    """Look z argumentów: plik .zklook ma pierwszeństwo przed tekstem."""
    import zk_core
    gfile = config.get_property("look-file")
    path = gfile.get_path() if gfile is not None else None
    if path:
        return zk_core.load_look_file(path)
    text = (config.get_property("look") or "").strip()
    return zk_core.look_from_text(text) if text else zk_core.Look()


def _run(procedure, run_mode, image, drawables, config, data):
    import zk_core
    import zk_gimp

    if image is None:
        return _error(procedure, tr("Brak otwartego obrazu – otwórz zdjęcie i spróbuj ponownie."))
    try:
        if run_mode == Gimp.RunMode.INTERACTIVE:
            import zk_ui
            if not zk_ui.run_dialog(PLUG_IN_BINARY, image, drawables, config):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
        else:
            if zk_gimp.needs_rgb_conversion(image):
                raise zk_gimp.PluginError(
                    tr("Obraz jest %s – wtyczka działa na obrazach RGB. Zmień tryb: "
                       "Obraz → Tryb → RGB.") % zk_gimp.base_type_name(image))
            look = _look_from_config(config)
            layers = zk_gimp.target_layers(image, drawables)
            Gimp.progress_init(tr("Zetmar Kolor…"))
            try:
                zk_gimp.apply_look(image, layers, look, config.get_property("output"),
                                   lambda f: Gimp.progress_update(f) or True)
            finally:
                Gimp.progress_end()
    except (zk_gimp.PluginError, zk_core.LookError) as e:
        return _error(procedure, str(e))
    except Exception as e:  # noqa – żadnych niezłapanych wyjątków
        return _error(procedure, tr("Nieoczekiwany błąd wtyczki Zetmar Kolor: %s") % e)
    Gimp.displays_flush()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class ZetmarKolor(Gimp.PlugIn):

    def do_query_procedures(self):
        return [PROC]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        if name != PROC:
            return None
        Gegl.init(None)
        rw = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, _run, None)
        p.set_menu_label(tr("Kolor (krzywe, Cz-B, duotone, toning)…"))
        p.set_documentation(
            tr("Krzywe, czerń-biel, sepia, monochromia, duotone i toning z podglądem."),
            tr("Okno z zakładkami Krzywe, Cz-B, Duotone i Toning, podglądem przed/po "
               "i zapisem looku (.zklook, zgodny z wersją dla Photoshopa). Wywołanie "
               "bez okna: look (tekst .zklook) albo look-file, output (new-layer / "
               "in-place)."), None)
        p.set_image_types("*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                               | Gimp.ProcedureSensitivityMask.DRAWABLES)
        p.add_string_argument("look", tr("Look (tekst .zklook)"),
                              tr("Ustawienia w formacie .zklook; puste = bez zmian"), "", rw)
        p.add_file_argument("look-file", tr("Plik looku (.zklook)"),
                            tr("Gdy podany, zastępuje argument look"),
                            Gimp.FileChooserAction.OPEN, True, None, rw)
        p.add_choice_argument(
            "output", tr("Wynik"), tr("Gdzie zapisać wynik"),
            _choice([("new-layer", tr("Nowa warstwa z efektem")),
                     ("in-place", tr("Na aktywnej warstwie"))]),
            "new-layer", rw)
        p.add_menu_path(MENU_PATH)
        p.set_attribution("Marek Zettel", "Marek Zettel (GPL-3.0)", "2026")
        return p


if __name__ == "__main__":
    Gimp.main(ZetmarKolor.__gtype__, sys.argv)
