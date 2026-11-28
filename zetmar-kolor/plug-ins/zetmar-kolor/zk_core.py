# -*- coding: utf-8 -*-
"""
Rdzeń obliczeń Zetmar Kolor (bez GIMP-a): krzywe, czerń-biel / sepia /
monochromia, duotone, toning i siła ogólna.

Algorytmy są przeniesione 1:1 z wtyczki Zetmar Kolor (.8bf) dla Photoshopa
(src/core/curves.cpp, bw_toning.cpp, pipeline.cpp) – bez modułu LUT.
Plik looku (.zklook) ma ten sam format, więc looki można przenosić między
Photoshopem a GIMP-em (linie LUT-a są tu pomijane).

Wartości pikseli to kodowanie perceptualne 0–1 (gamma sRGB, format babl
„R'G'B'A float”), tak jak w Photoshopie. Potok:

    krzywe → czerń-biel / sepia / monochromia → duotone → toning → siła ogólna

Dwa warianty obliczeń o tym samym wyniku: numpy (szybki) i czysty Python
(wolniejszy, gdy numpy nie ma). Kanał alfa nie jest zmieniany.
"""

import math
import os
from array import array

from zk_i18n import tr

PLUGIN_VERSION = "1.0.0"

LUMA = (0.2126, 0.7152, 0.0722)
MAX_POINTS = 16
MIN_GAP = 1.0 / 255.0
TABLE_SIZE = 4096

CH_RGB, CH_R, CH_G, CH_B = 0, 1, 2, 3
BW_OFF, BW_BW, BW_SEPIA, BW_MONO = 0, 1, 2, 3
SEPIA_HUE = 35
MIX_COLORS = 6          # czerwone, żółte, zielone, cyjany, niebieskie, magenty
DEFAULT_MIX = (40, 60, 40, 60, 20, 80)

LOOK_HEADER = "ZKLOOK 1"
MAX_LOOK_BYTES = 64 * 1024


class LookError(Exception):
    """Niepoprawny plik / tekst looku."""


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _clampi(v, lo, hi):
    v = int(v)
    return lo if v < lo else (hi if v > hi else v)


# ---------------------------------------------------------------------------
# Krzywe (PCHIP, Fritsch-Carlson – bez przerzutów ponad punkty)
# ---------------------------------------------------------------------------

def identity_curve():
    return [[0.0, 0.0], [1.0, 1.0]]


def is_identity_curve(pts):
    return len(pts) < 2 or all(abs(x - y) <= 1e-6 for x, y in pts)


def sanitize_curve(pts):
    """2–16 punktów, rosnące x z odstępem ≥ 1/255, końce w x = 0 i 1, y w 0–1."""
    try:
        pts = [[float(x), float(y)] for x, y in pts]
    except (TypeError, ValueError):
        return identity_curve()
    if not 2 <= len(pts) <= MAX_POINTS:
        return identity_curve()
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pts):
        return identity_curve()
    pts = sorted(([_clamp01(x), _clamp01(y)] for x, y in pts), key=lambda p: p[0])
    pts[0][0], pts[-1][0] = 0.0, 1.0
    out = [pts[0]]
    for p in pts[1:-1]:
        if p[0] - out[-1][0] >= MIN_GAP and 1.0 - p[0] >= MIN_GAP:
            out.append(p)
    out.append(pts[-1])
    return out


def _slopes(pts):
    n = len(pts)
    h = [pts[k + 1][0] - pts[k][0] for k in range(n - 1)]
    d = [(pts[k + 1][1] - pts[k][1]) / h[k] for k in range(n - 1)]
    if n == 2:
        return [d[0], d[0]]
    m = [0.0] * n
    for k in range(1, n - 1):
        if d[k - 1] * d[k] <= 0.0:
            continue
        w1, w2 = 2.0 * h[k] + h[k - 1], h[k] + 2.0 * h[k - 1]
        m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])

    def end(h0, h1, d0, d1):
        s = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if s * d0 <= 0.0:
            return 0.0
        if d0 * d1 <= 0.0 and abs(s) > abs(3.0 * d0):
            return 3.0 * d0
        return s

    m[0] = end(h[0], h[1], d[0], d[1])
    m[n - 1] = end(h[n - 2], h[n - 3], d[n - 2], d[n - 3])
    return m


