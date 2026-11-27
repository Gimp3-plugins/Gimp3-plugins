#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GIMP 3 Profile Backup - core (no GIMP dependency).

Detects the GIMP 3 user profile, backs it up to a ZIP (optionally split into
parts), verifies backups and restores them. Standard library only.

Can be used as a CLI:
    python pb_core.py detect
    python pb_core.py backup [--profile DIR] [--dest DIR]
    python pb_core.py verify ARCHIVE
    python pb_core.py restore ARCHIVE [--profile DIR] [--mode replace|merge] [--yes]
    python pb_core.py apply-pending PENDING_JSON [--wait-pid PID]

The technical log is always in English. Every user-facing message is an i18n
key (see pb_i18n.py); this module never builds UI text itself.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PLUGIN_VERSION = "1.0.0"
FORMAT_NAME = "gimp-profile-backup"
PARTS_FORMAT_NAME = "gimp-profile-backup-parts"
FORMAT_VERSION = 1
MANIFEST_NAME = "backup_manifest.json"
ARCHIVE_PREFIX = "GIMP3-profile-"
LOG_NAME = "gimp-profile-backup.log"
SETTINGS_DIR_NAME = "gimp-profile-backup"

MB = 1024 * 1024
DEFAULT_SPLIT_THRESHOLD = 500 * MB
DEFAULT_PART_SIZE = 200 * MB
CHUNK = 1024 * 1024
SPACE_MARGIN = 20 * MB

# --------------------------------------------------------------------------
# Exclusions - the one place to edit what is NOT backed up.
# --------------------------------------------------------------------------
# Directories excluded only at the top level of the profile.
EXCLUDE_TOP_DIRS = {
    "tmp",            # GIMP temporary files (swap/previews), recreated on start
}
# Directory names excluded at any depth.
EXCLUDE_ANY_DIRS = {
    "__pycache__",    # Python bytecode caches of plug-ins, regenerated
}
# File name patterns (fnmatch, case-insensitive) excluded at any depth.
EXCLUDE_FILE_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*.lock",
    ".lock",
    "lock",
    "*~",             # editor backup files
    ".DS_Store",
    "Thumbs.db",
)

ProgressFn = Callable[[float | None, str, str], None]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class PBError(Exception):
    """User-facing error. `key` is an i18n key, `params` its format args."""

    def __init__(self, key: str, **params):
        self.key = key
        self.params = params
        super().__init__(f"{key} {params}" if params else key)


class Cancelled(PBError):
    def __init__(self):
        super().__init__("err_cancelled")


class UnsafePath(ValueError):
    pass


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
IS_WINDOWS = os.name == "nt"


def _lp(path: Path | str) -> str:
    """Return a path string usable for OS calls. On Windows the long-path
    prefix (\\\\?\\) is ALWAYS added: even a short root can contain files
    whose full path exceeds MAX_PATH (os.walk / copytree descend into them),
    and long-path support is not enabled system-wide by default."""
    s = os.fspath(path)
    if not IS_WINDOWS or s.startswith("\\\\?\\"):
        return s
    s = os.path.abspath(s)
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def _short(e: BaseException, limit: int = 600) -> str:
    """Error text for the UI (shutil.Error can list thousands of files)."""
    if isinstance(e, shutil.Error) and e.args and isinstance(e.args[0], list):
        items = e.args[0]
        first = items[0][-1] if items else ""
        text = f"{len(items)} file(s) failed, first: {first}"
    else:
        text = str(e)
    return text if len(text) <= limit else text[:limit] + " …"


def _noop_progress(fraction, stage, detail=""):
    pass


def _check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def timestamp(now: _dt.datetime | None = None) -> str:
    return (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")


def is_relative_to(child: Path, parent: Path) -> bool:
    """True if `child` is `parent` or lies inside it (after resolving)."""
    try:
        c = Path(os.path.normcase(os.path.realpath(child)))
        p = Path(os.path.normcase(os.path.realpath(parent)))
    except OSError:
        return False
    return c == p or p in c.parents


def sha256_file(path: Path, cancel=None) -> str:
    h = hashlib.sha256()
    with open(_lp(path), "rb") as f:
        while True:
            _check_cancel(cancel)
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def get_logger(log_dir: Path | None = None) -> logging.Logger:
    """English technical log; a file in `log_dir` if given."""
    log = logging.getLogger("gimp_profile_backup")
    log.setLevel(logging.INFO)
    if log_dir is not None:
        target = os.path.abspath(os.path.join(os.fspath(log_dir), LOG_NAME))
        have = any(isinstance(h, logging.FileHandler) and
                   getattr(h, "baseFilename", None) == target for h in log.handlers)
        if not have:
            try:
                Path(log_dir).mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(target, encoding="utf-8")
                fh.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)s %(message)s"))
                log.addHandler(fh)
            except OSError:
                pass
    return log


# --------------------------------------------------------------------------
# 1. Profile detection
# --------------------------------------------------------------------------
@dataclass
class Candidate:
    path: Path
    source: str        # gimp-api | env | appdata | xdg | flatpak | snap | macos | manual
    series: str        # e.g. "3.0", "3.2"

    def to_dict(self):
        return {"path": str(self.path), "source": self.source, "series": self.series}


_SERIES_RE = re.compile(r"^3\.(\d+)$")


def _system_name(system: str | None) -> str:
    s = (system or platform.system()).lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin" or s.startswith("mac"):
        return "darwin"
    return "linux"


