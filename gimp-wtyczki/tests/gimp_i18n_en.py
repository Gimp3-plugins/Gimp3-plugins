# -*- coding: utf-8 -*-
"""
Test angielskiej wersji wtyczek w GIMP-ie. Uruchom z folderu gimp-wtyczki,
z wymuszonym językiem (dotyczy też procesów wtyczek, które GIMP uruchamia):

  set GIMP_WTYCZKI_LANG=en
  gimp-console-3.2.exe -i --batch-interpreter python-fu-eval ^
      -b "exec(open(r'tests/gimp_i18n_en.py', encoding='utf-8').read())" --quit

UWAGA: GIMP zapamiętuje etykiety menu wtyczek w pamięci podręcznej (pluginrc)
do zmiany pliku wtyczki. Aby test zobaczył angielskie etykiety, plik .py
wtyczki musi być świeższy niż wpis w pamięci podręcznej (np. po install.ps1
albo „touch”); po teście zainstaluj wtyczki ponownie i uruchom GIMP-a w swoim
języku, żeby menu wróciło do polskiego.
"""
import os
import re
import sys

os.environ["GIMP_WTYCZKI_LANG"] = "en"
sys.path.insert(0, os.path.join(os.environ.get("LUT_CUBE_REPO") or os.getcwd(), "tests"))

import gi  # noqa: E402
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, Gtk  # noqa: E402

import gimp_lut_helpers as helpers  # noqa: E402
import gimp_ops  # noqa: E402
import ui  # noqa: E402
import lut_i18n  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print("%s  %s %s" % ("PASS" if cond else "FAIL", name, info), flush=True)


check("język wtyczki = en", lut_i18n.language() == "en")

# 1. Etykiety menu zarejestrowane przez procesy wtyczek (wymusza en przez środowisko)
pdb = Gimp.get_pdb()
expected = {
    "python-fu-lut-cube-apply": "Apply LUT (.cube)…",
    "python-fu-lut-cube-library": "Manage library…",
    "python-fu-lut-cube-batch": "Batch (photo folder)…",
    "python-fu-lut-cube-hald-new": "Create Hald image (your own look)…",
    "python-fu-lut-cube-hald-save": "Save look as .cube…",
    "python-fu-podpis-tekst": "Text signature…",
    "python-fu-podpis-obraz": "Signature from image…",
    "python-fu-meme-maker": "Create meme…",
    "python-fu-meme-export": "Export meme…",
}
for name, label in expected.items():
    proc = pdb.lookup_procedure(name)
    got = proc.get_menu_label() if proc else None
    check("menu EN: %s" % name, got == label, repr(got))
paths = {n: [str(p) for p in (pdb.lookup_procedure(n).get_menu_paths() or [])]
         for n in ("python-fu-lut-cube-apply", "python-fu-podpis-tekst", "python-fu-meme-maker")}
check("ścieżki menu EN (Filters/LUT, Signature, Memes)",
      any(p.endswith("/LUT") for p in paths["python-fu-lut-cube-apply"])
      and any(p.endswith("/Signature") for p in paths["python-fu-podpis-tekst"])
      and any(p.endswith("/Memes") for p in paths["python-fu-meme-maker"]), paths)


