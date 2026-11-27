#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""BIMP for GIMP 3, rewritten from BIMP by Alessandro Francesconi."""

import json
import sys
from pathlib import Path

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, GLib, GObject

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bimp_model import atomic_json, load_settings, plan_outputs
from bimp_engine import process_one, validate_runtime


def run_batch(procedure, config, _data):
    Gegl.init(None)
    try:
        if config.get_property("run-mode") != Gimp.RunMode.NONINTERACTIVE:
            from bimp_window import BatchWindow

            BatchWindow().run()
        else:
            steps = load_settings(config.get_property("settings-file"))
            validate_runtime(steps)
            inputs = json.loads(config.get_property("input-files"))
            if not isinstance(inputs, list) or any(not isinstance(p, str) for p in inputs):
                raise ValueError("input-files: wymagana tablica JSON ze ścieżkami plików.")
            if not config.get_property("output-directory"):
                raise ValueError("Podaj katalog wyjściowy.")
            collision = config.get_property("collision-policy")
            policy = config.get_property("metadata-policy")
            if collision not in ("skip", "replace", "suffix") or policy not in ("preserve", "strip", "strip-gps"):
                raise ValueError("Nieprawidłowa polityka kolizji lub metadanych.")
            output_color = config.get_property("output-color")
            if output_color not in ("preserve", "srgb"):
                raise ValueError("output-color: wymagane preserve albo srgb.")
            # "overwrite" is kept for older callers; it is equivalent to collision-policy=replace.
            replace = config.get_property("overwrite") or collision == "replace"
            plan = plan_outputs(
                inputs,
                config.get_property("output-directory"),
                steps,
                config.get_property("keep-hierarchy"),
                collision="suffix" if collision == "suffix" else "error",
            )
            options = {
                "metadata": policy,
                "collision": "suffix" if collision == "suffix" else "error",
                "color_profile": config.get_property("embed-color-profile"),
                "output_color": output_color,
                "auto_orient": config.get_property("auto-orient"),
                "reserved_targets": [str(t) for _, t in plan],
            }
            failures, report = [], []
            for source, target in plan:
                try:
                    result = process_one(
                        source,
                        target,
                        steps,
                        replace,
                        config.get_property("keep-dates"),
                        options,
                    )
                    print(json.dumps(result, ensure_ascii=False))
                    report.append(result)
                except Exception as exc:
                    failures.append(f"{source}: {exc}")
                    report.append({"source": str(source), "target": str(target), "status": "error", "error": str(exc)})
            if config.get_property("report-file"):
                atomic_json(config.get_property("report-file"), report)
            if failures:
                raise RuntimeError("\n".join(failures))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    except Exception as exc:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


class Bimp3(Gimp.PlugIn):
    def do_query_procedures(self):
        return ["plug-in-bimp3"]

    def do_set_i18n(self, _name):
        return False, None, None

    def do_create_procedure(self, name):
        if name != "plug-in-bimp3":
            return None
        proc = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_batch, None)
        proc.set_menu_label("BIMP 3 — przetwarzanie wsadowe…")
        proc.add_menu_path("<Image>/File")
        proc.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.NO_IMAGE
            | Gimp.ProcedureSensitivityMask.NO_DRAWABLES
            | Gimp.ProcedureSensitivityMask.DRAWABLE
            | Gimp.ProcedureSensitivityMask.DRAWABLES
        )
        proc.set_documentation(
            "Wsadowa obróbka obrazów w GIMP 3",
            "Skalowanie, kadrowanie, obrót, kolory, filtry, znak wodny, format, nazwy i procedury GIMP 3.",
            name,
        )
        proc.set_attribution("Alessandro Francesconi; GIMP 3 rewrite", "GPL-2.0-or-later", "2026")
        flags = GObject.ParamFlags.READWRITE
        proc.add_enum_argument("run-mode", "Tryb", None, Gimp.RunMode.__gtype__, Gimp.RunMode.INTERACTIVE, flags)
        proc.add_string_argument("settings-file", "Zestaw ustawień", "Plik BIMP 3 JSON albo BIMP 2 .bimp", "", flags)
        proc.add_string_argument("input-files", "Pliki wejściowe", "Tablica JSON bezwzględnych ścieżek", "[]", flags)
        proc.add_string_argument("output-directory", "Katalog wyjściowy", None, "", flags)
        proc.add_boolean_argument(
            "overwrite", "Zastąp istniejące pliki", "To samo co collision-policy=replace (zgodność wsteczna)", False, flags
        )
        proc.add_boolean_argument("keep-hierarchy", "Zachowaj podfoldery", None, False, flags)
        proc.add_boolean_argument("keep-dates", "Zachowaj daty", None, False, flags)
        proc.add_string_argument("collision-policy", "Kolizje", "skip, replace lub suffix", "skip", flags)
        proc.add_string_argument("metadata-policy", "Metadane", "preserve, strip-gps lub strip", "strip-gps", flags)
        # Added after the first release: defaults keep the previous behaviour for old callers
        # (except EXIF orientation, which is now applied like in the window).
        proc.add_string_argument("output-color", "Kolory wyniku", "preserve lub srgb", "preserve", flags)
        proc.add_boolean_argument("embed-color-profile", "Osadź profil ICC", None, True, flags)
        proc.add_boolean_argument("auto-orient", "Obróć według EXIF", None, True, flags)
        proc.add_string_argument("report-file", "Raport JSON", "Opcjonalny plik z wynikiem każdego zdjęcia", "", flags)
        return proc


if __name__ == "__main__":
    Gimp.main(Bimp3.__gtype__, sys.argv)
