from array import array
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plug-ins' / 'zetmar-maski'))
from zm_core import Settings, Engine, tonal, dumps, loads


def mask(values, settings=Settings(), selection=None):
    rgba = array('f', (v for pixel in values for v in pixel)).tobytes()
    sel = array('f', selection).tobytes() if selection is not None else None
    out = array('f')
    out.frombytes(Engine(settings).mask(rgba, sel))
    return list(out)


class CoreTests(unittest.TestCase):
    def test_lights_and_shadows(self):
        pixels = [(0, 0, 0, 1), (.5, .5, .5, 1), (1, 1, 1, 1)]
        self.assertEqual(mask(pixels, Settings(feather=0)), [0, 1, 1])
        self.assertEqual(mask(pixels, Settings(low=0, high=.5, feather=0)), [1, 1, 0])

    def test_soft_transition(self):
        self.assertAlmostEqual(tonal(.375, .5, 1, .25), .5)
        self.assertEqual(tonal(.25, .5, 1, .25), 0)
        self.assertEqual(tonal(.5, .5, 1, .25), 1)

    def test_invert_then_selection(self):
        out = mask([(0, 0, 0, 1), (1, 1, 1, 1)], Settings(invert=True), [.25, 1])
        self.assertEqual(out, [.25, 0])

    def test_empty_alpha_is_never_selected(self):
        self.assertEqual(mask([(1, 1, 1, 0)], Settings(invert=True)), [0])

    def test_alpha_is_not_squared(self):
        self.assertEqual(mask([(1, 1, 1, .5)]), [1])

    def test_color_intersection(self):
        out = mask([(1, 0, 0, 1), (0, 0, 1, 1)], Settings(low=0, color_enabled=True, red=1, green=0, blue=0, tolerance=0, color_softness=.1))
        self.assertEqual(out, [1, 0])

    def test_selection_disabled(self):
        self.assertEqual(mask([(1, 1, 1, 1)], Settings(selection=False), [0]), [1])

    def test_nonfinite_pixels(self):
        self.assertEqual(mask([(float('nan'), 1, 1, 1)]), [0])

    def test_hdr_and_negative(self):
        self.assertEqual(mask([(4, 4, 4, 1), (-1, -1, -1, 1)]), [1, 0])

    def test_invalid_settings(self):
        for kwargs in ({'low': .8, 'high': .2}, {'feather': float('nan')}, {'high': float('inf')}, {'low': -1}, {'invert': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Settings(**kwargs)

    def test_preset_roundtrip_and_validation(self):
        settings = Settings(invert=True, color_enabled=True, low=.2)
        self.assertEqual(loads(dumps(settings)), settings)
        for text in ('{}', '{"zetmar-maski":2,"settings":{}}', ' '*17000):
            with self.assertRaises(ValueError):
                loads(text)

    def test_invalid_pixel_lengths(self):
        with self.assertRaises(ValueError):
            Engine(Settings()).mask(array('f', [1]).tobytes())
        with self.assertRaises(ValueError):
            mask([(1, 1, 1, 1)], selection=[1, 1])


if __name__ == '__main__':
    unittest.main()