def _eval(pts, m, x):
    n = len(pts)
    if x <= pts[0][0]:
        return _clamp01(pts[0][1])
    if x >= pts[-1][0]:
        return _clamp01(pts[-1][1])
    k = 0
    while k < n - 2 and x > pts[k + 1][0]:
        k += 1
    h = pts[k + 1][0] - pts[k][0]
    t = (x - pts[k][0]) / h
    t2 = t * t
    t3 = t2 * t
    return _clamp01((2 * t3 - 3 * t2 + 1) * pts[k][1] + (t3 - 2 * t2 + t) * h * m[k]
                    + (-2 * t3 + 3 * t2) * pts[k + 1][1] + (t3 - t2) * h * m[k + 1])


def eval_curve(pts, x):
    """Wartość krzywej w punkcie x (0–1)."""
    return _eval(pts, _slopes(pts), x)


def curve_table(pts, size=TABLE_SIZE):
    """Próbki krzywej (size wartości) albo None, gdy krzywa jest tożsamościowa."""
    if is_identity_curve(pts):
        return None
    m = _slopes(pts)
    return [_eval(pts, m, i / float(size - 1)) for i in range(size)]


def _lookup(t, v):
    f = _clamp01(v) * (TABLE_SIZE - 1)
    i = int(f)
    if i >= TABLE_SIZE - 1:
        return t[-1]
    return t[i] + (t[i + 1] - t[i]) * (f - i)


CURVE_PRESETS = [
    ("soft-s", tr("S-krzywa delikatna")),
    ("medium-s", tr("S-krzywa średnia")),
    ("strong-s", tr("S-krzywa mocna")),
    ("matte", tr("Matowy (podniesiona czerń)")),
    ("lift-shadows", tr("Rozjaśnienie cieni")),
    ("tame-highlights", tr("Ściągnięcie świateł")),
    ("cross", tr("Cross-process")),
    ("negative", tr("Negatyw")),
]

_CURVE_PRESET_POINTS = {
    "soft-s": {CH_RGB: [(0, 0), (0.25, 0.22), (0.75, 0.78), (1, 1)]},
    "medium-s": {CH_RGB: [(0, 0), (0.25, 0.19), (0.75, 0.81), (1, 1)]},
    "strong-s": {CH_RGB: [(0, 0), (0.25, 0.15), (0.75, 0.86), (1, 1)]},
    "matte": {CH_RGB: [(0, 0.08), (0.25, 0.27), (0.75, 0.76), (1, 0.96)]},
    "lift-shadows": {CH_RGB: [(0, 0), (0.22, 0.31), (0.55, 0.6), (1, 1)]},
    "tame-highlights": {CH_RGB: [(0, 0), (0.5, 0.5), (0.8, 0.74), (1, 0.94)]},
    "cross": {CH_R: [(0, 0), (0.25, 0.19), (0.75, 0.83), (1, 1)],
              CH_G: [(0, 0), (0.25, 0.21), (0.75, 0.8), (1, 1)],
              CH_B: [(0, 0.12), (0.5, 0.47), (1, 0.86)]},
    "negative": {CH_RGB: [(0, 1), (1, 0)]},
}


# ---------------------------------------------------------------------------
# Presety czerni-bieli, tonowania i duotonu (wartości jak w wersji .8bf)
# ---------------------------------------------------------------------------

BW_MODES = [(BW_OFF, tr("Wyłączony (kolor)")), (BW_BW, tr("Czerń-biel")),
            (BW_SEPIA, tr("Sepia")), (BW_MONO, tr("Monochromia (jeden kolor)"))]

MIX_LABELS = [tr("Czerwone"), tr("Żółte"), tr("Zielone"), tr("Cyjany"),
              tr("Niebieskie"), tr("Magenty")]

BW_FILTERS = [
    ("default", tr("Domyślny"), (40, 60, 40, 60, 20, 80)),
    ("red", tr("Czerwony (ciemne niebo)"), (120, 110, -10, -50, -50, 120)),
    ("orange", tr("Pomarańczowy"), (110, 130, 10, -30, -40, 70)),
    ("yellow", tr("Żółty"), (70, 140, 60, 0, -10, 40)),
    ("green", tr("Zielony"), (-30, 80, 140, 60, -20, -10)),
    ("blue", tr("Niebieski"), (-20, 0, 20, 110, 140, 90)),
    ("contrast", tr("Wysoki kontrast"), (150, 160, -40, -60, -80, 120)),
]

# (nick, etykieta, (hiHue, hiSat, shHue, shSat, balance))
TONING_PRESETS = [
    ("classic", tr("Klasyczny (ciepłe światła, zimne cienie)"), (40, 25, 215, 25, 0)),
    ("teal-orange", tr("Teal & Orange"), (30, 35, 190, 40, 10)),
    ("selenium", tr("Selenowy"), (30, 8, 285, 30, -20)),
    ("gold", tr("Złoty"), (45, 35, 35, 15, 20)),
    ("cold", tr("Chłodny"), (200, 15, 225, 35, -10)),
]

