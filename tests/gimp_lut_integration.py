# -*- coding: utf-8 -*-
"""
Test integracyjny wtyczki LUT w prawdziwym GIMP-ie (bez okna).
Uruchom z folderu repozytorium:
  gimp-console-3.2.exe -i --batch-interpreter python-fu-eval ^
      -b "exec(open(r'tests\\gimp_lut_integration.py', encoding='utf-8').read())" --quit
Wymaga zainstalowanej wtyczki (install.ps1 -Plugin lut-cube).
Wynik w konsoli: PASS/FAIL dla każdego kroku i czasy działania.
"""
import os
import shutil
import struct
import sys
import tempfile
import time

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio

sys.path.insert(0, os.path.join(os.environ.get("LUT_CUBE_REPO") or os.getcwd(),
                                "tests"))
import gimp_lut_helpers as helpers  # noqa: E402
import cube_parser  # noqa: E402
import lut_apply  # noqa: E402

LUT_FILE = helpers.cube_files()[0]
PROC = "python-fu-lut-cube-apply"
FMT = "R'G'B'A float"
results = []
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")   # konsola cp1250


def check(name, cond, info=""):
    results.append(bool(cond))
    print("%s  %s %s" % ("PASS" if cond else "FAIL", name, info), flush=True)


def new_image(w, h, alpha=False, precision=None, base=Gimp.ImageBaseType.RGB):
    if precision is None:
        img = Gimp.Image.new(w, h, base)
    else:
        img = Gimp.Image.new_with_precision(w, h, base, precision)
    if base == Gimp.ImageBaseType.GRAY:
        t = Gimp.ImageType.GRAY_IMAGE
    else:
        t = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(img, "tło", w, h, t, 100, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    return img, layer


def fill_gradient(layer, alpha=False):
    """Gradient barw i jasności (+ przezroczysta lewa kolumna, gdy alpha)."""
    w, h = layer.get_width(), layer.get_height()
    px = []
    for y in range(h):
        for x in range(w):
            a = 0.0 if (alpha and x < w // 4) else 1.0
            px += [x / (w - 1), y / (h - 1), 1 - (x + y) / (w + h), a]
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), FMT, struct.pack("<%df" % len(px), *px))
    buf.flush()


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    data = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, FMT,
                                  Gegl.AbyssPolicy.NONE)
    return struct.unpack("<%df" % (len(data) // 4), data)


def run(img, drawables, **props):
    proc = Gimp.get_pdb().lookup_procedure(PROC)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", drawables)
    cfg.set_property("lut-file", Gio.File.new_for_path(props.pop("lut", LUT_FILE)))
    for k, v in props.items():
        cfg.set_property(k.replace("_", "-"), v)
    res = proc.run(cfg)
    status = res.index(0)
    err = res.index(1) if res.length() > 1 else None
    return status, err


def max_diff(a, b, alpha_too=True):
    step = 1 if alpha_too else 4
    if alpha_too:
        return max(abs(x - y) for x, y in zip(a, b))
    return max(abs(a[i + c] - b[i + c]) for i in range(0, len(a), step)
               for c in range(3))


lut = cube_parser.parse_cube_file(LUT_FILE)
OK = Gimp.PDBStatusType.SUCCESS

# 1. Rejestracja procedur
pdb = Gimp.get_pdb()
check("procedura apply zarejestrowana", pdb.lookup_procedure(PROC) is not None)
check("procedura biblioteki zarejestrowana",
      pdb.lookup_procedure("python-fu-lut-cube-library") is not None)
print("numpy w teście:", lut_apply.backend_name(), flush=True)

# 2. Nowa warstwa, 80 %, wynik = moduł obliczeniowy
img, bg = new_image(120, 80)
fill_gradient(bg)
before = pixels(bg)
status, err = run(img, [bg], strength=80.0)
check("nowa warstwa: status SUCCESS", status == OK, err or "")
layers = img.get_layers()
top = layers[0]
name_expected = "LUT: %s 80%%" % os.path.splitext(os.path.basename(LUT_FILE))[0]
check("nowa warstwa nad oryginałem", len(layers) == 2 and top != bg)
check("nazwa warstwy", top.get_name() == name_expected, top.get_name())
check("tryb Normalny i krycie 100", top.get_mode() == Gimp.LayerMode.NORMAL
      and abs(top.get_opacity() - 100) < 1e-6)
check("oryginał bez zmian", pixels(bg) == before)
expected, _ = lut_apply.apply_rgba(lut, struct.pack("<%df" % len(before), *before),
                                   lut_apply.Params(0.8))
exp = struct.unpack("<%df" % (len(expected) // 4), expected)
d = max_diff(pixels(top), exp)
check("piksele = lut_apply (8 bit, tolerancja 1/255)", d <= 1 / 255 + 1e-6,
      "max różnica %.5f" % d)
img.delete()

# 3. Na aktywnej warstwie + siła 0 %
img, bg = new_image(60, 40)
fill_gradient(bg)
before = pixels(bg)
status, _ = run(img, [bg], strength=0.0, output="in-place")
check("siła 0 % na warstwie = bez zmian", status == OK and pixels(bg) == before)
status, _ = run(img, [bg], strength=100.0, output="in-place")
check("na aktywnej warstwie: brak nowej warstwy",
      status == OK and len(img.get_layers()) == 1)
check("na aktywnej warstwie: piksele zmienione", pixels(bg) != before)
img.delete()

# 4. Kanał alfa
img, bg = new_image(60, 40, alpha=True)
fill_gradient(bg, alpha=True)
before = pixels(bg)
status, _ = run(img, [bg], output="in-place")
after = pixels(bg)
alpha_same = all(after[i + 3] == before[i + 3] for i in range(0, len(after), 4))
check("alfa bez zmian (przezroczyste zostają przezroczyste)",
      status == OK and alpha_same)
img.delete()

# 5. Zaznaczenie z miękką krawędzią
img, bg = new_image(100, 60)
fill_gradient(bg)
before = pixels(bg)
img.select_rectangle(Gimp.ChannelOps.REPLACE, 30, 10, 40, 40)
Gimp.Selection.feather(img, 10)
status, _ = run(img, [bg], output="in-place")
after = pixels(bg)


def px(data, x, y, w=100):
    i = 4 * (y * w + x)
    return data[i:i + 3]


check("zaznaczenie: poza zaznaczeniem bez zmian",
      px(after, 2, 2) == px(before, 2, 2) and px(after, 97, 57) == px(before, 97, 57))
check("zaznaczenie: w środku zmienione", px(after, 50, 30) != px(before, 50, 30))
ful, _ = lut_apply.apply_rgba(lut, struct.pack("<4f", *px(before, 50, 30), 1.0),
                              lut_apply.Params())
check("zaznaczenie: środek = pełny LUT",
      max(abs(a - b) for a, b in zip(px(after, 50, 30),
                                     struct.unpack("<4f", ful)[:3])) <= 1 / 255 + 1e-6)
edge_before, edge_after = px(before, 30, 30), px(after, 30, 30)
edge_full = struct.unpack("<4f", lut_apply.apply_rgba(
    lut, struct.pack("<4f", *edge_before, 1.0), lut_apply.Params())[0])[:3]
partial = all(min(b, f) - 2 / 255 <= a <= max(b, f) + 2 / 255
              for a, b, f in zip(edge_after, edge_before, edge_full)) \
    and edge_after != edge_before and \
    max(abs(a - f) for a, f in zip(edge_after, edge_full)) > 2 / 255
check("zaznaczenie: miękka krawędź = częściowy efekt", partial,
      "%s / %s / %s" % ([round(v, 3) for v in edge_before],
                        [round(v, 3) for v in edge_after],
                        [round(v, 3) for v in edge_full]))
img.delete()

# 5b. Nowa warstwa z miękkim zaznaczeniem = ten sam wynik co „na warstwie”
img, bg = new_image(100, 60)
fill_gradient(bg)
img.select_rectangle(Gimp.ChannelOps.REPLACE, 30, 10, 40, 40)
Gimp.Selection.feather(img, 10)
status, _ = run(img, [bg], output="new-layer")
copy_px = pixels(img.get_layers()[0])
status2, _ = run(img, [bg], output="in-place")
d = max_diff(copy_px, pixels(bg))
check("nowa warstwa z zaznaczeniem = wynik GIMP-a (merge_shadow)",
      status == OK and status2 == OK and d <= 1 / 255 + 1e-6,
      "max różnica %.5f" % d)
img.delete()

# 6. Obraz 16-bitowy (precyzja zachowana, nie obcięta do 8 bitów)
img, bg = new_image(200, 2, precision=Gimp.Precision.U16_NON_LINEAR)
fill_gradient(bg)
status, _ = run(img, [bg], output="in-place")
check("16 bit: precyzja obrazu bez zmian",
      status == OK and img.get_precision() == Gimp.Precision.U16_NON_LINEAR)
vals = pixels(bg)
reds = {round(vals[i] * 65535) for i in range(0, 4 * 200, 4)}
not8 = any(r % 257 for r in reds)
check("16 bit: wynik ma wartości pośrednie (nie 8-bitowe)", not8,
      "%d różnych wartości R" % len(reds))
img.delete()

# 7. Obraz 32-bit float liniowy
img, bg = new_image(60, 40, precision=Gimp.Precision.FLOAT_LINEAR)
fill_gradient(bg)
before = pixels(bg)
status, _ = run(img, [bg], output="in-place")
expected, _ = lut_apply.apply_rgba(lut, struct.pack("<%df" % len(before), *before),
                                   lut_apply.Params())
d = max_diff(pixels(bg), struct.unpack("<%df" % (len(expected) // 4), expected))
check("32 bit liniowy: wynik w wartościach perceptualnych", status == OK
      and d < 1e-4, "max różnica %.6f" % d)
img.delete()

# 8. Siła jako krycie warstwy
img, bg = new_image(40, 30)
fill_gradient(bg)
status, _ = run(img, [bg], strength=60.0, strength_as_opacity=True)
top = img.get_layers()[0]
check("siła jako krycie: krycie 60",
      status == OK and abs(top.get_opacity() - 60) < 1e-6, str(top.get_opacity()))
img.delete()

# 9. Skala szarości → czytelny błąd (bez okna)
img, bg = new_image(40, 30, base=Gimp.ImageBaseType.GRAY)
status, err = run(img, [bg])
check("skala szarości: błąd z komunikatem po polsku",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and err and "RGB" in err,
      (err or ""))
img.delete()

# 10. Polskie znaki i spacje w ścieżce LUT-a
tmpdir = os.path.join(tempfile.gettempdir(), "LUT ąęśćżź test")
os.makedirs(tmpdir, exist_ok=True)
pl_path = os.path.join(tmpdir, "Zażółć gęślą jaźń.cube")
shutil.copyfile(LUT_FILE, pl_path)
img, bg = new_image(40, 30)
fill_gradient(bg)
status, err = run(img, [bg], lut=pl_path)
check("polskie znaki w ścieżce", status == OK, (err or ""))
check("nazwa warstwy z polskimi znakami",
      img.get_layers()[0].get_name() == "LUT: Zażółć gęślą jaźń 100%",
      img.get_layers()[0].get_name())
img.delete()

# 11. Uszkodzony .cube → błąd, obraz bez zmian
bad = os.path.join(tmpdir, "zepsuty.cube")
with open(bad, "w", encoding="utf-8") as f:
    f.write("LUT_3D_SIZE 2\n0,5 0 0\n")
img, bg = new_image(40, 30)
status, err = run(img, [bg], lut=bad)
check("uszkodzony .cube: błąd po polsku",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "przecink" in err,
      (err or ""))
check("uszkodzony .cube: brak nowej warstwy", len(img.get_layers()) == 1)
img.delete()
shutil.rmtree(tmpdir, ignore_errors=True)

# 12. Grupa warstw → błąd
img, bg = new_image(40, 30)
group = Gimp.GroupLayer.new(img, "grupa")
img.insert_layer(group, None, 0)
status, err = run(img, [group])
check("grupa warstw: błąd z komunikatem",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "grup" in err,
      (err or ""))
img.delete()

# 13. Trzy kształty zdjęcia: poziome, pionowe, bardzo małe
for w, h in ((300, 200), (200, 300), (3, 2)):
    img, bg = new_image(w, h)
    fill_gradient(bg) if w > 3 else None
    status, err = run(img, [bg])
    check("zdjęcie %d×%d" % (w, h), status == OK, (err or ""))
    img.delete()

# 14. Czas na zdjęciu ok. 24 Mpx (6000×4000, 8 bit)
img, bg = new_image(6000, 4000)
bg.get_buffer()  # noqa
Gimp.context_set_gradient_fg_bg_rgb()
bg.edit_gradient_fill(Gimp.GradientType.LINEAR, 0, False, 1, 0, True,
                      0, 0, 6000, 4000)
for mode in ("new-layer", "in-place"):
    t = time.perf_counter()
    status, err = run(img, [bg], strength=80.0, output=mode)
    dt = time.perf_counter() - t
    check("24 Mpx (%s)" % mode, status == OK, "czas %.1f s" % dt)
img.delete()

# 15. Maska tonalna przez PDB: tylko światła
img, bg = new_image(200, 2)
fill_gradient(bg)
before = pixels(bg)
status, _ = run(img, [bg], output="in-place", shadows=0.0, midtones=0.0,
                highlights=100.0)
expected, _ = lut_apply.apply_rgba(
    lut, struct.pack("<%df" % len(before), *before),
    lut_apply.Params(1.0, shadows=0.0, midtones=0.0, highlights=1.0))
d = max_diff(pixels(bg), struct.unpack("<%df" % (len(expected) // 4), expected))
check("maska tonalna przez PDB = lut_apply", status == OK and d <= 1 / 255 + 1e-6,
      "max różnica %.5f" % d)
img.delete()

# 16. Plik .3dl przez PDB (ten sam look co .cube)
tmp3 = os.path.join(helpers.TMP, "test.3dl")
n3 = 9
with open(tmp3, "w", encoding="utf-8") as f:
    f.write(" ".join(str(round(i * 1023 / (n3 - 1))) for i in range(n3)) + "\n")
    for r in range(n3):
        for g in range(n3):
            for b in range(n3):
                f.write("%d %d %d\n" % tuple(round(v / (n3 - 1) * 4095) for v in (g, b, r)))
img, bg = new_image(40, 30)
fill_gradient(bg)
status, err = run(img, [bg], lut=tmp3, output="in-place")
px0 = pixels(bg)[:3]
check("plik .3dl przez PDB", status == OK and len(px0) == 3, err or "")
img.delete()

# 17. Preset z biblioteki przez PDB
import gimp_ops  # noqa: E402
import library  # noqa: E402
lib = library.Library(gimp_ops.library_root())
had_preset = "Test integracji" in lib.presets
tmp_lib_added = []
res = lib.add_files([LUT_FILE])
tmp_lib_added = res.added
lut_id = (res.added or [lib._find_by_hash(library.file_sha256(LUT_FILE))])[0]
lib.save_preset("Test integracji", lut_id, {"strength": 30.0})
img, bg = new_image(60, 40)
fill_gradient(bg)
status, err = run(img, [bg], preset="test INTEGRACJI", strength=90.0)
top = img.get_layers()[0]
check("preset przez PDB (LUT i siła z presetu)",
      status == OK and top.get_name().endswith(" 30%"), (err, top.get_name()))
status, err = run(img, [bg], preset="nie ma takiego")
check("nieznany preset → czytelny błąd",
      status == Gimp.PDBStatusType.EXECUTION_ERROR and "presetu" in str(err), err)
img.delete()
lib = library.Library(gimp_ops.library_root())
if not had_preset:
    lib.delete_preset("Test integracji")
for i in tmp_lib_added:
    lib.remove(i, delete_file=True)

# 18. Tryb wsadowy
bdir = os.path.join(helpers.TMP, "wsadowo ąę")
shutil.rmtree(bdir, ignore_errors=True)
os.makedirs(os.path.join(bdir, "pod"))
src_imgs = helpers.make_test_images()
for name, target in (("male.png", "a.png"), ("alfa.png", "pod/b.png"),
                     ("16bit.png", "c.png")):
    shutil.copyfile(os.path.join(src_imgs, name), os.path.join(bdir, target))
out_dir = os.path.join(bdir, "wyniki")
os.makedirs(out_dir)        # GIMP sprawdza, czy wskazany folder istnieje
proc = Gimp.get_pdb().lookup_procedure("python-fu-lut-cube-batch")
cfg = proc.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("input-folder", Gio.File.new_for_path(bdir))
cfg.set_property("output-folder", Gio.File.new_for_path(out_dir))
cfg.set_property("recursive", True)
cfg.set_property("format", "jpg")
cfg.set_property("lut-file", Gio.File.new_for_path(LUT_FILE))
t = time.perf_counter()
res = proc.run(cfg)
outs = sorted(os.path.relpath(os.path.join(dp, f), out_dir).replace(os.sep, "/")
              for dp, _dn, fs in os.walk(out_dir) for f in fs)
check("wsadowo: 3 zdjęcia zapisane jako JPG (z podfolderem)",
      res.index(0) == OK and outs == ["a-lut.jpg", "c-lut.jpg", "pod/b-lut.jpg"],
      "%s, %.1f s %s" % (outs, time.perf_counter() - t,
                         res.index(1) if res.length() > 1 else ""))
orig = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                      Gio.File.new_for_path(os.path.join(bdir, "c.png")))
done = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                      Gio.File.new_for_path(os.path.join(out_dir, "c-lut.jpg")))
ref, _ = lut_apply.apply_rgba(lut, struct.pack("<4f", *pixels(orig.get_layers()[0])[:4]),
                              lut_apply.Params())
got = pixels(done.get_layers()[0])[:3]
check("wsadowo: piksel = LUT (JPG, tolerancja kompresji)",
      max(abs(a - b) for a, b in zip(got, struct.unpack("<4f", ref)[:3])) < 0.05,
      ([round(v, 3) for v in got], [round(v, 3) for v in struct.unpack("<4f", ref)[:3]]))
orig.delete()
done.delete()
cfg.set_property("output-folder", Gio.File.new_for_path(bdir))
cfg.set_property("suffix", "")
cfg.set_property("format", "same")
res = proc.run(cfg)
check("wsadowo: odmowa nadpisania oryginałów",
      res.index(0) == Gimp.PDBStatusType.EXECUTION_ERROR
      and "nadpisane" in str(res.index(1)), res.index(1))

# 19. Własny look: obraz Hald → korekta GIMP-a → .cube → ten sam efekt na zdjęciu
proc_new = Gimp.get_pdb().lookup_procedure("python-fu-lut-cube-hald-new")
cfg = proc_new.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("level", "l6")
res = proc_new.run(cfg)
hald = res.index(1)
check("Hald: nowy obraz 216×216, 16 bit",
      res.index(0) == OK and hald.get_width() == 216
      and hald.get_precision() == Gimp.Precision.U16_NON_LINEAR)
look = lambda d: (d.curves_spline(Gimp.HistogramChannel.VALUE,  # noqa: E731
                                  [0.0, 0.08, 0.5, 0.6, 1.0, 0.95])
                  and d.hue_saturation(Gimp.HueRange.ALL, 15.0, 0.0, -30.0, 0.0))
look(hald.get_layers()[0])
cube_out = os.path.join(helpers.TMP, "mój look ż.cube")
proc_save = Gimp.get_pdb().lookup_procedure("python-fu-lut-cube-hald-save")
cfg = proc_save.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("image", hald)
cfg.set_property("file", Gio.File.new_for_path(cube_out))
cfg.set_property("title", "Mój look")
cfg.set_property("add-to-library", False)
res = proc_save.run(cfg)
saved_lut = cube_parser.parse_cube_file(cube_out) if os.path.exists(cube_out) else None
check("Hald: zapisany .cube (siatka 36)",
      res.index(0) == OK and saved_lut is not None and saved_lut.size_3d == 36
      and saved_lut.title == "Mój look", res.index(1) if res.length() > 1 else "")
hald.delete()
img, bg = new_image(120, 80, precision=Gimp.Precision.U16_NON_LINEAR)
fill_gradient(bg)
ref_img = img.duplicate()
look(ref_img.get_layers()[0])
status, _ = run(img, [bg], lut=cube_out, output="in-place")
d = max_diff(pixels(bg), pixels(ref_img.get_layers()[0]), alpha_too=False)
check("Hald: LUT z looku = ta sama korekta GIMP-a na zdjęciu", status == OK and d < 0.02,
      "max różnica %.4f" % d)
img.delete()
ref_img.delete()

# 20. Zapis looku z obrazu, który nie jest Hald → czytelny błąd
img, bg = new_image(100, 80)
cfg.set_property("image", img)
res = proc_save.run(cfg)
check("Hald: obraz o złych wymiarach → błąd po polsku",
      res.index(0) == Gimp.PDBStatusType.EXECUTION_ERROR
      and "Hald" in str(res.index(1)), res.index(1))
img.delete()

print("WYNIK: %d/%d PASS" % (sum(results), len(results)), flush=True)
