# -*- coding: utf-8 -*-
"""
Testy rdzenia Zetmar Kolor (bez GIMP-a). Uruchomienie Pythonem z GIMP-a:

    "%LOCALAPPDATA%\\Programs\\GIMP 3\\bin\\python.exe" tests\\test_core.py
"""

import ast
import json
import os
import random
import re
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(os.path.dirname(HERE), "plug-ins", "zetmar-kolor")
sys.path.insert(0, PLUGIN)
os.environ.setdefault("GIMP_WTYCZKI_LANG", "pl")

import zk_core as zk  # noqa: E402

# numpy z folderu vendor/ wtyczki lut-cube zainstalowanej w GIMP-ie (jak po instalacji).
_INSTALLED = os.path.join(os.environ.get("APPDATA", ""), "GIMP", "3.2", "plug-ins")
_orig_dirs = zk._vendor_dirs
zk._vendor_dirs = lambda: _orig_dirs() + [os.path.join(_INSTALLED, "lut-cube", "vendor")]


def random_look(rnd):
    lk = zk.Look()
    lk.apply_curve_preset(rnd.choice([n for n, _ in zk.CURVE_PRESETS]))
    if rnd.random() < 0.5:
        lk.curves[zk.CH_G] = zk.sanitize_curve([(0, rnd.random() * 0.2), (0.5, rnd.random()),
                                                (1, 0.8 + rnd.random() * 0.2)])
    lk.luma_only = rnd.random() < 0.5
    lk.bw_mode = rnd.choice([0, 1, 2, 3])
    lk.bw_mix = [rnd.randint(-200, 300) for _ in range(6)]
    lk.tint_hue, lk.tint_sat = rnd.randint(0, 360), rnd.randint(0, 100)
    lk.duo_on = rnd.random() < 0.5
    lk.duo_shadow, lk.duo_highlight = rnd.randint(0, 0xFFFFFF), rnd.randint(0, 0xFFFFFF)
    lk.duo_mid, lk.duo_amount = rnd.randint(5, 95), rnd.randint(0, 100)
    lk.ton_on = rnd.random() < 0.7
    lk.hi_hue, lk.hi_sat = rnd.randint(0, 360), rnd.randint(0, 100)
    lk.sh_hue, lk.sh_sat = rnd.randint(0, 360), rnd.randint(0, 100)
    lk.balance = rnd.randint(-100, 100)
    lk.overall = rnd.choice([100, 100, rnd.randint(0, 100)])
    return lk.sanitize()


def rgba(pixels):
    flat = []
    for p in pixels:
        flat += [p[0], p[1], p[2], 1.0]
    return struct.pack("<%df" % len(flat), *flat)