# (nick, etykieta, kolor cieni, kolor świateł, punkt środkowy)
DUOTONE_PRESETS = [
    ("quick", tr("Szybki start"), 0x17213D, 0xF2A65A, 48),
    ("navy-orange", tr("Granatowy / pomarańczowy"), 0x101A3A, 0xFF9A3D, 50),
    ("green-gold", tr("Ciemna zieleń / złoty"), 0x12352B, 0xF2C14E, 50),
    ("purple-pink", tr("Fiolet / róż"), 0x24113F, 0xFF5C8A, 50),
    ("brown-cream", tr("Ciemny brąz / kremowy"), 0x2A1710, 0xF5D6A1, 50),
    ("black-teal", tr("Czarny / turkus"), 0x000000, 0x35D6D0, 50),
]


def hue_color(hue_deg):
    """Kolor czysty o danym odcieniu (HSL: S = 100 %, L = 50 %)."""
    h = math.fmod(float(hue_deg), 360.0)
    if h < 0:
        h += 360.0
    h /= 60.0
    i = int(h)
    f = h - i
    return [(1.0, f, 0.0), (1.0 - f, 1.0, 0.0), (0.0, 1.0, f),
            (0.0, 1.0 - f, 1.0), (f, 0.0, 1.0), (1.0, 0.0, 1.0 - f)][i % 6]


