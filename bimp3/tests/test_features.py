"""History/cleanup, profile pool and translations; standard unittest, no GIMP needed."""

import ast
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bimp3"))
os.environ.setdefault("BIMP_LANG", "pl")
import bimp_i18n  # noqa: E402
from bimp_history import clean_previews, delete_job, list_jobs, prune_jobs  # noqa: E402
from bimp_jobs import FileLock, Job, acquire_profile, new_job_directory  # noqa: E402
from bimp_model import SCHEMAS  # noqa: E402
from bimp_presets import PROFILES  # noqa: E402

BIMP3 = Path(__file__).resolve().parents[1] / "bimp3"


def make_job(home, source):
    return Job.create(new_job_directory(home), [(source, home / "out" / "a.png")], [], {"output_directory": str(home / "out")})


class HistoryTests(unittest.TestCase):
    def test_list_delete_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / "a.png"
            source.write_bytes(b"x")
            first = make_job(home, source)
            first.emit({"kind": "entry", "index": 0, "result": {"status": "success"}})
            first.emit({"kind": "finished", "status": "done"})
            time.sleep(1.1)  # job folders are named by the second
            second = make_job(home, source)
            rows = list_jobs(home)
            self.assertEqual([r["directory"] for r in rows], [str(second.directory), str(first.directory)])
            self.assertEqual((rows[1]["status"], rows[1]["counts"]), ("done", {"success": 1}))
            with self.assertRaisesRegex(ValueError, "otwarte"):
                delete_job(second.directory, protected=[second.directory])
            lock = FileLock(second.directory / ".worker.lock")
            self.assertTrue(lock.acquire())
            with self.assertRaisesRegex(ValueError, "trakcie"):
                delete_job(second.directory)
            lock.release()
            with self.assertRaisesRegex(ValueError, "folder zadania"):
                delete_job(home)
            old = time.time() - 40 * 86400
            os.utime(first.directory, (old, old))
            self.assertEqual(prune_jobs(home, 30), 1)
            self.assertFalse(first.directory.exists())
            delete_job(second.directory)
            self.assertEqual(list_jobs(home), [])

    def test_clean_previews_keeps_recent_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            recent = home / "previews" / "queue-1" / "recent"
            stale = home / "previews" / "queue-1" / "stale"
            legacy = home / "previews" / "profile-0123456789"
            for folder in (recent, stale, legacy, home / "previews" / "jobs" / "old"):
                folder.mkdir(parents=True)
            old = time.time() - 3600
            for folder in (stale, legacy, home / "previews" / "jobs" / "old"):
                os.utime(folder, (old, old))
            self.assertEqual(clean_previews(home), 3)
            self.assertTrue(recent.exists())
            self.assertFalse(stale.exists() or legacy.exists())

    def test_profile_pool_reuses_free_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, first_lock = acquire_profile(tmp, "batch")
            second, second_lock = acquire_profile(tmp, "batch")
            self.assertEqual((first.name, second.name), ("batch-1", "batch-2"))
            first_lock.release()
            again, again_lock = acquire_profile(tmp, "batch")
            self.assertEqual(again.name, "batch-1")
            for lock in (second_lock, again_lock):
                lock.release()
            for _number in range(1, 3):
                acquire_profile(tmp, "x", limit=2)
            with self.assertRaisesRegex(RuntimeError, "zajęte"):
                acquire_profile(tmp, "x", limit=2)


class TranslationTests(unittest.TestCase):
    def test_every_interface_string_has_english(self):
        strings = set(PROFILES)
        for label, fields in SCHEMAS.values():
            strings.add(label)
            for field in fields.values():
                strings.add(field[0])
                if len(field) > 2 and isinstance(field[2], list):
                    strings.update(x for x in field[2] if not re.fullmatch(r"[a-z0-9]+|\d+:\d+|\d+°", x))
        for path in BIMP3.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_" and node.args:
                    if isinstance(node.args[0], ast.Constant):
                        strings.add(node.args[0].value)
        missing = sorted(s for s in strings if s not in bimp_i18n.EN and s not in ("PO",))
        self.assertEqual(missing, [])
        for polish, english in bimp_i18n.EN.items():
            self.assertEqual(set(re.findall(r"\{\w+\}", polish)), set(re.findall(r"\{\w+\}", english)), polish)

    def test_language_switch_and_messages(self):
        try:
            bimp_i18n.set_language("en")
            self.assertEqual(bimp_i18n._("Uruchom"), "Run")
            self.assertEqual(bimp_i18n.status_label("success"), "saved")
            self.assertEqual(
                bimp_i18n.translate_message("Nie znaleziono pliku LUT: C:/a.cube\nWybierz katalog wyników."),
                "LUT file not found: C:/a.cube\nChoose an output folder.",
            )
            self.assertEqual(bimp_i18n._("Tekst bez tłumaczenia"), "Tekst bez tłumaczenia")
            bimp_i18n.set_language("pl")
            self.assertEqual(bimp_i18n._("Uruchom"), "Uruchom")
            self.assertEqual(bimp_i18n.status_label("success"), "zapisano")
        finally:
            bimp_i18n.set_language(bimp_i18n.preferred_language())

    def test_preference_file_selects_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferences = Path(tmp) / "preferences.json"
            preferences.write_text('{"language": "en"}', encoding="utf-8")
            forced = os.environ.pop("BIMP_LANG", None)
            try:
                self.assertEqual(bimp_i18n.preferred_language(preferences), "en")
            finally:
                if forced is not None:
                    os.environ["BIMP_LANG"] = forced
            self.assertEqual(bimp_i18n.preferred_language(preferences), os.environ.get("BIMP_LANG", "en"))


if __name__ == "__main__":
    unittest.main()
