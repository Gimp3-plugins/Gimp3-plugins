# -*- coding: utf-8 -*-
"""Szablony podpisów i domyślny tekst (bez GIMP-a): pytest tests/"""

import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "podpis-zdjecia" / "podpis-zdjecia.py"
_spec = importlib.util.spec_from_file_location("podpis_zdjecia_tpl", _PATH)
pz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pz)


def test_default_text_from_real_name():
    assert pz.default_text("Anna Nowak") == "© Anna Nowak"
    assert pz.default_text("  ") == "©"
    assert pz.default_text("Unknown") == "©"
    assert pz.default_text(None) == "©"


def test_templates_roundtrip_and_filtering(tmp_path):
    path = str(tmp_path / "sub folder ąę" / "szablony.json")
    assert pz.load_templates(path) == {}
    pz.save_template(path, "Marka", "text",
                     {"text": "© Ja", "color": [1, 0, 0, 1], "position": "top-left",
                      "file": "nie-dla-tekstu.png", "obce": 1})
    pz.save_template(path, "Logo", "image",
                     {"file": "C:/logo ż.png", "scale-percent": 20.0})
    t = pz.load_templates(path)
    assert set(t) == {"Marka", "Logo"}
    assert t["Marka"]["values"] == {"text": "© Ja", "color": [1, 0, 0, 1],
                                    "position": "top-left"}
    assert pz.find_template(t, "marka", "text")["text"] == "© Ja"
    assert pz.find_template(t, "Marka", "image") is None      # inny rodzaj
    assert pz.find_template(t, "brak", "text") is None
    pz.save_template(path, "Marka", "text", {"text": "© Nowy"})  # nadpisanie
    assert pz.load_templates(path)["Marka"]["values"] == {"text": "© Nowy"}


def test_templates_bad_file_and_empty_name(tmp_path):
    path = tmp_path / "szablony.json"
    path.write_text("{to nie json", encoding="utf-8")
    assert pz.load_templates(str(path)) == {}
    path.write_text(json.dumps({"x": {"kind": "zly", "values": {}}, "y": 5}),
                    encoding="utf-8")
    assert pz.load_templates(str(path)) == {}
    with pytest.raises(ValueError):
        pz.save_template(str(path), "  ", "text", {})
