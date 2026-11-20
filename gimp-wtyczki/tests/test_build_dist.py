# -*- coding: utf-8 -*-
"""Skrypt paczek wydań (tools/build_dist.py): pytest tests/"""

import importlib.util
import pathlib
import zipfile

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "tools" / "build_dist.py"
_spec = importlib.util.spec_from_file_location("build_dist", _PATH)
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)


@pytest.mark.parametrize("plugin", bd.PLUGINS)
def test_build_each_plugin(tmp_path, plugin):
    out, count = bd.build(plugin, "9.9.9", out_dir=str(tmp_path))
    assert out.endswith("%s-v9.9.9.zip" % plugin)
    names = zipfile.ZipFile(out).namelist()
    assert "install.ps1" in names
    assert "%s/%s.py" % (plugin, plugin) in names
    assert not [n for n in names if "__pycache__" in n or n.endswith((".cube", ".pyc"))]
    assert not [n for n in names if n.endswith("startup-dir.txt")]
    # Tłumaczenia PL/EN muszą trafić do paczki.
    assert "%s/en.json" % plugin in names
    assert any(n.startswith("%s/" % plugin) and n.endswith("_i18n.py") for n in names)
    if plugin == "lut-cube":
        assert "tools/fetch-numpy.ps1" in names
        assert "lut-cube/lut_formats.py" in names and "lut-cube/batch.py" in names


def test_unknown_plugin(tmp_path):
    with pytest.raises(SystemExit):
        bd.build("nie-ma", "1.0.0", out_dir=str(tmp_path))
