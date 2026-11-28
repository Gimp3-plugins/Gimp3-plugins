# -*- coding: utf-8 -*-
"""
Test w prawdziwym GIMP-ie (bez okna): rejestracja procedury, nałożenie looku
na warstwę (in-place i nowa warstwa z zaznaczeniem), porównanie z zk_core.

    gimp-console-3.2.exe -i --batch-interpreter=python-fu-eval ^
        -b "exec(open(r'<ścieżka>\\tests\\gimp_batch.py', encoding='utf-8').read())" --quit

Wynik: plik z env ZK_TEST_OUT (domyślnie gimp_batch_result.txt obok testu).
"""

import os
import struct
import sys
import traceback

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl  # noqa: E402

PLUGIN = os.path.join(os.environ["APPDATA"], "GIMP", "3.2", "plug-ins", "zetmar-kolor")
OUT = os.environ.get("ZK_TEST_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(PLUGIN)), "..", "zk_batch_result.txt")
sys.path.insert(0, PLUGIN)
log = []


def check(cond, msg):
    log.append(("OK   " if cond else "FAIL ") + msg)


def make_image(precision):
    w, h = 64, 32
    img = Gimp.Image.new_with_precision(w, h, Gimp.ImageBaseType.RGB, precision)
    layer = Gimp.Layer.new(img, "tlo", w, h, Gimp.ImageType.RGBA_IMAGE, 100,
                           Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    px = []
    for y in range(h):
        for x in range(w):
            px += (x / (w - 1.0), y / (h - 1.0), (x * 7 + y * 3) % 64 / 63.0, 1.0)
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A float", struct.pack("<%df" % len(px), *px))
    buf.flush()
    return img, layer


def read(layer):
    w, h = layer.get_width(), layer.get_height()
    data = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A float",
                                  Gegl.AbyssPolicy.CLAMP)
    return data, struct.unpack("<%df" % (len(data) // 4), data)


def run(img, layers, look_text, output):
    proc = Gimp.get_pdb().lookup_procedure("python-fu-zetmar-kolor")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", layers)
    cfg.set_property("look", look_text)
    cfg.set_property("output", output)
    res = proc.run(cfg)
    return res.index(0), (res.index(1) if res.length() > 1 else None)


try:
    import zk_core
    check(Gimp.get_pdb().procedure_exists("python-fu-zetmar-kolor"), "procedura zarejestrowana")
    look = zk_core.Look()
    look.apply_curve_preset("strong-s")
    look.bw_mode = zk_core.BW_MONO
    look.tint_hue, look.tint_sat = 200, 50
    look.apply_toning_preset("gold")
    look.overall = 85
    text = zk_core.look_to_text(look)
    pipe = zk_core.Pipeline(look)

    for prec, tol, name in ((Gimp.Precision.FLOAT_NON_LINEAR, 1e-4, "float"),
                            (Gimp.Precision.U8_NON_LINEAR, 2.6 / 255, "8 bit")):
        img, layer = make_image(prec)
        before, _ = read(layer)
        status, _ = run(img, [layer], text, "in-place")
        check(status == Gimp.PDBStatusType.SUCCESS, "%s in-place: status %s" % (name, status))
        _, after = read(layer)
        expected = struct.unpack("<%df" % (len(before) // 4), zk_core.apply_rgba(pipe, before))
        worst = max(abs(a - e) for a, e in zip(after, expected))
        check(worst <= tol, "%s in-place: zgodność z zk_core (maks. różnica %.6f)" % (name, worst))
        img.delete()

    # nowa warstwa + zaznaczenie prostokątne: poza zaznaczeniem bez zmian
    img, layer = make_image(Gimp.Precision.FLOAT_NON_LINEAR)
    before, bvals = read(layer)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 32, 32)
    status, _ = run(img, [layer], text, "new-layer")
    check(status == Gimp.PDBStatusType.SUCCESS, "nowa warstwa: status %s" % status)
    layers = img.get_layers()
    check(len(layers) == 2 and layers[0].get_name() == "Zetmar Kolor",
          "nowa warstwa nad oryginałem (%s)" % [l.get_name() for l in layers])
    _, orig_after = read(layer)
    check(orig_after == bvals, "oryginalna warstwa bez zmian")
    _, top = read(layers[0])
    exp = struct.unpack("<%df" % (len(before) // 4), zk_core.apply_rgba(pipe, before))
    inside = outside = 0.0
    for y in range(32):
        for x in range(64):
            for c in range(3):
                i = (y * 64 + x) * 4 + c
                if x < 31:
                    inside = max(inside, abs(top[i] - exp[i]))
                elif x > 32:
                    outside = max(outside, abs(top[i] - bvals[i]))
    check(inside < 1e-4, "w zaznaczeniu efekt (maks. różnica %.6f)" % inside)
    check(outside < 1e-6, "poza zaznaczeniem bez zmian (maks. różnica %.6f)" % outside)
    img.delete()

    # odczyt zmniejszonej kopii do podglądu okna (z maską zaznaczenia i bez)
    import zk_gimp
    img, layer = make_image(Gimp.Precision.U16_NON_LINEAR)
    data, mask, w, h = zk_gimp.read_scaled(img, layer, 32)
    check((w, h) == (32, 16) and len(data) == w * h * 16 and mask is None,
          "podgląd: %dx%d, bez maski" % (w, h))
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 32, 32)
    data, mask, w, h = zk_gimp.read_scaled(img, layer, 32)
    check(mask is not None and len(mask) == w * h * 4, "podgląd: maska zaznaczenia")
    img.delete()

    # błędny look → błąd z komunikatem
    img, layer = make_image(Gimp.Precision.U8_NON_LINEAR)
    status, _ = run(img, [layer], "to nie jest look", "in-place")
    check(status == Gimp.PDBStatusType.EXECUTION_ERROR, "zły look: błąd wykonania (%s)" % status)
    img.delete()
except Exception:
    log.append("EXCEPTION " + traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(log) + "\n")
