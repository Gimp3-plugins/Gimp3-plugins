import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bimp3"))
from bimp_model import new_step, plan_outputs, read_curves, atomic_json
from bimp_lut import read_cube
from bimp_jobs import Job


class RegressionTests(unittest.TestCase):
    def test_mixed_drive_hierarchy(self):
        from pathlib import PureWindowsPath
        from bimp_model import hierarchy_parts

        first, second = PureWindowsPath("C:/photos/a.png"), PureWindowsPath("D:/photos/b.png")
        result = hierarchy_parts([first, second])
        self.assertEqual(str(result[first]), "C")
        self.assertEqual(str(result[second]), "D")

    def test_failed_worker_launch_releases_lock(self):
        from bimp_jobs import Job, Worker

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "in.png"
            source.write_bytes(b"input")
            job = Job.create(
                root / "job", [(source, root / "out/result.png")], [], {"output_directory": str(root / "out")}
            )
            worker = Worker(job, executable=root / "no-such-gimp.exe")
            with self.assertRaises(OSError):
                worker.start()
            self.assertFalse(worker.lock.exists())

    def test_names_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "foto_##_@@.png"
            source.touch()
            self.assertEqual(plan_outputs([source], root / "out", [])[0][1].name, source.name)
            source2 = root / "logo.png"
            source2.touch()
            (root / "out").mkdir()
            asset = root / "out/logo.png"
            asset.touch()
            step = new_step("watermark")
            step["settings"].update(mode=False, image_file=str(asset))
            with self.assertRaisesRegex(ValueError, "zależność"):
                plan_outputs([source2], root / "out", [step])
            self.assertEqual(plan_outputs([source2], root / "out", [], collision="suffix")[0][1].name, "logo_2.png")

    def test_atomic_failure_preserves_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            target.write_text("old")
            with patch("bimp_model.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_json(target, {"new": True})
            self.assertEqual(target.read_text(), "old")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_curves_reject_odd_and_unsorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curve.txt"
            for points in ("5 0 0 1 1 0.5", "4 1 1 0 0"):
                path.write_text(f"# GIMP\n(channel value)\n(points {points})\n# end\n")
                with self.assertRaises(ValueError):
                    read_curves(path)

    def test_cube_identity_inversion_domain_and_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.cube"
            path.write_text(
                "LUT_3D_SIZE 2\n" + "\n".join(f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1))
            )
            cube = read_cube(path)
            rgb = (0.23, 0.51, 0.84)
            for a, b in zip(cube.rgb(rgb), rgb):
                self.assertAlmostEqual(a, b)
            raw = array("f", [*rgb, 0.3]).tobytes()
            self.assertEqual(cube.transform(raw, 0), raw)
            for a, b in zip(array("f", cube.transform(raw)), array("f", cube.transform(raw, accelerated=False))):
                self.assertAlmostEqual(a, b, places=5)
            self.assertAlmostEqual(array("f", cube.transform(raw))[3], 0.3)
            path = Path(tmp) / "inverse.cube"
            path.write_text("LUT_1D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\n1 1 1\n0 0 0\n")
            inverse = read_cube(path)
            self.assertEqual(inverse.rgb((0, 1, 2)), (1, 0.5, 0))
            original = array("f", [0, 1, 2, 0.7]).tobytes()
            for a, b in zip(
                array("f", inverse.transform(original, 50)),
                array("f", inverse.transform(original, 50, accelerated=False)),
            ):
                self.assertAlmostEqual(a, b, places=5)

    def test_cube_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, text in enumerate(
                (
                    "LUT_3D_SIZE 1\n",
                    "LUT_3D_SIZE 2\n0 0 0\n",
                    "LUT_1D_SIZE 2\nNaN 0 0\n1 1 1\n",
                    "LUT_1D_SIZE 2\nDOMAIN_MIN 1 1 1\nDOMAIN_MAX 0 0 0\n0 0 0\n1 1 1\n",
                )
            ):
                path = Path(tmp) / f"{i}.cube"
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_cube(path)

    def test_native_matches_reference_nonseparable_cube(self):
        from bimp_lut import Cube, native_module
        import random

        self.assertIsNotNone(native_module())
        random.seed(81)
        table = array("f", [random.uniform(-0.2, 1.3) for _ in range(3**3 * 3)])
        cube = Cube(3, 3, table, [-1, 0, -0.5], [2, 1, 1.5])
        source = array("f", [random.random() for _ in range(400)]).tobytes()
        fast, reference = array("f"), array("f")
        fast.frombytes(cube.transform(source, 37))
        reference.frombytes(cube.transform(source, 37, accelerated=False))
        for i, (a, b) in enumerate(zip(fast, reference)):
            self.assertAlmostEqual(a, b, places=5)
            if i % 4 == 3:
                self.assertEqual(a, array("f", source)[i])

    def test_job_recovery_and_changed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "in.png"
            source.write_bytes(b"input")
            target = root / "out/out.png"
            job = Job.create(root / "job", [(source, target)], [], {"output_directory": str(root / "out")})
            self.assertEqual(job.resume_indices(), [0])
            job.emit({"kind": "entry", "index": 0, "result": {"status": "running"}})
            restored = Job(job.path)
            self.assertEqual(restored.resume_indices(), [0])
            source.write_bytes(b"changed input")
            with self.assertRaises(ValueError):
                restored.resume_indices()


if __name__ == "__main__":
    unittest.main()
