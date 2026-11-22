"""Run with Python's standard unittest; no third-party dependencies."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bimp3"))
from bimp_model import (
    new_step,
    validate_steps,
    plan_outputs,
    resize_geometry,
    crop_geometry,
    save_settings,
    load_settings,
    import_legacy,
    read_curves,
)


class ModelTests(unittest.TestCase):
    def test_geometry(self):
        s = new_step("resize")["settings"]
        s.update(resize_mode_width=1, resize_mode_height=1, new_w_px=100, new_h_px=100)
        self.assertEqual(resize_geometry(200, 100, s), (100, 50, 100, 50))
        s["stretch_mode"] = 2
        self.assertEqual(resize_geometry(200, 100, s), (100, 50, 100, 100))
        s["resize_mode_height"] = 2
        self.assertEqual(resize_geometry(200, 100, s), (100, 50, 100, 50))
        c = new_step("crop")["settings"]
        self.assertEqual(crop_geometry(200, 100, c), (100, 100, 50, 0))
        c["start_pos"] = 2
        self.assertEqual(crop_geometry(200, 100, c), (100, 100, 100, 0))

    def test_output_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for folder in ("a", "b"):
                (root / folder).mkdir()
                (root / folder / "żółć.png").touch()
            inputs = [root / "a/żółć.png", root / "b/żółć.png"]
            with self.assertRaisesRegex(ValueError, "tę samą"):
                plan_outputs(inputs, root / "out", [])
            plans = plan_outputs(inputs, root / "out", [], hierarchy=True)
            self.assertEqual(plans[0][1], root / "out/a/żółć.png")
            with self.assertRaisesRegex(ValueError, "wejściowy"):
                plan_outputs(inputs[:1], root / "a", [])
            rename = new_step("rename")
            rename["settings"]["pattern"] = "$$_##_@@"
            plans = plan_outputs(inputs, root / "out", [rename], timestamp="2026")
            self.assertEqual(plans[1][1].name, "żółć_2_2026.png")
            for pattern in ("../escape", "CON", "test.", ""):
                rename["settings"]["pattern"] = pattern
                with self.assertRaises(ValueError):
                    validate_steps([rename])

    def test_settings_roundtrip_and_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zestaw.json"
            steps = [new_step("resize"), new_step("color")]
            save_settings(path, steps)
            self.assertEqual(load_settings(path), steps)
            for bad in (0, -2, float("nan"), "500", True):
                steps[0]["settings"]["new_w_px"] = bad
                with self.assertRaises(ValueError):
                    validate_steps(steps)

    def test_legacy_mapping(self):
        steps = import_legacy(
            "# BIMP 2.6\n[RESIZE]\nnew_w_px=320\nresize_mode_width=1\n[CHANGEFORMAT]\nformat=3\nquality=85\nsubsampling=2\ndct=1\ncomment=\nmarkers=0\n"
        )
        self.assertEqual(steps[0]["settings"]["new_w_px"], 320)
        self.assertEqual(
            steps[1]["settings"]["arguments"], {"quality": 0.85, "sub-sampling": "sub-sampling-1x1", "dct": "fixed"}
        )
        with self.assertRaisesRegex(ValueError, "procedurę GIMP 2"):
            import_legacy("# BIMP 2.6\n[USERDEF0]\nprocedure=plug-in-gauss\n")
        with self.assertRaisesRegex(ValueError, "odpowiednika"):
            import_legacy("# BIMP 2.6\n[CHANGEFORMAT]\nformat=4\nsavegamma=true\n")

    def test_curve_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.txt"
            path.write_text(
                "# GIMP curves tool settings\n(channel value)\n(curve\n (points 6 0 0 0.5 0.7 1 1))\n# end\n",
                encoding="utf-8",
            )
            self.assertEqual(read_curves(path)["value"], [0, 0, 0.5, 0.7, 1, 1])
            path.write_text("# GIMP\n(channel value)\n(points 8 0 0 1 1)", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_curves(path)


if __name__ == "__main__":
    unittest.main()