def _gimp_bases(system: str, env: dict, home: Path) -> list[tuple[str, Path]]:
    """(source, '<...>/GIMP' directory) pairs to search for 3.x profiles."""
    bases: list[tuple[str, Path]] = []
    if system == "windows":
        appdata = env.get("APPDATA") or str(home / "AppData" / "Roaming")
        bases.append(("appdata", Path(appdata) / "GIMP"))
    elif system == "darwin":
        bases.append(("macos", home / "Library" / "Application Support" / "GIMP"))
    else:
        xdg = env.get("XDG_CONFIG_HOME") or str(home / ".config")
        bases.append(("xdg", Path(xdg) / "GIMP"))
        if Path(xdg) != home / ".config":
            bases.append(("xdg", home / ".config" / "GIMP"))
        bases.append(("flatpak", home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP"))
        bases.append(("snap", home / "snap" / "gimp" / "current" / ".config" / "GIMP"))
    return bases


def _series_dirs(base: Path) -> list[Path]:
    try:
        items = [p for p in base.iterdir() if p.is_dir() and _SERIES_RE.match(p.name)]
    except OSError:
        return []
    return sorted(items, key=lambda p: int(_SERIES_RE.match(p.name).group(1)), reverse=True)


def detect_profiles(*, gimp_dir: str | Path | None = None, env: dict | None = None,
                    system: str | None = None, home: Path | None = None) -> list[Candidate]:
    """Return GIMP 3 profile candidates, most trustworthy first.

    gimp_dir: value of Gimp.directory() when running inside GIMP.
    env/system/home: injectable for tests (default: the real ones).
    """
    env = dict(os.environ) if env is None else env
    system = _system_name(system)
    home = Path(home) if home is not None else Path.home()
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(path: Path, source: str):
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return
        seen.add(key)
        m = _SERIES_RE.match(path.name)
        out.append(Candidate(Path(path), source, m.group(0) if m else "3.x"))

    if gimp_dir:
        add(Path(gimp_dir), "gimp-api")
    env_dir = env.get("GIMP3_DIRECTORY")
    if env_dir and Path(env_dir).is_dir():
        add(Path(env_dir), "env")
    for source, base in _gimp_bases(system, env, home):
        for d in _series_dirs(base):
            add(d, source)
    return out


def detect_legacy_profiles(*, env=None, system=None, home=None) -> list[Path]:
    """GIMP 2.x profiles (informational only - never mixed with 3.x)."""
    env = dict(os.environ) if env is None else env
    system = _system_name(system)
    home = Path(home) if home is not None else Path.home()
    found = []
    for _, base in _gimp_bases(system, env, home):
        for name in ("2.10", "2.8"):
            p = base / name
            if p.is_dir():
                found.append(p)
    if system != "windows":
        p = home / ".gimp-2.8"
        if p.is_dir():
            found.append(p)
    return found


def default_backup_dir(system: str | None = None, home: Path | None = None) -> Path:
    system = _system_name(system)
    home = Path(home) if home is not None else Path.home()
    if system == "windows":
        docs = _windows_documents_dir() if home == Path.home() else None
        return Path(docs or (home / "Documents")) / "GIMP-Backups"
    return home / "GIMP-Backups"


def _windows_documents_dir() -> str | None:
    """Real 'Documents' folder (may be redirected, e.g. to OneDrive)."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                   (wintypes.BYTE * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        ptr = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                       ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0:
            value = ptr.value
            ctypes.windll.ole32.CoTaskMemFree(ptr)
            return value
    except Exception:
        pass
    return None


def settings_path(system: str | None = None, env: dict | None = None,
                  home: Path | None = None) -> Path:
    """Small settings file, deliberately OUTSIDE the GIMP profile."""
    env = dict(os.environ) if env is None else env
    system = _system_name(system)
    home = Path(home) if home is not None else Path.home()
    if system == "windows":
        base = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    elif system == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    return base / SETTINGS_DIR_NAME / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    path = path or settings_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        get_logger().warning("Could not save settings to %s", path)


# --------------------------------------------------------------------------
# 2. Scanning
# --------------------------------------------------------------------------
@dataclass
class FileEntry:
    rel: str             # relative path, '/' separators
    path: Path
    size: int
    mtime_ns: int
    mode: int


@dataclass
class ScanResult:
    root: Path
    files: list[FileEntry] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (rel, reason)
    excluded: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


def _excluded_file(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, g.lower()) for g in EXCLUDE_FILE_GLOBS)


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def scan_profile(root: Path, cancel=None) -> ScanResult:
    root = Path(root)
    if not root.is_dir():
        raise PBError("err_profile_missing", path=str(root))
    res = ScanResult(root=root)
    root_s = _lp(root)
    for dirpath, dirnames, filenames in os.walk(root_s, followlinks=False):
        _check_cancel(cancel)
        rel_dir = os.path.relpath(dirpath, root_s)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            full = os.path.join(dirpath, d)
            if (not rel_dir and d in EXCLUDE_TOP_DIRS) or d in EXCLUDE_ANY_DIRS:
                res.excluded.append(rel + "/")
                continue
            if _is_link(full):
                res.skipped.append((rel + "/", "symlink"))
                continue
            keep.append(d)
            res.dirs.append(rel)
        dirnames[:] = keep
        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}" if rel_dir else name
            full = os.path.join(dirpath, name)
            if not rel_dir and name == MANIFEST_NAME:
                res.skipped.append((rel, "reserved-name"))
                continue
            if _excluded_file(name):
                res.excluded.append(rel)
                continue
            if _is_link(full):
                res.skipped.append((rel, "symlink"))
                continue
            try:
                st = os.stat(full)
            except OSError as e:
                res.skipped.append((rel, f"stat-error: {e.strerror or e}"))
                continue
            if not stat.S_ISREG(st.st_mode):
                res.skipped.append((rel, "not-a-regular-file"))
                continue
            res.files.append(FileEntry(rel, Path(full), st.st_size, st.st_mtime_ns,
                                       stat.S_IMODE(st.st_mode)))
    return res


def profile_size(root: Path) -> tuple[int, int]:
    """(file count, total bytes) of what would be backed up."""
    s = scan_profile(root)
    return len(s.files), s.total_size


# --------------------------------------------------------------------------
# Free space
# --------------------------------------------------------------------------
def free_space(path: Path) -> int:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(os.fspath(p)).free


def check_free_space(path: Path, needed: int) -> tuple[bool, int, int]:
    """(enough?, free bytes, needed bytes incl. margin)."""
    needed = int(needed) + SPACE_MARGIN
    try:
        free = free_space(path)
    except OSError:
        return True, -1, needed
    return free >= needed, free, needed


# --------------------------------------------------------------------------
# Multi-part files (plain byte split: name.zip.001, .002, ...)
# --------------------------------------------------------------------------
def part_name(base: Path, index: int) -> Path:
    return Path(f"{base}.{index + 1:03d}")


class SplitWriter(io.RawIOBase):
    """Seekable writable file that spreads its bytes over fixed-size parts.

    Only one part handle is open at a time, so thousands of parts are fine.
    Concatenating the parts yields the exact byte stream written.
    """

    def __init__(self, base: Path, part_size: int):
        super().__init__()
        if part_size < 64 * 1024:
            raise ValueError("part size too small")
        self.base = Path(base)
        self.part_size = int(part_size)
        self.pos = 0
        self.size = 0
        self._idx = -1
        self._fh = None
        self.created: list[Path] = []

    def _select(self, idx: int):
        if idx == self._idx:
            return
        if self._fh is not None:
            self._fh.close()
        p = part_name(self.base, idx)
        if p in self.created:
            self._fh = open(_lp(p), "r+b")
        else:
            # make sure every earlier part exists (they always do when
            # writing sequentially, which is how zipfile writes)
            self._fh = open(_lp(p), "w+b")
            self.created.append(p)
        self._idx = idx

    def writable(self):
        return True

    def seekable(self):
        return True

    def readable(self):
        return False

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            new = offset
        elif whence == io.SEEK_CUR:
            new = self.pos + offset
        elif whence == io.SEEK_END:
            new = self.size + offset
        else:
            raise ValueError("bad whence")
        if new < 0:
            raise ValueError("negative seek")
        self.pos = new
        return self.pos

    def write(self, b):
        mv = memoryview(b).cast("B")
        total = len(mv)
        while mv:
            idx, off = divmod(self.pos, self.part_size)
            self._select(idx)
            self._fh.seek(off)
            n = min(len(mv), self.part_size - off)
            self._fh.write(mv[:n])
            self.pos += n
            mv = mv[n:]
        self.size = max(self.size, self.pos)
        return total

    def flush(self):
        if self._fh is not None:
            self._fh.flush()

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        super().close()


class MultiPartReader(io.RawIOBase):
    """Seekable read-only view over parts, as if they were one file.

    Lets zipfile read a split archive without joining it on disk first.
    """

    def __init__(self, parts: list[Path]):
        super().__init__()
        self.parts = [Path(p) for p in parts]
        self.sizes = [os.path.getsize(_lp(p)) for p in self.parts]
        self.offsets = []
        acc = 0
        for s in self.sizes:
            self.offsets.append(acc)
            acc += s
        self.size = acc
        self.pos = 0
        self._idx = -1
        self._fh = None

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            new = offset
        elif whence == io.SEEK_CUR:
            new = self.pos + offset
        elif whence == io.SEEK_END:
            new = self.size + offset
        else:
            raise ValueError("bad whence")
        if new < 0:
            raise ValueError("negative seek")
        self.pos = new
        return self.pos

    def _locate(self, pos):
        lo, hi = 0, len(self.offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.offsets[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def readinto(self, buf):
        mv = memoryview(buf).cast("B")
        done = 0
        while done < len(mv) and self.pos < self.size:
            idx = self._locate(self.pos)
            if idx != self._idx:
                if self._fh is not None:
                    self._fh.close()
                self._fh = open(_lp(self.parts[idx]), "rb")
                self._idx = idx
            off = self.pos - self.offsets[idx]
            self._fh.seek(off)
            want = min(len(mv) - done, self.sizes[idx] - off)
            n = self._fh.readinto(mv[done:done + want])
            if not n:
                break
            done += n
            self.pos += n
        return done

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        super().close()


# --------------------------------------------------------------------------
# 7-Zip (optional accelerator)
# --------------------------------------------------------------------------
def find_7z() -> str | None:
    for name in ("7zz", "7z", "7za"):
        p = shutil.which(name)
        if p:
            return p
    if IS_WINDOWS:
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                 os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
        for r in roots:
            if r:
                p = Path(r) / "7-Zip" / "7z.exe"
                if p.is_file():
                    return str(p)
    return None


# --------------------------------------------------------------------------
# 3. Backup
# --------------------------------------------------------------------------
@dataclass
class BackupReport:
    archive: Path                    # .zip, or the base name of parts
    parts: list[Path]
    parts_manifest: Path | None
    file_count: int
    dir_count: int
    source_size: int
    archive_size: int
    skipped: list[tuple[str, str]]
    excluded: list[str]
    method: str                      # "python" | "7z"
    seconds: float
    log_path: Path | None

    @property
    def outputs(self) -> list[Path]:
        out = list(self.parts) if self.parts else [self.archive]
        if self.parts_manifest:
            out.append(self.parts_manifest)
        return out


def archive_base_name(now=None) -> str:
    return f"{ARCHIVE_PREFIX}{timestamp(now)}.zip"


def parts_manifest_path(zip_base: Path) -> Path:
    """'X.zip' -> 'X.manifest.json' next to it."""
    name = zip_base.name
    stem = name[:-4] if name.lower().endswith(".zip") else name
    return zip_base.with_name(stem + ".manifest.json")


def _validate_destination(profile: Path, dest: Path):
    if is_relative_to(dest, profile):
        raise PBError("err_dest_inside_profile", dest=str(dest), profile=str(profile))
    try:
        Path(_lp(dest)).mkdir(parents=True, exist_ok=True)
        probe = Path(dest) / f".pb-write-test-{os.getpid()}"
        with open(_lp(probe), "wb") as f:
            f.write(b"x")
        os.remove(_lp(probe))
    except OSError as e:
        raise PBError("err_dest_not_writable", path=str(dest), error=_short(e)) from e


def _open_source(path: Path):
    """Separate function so tests can simulate locked/unreadable files."""
    return open(_lp(path), "rb")


def _base_manifest(profile: Path, gimp_version: str | None, now: _dt.datetime) -> dict:
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "gimp_version": gimp_version or "unknown",
        "profile_series": profile.name,
        "system": platform.system(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "created": now.astimezone().isoformat(timespec="seconds"),
        "source_path": str(profile),
        "exclusions": {
            "top_dirs": sorted(EXCLUDE_TOP_DIRS),
            "any_dirs": sorted(EXCLUDE_ANY_DIRS),
            "file_globs": list(EXCLUDE_FILE_GLOBS),
        },
    }


def create_backup(profile: Path, dest_dir: Path, *,
                  split_threshold: int = DEFAULT_SPLIT_THRESHOLD,
                  part_size: int = DEFAULT_PART_SIZE,
                  use_7z: bool = False,
                  seven_zip: str | None = None,
                  gimp_version: str | None = None,
                  ignore_space: bool = False,
                  progress: ProgressFn | None = None,
                  cancel: threading.Event | None = None,
                  now: _dt.datetime | None = None,
                  log: logging.Logger | None = None) -> BackupReport:
    progress = progress or _noop_progress
    profile = Path(profile)
    dest_dir = Path(dest_dir)
    now = now or _dt.datetime.now()
    t0 = time.monotonic()

    if not profile.is_dir():
        raise PBError("err_profile_missing", path=str(profile))
    _validate_destination(profile, dest_dir)
    log = log or get_logger(dest_dir)
    log.info("Backup start: profile=%s dest=%s", profile, dest_dir)

    progress(None, "stage_scanning", str(profile))
    scan = scan_profile(profile, cancel)
    total = scan.total_size
    split = total > split_threshold
    log.info("Scanned %d files, %d dirs, %d bytes; split=%s", len(scan.files),
             len(scan.dirs), total, split)

    ok, free, needed = check_free_space(dest_dir, total)
    if not ok and not ignore_space:
        raise PBError("err_no_space", path=str(dest_dir), free=human_size(free),
                      needed=human_size(needed))

    archive = dest_dir / archive_base_name(now)
    if archive.exists() or part_name(archive, 0).exists():
        raise PBError("err_output_exists", path=str(archive))

    seven = None
    if use_7z:
        seven = seven_zip or find_7z()
        if not seven:
            log.warning("7z requested but not found - using Python zipfile")

    manifest = _base_manifest(profile, gimp_version, now)
    manifest["split"] = {"enabled": split, "part_size": part_size if split else None,
                         "method": "7z" if seven else "python"}
    if split:
        manifest["parts_info"] = (f"Part list and SHA-256 of parts: "
                                  f"{parts_manifest_path(archive).name}")

    try:
        if seven:
            files, skipped = _backup_with_7z(seven, scan, archive, split, part_size,
                                             manifest, progress, cancel, log)
        else:
            files, skipped = _backup_with_zipfile(scan, archive, split, part_size,
                                                  manifest, progress, cancel, log)
    except BaseException:
        _remove_outputs(archive)
        log.info("Backup aborted, partial output removed")
        raise

    # Collect resulting files
    parts = []
    i = 0
    while part_name(archive, i).exists():
        parts.append(part_name(archive, i))
        i += 1
    pm = None
    if len(parts) == 1:
        os.replace(_lp(parts[0]), _lp(archive))
        parts = []
    if parts:
        progress(None, "stage_hashing_parts", "")
        pm = _write_parts_manifest(archive, parts, manifest, len(files), total, cancel)

    archive_size = sum(os.path.getsize(_lp(p)) for p in (parts or [archive]))
    rep = BackupReport(
        archive=archive, parts=parts, parts_manifest=pm, file_count=len(files),
        dir_count=len(scan.dirs), source_size=total, archive_size=archive_size,
        skipped=skipped, excluded=scan.excluded, method="7z" if seven else "python",
        seconds=time.monotonic() - t0, log_path=dest_dir / LOG_NAME)
    log.info("Backup done: %s (%d parts), %d files, %d bytes -> %d bytes, %d skipped",
             archive, len(parts), rep.file_count, total, archive_size, len(skipped))
    for rel, reason in skipped:
        log.warning("Skipped %s: %s", rel, reason)
    progress(1.0, "stage_done", "")
    return rep


def _remove_outputs(archive: Path):
    for p in [archive, parts_manifest_path(archive)]:
        try:
            os.remove(_lp(p))
        except OSError:
            pass
    i = 0
    while True:
        p = part_name(archive, i)
        if not p.exists():
            break
        try:
            os.remove(_lp(p))
        except OSError:
            pass
        i += 1


def _backup_with_zipfile(scan, archive, split, part_size, manifest, progress, cancel, log):
    total = max(scan.total_size, 1)
    done = 0
    files_meta = []
    skipped = list(scan.skipped)
    fh = SplitWriter(archive, part_size) if split else open(_lp(archive), "w+b")
    try:
        with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True, strict_timestamps=False) as zf:
            for d in scan.dirs:
                zi = zipfile.ZipInfo(d + "/", (1980, 1, 1, 0, 0, 0))
                zi.external_attr = (0o40755 << 16) | 0x10
                zf.writestr(zi, b"")
            for fe in scan.files:
                _check_cancel(cancel)
                progress(done / total, "stage_archiving", fe.rel)
                try:
                    src = _open_source(fe.path)
                except OSError as e:
                    skipped.append((fe.rel, f"open-error: {e.strerror or e}"))
                    continue
                with src:
                    zi = zipfile.ZipInfo(fe.rel, _zip_date(fe.mtime_ns))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = ((stat.S_IFREG | (fe.mode or 0o644)) & 0xFFFF) << 16
                    h = hashlib.sha256()
                    size = 0
                    try:
                        with zf.open(zi, "w", force_zip64=True) as dst:
                            while True:
                                _check_cancel(cancel)
                                b = src.read(CHUNK)
                                if not b:
                                    break
                                h.update(b)
                                dst.write(b)
                                size += len(b)
                                progress((done + size) / total, "stage_archiving", fe.rel)
                    except OSError as e:
                        # Entry is truncated: leave it out of the manifest so
                        # restore will ignore it.
                        skipped.append((fe.rel, f"read-error: {e.strerror or e}"))
                        done += fe.size
                        continue
                done += fe.size
                files_meta.append({"path": fe.rel, "size": size, "mtime_ns": fe.mtime_ns,
                                   "mode": fe.mode, "sha256": h.hexdigest()})
            _finish_manifest(manifest, scan, files_meta, skipped)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
    finally:
        fh.close()
    return files_meta, skipped


def _zip_date(mtime_ns: int):
    t = time.localtime(mtime_ns / 1e9)
    if t.tm_year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    if t.tm_year > 2107:
        return (2107, 12, 31, 23, 59, 58)
    return t[:6]


def _finish_manifest(manifest, scan, files_meta, skipped):
    manifest["file_count"] = len(files_meta)
    manifest["dir_count"] = len(scan.dirs)
    manifest["total_size"] = sum(f["size"] for f in files_meta)
    manifest["dirs"] = scan.dirs
    manifest["files"] = files_meta
    manifest["skipped"] = [{"path": r, "reason": why} for r, why in skipped]
    manifest["excluded"] = scan.excluded


def _backup_with_7z(seven, scan, archive, split, part_size, manifest, progress, cancel, log):
    """Hash files first (manifest), then let 7-Zip build the (split) ZIP."""
    total = max(scan.total_size, 1)
    done = 0
    files_meta = []
    skipped = list(scan.skipped)
    for fe in scan.files:
        _check_cancel(cancel)
        progress(0.5 * done / total, "stage_hashing", fe.rel)
        try:
            with _open_source(fe.path) as src:
                h = hashlib.sha256()
                size = 0
                while True:
                    _check_cancel(cancel)
                    b = src.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    size += len(b)
        except OSError as e:
            skipped.append((fe.rel, f"read-error: {e.strerror or e}"))
            done += fe.size
            continue
        done += fe.size
        files_meta.append({"path": fe.rel, "size": size, "mtime_ns": fe.mtime_ns,
                           "mode": fe.mode, "sha256": h.hexdigest()})
    _finish_manifest(manifest, scan, files_meta, skipped)

    tmpdir = Path(tempfile.mkdtemp(prefix="pb7z-"))
    try:
        mpath = tmpdir / MANIFEST_NAME
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        listfile = tmpdir / "list.txt"
        # Only files: a directory argument would make 7-Zip recurse into it
        # (including excluded files). Empty dirs are recreated from the
        # manifest's "dirs" list on restore.
        entries = [f["path"] for f in files_meta]
        listfile.write_text("\n".join(e.replace("/", os.sep) for e in entries) + "\n",
                            encoding="utf-8")
        cmd = [seven, "a", "-tzip", "-mx=5", "-mmt=on", "-scsUTF-8", "-spd", "-bsp1",
               "-bso0", "-y"]
        if split:
            cmd.append(f"-v{max(1, part_size // 1024)}k")
        cmd += [str(archive), f"@{listfile}", str(mpath)]
        log.info("Running 7-Zip: %s", " ".join(cmd))
        flags = 0x08000000 if IS_WINDOWS else 0   # CREATE_NO_WINDOW
        # plain path: CreateProcess does not accept a \\?\ working directory
        proc = subprocess.Popen(cmd, cwd=os.fspath(scan.root), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=flags)
        buf = b""
        tail = []
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in (b"\r", b"\n", b"\b"):
                line = buf.decode("utf-8", "replace").strip()
                buf = b""
                m = re.search(r"(\d+)%", line)
                if m:
                    progress(0.5 + 0.5 * int(m.group(1)) / 100, "stage_archiving_7z", "")
                elif line:
                    tail = (tail + [line])[-20:]
            else:
                buf += ch
        rc = proc.wait()
        if rc not in (0, 1):
            raise PBError("err_7z_failed", code=rc, output=" | ".join(tail))
        if rc == 1:
            log.warning("7-Zip finished with warnings: %s", " | ".join(tail))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return files_meta, skipped


def _write_parts_manifest(archive: Path, parts: list[Path], manifest: dict,
                          file_count: int, total: int, cancel) -> Path:
    whole = hashlib.sha256()
    plist = []
    for p in parts:
        h = hashlib.sha256()
        with open(_lp(p), "rb") as f:
            while True:
                _check_cancel(cancel)
                b = f.read(CHUNK)
                if not b:
                    break
                h.update(b)
                whole.update(b)
        plist.append({"name": p.name, "size": os.path.getsize(_lp(p)),
                      "sha256": h.hexdigest()})
    data = {
        "format": PARTS_FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "archive": archive.name,
        "archive_sha256": whole.hexdigest(),
        "archive_size": sum(x["size"] for x in plist),
        "part_count": len(plist),
        "parts": plist,
        "summary": {k: manifest.get(k) for k in
                    ("plugin_version", "gimp_version", "profile_series", "system",
                     "created", "source_path")},
        "file_count": file_count,
        "total_size": total,
        "join_hint": {
            "windows": f'copy /b "{archive.name}.001"+"{archive.name}.002"+... "{archive.name}"',
            "linux": f'cat "{archive.name}".[0-9][0-9][0-9] > "{archive.name}"',
        },
    }
    pm = parts_manifest_path(archive)
    with open(_lp(pm), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return pm


# --------------------------------------------------------------------------
# 4. Opening / verifying a backup
# --------------------------------------------------------------------------
_PART_RE = re.compile(r"^(?P<base>.+\.zip)\.(?P<num>\d{3})$", re.IGNORECASE)


@dataclass
class BackupSource:
    archive: Path                 # logical archive name (X.zip)
    parts: list[Path]             # [] for a single .zip
    parts_manifest: dict | None
    manifest: dict
    zip_entries: list[str]

    @property
    def is_split(self) -> bool:
        return bool(self.parts)

    def open_stream(self):
        if self.parts:
            return MultiPartReader(self.parts)
        return open(_lp(self.archive), "rb")

    @property
    def summary(self) -> dict:
        m = self.manifest
        return {"created": m.get("created"), "gimp_version": m.get("gimp_version"),
                "profile_series": m.get("profile_series"), "system": m.get("system"),
                "file_count": m.get("file_count"), "total_size": m.get("total_size"),
                "source_path": m.get("source_path"), "parts": len(self.parts),
                "plugin_version": m.get("plugin_version")}


def resolve_parts(path: Path) -> tuple[Path, list[Path], dict | None]:
    """From .zip / .zip.001 / .manifest.json find (archive, parts, parts-manifest)."""
    path = Path(path)
    name = path.name
    pm_data = None
    if name.lower().endswith(".manifest.json"):
        try:
            pm_data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PBError("err_manifest_unreadable", path=str(path), error=_short(e)) from e
        if pm_data.get("format") != PARTS_FORMAT_NAME:
            raise PBError("err_not_a_backup", path=str(path))
        archive = path.with_name(pm_data["archive"])
    else:
        m = _PART_RE.match(name)
        if m:
            archive = path.with_name(m.group("base"))
        elif name.lower().endswith(".zip"):
            archive = path
        else:
            raise PBError("err_not_a_backup", path=str(path))
        pm = parts_manifest_path(archive)
        if pm.exists():
            try:
                pm_data = json.loads(pm.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise PBError("err_manifest_unreadable", path=str(pm), error=_short(e)) from e

    if pm_data is not None:
        parts = [archive.with_name(p["name"]) for p in pm_data.get("parts", [])]
        missing = [p.name for p in parts if not p.exists()]
        if missing:
            raise PBError("err_parts_missing", parts=", ".join(missing))
        return archive, parts, pm_data

    if archive.exists() and not part_name(archive, 0).exists():
        return archive, [], None
    # Parts without a manifest: take the consecutive run starting at .001
    parts = []
    i = 0
    while part_name(archive, i).exists():
        parts.append(part_name(archive, i))
        i += 1
    if not parts:
        if archive.exists():
            return archive, [], None
        raise PBError("err_file_missing", path=str(path))
    # detect gaps such as .001 .002 .004
    later = sorted(archive.parent.glob(archive.name + ".[0-9][0-9][0-9]"))
    if len(later) != len(parts):
        raise PBError("err_parts_missing", parts=part_name(archive, len(parts)).name)
    return archive, parts, None


def open_backup(path: Path, *, verify: bool = True, progress: ProgressFn | None = None,
                cancel=None) -> BackupSource:
    progress = progress or _noop_progress
    archive, parts, pm = resolve_parts(Path(path))

    if parts and pm is not None and verify:
        total = max(sum(p.get("size", 0) for p in pm["parts"]), 1)
        done = 0
        for p, meta in zip(parts, pm["parts"]):
            progress(done / total, "stage_verifying_parts", p.name)
            size = os.path.getsize(_lp(p))
            if size != meta.get("size"):
                raise PBError("err_part_corrupt", part=p.name)
            if sha256_file(p, cancel) != meta.get("sha256"):
                raise PBError("err_part_corrupt", part=p.name)
            done += size
    elif parts and pm is None:
        get_logger().warning("No parts manifest for %s - part checksums not verified", archive)

    src = BackupSource(archive, parts, pm, {}, [])
    try:
        with src.open_stream() as fh, zipfile.ZipFile(fh) as zf:
            src.zip_entries = zf.namelist()
            try:
                raw = zf.read(MANIFEST_NAME)
            except KeyError:
                raise PBError("err_not_a_backup", path=str(archive))
            src.manifest = json.loads(raw.decode("utf-8"))
    except zipfile.BadZipFile as e:
        raise PBError("err_zip_corrupt", path=str(archive), error=_short(e)) from e
    except (OSError, ValueError) as e:
        raise PBError("err_zip_corrupt", path=str(archive), error=_short(e)) from e
    if src.manifest.get("format") != FORMAT_NAME:
        raise PBError("err_not_a_backup", path=str(archive))
    return src


# --------------------------------------------------------------------------
# 5. Restore
# --------------------------------------------------------------------------
def safe_target(root: Path, name: str) -> Path:
    """Map an archive entry name to a path inside `root` (zip-slip guard)."""
    if not name or "\x00" in name:
        raise UnsafePath(name)
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        raise UnsafePath(name)
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise UnsafePath(name)
    if IS_WINDOWS and any(":" in p for p in parts):   # NTFS alternate streams
        raise UnsafePath(name)
    target = Path(root).joinpath(*parts)
    r = os.path.normcase(os.path.abspath(root))
    t = os.path.normcase(os.path.abspath(target))
    if not t.startswith(r.rstrip(os.sep) + os.sep):
        raise UnsafePath(name)
    return target


@dataclass
class RestoreReport:
    profile: Path
    restored: int = 0
    dirs: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    safety_copy: Path | None = None
    mode: str = "replace"
    staging: Path | None = None
    pending_file: Path | None = None
    seconds: float = 0.0


def extract_to(src: BackupSource, target_dir: Path, *, progress=None, cancel=None,
               log: logging.Logger | None = None) -> RestoreReport:
    """Extract and verify a backup into `target_dir` (which should be empty)."""
    progress = progress or _noop_progress
    log = log or get_logger()
    target_dir = Path(target_dir)
    Path(_lp(target_dir)).mkdir(parents=True, exist_ok=True)
    rep = RestoreReport(profile=target_dir)
    man = src.manifest
    files = man.get("files", [])
    total = max(sum(int(f.get("size", 0)) for f in files), 1)
    done = 0
    listed = {f["path"] for f in files} | {d + "/" for d in man.get("dirs", [])}
    listed.add(MANIFEST_NAME)

    for entry in src.zip_entries:
        if entry not in listed and entry.rstrip("/") + "/" not in listed:
            try:
                safe_target(target_dir, entry)
                rep.skipped.append((entry, "not-in-manifest"))
            except UnsafePath:
                rep.skipped.append((entry, "unsafe-path"))
                log.warning("Rejected unsafe archive entry: %r", entry)

    for d in man.get("dirs", []):
        try:
            p = safe_target(target_dir, d)
        except UnsafePath:
            rep.skipped.append((d, "unsafe-path"))
            continue
        Path(_lp(p)).mkdir(parents=True, exist_ok=True)
        rep.dirs += 1

    with src.open_stream() as fh, zipfile.ZipFile(fh) as zf:
        names = set(src.zip_entries)
        for f in files:
            _check_cancel(cancel)
            rel = f["path"]
            progress(done / total, "stage_extracting", rel)
            try:
                dst = safe_target(target_dir, rel)
            except UnsafePath:
                rep.skipped.append((rel, "unsafe-path"))
                log.warning("Rejected unsafe manifest path: %r", rel)
                continue
            if rel not in names:
                rep.skipped.append((rel, "missing-in-archive"))
                continue
            Path(_lp(dst.parent)).mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            try:
                with zf.open(rel) as s, open(_lp(dst), "wb") as o:
                    while True:
                        _check_cancel(cancel)
                        b = s.read(CHUNK)
                        if not b:
                            break
                        h.update(b)
                        o.write(b)
            except (zipfile.BadZipFile, OSError) as e:
                raise PBError("err_extract_failed", path=rel, error=_short(e)) from e
            if h.hexdigest() != f.get("sha256"):
                raise PBError("err_checksum_mismatch", path=rel)
            if not IS_WINDOWS and f.get("mode") is not None:
                try:
                    os.chmod(dst, int(f["mode"]) & 0o7777)
                except OSError:
                    pass
            mt = f.get("mtime_ns")
            if mt is not None:
                try:
                    os.utime(_lp(dst), ns=(int(mt), int(mt)))
                except OSError:
                    pass
            rep.restored += 1
            done += int(f.get("size", 0))
    progress(1.0, "stage_extracted", "")
    return rep


def safety_copy_path(profile: Path, now=None) -> Path:
    return profile.with_name(f"{profile.name}.before-restore-{timestamp(now)}")


def staging_path(profile: Path, now=None) -> Path:
    return profile.with_name(f"{profile.name}.restore-staging-{timestamp(now)}")


def pending_file_path(profile: Path) -> Path:
    return profile.with_name(f"{profile.name}.restore-pending.json")


def result_file_path(profile: Path) -> Path:
    return profile.with_name(f"{profile.name}.restore-result.json")


def apply_staged(staging: Path, profile: Path, mode: str, safety: Path,
                 log: logging.Logger | None = None) -> Path | None:
    """Put a fully extracted & verified `staging` tree in place of `profile`.

    replace: profile -> safety (rename), staging -> profile (rename).
    merge:   copy profile -> safety, then copy staged files over the profile.
    On failure the original profile is put back. Returns the safety path
    (None if there was no profile before).
    """
    log = log or get_logger()
    staging, profile, safety = Path(staging), Path(profile), Path(safety)
    if mode not in ("replace", "merge"):
        raise ValueError(mode)
    if not staging.is_dir():
        raise PBError("err_staging_missing", path=str(staging))
    had_profile = profile.exists()

    if mode == "replace" or not had_profile:
        if had_profile:
            try:
                os.replace(_lp(profile), _lp(safety))
            except OSError as e:
                raise PBError("err_profile_in_use", path=str(profile), error=_short(e)) from e
        try:
            os.replace(_lp(staging), _lp(profile))
        except OSError as e:
            if had_profile:
                try:
                    os.replace(_lp(safety), _lp(profile))
                except OSError:
                    log.error("ROLLBACK FAILED - original profile is at %s", safety)
                    raise PBError("err_rollback_failed", safety=str(safety)) from e
            raise PBError("err_apply_failed", error=_short(e)) from e
        log.info("Profile replaced; previous profile moved to %s", safety)
        return safety if had_profile else None

    # merge
    try:
        shutil.copytree(_lp(profile), _lp(safety), symlinks=True)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(_lp(safety), ignore_errors=True)
        raise PBError("err_safety_copy_failed", path=str(safety), error=_short(e)) from e
    try:
        for dirpath, dirnames, filenames in os.walk(_lp(staging)):
            rel = os.path.relpath(dirpath, _lp(staging))
            out_dir = os.path.join(_lp(profile), rel) if rel != "." else _lp(profile)
            os.makedirs(out_dir, exist_ok=True)
            for n in filenames:
                _merge_copy(os.path.join(dirpath, n), os.path.join(out_dir, n))
    except OSError as e:
        failed = profile.with_name(profile.name + ".merge-failed-" + timestamp())
        try:
            os.replace(_lp(profile), _lp(failed))
            os.replace(_lp(safety), _lp(profile))
            shutil.copytree(_lp(profile), _lp(safety), symlinks=True)
        except OSError:
            log.error("ROLLBACK FAILED - original profile copy is at %s", safety)
            raise PBError("err_rollback_failed", safety=str(safety)) from e
        raise PBError("err_apply_failed", error=_short(e)) from e
    shutil.rmtree(_lp(staging), ignore_errors=True)
    log.info("Profile merged; safety copy at %s", safety)
    return safety


def _merge_copy(src: str, dst: str):
    """Separate so tests can inject failures."""
    shutil.copy2(src, dst)


def restore_backup(path: Path, profile: Path, *, mode: str = "replace",
                   progress=None, cancel=None, log=None, now=None) -> RestoreReport:
    """Direct restore - use only while GIMP is NOT running (CLI)."""
    t0 = time.monotonic()
    profile = Path(profile)
    log = log or get_logger(profile.parent)
    src = open_backup(path, progress=progress, cancel=cancel)
    need = int(src.manifest.get("total_size", 0))
    if mode == "merge" and profile.exists():
        need += scan_profile(profile).total_size
    ok, free, needed = check_free_space(profile.parent, need)
    if not ok:
        raise PBError("err_no_space", path=str(profile.parent), free=human_size(free),
                      needed=human_size(needed))
    staging = staging_path(profile, now)
    try:
        rep = extract_to(src, staging, progress=progress, cancel=cancel, log=log)
        safety = apply_staged(staging, profile, mode, safety_copy_path(profile, now), log)
    except BaseException:
        shutil.rmtree(_lp(staging), ignore_errors=True)
        raise
    rep.profile, rep.mode, rep.safety_copy = profile, mode, safety
    rep.seconds = time.monotonic() - t0
    log.info("Restore done: %d files into %s (mode=%s), skipped %d", rep.restored,
             profile, mode, len(rep.skipped))
    return rep


def prepare_pending_restore(path: Path, profile: Path, *, mode: str = "replace",
                            progress=None, cancel=None, log=None, now=None,
                            lang: str = "en") -> RestoreReport:
    """Restore for use INSIDE GIMP: extract & verify next to the profile and
    write a pending-restore file. The live profile is not touched; the swap is
    done by `apply_pending` after GIMP has exited."""
    t0 = time.monotonic()
    profile = Path(profile)
    log = log or get_logger(profile.parent)
    src = open_backup(path, progress=progress, cancel=cancel)
    need = int(src.manifest.get("total_size", 0))
    ok, free, needed = check_free_space(profile.parent, need)
    if not ok:
        raise PBError("err_no_space", path=str(profile.parent), free=human_size(free),
                      needed=human_size(needed))
    cancel_pending(profile)
    staging = staging_path(profile, now)
    try:
        rep = extract_to(src, staging, progress=progress, cancel=cancel, log=log)
    except BaseException:
        shutil.rmtree(_lp(staging), ignore_errors=True)
        raise
    pending = {
        "staging": str(staging), "profile": str(profile), "mode": mode,
        "safety": str(safety_copy_path(profile, now)), "source": str(src.archive),
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": rep.restored, "lang": lang, "plugin_version": PLUGIN_VERSION,
    }
    pf = pending_file_path(profile)
    pf.write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    rep.profile, rep.mode, rep.staging, rep.pending_file = profile, mode, staging, pf
    rep.safety_copy = Path(pending["safety"])
    rep.seconds = time.monotonic() - t0
    log.info("Pending restore prepared: staging=%s pending=%s", staging, pf)
    return rep


def read_pending(profile: Path) -> dict | None:
    pf = pending_file_path(Path(profile))
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cancel_pending(profile: Path) -> bool:
    """Drop a previously prepared (not yet applied) restore."""
    data = read_pending(profile)
    pf = pending_file_path(Path(profile))
    if data is None:
        return False
    st = Path(data.get("staging", ""))
    if st.name.startswith(Path(profile).name + ".restore-staging-"):
        shutil.rmtree(_lp(st), ignore_errors=True)
    try:
        os.remove(_lp(pf))
    except OSError:
        pass
    return True


def wait_for_pid(pid: int, poll: float = 1.0, timeout: float | None = None) -> bool:
    """Block until process `pid` has exited. True if it exited."""
    deadline = None if timeout is None else time.monotonic() + timeout
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
        if not h:
            return True
        try:
            ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
            return k.WaitForSingleObject(h, ms) == 0
        finally:
            k.CloseHandle(h)
    while True:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if deadline is not None and time.monotonic() > deadline:
            return False
        time.sleep(poll)


def apply_pending(pending_file: Path, *, wait_pid: int | None = None,
                  log: logging.Logger | None = None) -> dict:
    """Apply a prepared restore (run after GIMP exits). Writes a result file
    next to the profile that the plug-in shows on its next run."""
    pending_file = Path(pending_file)
    data = json.loads(pending_file.read_text(encoding="utf-8"))
    profile = Path(data["profile"])
    log = log or get_logger(profile.parent)
    if wait_pid:
        log.info("Waiting for GIMP (pid %s) to exit before applying restore", wait_pid)
        wait_for_pid(wait_pid)
        time.sleep(2)
    result = {"ok": False, "profile": str(profile), "mode": data["mode"],
              "safety": None, "files": data.get("files"), "source": data.get("source"),
              "finished": None, "error": None, "error_key": None}
    try:
        safety = apply_staged(Path(data["staging"]), profile, data["mode"],
                              Path(data["safety"]), log)
        result["ok"] = True
        result["safety"] = str(safety) if safety else None
        try:
            os.remove(_lp(pending_file))
        except OSError:
            pass
    except PBError as e:
        result["error"] = str(e)
        result["error_key"] = e.key
        result["error_params"] = e.params
        log.error("Applying pending restore failed: %s", e)
    except Exception as e:     # never die silently in a detached process
        result["error"] = repr(e)
        log.exception("Applying pending restore failed")
    result["finished"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        result_file_path(profile).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    except OSError:
        pass
    return result


def pop_restore_result(profile: Path) -> dict | None:
    rf = result_file_path(Path(profile))
    try:
        data = json.loads(rf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        os.remove(_lp(rf))
    except OSError:
        pass
    return data


def spawn_apply_helper(pending_file: Path, wait_pid: int,
                       python_exe: str | None = None) -> subprocess.Popen:
    """Start a detached process that applies the restore once GIMP exits."""
    exe = python_exe or sys.executable
    if IS_WINDOWS:
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            exe = str(w)
    cmd = [exe, str(Path(__file__).resolve()), "apply-pending", str(pending_file),
           "--wait-pid", str(int(wait_pid))]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    if IS_WINDOWS:
        base = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED|NEW_GROUP|NO_WINDOW
        try:
            return subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)  # BREAKAWAY
        except OSError:
            return subprocess.Popen(cmd, creationflags=base, **kw)
    return subprocess.Popen(cmd, start_new_session=True, **kw)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _cli(argv=None) -> int:
    import argparse
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pb_i18n import tr, detect_language, reason_text

    p = argparse.ArgumentParser(prog="pb_core.py",
                                description="GIMP 3 profile backup / restore")
    p.add_argument("--lang", choices=["pl", "en"], default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("detect")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("backup")
    sp.add_argument("--profile")
    sp.add_argument("--dest")
    sp.add_argument("--threshold-mb", type=int, default=DEFAULT_SPLIT_THRESHOLD // MB)
    sp.add_argument("--part-mb", type=int, default=DEFAULT_PART_SIZE // MB)
    sp.add_argument("--use-7z", action="store_true")
    sp = sub.add_parser("verify")
    sp.add_argument("archive")
    sp = sub.add_parser("restore")
    sp.add_argument("archive")
    sp.add_argument("--profile")
    sp.add_argument("--mode", choices=["replace", "merge"], default="replace")
    sp.add_argument("--yes", action="store_true")
    sp = sub.add_parser("apply-pending")
    sp.add_argument("pending")
    sp.add_argument("--wait-pid", type=int)
    a = p.parse_args(argv)
    lang = a.lang or detect_language()

    def say(key, **kw):
        print(tr(key, lang, **kw))

    def prog(fraction, stage, detail=""):
        if fraction is not None:
            sys.stderr.write(f"\r{fraction * 100:5.1f}%  {tr(stage, lang)}"[:110].ljust(110))
            sys.stderr.flush()

    def pick_profile(explicit):
        if explicit:
            return Path(explicit)
        c = detect_profiles()
        if not c:
            raise PBError("err_no_profile_found")
        return c[0].path

    try:
        if a.cmd == "detect":
            c = detect_profiles()
            if a.json:
                print(json.dumps({"candidates": [x.to_dict() for x in c],
                                  "legacy": [str(x) for x in detect_legacy_profiles()]},
                                 ensure_ascii=False))
                return 0 if c else 1
            if not c:
                say("err_no_profile_found")
                return 1
            for x in c:
                n, size = profile_size(x.path)
                print(f"{x.path}  [{x.source}]  {n} / {human_size(size)}")
            for x in detect_legacy_profiles():
                say("info_legacy_profile", path=str(x))
            return 0
        if a.cmd == "backup":
            prof = pick_profile(a.profile)
            dest = Path(a.dest) if a.dest else default_backup_dir()
            rep = create_backup(prof, dest, split_threshold=a.threshold_mb * MB,
                                part_size=a.part_mb * MB, use_7z=a.use_7z, progress=prog)
            sys.stderr.write("\n")
            say("report_backup", files=rep.file_count, size=human_size(rep.source_size),
                archive_size=human_size(rep.archive_size),
                where="\n  ".join(str(x) for x in rep.outputs))
            for rel, why in rep.skipped:
                print(f"  ! {rel}: {reason_text(why, lang)}")
            return 0
        if a.cmd == "verify":
            src = open_backup(Path(a.archive), progress=prog)
            sys.stderr.write("\n")
            s = src.summary
            say("summary_backup", created=s["created"], gimp=s["gimp_version"],
                series=s["profile_series"], files=s["file_count"],
                size=human_size(s["total_size"] or 0), parts=s["parts"] or 1,
                source=s["source_path"])
            say("verify_ok")
            return 0
        if a.cmd == "restore":
            prof = pick_profile(a.profile)
            src = open_backup(Path(a.archive), progress=prog)
            sys.stderr.write("\n")
            s = src.summary
            say("summary_backup", created=s["created"], gimp=s["gimp_version"],
                series=s["profile_series"], files=s["file_count"],
                size=human_size(s["total_size"] or 0), parts=s["parts"] or 1,
                source=s["source_path"])
            say("warn_close_gimp")
            say("confirm_restore_cli", profile=str(prof), mode=tr("mode_" + a.mode, lang))
            if not a.yes:
                ans = input("> ").strip().lower()
                if ans not in ("y", "yes", "t", "tak"):
                    say("err_cancelled")
                    return 2
            rep = restore_backup(Path(a.archive), prof, mode=a.mode, progress=prog)
            sys.stderr.write("\n")
            say("report_restore", files=rep.restored, profile=str(rep.profile),
                safety=str(rep.safety_copy or "-"))
            for rel, why in rep.skipped:
                print(f"  ! {rel}: {reason_text(why, lang)}")
            return 0
        if a.cmd == "apply-pending":
            res = apply_pending(Path(a.pending), wait_pid=a.wait_pid)
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 0 if res["ok"] else 1
    except PBError as e:
        sys.stderr.write("\n")
        print(tr(e.key, lang, **e.params), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