# 2. Komunikaty błędów z procesów wtyczek po angielsku
def run(proc_name, img, drawables, **props):
    proc = pdb.lookup_procedure(proc_name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", drawables)
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    return res.index(0), (res.index(1) if res.length() > 1 else "")


img = Gimp.Image.new(40, 30, Gimp.ImageBaseType.GRAY)
layer = Gimp.Layer.new(img, "g", 40, 30, Gimp.ImageType.GRAY_IMAGE, 100, Gimp.LayerMode.NORMAL)
img.insert_layer(layer, None, 0)
from gi.repository import Gio  # noqa: E402
status, err = run("python-fu-lut-cube-apply", img, [layer],
                  **{"lut-file": Gio.File.new_for_path(helpers.cube_files()[0])})
check("błąd LUT po angielsku",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "LUTs work on RGB images" in err
      and not POLISH.search(err), err)
status, err = run("python-fu-podpis-tekst", img, [layer], text="  ")
check("błąd Podpisu po angielsku (pusty tekst)",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "signature text is empty" in err
      and not POLISH.search(err), err)
status, err = run("python-fu-meme-maker", img, [layer])
check("błąd Kreatora memów po angielsku (puste pola)",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "Both text fields are empty" in err
      and not POLISH.search(err), err)
img.delete()


# 3. Okno LUT: żaden widżet nie pokazuje polskiego tekstu
def texts(widget, out):
    for getter in ("get_label", "get_text", "get_tooltip_text", "get_title"):
        fn = getattr(widget, getter, None)
        if fn:
            try:
                v = fn()
            except TypeError:
                continue
            if isinstance(v, str) and v:
                out.append((type(widget).__name__, getter, v))
    if isinstance(widget, Gtk.ComboBoxText):
        model = widget.get_model()
        for row in model:
            out.append(("ComboBoxText", "row", row[0]))
    if isinstance(widget, Gtk.ListStore) or isinstance(widget, Gtk.TreeView):
        pass
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            texts(child, out)


GimpUi.init("lut-cube")
lib_root = os.path.join(helpers.TMP, "biblioteka-en")
import shutil  # noqa: E402
shutil.rmtree(lib_root, ignore_errors=True)
gimp_ops.library_root = lambda: lib_root
ui._ask = lambda parent, text, secondary, buttons, kind=None: texts_seen.append(
    (text, secondary, [b[0] for b in buttons])) or 0
ui._message = lambda parent, text, secondary="", kind=None: texts_seen.append(
    (text, secondary, []))
texts_seen = []
plugin_dir = os.path.join(helpers.TMP, "wtyczka-en")
os.makedirs(plugin_dir, exist_ok=True)
with open(os.path.join(plugin_dir, "startup-dir.txt"), "w", encoding="utf-8") as f:
    f.write(helpers.luts_dir())
win = ui.LutWindow(plugin_dir, offscreen=True)
for _ in range(200):                    # krótkie ożywienie pętli zdarzeń
    while Gtk.events_pending():
        Gtk.main_iteration()
found = []
texts(win.offscreen_window, found)
bad = [t for t in found if POLISH.search(t[2])]
check("okno LUT: brak polskich liter w widżetach (%d tekstów)" % len(found), not bad, bad[:5])
check("okno LUT: angielskie etykiety (Presets, Strength, Categories…)",
      any(t[2].startswith("Presets") for t in found)
      and any(t[2] == "Strength" for t in found), [t[2] for t in found][:6])
bad_dialogs = [d for d in texts_seen if POLISH.search(" ".join([d[0], d[1]] + d[2]))]
check("okna dialogowe (import startowy) po angielsku", texts_seen and not bad_dialogs,
      bad_dialogs[:2] or texts_seen[:1])
# menu „Więcej” i lista presetów
menu_texts = []
texts(win._build_menu(for_item=False), menu_texts)
labels = [m[2] for m in menu_texts if m[1] == "get_label"]
check("menu „More”: angielskie pozycje", "Rename…" in labels and "Settings…" in labels
      and not [x for x in labels if POLISH.search(x)], labels)
win.close()

# 4. Okno z obrazem: przyciski wyniku, pasek statusu, tryby podglądu, preset
photo = Gimp.Image.new(120, 80, Gimp.ImageBaseType.RGB)
pl = Gimp.Layer.new(photo, "p", 120, 80, Gimp.ImageType.RGB_IMAGE, 100, Gimp.LayerMode.NORMAL)
photo.insert_layer(pl, None, 0)
win = ui.LutWindow(plugin_dir, photo, [pl], None, offscreen=True)
for _ in range(300):
    while Gtk.events_pending():
        Gtk.main_iteration()
win._update_preview()
found = []
texts(win.offscreen_window, found)
bad = [t for t in found if POLISH.search(t[2])]
labels = [t[2] for t in found]
check("okno z obrazem: brak polskich liter (%d tekstów)" % len(found), not bad, bad[:5])
check("okno z obrazem: „New layer with the effect”, „Result”, „Interpolation”",
      "New layer with the effect" in labels and "Result" in labels
      and "Interpolation" in labels, labels[-8:])
check("pasek statusu po angielsku", "preview" in win.status.get_text()
      and not POLISH.search(win.status.get_text()), win.status.get_text())
modes = [row[0] for row in win.mode_combo.get_model()]
check("tryby podglądu po angielsku", "Before/after slider" in modes and "Side by side" in modes
      and not [m for m in modes if POLISH.search(m)], modes)
win.close()
photo.delete()
print("WYNIK: %d/%d PASS" % (sum(results), len(results)), flush=True)
