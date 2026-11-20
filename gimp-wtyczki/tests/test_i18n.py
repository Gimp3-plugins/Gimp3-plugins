# -*- coding: utf-8 -*-
"""Tłumaczenia PL/EN wszystkich trzech wtyczek: pytest tests/"""

import ast
import glob
import importlib
import importlib.util
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# folder wtyczki, moduł tłumaczeń, pliki ze źródłami do skanowania
PLUGINS = {
    "podpis-zdjecia": ("podpis_i18n", ["podpis-zdjecia.py"]),
    "meme-maker": ("meme_i18n", ["meme-maker.py"]),
    "lut-cube": ("lut_i18n", None),             # None = wszystkie *.py
}
PLACEHOLDER = re.compile(r"%[#0\-+]*\d*(?:\.\d+)?[sdrgfx%]")


def _load_i18n(folder):
    modname = PLUGINS[folder][0]
    if str(ROOT / folder) not in sys.path:
        sys.path.insert(0, str(ROOT / folder))
    return importlib.import_module(modname)


def _sources(folder):
    names = PLUGINS[folder][1]
    files = ([ROOT / folder / n for n in names] if names
             else [pathlib.Path(p) for p in glob.glob(str(ROOT / folder / "*.py"))])
    return [f for f in files if not f.name.endswith("_i18n.py")]


def _used_keys(folder):
    keys = {}
    for f in _sources(folder):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)):
                keys.setdefault(n.args[0].value, "%s:%d" % (f.name, n.lineno))
    return keys


def _catalog(folder):
    path = ROOT / folder / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _restore_polish():
    yield
    for folder in PLUGINS:
        _load_i18n(folder).set_language("pl")


@pytest.mark.parametrize("folder", PLUGINS)
def test_every_tr_key_has_english(folder):
    used, cat = _used_keys(folder), _catalog(folder)
    missing = {k: where for k, where in used.items() if k not in cat}
    assert not missing, "Brak tłumaczenia EN: %s" % json.dumps(missing, ensure_ascii=False)


@pytest.mark.parametrize("folder", PLUGINS)
def test_no_stale_catalog_entries(folder):
    used, cat = _used_keys(folder), _catalog(folder)
    stale = [k for k in cat if k not in used]
    assert not stale, "Nieużywane wpisy w en.json: %s" % stale


@pytest.mark.parametrize("folder", PLUGINS)
def test_placeholders_and_edges_match(folder):
    for pl, en in _catalog(folder).items():
        assert sorted(PLACEHOLDER.findall(pl)) == sorted(PLACEHOLDER.findall(en)), (pl, en)
        assert pl[:1] == "\n" if en[:1] == "\n" else pl[:1] != "\n", (pl, en)
        assert pl[-1:] == "\n" if en[-1:] == "\n" else pl[-1:] != "\n", (pl, en)
        assert en.strip(), pl


@pytest.mark.parametrize("folder", PLUGINS)
def test_english_is_not_polish(folder):
    """W angielskich tekstach nie ma polskich liter (poza znakami specjalnymi)."""
    polish = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
    bad = [en for en in _catalog(folder).values() if polish.search(en)]
    assert not bad, bad


def test_i18n_module_copies_are_identical():
    texts = {f: (ROOT / f / (PLUGINS[f][0] + ".py")).read_text(encoding="utf-8")
             for f in PLUGINS}
    assert len(set(texts.values())) == 1


@pytest.mark.parametrize("folder", PLUGINS)
def test_tr_switches_language(folder):
    mod = _load_i18n(folder)
    key = next(iter(_catalog(folder)))
    mod.set_language("pl")
    assert mod.tr(key) == key
    mod.set_language("en")
    assert mod.tr(key) == _catalog(folder)[key] != key
    assert mod.tr("tekst, którego nie ma w katalogu") == "tekst, którego nie ma w katalogu"
    with pytest.raises(ValueError):
        mod.set_language("de")


def test_detect_language(monkeypatch):
    mod = _load_i18n("lut-cube")
    for var in ("GIMP_WTYCZKI_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    cases = [
        ({"LANGUAGE": "pl"}, "pl"),
        ({"LANGUAGE": "pl:en"}, "pl"),
        ({"LANGUAGE": "en_GB"}, "en"),
        ({"LANGUAGE": "de"}, "en"),
        ({"LANG": "pl_PL.UTF-8"}, "pl"),
        ({"LANG": "C"}, None),                   # C/POSIX: decyduje reszta systemu
        ({"LANGUAGE": "de", "GIMP_WTYCZKI_LANG": "pl"}, "pl"),    # wymuszenie
        ({"LANGUAGE": "pl", "GIMP_WTYCZKI_LANG": "en"}, "en"),
        ({"LANGUAGE": "pl", "GIMP_WTYCZKI_LANG": "xx"}, "pl"),    # zły override ignorowany
    ]
    for env, expected in cases:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        got = mod.detect_language()
        if expected is not None:
            assert got == expected, (env, got)
        else:
            assert got in ("pl", "en")
        for k in env:
            monkeypatch.delenv(k)


def _load_plugin_main(folder, fname, alias):
    spec = importlib.util.spec_from_file_location(alias, ROOT / folder / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_podpis_runtime_english():
    i18n = _load_i18n("podpis-zdjecia")
    i18n.set_language("en")
    pz = _load_plugin_main("podpis-zdjecia", "podpis-zdjecia.py", "podpis_en")
    labels = dict(pz.POSITIONS)
    assert labels["top-left"] == "Top – left"
    assert labels["center"] == "Middle"
    with pytest.raises(ValueError, match="Unknown position"):
        pz.split_position("nigdzie")
    i18n.set_language("pl")
    pz_pl = _load_plugin_main("podpis-zdjecia", "podpis-zdjecia.py", "podpis_pl")
    assert dict(pz_pl.POSITIONS)["top-left"] == "Góra – lewo"


def test_lut_errors_in_english_and_polish():
    sys.path.insert(0, str(ROOT / "lut-cube"))
    import cube_parser
    i18n = _load_i18n("lut-cube")
    bad = "LUT_3D_SIZE 2\n0,5 0 0\n"
    i18n.set_language("en")
    with pytest.raises(cube_parser.CubeError, match="decimal comma"):
        cube_parser.parse_cube_text(bad, "x.cube")
    with pytest.raises(cube_parser.CubeError, match="wrong number of data rows"):
        cube_parser.parse_cube_text("LUT_3D_SIZE 2\n0 0 0\n", "x.cube")
    i18n.set_language("pl")
    with pytest.raises(cube_parser.CubeError, match="przecink"):
        cube_parser.parse_cube_text(bad, "x.cube")


def test_file_formats_are_never_translated(tmp_path):
    """Zapisany .cube ma te same słowa kluczowe po polsku i po angielsku."""
    sys.path.insert(0, str(ROOT / "lut-cube"))
    import cube_parser
    import lut_formats
    i18n = _load_i18n("lut-cube")
    lut = cube_parser.parse_cube_text(
        "TITLE \"x\"\nLUT_3D_SIZE 2\n" + "0 0 0\n" * 8, "x.cube")
    outputs = {}
    for lang in ("pl", "en"):
        i18n.set_language(lang)
        path = tmp_path / ("look-%s.cube" % lang)
        lut_formats.write_cube(lut, str(path), "Mój look")
        outputs[lang] = path.read_text(encoding="utf-8")
    assert outputs["pl"] == outputs["en"]
    assert outputs["pl"].startswith('TITLE "Mój look"\nLUT_3D_SIZE 2\n')
