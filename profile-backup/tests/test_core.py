# -*- coding: utf-8 -*-
"""pytest suite for the GIMP-independent core (pb_core, pb_i18n)."""

import hashlib
import json
import os
import re
import string
import sys
import threading
import zipfile
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plug-ins" / "profile-backup"
sys.path.insert(0, str(PLUGIN_DIR))

import pb_core as core  # noqa: E402
import pb_i18n as i18n  # noqa: E402

KB = 1024


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------
def make_profile(root: Path) -> Path:
    p = root / "GIMP" / "3.2"
    files = {
        "gimprc": "(language \"pl\")\n",
        "sessionrc": "(session-info)\n" * 50,
        "menurc": "",
        "shortcutsrc": "x" * 3000,
        "plug-ins/my-plugin/my-plugin.py": "#!/usr/bin/env python3\nprint('hi')\n",
        "scripts/test.scm": "(define x 1)",
        "brushes/Zażółć gęślą jaźń.gbr": "ŻÓŁW" * 100,
        "folder ze spacjami/ąę ść plik.txt": "polskie znaki",
        "palettes/deep/a/b/c/palette.gpl": "GIMP Palette\n",
        "tool-options/binary.bin": None,  # random binary
        # excluded:
        "tmp/swap-file": "temporary",
        "plug-ins/my-plugin/__pycache__/x.cpython-312.pyc": "bytecode",
        "some.lock": "lock",
    }
    for rel, content in files.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            f.write_bytes(os.urandom(300 * KB))
        else:
            f.write_text(content, encoding="utf-8")
    (p / "patterns").mkdir()           # empty directory must survive
    (p / "gradients" / "empty-sub").mkdir(parents=True)
    os.utime(p / "gimprc", (1_600_000_000, 1_600_000_000))
    return p


