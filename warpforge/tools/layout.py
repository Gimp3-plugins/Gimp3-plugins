# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared description of the installed plug-in layout.

    plug-ins/warpforge/warpforge.py          launcher (GIMP runs this)
    plug-ins/warpforge/lib/warpforge/...     the Python package
    plug-ins/warpforge/lib/warpforge/native/<library>   compiled Rust kernels
    plug-ins/warpforge/LICENSE
"""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "src" / "warpforge"
LAUNCHER = ROOT / "packaging" / "plug-in" / "warpforge.py"
PLUGIN_NAME = "warpforge"
NATIVE_DIR = PACKAGE_DIR / "native"

_SKIP_DIRS = {"__pycache__", "target", ".mypy_cache", ".pytest_cache"}
# Rust sources are built separately; only the compiled library ships (stage 2+).
_SKIP_SUFFIXES = {".pyc", ".pyo", ".rs", ".toml", ".lock"}


def version() -> str:
    text = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("cannot find __version__")
    return match.group(1)


def native_library_name() -> str:
    """Must match ``warpforge.native_backend.library_name``."""
    if sys.platform == "win32":
        return "warpforge_native.dll"
    if sys.platform == "darwin":
        return "libwarpforge_native.dylib"
    return "libwarpforge_native.so"


def native_library() -> Path | None:
    """The release build of the native library, if it has been built."""
    path = NATIVE_DIR / "target" / "release" / native_library_name()
    return path if path.is_file() else None


def platform_tag() -> str:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower().replace("amd64", "x86_64")
    return f"{system}-{machine}"


def plugin_files() -> Iterator[tuple[Path, str]]:
    """Yield (source path, path relative to plug-ins/warpforge/)."""
    yield LAUNCHER, f"{PLUGIN_NAME}.py"
    yield ROOT / "LICENSE", "LICENSE"
    for schema in sorted((ROOT / "data" / "schemas").glob("*.json")):
        yield schema, f"schemas/{schema.name}"
    for path in sorted(PACKAGE_DIR.rglob("*")):
        rel = path.relative_to(PACKAGE_DIR)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_file() and path.suffix not in _SKIP_SUFFIXES:
            yield path, f"lib/warpforge/{rel.as_posix()}"
    library = native_library()
    if library is not None:
        yield library, f"lib/warpforge/native/{library.name}"