def hex_to_rgb(c):
    return (((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0)


# ---------------------------------------------------------------------------
# Look: komplet ustawień
# ---------------------------------------------------------------------------

class Look:
    """Wszystkie ustawienia wtyczki (odpowiednik FilterParams z wersji .8bf)."""

    def __init__(self):
        self.curves_on = True
        self.luma_only = False
        self.curves = [identity_curve() for _ in range(4)]
        self.bw_mode = BW_OFF
        self.bw_mix = list(DEFAULT_MIX)
        self.tint_hue = SEPIA_HUE
        self.tint_sat = 35
        self.duo_on = False
        self.duo_shadow = 0x17213D
        self.duo_highlight = 0xF2A65A
        self.duo_mid = 48
        self.duo_amount = 100
        self.ton_on = False
        self.hi_hue, self.hi_sat = 40, 0
        self.sh_hue, self.sh_sat = 210, 0
        self.balance = 0
        self.overall = 100

    def copy(self):
        return look_from_text(look_to_text(self))

    # --- moduły ---------------------------------------------------------------

    def reset_curves(self):
        self.curves = [identity_curve() for _ in range(4)]
        self.luma_only = False

    def reset_bw(self):
        d = Look()
        self.bw_mode, self.bw_mix = d.bw_mode, list(d.bw_mix)
        self.tint_hue, self.tint_sat = d.tint_hue, d.tint_sat

    def reset_duotone(self):
        d = Look()
        self.duo_on, self.duo_shadow, self.duo_highlight = d.duo_on, d.duo_shadow, d.duo_highlight
        self.duo_mid, self.duo_amount = d.duo_mid, d.duo_amount

    def reset_toning(self):
        d = Look()
        self.ton_on, self.hi_hue, self.hi_sat = d.ton_on, d.hi_hue, d.hi_sat
        self.sh_hue, self.sh_sat, self.balance = d.sh_hue, d.sh_sat, d.balance

    def apply_curve_preset(self, nick):
        self.curves = [identity_curve() for _ in range(4)]
        for ch, pts in _CURVE_PRESET_POINTS[nick].items():
            self.curves[ch] = sanitize_curve(pts)
        self.curves_on = True

    def apply_bw_filter(self, nick):
        for n, _label, mix in BW_FILTERS:
            if n == nick:
                self.bw_mix = list(mix)

    def apply_toning_preset(self, nick):
        for n, _label, v in TONING_PRESETS:
            if n == nick:
                self.ton_on = True
                self.hi_hue, self.hi_sat, self.sh_hue, self.sh_sat, self.balance = v

    def apply_duotone_preset(self, nick):
        for n, _label, sh, hi, mid in DUOTONE_PRESETS:
            if n == nick:
                self.duo_on = True
                self.duo_shadow, self.duo_highlight, self.duo_mid = sh, hi, mid

    def sanitize(self):
        self.curves_on = bool(self.curves_on)
        self.luma_only = bool(self.luma_only)
        self.curves = [sanitize_curve(c) for c in (list(self.curves) + [identity_curve()] * 4)[:4]]
        self.bw_mode = self.bw_mode if self.bw_mode in (0, 1, 2, 3) else BW_OFF
        self.bw_mix = [_clampi(v, -200, 300) for v in (list(self.bw_mix) + list(DEFAULT_MIX))[:6]]
        self.tint_hue = _clampi(self.tint_hue, 0, 360)
        self.tint_sat = _clampi(self.tint_sat, 0, 100)
        self.duo_on = bool(self.duo_on)
        self.duo_shadow = int(self.duo_shadow) & 0xFFFFFF
        self.duo_highlight = int(self.duo_highlight) & 0xFFFFFF
        self.duo_mid = _clampi(self.duo_mid, 5, 95)
        self.duo_amount = _clampi(self.duo_amount, 0, 100)
        self.ton_on = bool(self.ton_on)
        self.hi_hue, self.sh_hue = _clampi(self.hi_hue, 0, 360), _clampi(self.sh_hue, 0, 360)
        self.hi_sat, self.sh_sat = _clampi(self.hi_sat, 0, 100), _clampi(self.sh_sat, 0, 100)
        self.balance = _clampi(self.balance, -100, 100)
        self.overall = _clampi(self.overall, 0, 100)
        return self

    # --- stan -----------------------------------------------------------------

    def curves_active(self):
        return self.curves_on and not all(is_identity_curve(c) for c in self.curves)

    def bw_active(self):
        return self.bw_mode in (BW_BW, BW_SEPIA, BW_MONO)

    def duotone_active(self):
        return self.duo_on and self.duo_amount > 0

    def toning_active(self):
        return self.ton_on and (self.hi_sat > 0 or self.sh_sat > 0)

    def is_neutral(self):
        """True, gdy look nie zmienia obrazu."""
        return self.overall == 0 or not (self.curves_active() or self.bw_active()
                                         or self.duotone_active() or self.toning_active())


# --- zapis / odczyt (.zklook, zgodny z wersją .8bf) ------------------------------

def look_to_text(look):
    o = [LOOK_HEADER,
         "curvesOn %d" % (1 if look.curves_on else 0),
         "lumaOnly %d" % (1 if look.luma_only else 0)]
    for ch, c in enumerate(look.curves):
        o.append("curve %d %d %s" % (ch, len(c), " ".join(
            "%d %d" % (round(x * 1e6), round(y * 1e6)) for x, y in c)))
    o.append("bw %d %s %d %d" % (look.bw_mode, " ".join(str(int(v)) for v in look.bw_mix),
                                 look.tint_hue, look.tint_sat))
    o.append("toning %d %d %d %d %d %d" % (1 if look.ton_on else 0, look.hi_hue, look.hi_sat,
                                           look.sh_hue, look.sh_sat, look.balance))
    o.append("duotone %d %d %d %d %d" % (1 if look.duo_on else 0, look.duo_shadow & 0xFFFFFF,
                                         look.duo_highlight & 0xFFFFFF, look.duo_mid,
                                         look.duo_amount))
    # Linie LUT-a zostają (zgodność z wersją .8bf), ale bez pliku LUT-a.
    o.append("lut 100 0")
    o.append("lutpath ")
    o.append("overall %d" % look.overall)
    return "\n".join(o) + "\n"


def _ints(rest, lo_count, hi_count):
    parts = rest.split()
    if not lo_count <= len(parts) <= hi_count:
        raise LookError(tr("Zła liczba wartości: %s") % rest)
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise LookError(tr("Oczekiwano liczb całkowitych: %s") % rest)


def look_from_text(text):
    """Look z tekstu .zklook. Rzuca LookError, gdy tekst nie jest lookiem."""
    if isinstance(text, bytes):
        if len(text) > MAX_LOOK_BYTES:
            raise LookError(tr("Plik looku jest za duży."))
        try:
            text = text.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise LookError(tr("Plik looku nie jest tekstem UTF-8."))
    if len(text) > MAX_LOOK_BYTES or "\0" in text:
        raise LookError(tr("To nie jest plik looku Zetmar Kolor."))
    text = text.lstrip("﻿")
    t = Look()
    header = False
    seen = 0
    for line in text.splitlines():
        line = line.rstrip("\r ")
        if not line:
            continue
        if not header:
            if line != LOOK_HEADER:
                raise LookError(tr("To nie jest plik looku Zetmar Kolor."))
            header = True
            continue
        key, _, rest = line.partition(" ")
        if key == "curvesOn":
            t.curves_on = _ints(rest, 1, 1)[0] != 0
        elif key == "lumaOnly":
            t.luma_only = _ints(rest, 1, 1)[0] != 0
        elif key == "curve":
            v = _ints(rest, 2, 2 + 2 * MAX_POINTS)
            if not (0 <= v[0] < 4 and 2 <= v[1] <= MAX_POINTS and len(v) == 2 + 2 * v[1]):
                raise LookError(tr("Niepoprawna krzywa: %s") % rest)
            t.curves[v[0]] = [[v[2 + 2 * i] / 1e6, v[3 + 2 * i] / 1e6] for i in range(v[1])]
            seen += 1
        elif key == "bw":
            v = _ints(rest, 9, 9)
            t.bw_mode, t.bw_mix, t.tint_hue, t.tint_sat = v[0], v[1:7], v[7], v[8]
            seen += 1
        elif key == "toning":
            v = _ints(rest, 6, 6)
            t.ton_on = v[0] != 0
            t.hi_hue, t.hi_sat, t.sh_hue, t.sh_sat, t.balance = v[1:]
            seen += 1
        elif key == "duotone":
            v = _ints(rest, 5, 5)
            t.duo_on, t.duo_shadow, t.duo_highlight = v[0] != 0, v[1], v[2]
            t.duo_mid, t.duo_amount = v[3], v[4]
            seen += 1
        elif key == "overall":
            t.overall = _ints(rest, 1, 1)[0]
        # lut, lutpath i nieznane klucze: pomijane
    if not header or seen == 0:
        raise LookError(tr("To nie jest plik looku Zetmar Kolor."))
    return t.sanitize()


def load_look_file(path):
    try:
        if os.path.getsize(path) > MAX_LOOK_BYTES:
            raise LookError(tr("Plik looku jest za duży."))
        with open(path, "rb") as f:
            return look_from_text(f.read())
    except OSError as e:
        raise LookError(tr("Nie udało się wczytać pliku: %s") % e)


def save_look_file(path, look):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(look_to_text(look))
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Potok przetwarzania
# ---------------------------------------------------------------------------

class Pipeline:
    """Look przygotowany do szybkiego nakładania (tablice krzywych, kolory)."""

    def __init__(self, look):
        look = look.copy()
        self.look = look
        self.tables = [None] * 4
        if look.curves_on:
            self.tables = [curve_table(c) for c in look.curves]
        self.curves = any(t is not None for t in self.tables)
        self.luma_only = look.luma_only
        self.bw = look.bw_active()
        self.mix = [v / 100.0 for v in look.bw_mix]
        self.tint = None
        if look.bw_mode in (BW_SEPIA, BW_MONO):
            hue = SEPIA_HUE if look.bw_mode == BW_SEPIA else look.tint_hue
            self.tint = (hue_color(hue), look.tint_sat / 100.0)
        self.duo = look.duotone_active()
        self.duo_c0 = hex_to_rgb(look.duo_shadow)
        self.duo_c1 = hex_to_rgb(look.duo_highlight)
        mid = look.duo_mid / 100.0
        self.duo_exp = None if look.duo_mid == 50 else math.log(0.5) / math.log(mid)
        self.duo_a = look.duo_amount / 100.0
        self.ton = look.toning_active()
        self.split = 0.5 - look.balance / 400.0
        self.hi = (hue_color(look.hi_hue), look.hi_sat / 100.0 * 0.6) if look.hi_sat > 0 else None
        self.sh = (hue_color(look.sh_hue), look.sh_sat / 100.0 * 0.6) if look.sh_sat > 0 else None
        self.overall = look.overall / 100.0
        self.neutral = look.is_neutral()

    # --- czysty Python (wzorzec dla wariantu numpy) -------------------------------

    def bw_gray(self, rgb):
        imax = imin = 0
        for c in (1, 2):
            if rgb[c] > rgb[imax]:
                imax = c
            if rgb[c] < rgb[imin]:
                imin = c
        if imax == imin:
            return rgb[0]
        imid = 3 - imax - imin
        wp = self.mix[(0, 2, 4)[imax]]
        ws = self.mix[_SECONDARY[(1 << imax) | (1 << imid)]]
        return _clamp01(rgb[imin] + (rgb[imid] - rgb[imin]) * ws + (rgb[imax] - rgb[imid]) * wp)

    def pixel(self, src):
        """Jeden piksel RGB (0–1) → wynik (lista 3 wartości)."""
        rgb = [_clamp01(v) for v in src[:3]]
        orig = list(rgb)
        if self.neutral:
            return orig
        t = self.tables
        if self.curves:
            if t[0] is not None:
                if self.luma_only:
                    y = LUMA[0] * rgb[0] + LUMA[1] * rgb[1] + LUMA[2] * rgb[2]
                    dy = _lookup(t[0], y) - y
                    rgb = [_clamp01(v + dy) for v in rgb]
                else:
                    rgb = [_lookup(t[0], v) for v in rgb]
            for c in range(3):
                if t[c + 1] is not None:
                    rgb[c] = _lookup(t[c + 1], rgb[c])
        if self.bw:
            y = self.bw_gray(rgb)
            rgb = [y, y, y]
            if self.tint is not None:
                _tint(self.tint[0], self.tint[1], y, rgb, 1.0)
                rgb = [_clamp01(v) for v in rgb]
        if self.duo:
            g = self.bw_gray(rgb)
            if self.duo_exp is not None and 0.0 < g < 1.0:
                g = g ** self.duo_exp
            rgb = [_clamp01(rgb[k] + (self.duo_c0[k] + (self.duo_c1[k] - self.duo_c0[k]) * g
                                      - rgb[k]) * self.duo_a) for k in range(3)]
        if self.ton:
            y = _clamp01(LUMA[0] * rgb[0] + LUMA[1] * rgb[1] + LUMA[2] * rgb[2])
            wh = _smoothstep(self.split - 0.25, self.split + 0.25, y)
            if self.hi is not None:
                _tint(self.hi[0], self.hi[1], y, rgb, wh)
            if self.sh is not None:
                _tint(self.sh[0], self.sh[1], y, rgb, 1.0 - wh)
            rgb = [_clamp01(v) for v in rgb]
        if self.overall < 1.0:
            rgb = [orig[k] + (rgb[k] - orig[k]) * self.overall for k in range(3)]
        return rgb

    # --- numpy ----------------------------------------------------------------------

    def np_bw_gray(self, np, x):
        imax = np.argmax(x, axis=1)
        imin = np.argmin(x, axis=1)
        mx = np.take_along_axis(x, imax[:, None], 1)[:, 0]
        mn = np.take_along_axis(x, imin[:, None], 1)[:, 0]
        imid = np.clip(3 - imax - imin, 0, 2)
        md = np.take_along_axis(x, imid[:, None], 1)[:, 0]
        mix = self.mix
        wp = np.asarray([mix[0], mix[2], mix[4]], dtype=np.float32)[imax]
        sec = np.zeros(8, dtype=np.float32)
        sec[3], sec[6], sec[5] = mix[1], mix[3], mix[5]
        ws = sec[(1 << imax) | (1 << imid)]
        g = np.clip(mn + (md - mn) * ws + (mx - md) * wp, 0.0, 1.0)
        return np.where(imax == imin, x[:, 0], g).astype(np.float32)

    def np_process(self, np, src):
        """Tablica (N, 3) float32 → nowa tablica (N, 3) float32."""
        orig = np.clip(src, 0.0, 1.0).astype(np.float32)
        if self.neutral:
            return orig.copy()
        x = orig.copy()
        luma = np.asarray(LUMA, dtype=np.float32)
        if self.curves:
            grid = np.linspace(0.0, 1.0, TABLE_SIZE, dtype=np.float32)
            t = self.tables
            if t[0] is not None:
                t0 = np.asarray(t[0], dtype=np.float32)
                if self.luma_only:
                    y = x @ luma
                    dy = np.interp(y, grid, t0).astype(np.float32) - y
                    x = np.clip(x + dy[:, None], 0.0, 1.0)
                else:
                    x = np.interp(x, grid, t0).astype(np.float32)
            for c in range(3):
                if t[c + 1] is not None:
                    x[:, c] = np.interp(x[:, c], grid, np.asarray(t[c + 1], dtype=np.float32))
        if self.bw:
            y = self.np_bw_gray(np, x)
            x = np.repeat(y[:, None], 3, axis=1)
            if self.tint is not None:
                _np_tint(np, self.tint[0], self.tint[1], y, x, None)
                np.clip(x, 0.0, 1.0, out=x)
        if self.duo:
            g = self.np_bw_gray(np, x)
            if self.duo_exp is not None:
                inside = (g > 0.0) & (g < 1.0)
                g = np.where(inside, np.power(np.clip(g, 1e-12, 1.0), self.duo_exp), g)
            c0 = np.asarray(self.duo_c0, dtype=np.float32)
            c1 = np.asarray(self.duo_c1, dtype=np.float32)
            d = c0 + (c1 - c0) * g[:, None].astype(np.float32)
            x = np.clip(x + (d - x) * np.float32(self.duo_a), 0.0, 1.0)
        if self.ton:
            y = np.clip(x @ luma, 0.0, 1.0)
            e0, e1 = self.split - 0.25, self.split + 0.25
            s = np.clip((y - e0) / (e1 - e0), 0.0, 1.0)
            wh = s * s * (3.0 - 2.0 * s)
            if self.hi is not None:
                _np_tint(np, self.hi[0], self.hi[1], y, x, wh)
            if self.sh is not None:
                _np_tint(np, self.sh[0], self.sh[1], y, x, 1.0 - wh)
            np.clip(x, 0.0, 1.0, out=x)
        if self.overall < 1.0:
            x = orig + (x - orig) * np.float32(self.overall)
        return x.astype(np.float32)


_SECONDARY = {3: 1, 6: 3, 5: 5}     # R+G → żółte, G+B → cyjany, R+B → magenty


def _smoothstep(e0, e1, x):
    t = _clamp01((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


def _tint(c, amount, y, out, weight):
    """Przesunięcie chromatyczne koloru c, wygaszane ku czerni i bieli (4y(1−y))."""
    yc = LUMA[0] * c[0] + LUMA[1] * c[1] + LUMA[2] * c[2]
    k = amount * 4.0 * y * (1.0 - y) * weight
    for i in range(3):
        out[i] += (c[i] - yc) * k


def _np_tint(np, c, amount, y, x, weight):
    yc = LUMA[0] * c[0] + LUMA[1] * c[1] + LUMA[2] * c[2]
    k = np.float32(amount) * 4.0 * y * (1.0 - y)
    if weight is not None:
        k = k * weight
    x += (np.asarray(c, dtype=np.float32) - np.float32(yc)) * k[:, None].astype(np.float32)


# ---------------------------------------------------------------------------
# numpy (opcjonalnie: system, vendor/ obok wtyczki albo vendor/ wtyczki lut-cube)
# ---------------------------------------------------------------------------

_np = None
_np_checked = False
NUMPY_SOURCE = ""
NUMPY_ERROR = ""


def _vendor_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(here, "vendor"),
            os.path.join(os.path.dirname(here), "lut-cube", "vendor")]


def _vendor_matches(vendor):
    import json
    import sys
    import sysconfig
    try:
        with open(os.path.join(vendor, "VENDOR.json"), encoding="utf-8-sig") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return False
    return (info.get("python") == "%d.%d" % sys.version_info[:2]
            and info.get("ext_suffix") == sysconfig.get_config_var("EXT_SUFFIX"))


def get_numpy(allow=True):
    """Moduł numpy albo None (ZETMAR_KOLOR_NO_NUMPY=1 wymusza czysty Python)."""
    global _np, _np_checked, NUMPY_SOURCE, NUMPY_ERROR
    import sys
    if not allow or os.environ.get("ZETMAR_KOLOR_NO_NUMPY"):
        return None
    if _np_checked:
        return _np
    _np_checked = True
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        import numpy
        _np, NUMPY_SOURCE = numpy, "system"
        return _np
    except ImportError as e:
        NUMPY_ERROR = str(e)
    for vendor in _vendor_dirs():
        if not (os.path.isdir(vendor) and _vendor_matches(vendor)):
            continue
        added = None
        site = os.path.join(vendor, "site-packages")
        try:
            if hasattr(os, "add_dll_directory") and os.path.isdir(os.path.join(vendor, "bin")):
                added = os.add_dll_directory(os.path.join(vendor, "bin"))
            sys.path.insert(0, site)
            import numpy
            _np, NUMPY_SOURCE = numpy, "vendor: %s" % vendor
            return _np
        except Exception as e:  # noqa – każdy błąd = wariant bez numpy
            NUMPY_ERROR = "vendor: %s" % e
            if site in sys.path:
                sys.path.remove(site)
            for name in [m for m in sys.modules if m == "numpy" or m.startswith("numpy.")]:
                del sys.modules[name]
            if added is not None:
                added.close()
    return None


def backend_name(use_numpy=True):
    np = get_numpy(use_numpy)
    if np is not None:
        return "numpy %s" % np.__version__
    return tr("czysty Python (wolniejszy)")


# ---------------------------------------------------------------------------
# Nakładanie na bufory RGBA float32 (z maską zaznaczenia)
# ---------------------------------------------------------------------------

def _decode(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _encode(v):
    if v <= 0.0:
        return 0.0
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055


def _np_decode(np, v):
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _np_encode(np, v):
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1.0 / 2.4) - 0.055)


CHUNK = 1 << 17
_pool = None


def _thread_pool():
    global _pool
    if _pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _pool = ThreadPoolExecutor(max(1, min(8, os.cpu_count() or 2)))
    return _pool


def apply_rgba(pipe, data, mask=None, use_numpy=True):
    """
    Nakłada potok na piksele RGBA float32 (bytes). mask – opcjonalne wagi 0–1
    (float32, po jednej na piksel): miękkie zaznaczenie mieszane w świetle
    liniowym, tak jak GIMP przy scalaniu. Zwraca bytes.
    """
    if len(data) % 16:
        raise ValueError(tr("Dane muszą być RGBA float32 (wielokrotność 16 B)."))
    if mask is not None and len(mask) * 4 != len(data):
        raise ValueError(tr("Maska ma inną liczbę pikseli niż obraz."))
    if pipe.neutral:
        return bytes(data)
    np = get_numpy(use_numpy)
    if np is not None:
        return _apply_numpy(np, pipe, data, mask)
    return _apply_pure(pipe, data, mask)


def _apply_numpy(np, pipe, data, mask):
    px = np.frombuffer(data, dtype=np.float32).reshape(-1, 4).copy()
    m = None if mask is None else np.frombuffer(mask, dtype=np.float32)

    def work(start):
        rgb = px[start:start + CHUNK, :3]
        out = pipe.np_process(np, rgb)
        if m is None:
            rgb[...] = out
            return
        w = m[start:start + CHUNK, None]
        lin = _np_decode(np, rgb)
        mixed = _np_encode(np, lin + w * (_np_decode(np, out) - lin))
        rgb[...] = np.where(w >= 1.0, out, np.where(w <= 0.0, rgb, mixed))

    starts = range(0, len(px), CHUNK)
    if len(starts) > 1:
        list(_thread_pool().map(work, starts))
    elif len(starts):
        work(0)
    return px.tobytes()


def _apply_pure(pipe, data, mask):
    buf = array("f")
    buf.frombytes(bytes(data))
    m = None
    if mask is not None:
        m = array("f")
        m.frombytes(bytes(mask))
    cache = {}
    for i in range(0, len(buf), 4):
        w = 1.0 if m is None else m[i >> 2]
        if w <= 0.0:
            continue
        key = (buf[i], buf[i + 1], buf[i + 2])
        out = cache.get(key)
        if out is None:
            out = pipe.pixel(key)
            if len(cache) < 200000:
                cache[key] = out
        if w >= 1.0:
            buf[i], buf[i + 1], buf[i + 2] = out
        else:
            for c in range(3):
                lin = _decode(_clamp01(buf[i + c]))
                buf[i + c] = _encode(lin + w * (_decode(_clamp01(out[c])) - lin))
    return buf.tobytes()


def to_rgba8(data, use_numpy=True):
    """RGBA float32 → RGBA 8 bit (podgląd)."""
    np = get_numpy(use_numpy)
    if np is not None:
        px = np.frombuffer(data, dtype=np.float32)
        return (np.clip(px, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).tobytes()
    buf = array("f")
    buf.frombytes(bytes(data))
    return bytes(0 if v <= 0.0 else (255 if v >= 1.0 else int(v * 255.0 + 0.5)) for v in buf)


def histograms(data, use_numpy=True):
    """Histogramy 256 przedziałów: [jasność (Rec.709), R, G, B] z RGBA float32."""
    np = get_numpy(use_numpy)
    if np is not None:
        px = np.clip(np.frombuffer(data, dtype=np.float32).reshape(-1, 4)[:, :3], 0.0, 1.0)
        y = px @ np.asarray(LUMA, dtype=np.float32)
        return [np.bincount((v * 255.0 + 0.5).astype(np.int64), minlength=256)[:256].tolist()
                for v in (y, px[:, 0], px[:, 1], px[:, 2])]
    buf = array("f")
    buf.frombytes(bytes(data))
    h = [[0] * 256 for _ in range(4)]
    for i in range(0, len(buf), 4):
        r, g, b = (_clamp01(buf[i + k]) for k in range(3))
        y = LUMA[0] * r + LUMA[1] * g + LUMA[2] * b
        for k, v in enumerate((y, r, g, b)):
            h[k][int(v * 255.0 + 0.5)] += 1
    return h