def tree_digest(root: Path) -> dict:
    """{relpath: sha256} for files, {relpath/: 'dir'} for dirs, minus exclusions."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames
                       if not (rel_dir == "" and d in core.EXCLUDE_TOP_DIRS)
                       and d not in core.EXCLUDE_ANY_DIRS]
        for d in dirnames:
            out[(f"{rel_dir}/{d}" if rel_dir else d) + "/"] = "dir"
        for n in filenames:
            if core._excluded_file(n):
                continue
            rel = f"{rel_dir}/{n}" if rel_dir else n
            out[rel] = hashlib.sha256((Path(dirpath) / n).read_bytes()).hexdigest()
    return out


@pytest.fixture
def profile(tmp_path):
    return make_profile(tmp_path / "home")


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------
def test_detect_windows_prefers_newest_series(tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    for v in ("3.0", "3.2", "2.10"):
        (appdata / "GIMP" / v).mkdir(parents=True)
    c = core.detect_profiles(env={"APPDATA": str(appdata)}, system="Windows", home=tmp_path)
    assert [x.path.name for x in c] == ["3.2", "3.0"]
    assert all(x.source == "appdata" for x in c)
    legacy = core.detect_legacy_profiles(env={"APPDATA": str(appdata)}, system="Windows",
                                         home=tmp_path)
    assert [x.name for x in legacy] == ["2.10"]


def test_detect_linux_native_flatpak_snap(tmp_path):
    (tmp_path / ".config" / "GIMP" / "3.0").mkdir(parents=True)
    (tmp_path / ".var/app/org.gimp.GIMP/config/GIMP/3.0").mkdir(parents=True)
    (tmp_path / "snap/gimp/current/.config/GIMP/3.0").mkdir(parents=True)
    c = core.detect_profiles(env={}, system="Linux", home=tmp_path)
    assert [x.source for x in c] == ["xdg", "flatpak", "snap"]


def test_detect_xdg_config_home(tmp_path):
    xdg = tmp_path / "cfg"
    (xdg / "GIMP" / "3.0").mkdir(parents=True)
    c = core.detect_profiles(env={"XDG_CONFIG_HOME": str(xdg)}, system="Linux", home=tmp_path)
    assert c[0].path == xdg / "GIMP" / "3.0"


def test_detect_macos(tmp_path):
    (tmp_path / "Library/Application Support/GIMP/3.0").mkdir(parents=True)
    c = core.detect_profiles(env={}, system="Darwin", home=tmp_path)
    assert c[0].source == "macos"


def test_detect_env_and_gimp_api_take_priority(tmp_path):
    (tmp_path / ".config" / "GIMP" / "3.0").mkdir(parents=True)
    custom = tmp_path / "custom-profile"
    custom.mkdir()
    api = tmp_path / "from-api" / "3.2"
    api.mkdir(parents=True)
    c = core.detect_profiles(gimp_dir=api, env={"GIMP3_DIRECTORY": str(custom)},
                             system="Linux", home=tmp_path)
    assert [x.source for x in c] == ["gimp-api", "env", "xdg"]
    # duplicates are collapsed
    c2 = core.detect_profiles(gimp_dir=custom, env={"GIMP3_DIRECTORY": str(custom)},
                              system="Linux", home=tmp_path)
    assert [x.source for x in c2] == ["gimp-api", "xdg"]


def test_detect_nothing(tmp_path):
    assert core.detect_profiles(env={}, system="Linux", home=tmp_path) == []


def test_settings_live_outside_profile(tmp_path):
    s = core.settings_path(system="Windows", env={"APPDATA": str(tmp_path)}, home=tmp_path)
    assert "GIMP" not in s.parts
    core.save_settings({"dest": "x"}, s)
    assert core.load_settings(s) == {"dest": "x"}


# --------------------------------------------------------------------------
# backup + restore round trip
# --------------------------------------------------------------------------
def test_scan_excludes_tmp_cache_locks(profile):
    s = core.scan_profile(profile)
    rels = {f.rel for f in s.files}
    assert "tmp/swap-file" not in rels
    assert not any("__pycache__" in r for r in rels)
    assert "some.lock" not in rels
    assert "patterns" in s.dirs and "gradients/empty-sub" in s.dirs


def test_backup_and_restore_identical(profile, dest, tmp_path):
    rep = core.create_backup(profile, dest, gimp_version="3.2.0")
    assert rep.archive.exists() and not rep.parts
    assert re.fullmatch(r"GIMP3-profile-\d{8}-\d{6}\.zip", rep.archive.name)
    assert rep.file_count == 10 and not rep.skipped

    with zipfile.ZipFile(rep.archive) as zf:
        names = zf.namelist()
        man = json.loads(zf.read(core.MANIFEST_NAME))
    assert all("\\" not in n and not n.startswith("/") for n in names)
    assert man["gimp_version"] == "3.2.0" and man["file_count"] == 10
    assert all(len(f["sha256"]) == 64 for f in man["files"])

    target = tmp_path / "restored" / "3.2"
    r = core.restore_backup(rep.archive, target)
    assert r.restored == 10 and r.safety_copy is None
    assert tree_digest(target) == tree_digest(profile)
    # mtime kept
    assert int((target / "gimprc").stat().st_mtime) == 1_600_000_000


def test_polish_names_and_spaces(profile, dest, tmp_path):
    rep = core.create_backup(profile, dest)
    with zipfile.ZipFile(rep.archive) as zf:
        names = zf.namelist()
    assert "brushes/Zażółć gęślą jaźń.gbr" in names
    assert "folder ze spacjami/ąę ść plik.txt" in names
    target = tmp_path / "out dir ąę" / "3.2"
    core.restore_backup(rep.archive, target)
    assert (target / "brushes" / "Zażółć gęślą jaźń.gbr").read_text(encoding="utf-8") == "ŻÓŁW" * 100


def test_backup_reports_unreadable_file(profile, dest, monkeypatch):
    real = core._open_source

    def fake(path):
        if Path(path).name == "menurc":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(core, "_open_source", fake)
    rep = core.create_backup(profile, dest)
    assert ("menurc", "open-error: Permission denied") in rep.skipped
    assert rep.file_count == 9
    with zipfile.ZipFile(rep.archive) as zf:
        man = json.loads(zf.read(core.MANIFEST_NAME))
    assert {"path": "menurc", "reason": "open-error: Permission denied"} in man["skipped"]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinks_not_followed(profile, dest, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, profile / "link-dir")
    os.symlink(outside / "secret.txt", profile / "link-file")
    rep = core.create_backup(profile, dest)
    with zipfile.ZipFile(rep.archive) as zf:
        assert not any("secret" in n or n.startswith("link") for n in zf.namelist())
    assert ("link-dir/", "symlink") in rep.skipped


def test_cancel_removes_partial_output(profile, dest):
    ev = threading.Event()
    calls = []

    def prog(fr, stage, detail=""):
        calls.append(stage)
        if stage == "stage_archiving":
            ev.set()

    with pytest.raises(core.Cancelled):
        core.create_backup(profile, dest, progress=prog, cancel=ev)
    assert not list(dest.glob("GIMP3-profile-*"))


def test_long_paths_backup_restore_merge(tmp_path, dest):
    """Regression: a short root with descendants beyond MAX_PATH (260)."""
    prof = tmp_path / "p" / "3.2"
    deep = prof.joinpath(*(["katalog-z-długą-nazwą-ąę"] * 12))
    os.makedirs(core._lp(deep))
    with open(core._lp(deep / "plik ż.txt"), "w", encoding="utf-8") as f:
        f.write("deep")
    assert len(str(deep / "plik ż.txt")) > 260
    rep = core.create_backup(prof, dest)
    assert rep.file_count == 1 and not rep.skipped
    # restore into a location whose full paths are even longer
    target = tmp_path / ("y" * 40) / "3.2"
    core.restore_backup(rep.archive, target)
    with open(core._lp(target.joinpath(*(["katalog-z-długą-nazwą-ąę"] * 12)) / "plik ż.txt"),
              encoding="utf-8") as f:
        assert f.read() == "deep"
    r = core.restore_backup(rep.archive, target, mode="merge")    # copytree of long tree
    assert r.safety_copy.is_dir()


# --------------------------------------------------------------------------
# multi-part archives
# --------------------------------------------------------------------------
def split_backup(profile, dest):
    return core.create_backup(profile, dest, split_threshold=10 * KB, part_size=64 * KB)


def test_split_and_restore(profile, dest, tmp_path):
    rep = split_backup(profile, dest)
    assert len(rep.parts) >= 3
    assert [p.name for p in rep.parts][0].endswith(".zip.001")
    pm = json.loads(rep.parts_manifest.read_text(encoding="utf-8"))
    assert pm["part_count"] == len(rep.parts)
    assert all(len(p["sha256"]) == 64 for p in pm["parts"])
    # joined parts == a valid zip (what `copy /b` / `cat` would produce)
    joined = tmp_path / "joined.zip"
    joined.write_bytes(b"".join(p.read_bytes() for p in rep.parts))
    assert hashlib.sha256(joined.read_bytes()).hexdigest() == pm["archive_sha256"]
    with zipfile.ZipFile(joined) as zf:
        assert zf.testzip() is None
    # restore from the first part and from the manifest
    for start in (rep.parts[0], rep.parts_manifest):
        target = tmp_path / f"r-{start.suffix}" / "3.2"
        core.restore_backup(start, target)
        assert tree_digest(target) == tree_digest(profile)


def test_small_profile_over_threshold_single_part_becomes_zip(profile, dest):
    rep = core.create_backup(profile, dest, split_threshold=10 * KB, part_size=100 * MB)
    assert rep.parts == [] and rep.archive.suffix == ".zip" and rep.archive.exists()


MB = 1024 * 1024


def test_missing_part_detected(profile, dest):
    rep = split_backup(profile, dest)
    rep.parts[1].unlink()
    with pytest.raises(core.PBError) as e:
        core.open_backup(rep.parts[0])
    assert e.value.key == "err_parts_missing"


def test_missing_part_detected_without_manifest(profile, dest):
    rep = split_backup(profile, dest)
    rep.parts_manifest.unlink()
    rep.parts[1].unlink()
    with pytest.raises(core.PBError) as e:
        core.open_backup(rep.parts[0])
    assert e.value.key == "err_parts_missing"


def test_corrupt_part_detected(profile, dest):
    rep = split_backup(profile, dest)
    data = bytearray(rep.parts[1].read_bytes())
    data[100] ^= 0xFF
    rep.parts[1].write_bytes(bytes(data))
    with pytest.raises(core.PBError) as e:
        core.open_backup(rep.parts[0])
    assert e.value.key == "err_part_corrupt"


def test_corrupt_single_zip_detected(profile, dest, tmp_path):
    rep = core.create_backup(profile, dest)
    data = bytearray(rep.archive.read_bytes())
    # flip bytes in the middle of the data area
    for i in range(2000, 2100):
        data[i] ^= 0x55
    rep.archive.write_bytes(bytes(data))
    with pytest.raises(core.PBError) as e:
        core.restore_backup(rep.archive, tmp_path / "x" / "3.2")
    assert e.value.key in ("err_extract_failed", "err_checksum_mismatch", "err_zip_corrupt")
    assert not (tmp_path / "x" / "3.2").exists()


@pytest.mark.skipif(core.find_7z() is None, reason="7-Zip not installed")
def test_7z_split_roundtrip(profile, dest, tmp_path):
    rep = core.create_backup(profile, dest, split_threshold=10 * KB, part_size=64 * KB,
                             use_7z=True)
    assert rep.method == "7z" and len(rep.parts) >= 2
    target = tmp_path / "r7" / "3.2"
    r = core.restore_backup(rep.parts[0], target)
    assert tree_digest(target) == tree_digest(profile)
    assert not [s for s in r.skipped if s[1] != "not-in-manifest"]


# --------------------------------------------------------------------------
# zip-slip
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", [
    "../../evil.txt", "a/../../evil.txt", "/etc/passwd", "C:/Windows/evil.txt",
    "..\\..\\evil.txt", "", "a/\x00b",
])
def test_safe_target_rejects(tmp_path, name):
    with pytest.raises(core.UnsafePath):
        core.safe_target(tmp_path / "root", name)


def test_safe_target_accepts(tmp_path):
    assert core.safe_target(tmp_path, "a/b/c.txt") == tmp_path / "a" / "b" / "c.txt"
    assert core.safe_target(tmp_path, "./a//b") == tmp_path / "a" / "b"


def test_zip_slip_archive_is_harmless(tmp_path):
    evil = tmp_path / "evil.zip"
    payload = b"pwned"
    man = {
        "format": core.FORMAT_NAME, "format_version": 1, "dirs": [],
        "files": [
            {"path": "../../coś.txt", "size": 5, "sha256": hashlib.sha256(payload).hexdigest()},
            {"path": "ok.txt", "size": 2, "sha256": hashlib.sha256(b"ok").hexdigest()},
        ],
        "total_size": 7, "file_count": 2,
    }
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../coś.txt", payload)
        zf.writestr("../stray.txt", payload)
        zf.writestr("ok.txt", b"ok")
        zf.writestr(core.MANIFEST_NAME, json.dumps(man))
    target = tmp_path / "deep" / "er" / "3.2"
    r = core.restore_backup(evil, target)
    assert r.restored == 1
    assert (target / "ok.txt").read_bytes() == b"ok"
    assert ("../../coś.txt", "unsafe-path") in r.skipped
    assert ("../stray.txt", "unsafe-path") in r.skipped
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p.name in ("coś.txt", "stray.txt")]
    assert written == []


# --------------------------------------------------------------------------
# space / permissions / safety
# --------------------------------------------------------------------------
def test_no_space_clear_error(profile, dest, monkeypatch):
    before = tree_digest(profile)

    class Usage:
        total, used, free = 10 ** 9, 10 ** 9, 1000

    monkeypatch.setattr(core.shutil, "disk_usage", lambda p: Usage)
    with pytest.raises(core.PBError) as e:
        core.create_backup(profile, dest)
    assert e.value.key == "err_no_space"
    assert "free" in e.value.params and "needed" in e.value.params
    assert not list(dest.glob("GIMP3-profile-*"))
    assert tree_digest(profile) == before


def test_destination_not_writable(profile, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    with pytest.raises(core.PBError) as e:
        core.create_backup(profile, blocker / "sub")
    assert e.value.key == "err_dest_not_writable"


def test_destination_inside_profile_refused(profile):
    with pytest.raises(core.PBError) as e:
        core.create_backup(profile, profile / "backups")
    assert e.value.key == "err_dest_inside_profile"
    assert not (profile / "backups").exists()


def test_restore_replace_makes_safety_copy(profile, dest):
    rep = core.create_backup(profile, dest)
    original = tree_digest(profile)
    (profile / "added-later.txt").write_text("new")
    (profile / "gimprc").write_text("changed")
    r = core.restore_backup(rep.archive, profile, mode="replace")
    assert r.safety_copy and r.safety_copy.is_dir()
    assert ".before-restore-" in r.safety_copy.name
    assert (r.safety_copy / "added-later.txt").read_text() == "new"
    assert tree_digest(profile) == original      # replace drops added-later.txt
    assert not list(profile.parent.glob("*.restore-staging-*"))


def test_restore_merge_keeps_extra_files(profile, dest):
    rep = core.create_backup(profile, dest)
    (profile / "added-later.txt").write_text("new")
    (profile / "gimprc").write_text("changed")
    r = core.restore_backup(rep.archive, profile, mode="merge")
    assert (profile / "added-later.txt").read_text() == "new"
    assert (profile / "gimprc").read_text(encoding="utf-8") == "(language \"pl\")\n"
    assert (r.safety_copy / "gimprc").read_text() == "changed"


def test_failed_replace_rolls_back(profile, dest, monkeypatch):
    rep = core.create_backup(profile, dest)
    (profile / "marker").write_text("original")
    before = tree_digest(profile)
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 2:          # staging -> profile
            raise PermissionError(13, "denied")
        return real(a, b)

    monkeypatch.setattr(core.os, "replace", flaky)
    with pytest.raises(core.PBError) as e:
        core.restore_backup(rep.archive, profile)
    assert e.value.key == "err_apply_failed"
    monkeypatch.setattr(core.os, "replace", real)
    assert tree_digest(profile) == before
    assert not list(profile.parent.glob("*.restore-staging-*"))


def test_failed_merge_rolls_back(profile, dest, monkeypatch):
    rep = core.create_backup(profile, dest)
    (profile / "gimprc").write_text("local change")
    before = tree_digest(profile)
    n = {"i": 0}
    real = core._merge_copy

    def flaky(a, b):
        n["i"] += 1
        if n["i"] == 3:
            raise OSError(28, "No space left on device")
        return real(a, b)

    monkeypatch.setattr(core, "_merge_copy", flaky)
    with pytest.raises(core.PBError) as e:
        core.restore_backup(rep.archive, profile, mode="merge")
    assert e.value.key == "err_apply_failed"
    assert tree_digest(profile) == before


def test_restore_no_space(profile, dest, tmp_path, monkeypatch):
    rep = core.create_backup(profile, dest)

    class Usage:
        total, used, free = 10 ** 9, 10 ** 9, 10

    monkeypatch.setattr(core.shutil, "disk_usage", lambda p: Usage)
    with pytest.raises(core.PBError) as e:
        core.restore_backup(rep.archive, profile)
    assert e.value.key == "err_no_space"
    assert (profile / "gimprc").exists()


# --------------------------------------------------------------------------
# restore prepared inside GIMP, applied after exit
# --------------------------------------------------------------------------
def test_pending_restore_then_apply(profile, dest):
    rep = core.create_backup(profile, dest)
    original = tree_digest(profile)
    (profile / "gimprc").write_text("live")
    live = tree_digest(profile)
    r = core.prepare_pending_restore(rep.archive, profile)
    assert tree_digest(profile) == live           # live profile untouched
    assert r.pending_file.exists() and r.staging.is_dir()
    res = core.apply_pending(r.pending_file)
    assert res["ok"] and Path(res["safety"]).is_dir()
    assert tree_digest(profile) == original
    assert not r.pending_file.exists()
    shown = core.pop_restore_result(profile)
    assert shown["ok"] and core.pop_restore_result(profile) is None


def test_cancel_pending(profile, dest):
    rep = core.create_backup(profile, dest)
    r = core.prepare_pending_restore(rep.archive, profile)
    assert core.cancel_pending(profile)
    assert not r.staging.exists() and not r.pending_file.exists()


def test_wait_for_pid_of_finished_process():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert core.wait_for_pid(p.pid, timeout=5)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def test_cli_backup_verify_restore(profile, dest, tmp_path, capsys):
    assert core._cli(["--lang", "en", "backup", "--profile", str(profile),
                      "--dest", str(dest)]) == 0
    zips = list(dest.glob("*.zip"))
    assert len(zips) == 1
    assert core._cli(["--lang", "pl", "verify", str(zips[0])]) == 0
    assert "sumy kontrolne się zgadzają" in capsys.readouterr().out
    target = tmp_path / "cli" / "3.2"
    assert core._cli(["restore", str(zips[0]), "--profile", str(target), "--yes"]) == 0
    assert tree_digest(target) == tree_digest(profile)


def test_cli_error_is_translated(tmp_path, capsys):
    assert core._cli(["--lang", "pl", "verify", str(tmp_path / "nope.txt")]) == 1
    assert "To nie jest kopia" in capsys.readouterr().err


# --------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------
def test_every_key_has_pl_and_en():
    for key, entry in i18n.STRINGS.items():
        assert set(entry) == {"pl", "en"}, key
        assert entry["pl"].strip() and entry["en"].strip(), key


def test_placeholders_match_between_languages():
    fmt = string.Formatter()
    for key, entry in i18n.STRINGS.items():
        names = [{f for _, f, _, _ in fmt.parse(entry[lang]) if f} for lang in ("pl", "en")]
        assert names[0] == names[1], key


KEY_RE = re.compile(r"""["']((?:err|stage|report|lbl|btn|ask|mode|menu|doc|title|reason|info|"""
                    r"""summary|verify|warn|confirm|dlg|filter)_[a-z0-9_]+)["']""")


