#!/usr/bin/env python3
"""Zetmar Maski 1.0.0 — GIMP 3. SPDX-License-Identifier: MIT."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, GObject, GLib
from zm_core import Settings

PROC = 'python-fu-zetmar-maski'


def run(procedure, run_mode, image, drawables, config, data):
    try:
        from zm_gimp import target, apply
        layer = target(image, drawables)
        if run_mode == Gimp.RunMode.INTERACTIVE:
            from zm_ui import dialog
            if not dialog(image, layer, config):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
        settings = Settings(**{key: config.get_property(key.replace('_', '-')) for key in Settings.__dataclass_fields__})
        apply(image, layer, settings, config.get_property('output'), config.get_property('name') or 'Zetmar Maski')
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    except Exception as exc:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


class ZetmarMaski(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        Gegl.init(None)
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_menu_label('Maski jasności i koloru…')
        p.add_menu_path('<Image>/Filters/Zetmar')
        p.set_image_types('RGB*')
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_documentation('Twórz maski jasności i koloru z podglądem.',
                            'Maska warstwy, kanał lub zaznaczenie. Obliczenia float, bez zmiany pikseli źródła.', None)
        p.set_attribution('Marek Zettel', 'Marek Zettel', '2026')
        rw = GObject.ParamFlags.READWRITE
        labels = {'low': 'Początek zakresu', 'high': 'Koniec zakresu', 'feather': 'Łagodność przejścia',
                  'red': 'Czerwony', 'green': 'Zielony', 'blue': 'Niebieski', 'tolerance': 'Tolerancja koloru',
                  'color_softness': 'Łagodność koloru', 'invert': 'Odwróć maskę',
                  'color_enabled': 'Ogranicz do koloru', 'selection': 'Ogranicz do zaznaczenia'}
        for key, default in Settings().__dict__.items():
            nick = key.replace('_', '-')
            if type(default) is bool:
                p.add_boolean_argument(nick, labels[key], labels[key], default, rw)
            else:
                p.add_double_argument(nick, labels[key], labels[key], 0., 1., default, rw)
        choice = Gimp.Choice.new()
        for i, (nick, label) in enumerate([('new-layer', 'Nowa warstwa z maską'), ('layer-mask', 'Maska aktywnej warstwy'),
                                         ('channel', 'Kanał'), ('selection', 'Zaznaczenie')]):
            choice.add(nick, i, label, '')
        p.add_choice_argument('output', 'Wynik', 'Sposób zapisania maski', choice, 'new-layer', rw)
        p.add_string_argument('name', 'Nazwa', 'Nazwa warstwy lub kanału', 'Zetmar Maski', rw)
        return p


if __name__ == '__main__':
    Gimp.main(ZetmarMaski.__gtype__, sys.argv)
