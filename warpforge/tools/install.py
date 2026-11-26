#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install WarpForge into the GIMP 3 user plug-in folder.

    python tools/install.py              copy the plug-in (newest GIMP 3.x profile)
    python tools/install.py --dev        install a launcher that runs src/ directly
    python tools/install.py --flatpak    target the Flatpak GIMP profile (Linux)
    python tools/install.py --target DIR install into an explicit plug-ins folder
    python tools/install.py --uninstall  remove the plug-in

Restart GIMP after installing.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import stat
import sys
from pathlib import Path

from layout import LAUNCHER, PLUGIN_NAME, ROOT, native_library, plugin_files

log = logging.getLogger("install")


def gimp_config_bases(flatpak: bool) -> list[Path]:
    home = Path.home()
    if flatpak:
        return [home / ".var/app/org.gimp.GIMP/config/GIMP"]
    if sys.platform == "win32":
        return [Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "GIMP"]
    if sys.platform == "darwin":
        return [home / "Library/Application Support/GIMP"]
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return [xdg / "GIMP"]


def find_plugin_dir(flatpak: bool) -> Path:
    """Newest existing GIMP 3.x profile's plug-ins folder."""
    candidates: list[tuple[tuple[int, int], Path]] = []
    for base in gimp_config_bases(flatpak):
        if not base.is_dir():
            continue
        for profile in base.iterdir():
            match = re.fullmatch(r"3\.(\d+)", profile.name)
            if match and profile.is_dir():
                candidates.append(((3, int(match.group(1))), profile / "plug-ins"))
    if not candidates:
        raise SystemExit(
            "No GIMP 3 profile found. Start GIMP 3 once, or pass --target <plug-ins dir>."
        )
    return max(candidates)[1]


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install(dest: Path, dev: bool) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if dev:
        src_dir = (ROOT / "src").as_posix()
        launcher = LAUNCHER.read_text(encoding="utf-8")
        launcher = re.sub(r"^LIB_DIR = .*$", f"LIB_DIR = {src_dir!r}", launcher, flags=re.M)
        (dest / f"{PLUGIN_NAME}.py").write_text(launcher, encoding="utf-8")
    else:
        for source, rel in plugin_files():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    make_executable(dest / f"{PLUGIN_NAME}.py")
    if native_library() is None:
        log.warning("Native library not built: WarpForge will use the slow Python backend. "
                    "Run: cargo build --release --manifest-path src/warpforge/native/Cargo.toml")
    log.info("Installed %s into %s%s", PLUGIN_NAME, dest, " (dev mode)" if dev else "")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=Path, help="GIMP plug-ins folder to install into")
    parser.add_argument("--flatpak", action="store_true", help="use the Flatpak GIMP profile")
    parser.add_argument("--dev", action="store_true", help="run the plug-in from this checkout")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    plugin_root = args.target or find_plugin_dir(args.flatpak)
    dest = plugin_root / PLUGIN_NAME
    if args.uninstall:
        if dest.exists():
            shutil.rmtree(dest)
            log.info("Removed %s", dest)
        else:
            log.info("Nothing to remove at %s", dest)
        return 0
    install(dest, args.dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
