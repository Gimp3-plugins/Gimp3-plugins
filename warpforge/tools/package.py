#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build ``dist/warpforge-<version>-<platform>.zip``.

The archive holds a single ``warpforge/`` folder that users drop into their
GIMP ``plug-ins`` directory. It contains the native library for the platform
it was built on, so build it first:

    cargo build --release --manifest-path src/warpforge/native/Cargo.toml
    python tools/package.py

Without the library the ZIP still works, using the slow Python backend
(``--allow-python-only`` acknowledges that).
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path

from layout import (
    PLUGIN_NAME,
    ROOT,
    native_library,
    platform_tag,
    plugin_files,
    version,
)

log = logging.getLogger("package")


def installers(windows: bool) -> list[Path]:
    """Installer scripts shipped at the root of the ZIP for this platform."""
    if windows:
        return [ROOT / "packaging" / "windows" / "install.ps1"]
    return [ROOT / "packaging" / "linux" / "install.sh"]


def build() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-python-only", action="store_true",
                        help="package without the native library")
    args = parser.parse_args()
    if native_library() is None:
        if not args.allow_python_only:
            log.error("Native library not built. Run cargo build --release first, "
                      "or pass --allow-python-only.")
            return 1
        tag = "python"
    else:
        tag = platform_tag()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"{PLUGIN_NAME}-{version()}-{tag}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for source, rel in plugin_files():
            info = zipfile.ZipInfo.from_file(source, f"{PLUGIN_NAME}/{rel}")
            if rel == f"{PLUGIN_NAME}.py":
                info.external_attr = (0o755 << 16)  # keep the launcher executable on Linux
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, source.read_bytes())
        # An installer next to the folder, for users without Python or a terminal habit.
        windows = tag.startswith("windows") or (tag == "python" and sys.platform == "win32")
        for installer in installers(windows):
            info = zipfile.ZipInfo.from_file(installer, installer.name)
            info.external_attr = (0o755 << 16) if installer.suffix == ".sh" else 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, installer.read_bytes())
    log.info("Wrote %s", archive)
    return 0


if __name__ == "__main__":
    sys.exit(build())
