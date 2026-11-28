"""Mask mathematics, independent of GIMP. SPDX-License-Identifier: MIT."""
from array import array
from dataclasses import dataclass
import json
import math


@dataclass(frozen=True)
class Settings:
    low: float = 0.5
    high: float = 1.0
    feather: float = 0.25
    invert: bool = False
    color_enabled: bool = False
    red: float = 0.2
    green: float = 0.4
    blue: float = 0.8
    tolerance: float = 0.2
    color_softness: float = 0.15
    selection: bool = True

    def __post_init__(self):
        for name in ('low', 'high', 'feather', 'red', 'green', 'blue',
                     'tolerance', 'color_softness'):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError(f'Nieprawidłowa wartość: {name} (wymagane 0–1).')
        if self.low > self.high:
            raise ValueError('Początek zakresu nie może być większy od końca.')
        for name in ('invert', 'color_enabled', 'selection'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'Nieprawidłowa wartość logiczna: {name}.')


PRESETS = {
    'Światła': (0.5, 1.0, 0.25),
    'Jasne światła': (0.75, 1.0, 0.2),
    'Najjaśniejsze światła': (0.9, 1.0, 0.1),
    'Cienie': (0.0, 0.5, 0.25),
    'Głębokie cienie': (0.0, 0.25, 0.2),
    'Najgłębsze cienie': (0.0, 0.1, 0.1),
    'Półtony': (0.3, 0.7, 0.25),
    'Wszystkie tony / tylko kolor': (0.0, 1.0, 0.0),
}


def smooth(v):
    v = min(1.0, max(0.0, v))
    return v * v * (3 - 2 * v)


def tonal(v, low, high, feather):
    """Plateau [low, high]; feather extends outside it, except at 0 and 1."""
    if not math.isfinite(v):
        return 0.0
    if v < low:
        return smooth((v - low + feather) / feather) if feather else 0.0
    if v > high:
        return smooth((high + feather - v) / feather) if feather else 0.0
    return 1.0


class Engine:
    def __init__(self, settings):
        self.s = settings
        self.lut = [tonal(i / 4096, settings.low, settings.high, settings.feather)
                    for i in range(4097)]

    def mask(self, rgba, selection=None):
        """RGBA perceptual sRGB float bytes -> Y float bytes; native byte order."""
        pixels = array('f')
        pixels.frombytes(bytes(rgba))
        if len(pixels) % 4:
            raise ValueError('Niepełne dane RGBA.')
        selected = None
        if selection is not None and self.s.selection:
            selected = array('f')
            selected.frombytes(bytes(selection))
            if len(selected) != len(pixels) // 4:
                raise ValueError('Rozmiar zaznaczenia nie pasuje do obrazu.')
        s, lut = self.s, self.lut
        out = array('f')
        for n, i in enumerate(range(0, len(pixels), 4)):
            r, g, b, a = pixels[i:i + 4]
            if not all(map(math.isfinite, (r, g, b, a))) or a <= 0:
                out.append(0.0)
                continue
            # Perceptual brightness; HDR values saturate only in the mask calculation.
            r, g, b = min(1., max(0., r)), min(1., max(0., g)), min(1., max(0., b))
            y = 0.2126 * r + 0.7152 * g + 0.0722 * b
            v = lut[min(4096, max(0, round(y * 4096)))]
            if s.color_enabled:
                distance = math.sqrt(((r-s.red)**2 + (g-s.green)**2 + (b-s.blue)**2) / 3)
                c = (1 - smooth((distance-s.tolerance)/s.color_softness)
                     if s.color_softness else float(distance <= s.tolerance))
                v *= c
            if s.invert:
                v = 1 - v
            if selected is not None:
                sv = selected[n]
                v *= min(1., max(0., sv)) if math.isfinite(sv) else 0.
            out.append(v)
        return out.tobytes()


def dumps(settings):
    return json.dumps({'zetmar-maski': 1, 'settings': settings.__dict__}, ensure_ascii=False, indent=2)


def loads(text):
    if len(text) > 16384:
        raise ValueError('Preset jest zbyt duży.')
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('zetmar-maski') != 1 or not isinstance(data.get('settings'), dict):
        raise ValueError('Nieobsługiwany preset Zetmar Maski.')
    return Settings(**data['settings'])