def unpack(b):
    v = struct.unpack("<%df" % (len(b) // 4), b)
    return [v[i:i + 4] for i in range(0, len(v), 4)]


class CurveTests(unittest.TestCase):

    def test_identity_and_points(self):
        self.assertIsNone(zk.curve_table(zk.identity_curve()))
        pts = zk.sanitize_curve([(0, 0), (0.25, 0.15), (0.75, 0.86), (1, 1)])
        for x, y in pts:
            self.assertAlmostEqual(zk.eval_curve(pts, x), y, places=6)

    def test_monotone_no_overshoot(self):
        pts = zk.sanitize_curve([(0, 0), (0.1, 0.5), (0.2, 0.52), (1, 1)])
        prev = -1
        for i in range(1001):
            v = zk.eval_curve(pts, i / 1000.0)
            self.assertGreaterEqual(v, prev - 1e-7)
            prev = v
        # między punktami (0.1, 0.5) i (0.2, 0.52) nie wychodzi poza ich zakres
        for i in range(101):
            v = zk.eval_curve(pts, 0.1 + i / 1000.0)
            self.assertTrue(0.5 - 1e-6 <= v <= 0.52 + 1e-6)

    def test_sanitize(self):
        c = zk.sanitize_curve([(0.3, 2), (0.5, 0.5), (0.501, 0.6), (0.9, -1)])
        self.assertEqual(c[0][0], 0.0)
        self.assertEqual(c[-1][0], 1.0)
        self.assertEqual(len(c), 3)            # 0.501 za blisko 0.5
        self.assertEqual(zk.sanitize_curve([(0, 0)]), zk.identity_curve())
        self.assertEqual(zk.sanitize_curve([(0, float("nan")), (1, 1)]), zk.identity_curve())


class PixelTests(unittest.TestCase):

    def test_neutral_look_is_identity(self):
        pipe = zk.Pipeline(zk.Look())
        self.assertTrue(pipe.neutral)
        data = rgba([(0.1, 0.5, 0.9), (1, 0, 0)])
        self.assertEqual(zk.apply_rgba(pipe, data), data)

    def test_bw_keeps_neutral_gray(self):
        lk = zk.Look()
        lk.bw_mode = zk.BW_BW
        lk.bw_mix = [150, -200, 300, 0, 77, -50]
        pipe = zk.Pipeline(lk)
        for g in (0.0, 0.2, 0.5, 1.0):
            out = pipe.pixel((g, g, g))
            for v in out:
                self.assertAlmostEqual(v, g, places=6)

    def test_bw_default_mixer_values(self):
        pipe = zk.Pipeline(zk.Look())
        # czysta czerwień: szarość = waga czerwonych (40 %)
        self.assertAlmostEqual(pipe.bw_gray([1.0, 0.0, 0.0]), 0.40, places=6)
        # czysty żółty: min 0, mid 1 (·żółte 60 %), max−mid 0
        self.assertAlmostEqual(pipe.bw_gray([1.0, 1.0, 0.0]), 0.60, places=6)

    def test_sepia_keeps_black_and_white(self):
        lk = zk.Look()
        lk.bw_mode = zk.BW_SEPIA
        lk.tint_sat = 100
        pipe = zk.Pipeline(lk)
        self.assertEqual(pipe.pixel((0, 0, 0)), [0.0, 0.0, 0.0])
        self.assertEqual(pipe.pixel((1, 1, 1)), [1.0, 1.0, 1.0])
        r, g, b = pipe.pixel((0.5, 0.5, 0.5))
        self.assertGreater(r, b)              # ciepły odcień

    def test_overall_zero(self):
        lk = random_look(random.Random(1))
        lk.overall = 0
        self.assertTrue(zk.Pipeline(lk).neutral)

    def test_numpy_matches_pure(self):
        np = zk.get_numpy()
        if np is None:
            self.skipTest("brak numpy")
        rnd = random.Random(7)
        pixels = [(rnd.random(), rnd.random(), rnd.random()) for _ in range(3000)]
        pixels += [(0, 0, 0), (1, 1, 1), (0.5, 0.5, 0.5), (1, 1, 0), (0, 1, 1), (0.3, 0.3, 0.9)]
        data = rgba(pixels)
        mask = struct.pack("<%df" % len(pixels), *[rnd.choice([0.0, 1.0, rnd.random()])
                                                   for _ in pixels])
        for seed in range(40):
            pipe = zk.Pipeline(random_look(random.Random(seed)))
            for m in (None, mask):
                a = unpack(zk.apply_rgba(pipe, data, m, use_numpy=True))
                b = unpack(zk.apply_rgba(pipe, data, m, use_numpy=False))
                worst = max(abs(p[k] - q[k]) for p, q in zip(a, b) for k in range(4))
                self.assertLess(worst, 2e-4, "seed %d, maska %s" % (seed, m is not None))

    def test_alpha_untouched(self):
        lk = random_look(random.Random(3))
        lk.overall = 100
        data = struct.pack("<8f", 0.2, 0.4, 0.6, 0.25, 0.9, 0.1, 0.3, 0.0)
        for use_np in (True, False):
            out = unpack(zk.apply_rgba(zk.Pipeline(lk), data, use_numpy=use_np))
            self.assertAlmostEqual(out[0][3], 0.25)
            self.assertAlmostEqual(out[1][3], 0.0)

    def test_histograms(self):
        h_np = zk.histograms(rgba([(0, 0, 0), (1, 1, 1), (1, 0, 0)]), True)
        h_py = zk.histograms(rgba([(0, 0, 0), (1, 1, 1), (1, 0, 0)]), False)
        self.assertEqual(h_np, h_py)
        self.assertEqual(h_np[1][255], 2)


class LookTests(unittest.TestCase):

    def test_roundtrip(self):
        for seed in range(30):
            lk = random_look(random.Random(seed))
            text = zk.look_to_text(lk)
            self.assertEqual(zk.look_to_text(zk.look_from_text(text)), text)

    def test_photoshop_file_with_lut(self):
        text = ("ZKLOOK 1\ncurvesOn 1\nlumaOnly 0\ncurve 0 3 0 0 500000 600000 1000000 1000000\n"
                "curve 1 2 0 0 1000000 1000000\ncurve 2 2 0 0 1000000 1000000\n"
                "curve 3 2 0 0 1000000 1000000\nbw 2 40 60 40 60 20 80 35 50\n"
                "toning 1 40 25 215 25 0\nduotone 0 1515837 15902298 48 100\n"
                "lut 80 1\nlutpath C:\\LUTs\\Film.cube\noverall 90\nfuture 1 2 3\n")
        lk = zk.look_from_text(text.encode("utf-8"))
        self.assertEqual(lk.bw_mode, zk.BW_SEPIA)
        self.assertEqual(lk.overall, 90)
        self.assertAlmostEqual(lk.curves[0][1][1], 0.6)
        self.assertTrue(lk.ton_on)

    def test_rejects_garbage(self):
        for bad in ("", "hello", "ZKLOOK 1\n", "ZKLOOK 1\ncurve 0 2 0 0\n",
                    "ZKLOOK 1\nbw 1 2 3\n", "ZKLOOK 1\ncurve 9 2 0 0 1 1\n"):
            with self.assertRaises(zk.LookError):
                zk.look_from_text(bad)


class TranslationTests(unittest.TestCase):

    def test_all_strings_translated(self):
        with open(os.path.join(PLUGIN, "en.json"), encoding="utf-8") as f:
            en = json.load(f)
        missing = []
        pat = re.compile(r'tr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)')
        for name in os.listdir(PLUGIN):
            if not name.endswith(".py") or name == "zk_i18n.py":
                continue
            with open(os.path.join(PLUGIN, name), encoding="utf-8") as f:
                src = f.read()
            for m in pat.finditer(src):
                text = "".join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1)))
                if text not in en:
                    missing.append("%s: %r" % (name, text))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
