# SPDX-License-Identifier: GPL-3.0-or-later
"""The install/ZIP layout must contain exactly what GIMP needs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import layout


def test_layout_has_launcher_package_and_license() -> None:
    rels = {rel for _src, rel in layout.plugin_files()}
    assert "warpforge.py" in rels
    assert "LICENSE" in rels
    assert "lib/warpforge/__init__.py" in rels
    assert "lib/warpforge/gimp_bridge.py" in rels
    assert "lib/warpforge/presets.py" in rels
    assert "schemas/warpforge-preset-v1.schema.json" in rels


def test_layout_excludes_build_artifacts_and_sources() -> None:
    rels = [rel for _src, rel in layout.plugin_files()]
    assert not any("__pycache__" in r or "/target/" in r for r in rels)
    assert not any(r.endswith((".rs", ".pyc", "Cargo.toml")) for r in rels)


def test_version_matches_package() -> None:
    import warpforge

    assert layout.version() == warpforge.__version__


def test_native_library_ships_when_built() -> None:
    rels = [rel for _src, rel in layout.plugin_files()]
    library = layout.native_library()
    if library is None:
        assert not any(r.startswith("lib/warpforge/native/") for r in rels)
    else:
        assert f"lib/warpforge/native/{library.name}" in rels