def test_all_keys_used_in_code_exist():
    used = set()
    for f in PLUGIN_DIR.glob("*.py"):
        if f.name == "pb_i18n.py":
            continue
        used |= set(KEY_RE.findall(f.read_text(encoding="utf-8")))
    missing = sorted(k for k in used if k not in i18n.STRINGS)
    assert not missing, missing


def test_polish_has_diacritics_and_files_are_utf8():
    pl = " ".join(e["pl"] for e in i18n.STRINGS.values())
    assert any(ch in pl for ch in "ąćęłńóśźż")
    for f in list(PLUGIN_DIR.glob("*.py")) + [Path(__file__)]:
        f.read_bytes().decode("utf-8")


def test_reason_text():
    assert i18n.reason_text("open-error: Permission denied", "pl").startswith("nie można otworzyć")
    assert i18n.reason_text("symlink", "en") == "symbolic link (not followed)"


def test_language_detection(tmp_path):
    rc = tmp_path / "gimprc"
    rc.write_text('(language "pl")\n')
    assert i18n.detect_language(rc, env={}, windows_ui=False) == "pl"
    rc.write_text('(language "")\n(prev-language "de")\n')
    assert i18n.detect_language(rc, env={"LANG": "pl_PL.UTF-8"}, windows_ui=False) == "pl"
    assert i18n.detect_language(rc, env={"LANG": "de_DE.UTF-8"}, windows_ui=False) == "en"
    assert i18n.detect_language(None, env={"LANGUAGE": "pl:en"}, windows_ui=False) == "pl"
    assert i18n._from_code("Polish_Poland") == "pl"
