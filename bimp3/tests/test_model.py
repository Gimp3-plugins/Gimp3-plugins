"""Run with Python's standard unittest; no third-party dependencies."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bimp3"))
# Messages are asserted in Polish; the interface language is chosen per user otherwise.
os.environ.setdefault("BIMP_LANG", "pl")
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

    def test_only_shrink_and_orientation_aware_crop(self):
        s = new_step("resize")["settings"]
        s.update(resize_mode_width=1, resize_mode_height=1, new_w_px=1600, new_h_px=1600, no_upscale=True)
        self.assertEqual(resize_geometry(800, 600, s), (800, 600, 800, 600))
        self.assertEqual(resize_geometry(3200, 2400, s), (1600, 1200, 1600, 1200))
        s["stretch_mode"] = 2  # padding keeps the requested canvas, without enlarging the photo
        self.assertEqual(resize_geometry(800, 600, s), (800, 600, 1600, 1600))
        s["stretch_mode"] = 0
        self.assertEqual(resize_geometry(800, 3200, s), (800, 1600, 800, 1600))
        s["no_upscale"] = False
        self.assertEqual(resize_geometry(800, 600, dict(s, stretch_mode=1)), (1600, 1200, 1600, 1200))
        c = new_step("crop")["settings"]
        c.update(ratio=1)  # 3:2
        self.assertEqual(crop_geometry(400, 600, c)[:2], (400, 267))
        c["match_orientation"] = True
        self.assertEqual(crop_geometry(400, 600, c)[:2], (400, 600))
        self.assertEqual(crop_geometry(600, 400, c)[:2], (600, 400))
        c.update(manual=True, new_w=300, new_h=200)
        self.assertEqual(crop_geometry(400, 600, c)[:2], (200, 300))
        # Presets saved before these options existed still validate.
        old = new_step("resize")
        del old["settings"]["no_upscale"]
        self.assertFalse(validate_steps([old])[0]["settings"]["no_upscale"])

    def test_name_tokens_exif_and_size(self):
        import struct
        import zlib
        from bimp_naming import read_image_facts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "Wakacje.png"
            raw = b"".join(b"\0" + b"\0\0\0" * 3 for _ in range(2))
            chunks = [
                (b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 2, 0, 0, 0)),
                (b"IDAT", zlib.compress(raw)),
                (b"IEND", b""),
            ]
            png.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + b"".join(struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d)) for k, d in chunks)
            )
            # JPEG headers only: EXIF (orientation 6, DateTimeOriginal) and SOF0 640x480.
            stamp = b"2021:07:04 10:20:30\0"
            ifd0 = struct.pack("<H", 2) + struct.pack("<HHIHH", 0x0112, 3, 1, 6, 0)
            ifd0 += struct.pack("<HHII", 0x8769, 4, 1, 38) + struct.pack("<I", 0)
            exif_ifd = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, len(stamp), 56) + struct.pack("<I", 0)
            tiff = b"II*\0" + struct.pack("<I", 8) + ifd0 + exif_ifd + stamp
            app1 = b"Exif\0\0" + tiff
            sof = struct.pack(">BHHB", 8, 480, 640, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
            jpeg = root / "IMG_1.jpg"
            jpeg.write_bytes(
                b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
                + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"
            )
            facts = read_image_facts(jpeg)
            self.assertEqual((facts["width"], facts["height"], facts["orientation"]), (480, 640, 6))
            rename = new_step("rename")
            rename["settings"].update(pattern="{exif:%Y-%m-%d}_{n:03}_{name:lower}_{w}x{h}", start=7)
            plans = plan_outputs([jpeg, png], root / "out", [rename])
            self.assertEqual(plans[0][1].name, "2021-07-04_007_img_1_480x640.jpg")
            self.assertEqual(plans[1][1].name.split("_", 1)[1], "008_wakacje_3x2.png")
            for bad in ("{nieznany}", "{name:dziwne}", "foto{", "{w:5}"):
                rename["settings"]["pattern"] = bad
                with self.assertRaises(ValueError):
                    validate_steps([rename])

    def test_variant_planning_and_collisions(self):
        from bimp_model import variant_targets

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "foto.png"
            source.touch()
            thumb = new_step("variant")
            thumb["settings"].update(suffix="_min", format=4)  # FORMATS[3] = jpg
            web = new_step("variant")
            web["settings"].update(suffix="_web", format=0)
            target = plan_outputs([source], root / "out", [thumb, web])[0][1]
            self.assertEqual([p.name for p in variant_targets(target, [thumb, web])], ["foto_min.jpg", "foto_web.png"])
            (root / "out").mkdir()
            (root / "out" / "foto_min.jpg").touch()
            # In suffix mode an existing variant moves the whole group to the next free number.
            target = plan_outputs([source], root / "out", [thumb], collision="suffix")[0][1]
            self.assertEqual(target.name, "foto_2.png")
            duplicate = new_step("variant")
            duplicate["settings"]["suffix"] = "_min"
            with self.assertRaisesRegex(ValueError, "przyrostka"):
                validate_steps([thumb, duplicate])
            # A variant may not overwrite a source photo.
            clash = new_step("variant")
            clash["settings"].update(suffix="_a", format=0)
            (root / "out" / "x_a.png").touch()
            (root / "x.png").touch()
            with self.assertRaisesRegex(ValueError, "wejściowy.*x.png"):
                plan_outputs([root / "x.png", root / "out" / "x_a.png"], root / "out", [clash], collision="error")

    def test_output_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
