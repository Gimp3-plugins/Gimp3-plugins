# -*- coding: utf-8 -*-
"""
Zrzuty okna wtyczki bez GIMP-a (obrazek testowy, okno poza ekranem):

    python.exe tests\\ui_snapshot.py <folder wyjściowy> [pl|en]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plug-ins", "zetmar-kolor"))
os.environ["GIMP_WTYCZKI_LANG"] = sys.argv[2] if len(sys.argv) > 2 else "pl"

import zk_core  # noqa: E402

_installed = os.path.join(os.environ.get("APPDATA", ""), "GIMP", "3.2", "plug-ins")
_orig = zk_core._vendor_dirs
zk_core._vendor_dirs = lambda: _orig() + [os.path.join(_installed, "lut-cube", "vendor")]

import zk_ui  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)

look = zk_core.Look()
look.apply_curve_preset("medium-s")
look.curves[zk_core.CH_RGB].insert(2, [0.5, 0.55])
look.apply_toning_preset("teal-orange")
win = zk_ui.ZkWindow(zk_ui.SampleSource(), look, offscreen=True)
win.editor.sel = 2
win._update_preview()
win.snapshot(os.path.join(out, "1_krzywe.png"))

win.notebook.set_current_page(1)
win.look.bw_mode = zk_core.BW_SEPIA
win.look.tint_sat = 60
win._sync_widgets()
win._update_preview()
win.snapshot(os.path.join(out, "2_czb.png"))

win.notebook.set_current_page(2)
win.look = zk_core.Look()
win.look.apply_duotone_preset("navy-orange")
win._sync_widgets()
win._update_preview()
win.snapshot(os.path.join(out, "3_duotone.png"))

win.notebook.set_current_page(3)
win.look = zk_core.Look()
win.look.apply_toning_preset("classic")
win._sync_widgets()
win.mode_combo.set_active_id("after")
win._update_preview()
win.snapshot(os.path.join(out, "4_toning.png"))
win.close()
print("OK", out)
