# -*- coding: utf-8 -*-
"""
Tłumaczenia interfejsu PL/EN (bez gettext i plików .mo).

Teksty w kodzie są pisane po polsku i opakowane w tr("…"). Dla języka
angielskiego tr() zwraca tłumaczenie z pliku en.json (klucz = polski tekst);
dla polskiego i dla brakujących wpisów – tekst bez zmian.

Język wybierany jest automatycznie według języka interfejsu GIMP-a
(GIMP ustawia zmienną LANGUAGE dla wtyczek). Wszystko, co nie jest polskie,
dostaje angielski. Wymusić język można zmienną GIMP_WTYCZKI_LANG=pl albo en.

Ten sam plik (pod inną nazwą) leży w każdej wtyczce – wtyczki są niezależne,
a każda ma własny en.json. Nie zmieniaj go w jednym miejscu: skopiuj do
pozostałych (test sprawdza, czy kopie są identyczne).
"""

import json
import os

LANGUAGES = ("pl", "en")
_DIR = os.path.dirname(os.path.abspath(__file__))
_lang = None
_catalog = None


def detect_language():
    """„pl” albo „en” wg zmiennych środowiska, a na Windows wg języka systemu."""
    forced = os.environ.get("GIMP_WTYCZKI_LANG", "").strip().lower()[:2]
    if forced in LANGUAGES:
        return forced
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        for part in os.environ.get(var, "").split(":"):   # LANGUAGE = "pl:en"
            part = part.strip().lower()
            if part and part not in ("c", "posix"):
                return "pl" if part.startswith("pl") else "en"
    try:
        import ctypes
        return "pl" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x15 \
            else "en"
    except (AttributeError, OSError, ImportError):
        pass
    try:
        import locale
        loc = (locale.getlocale()[0] or "").lower()
    except (ValueError, TypeError):
        loc = ""
    return "pl" if loc.startswith(("pl", "polish")) else "en"


def language():
    global _lang
    if _lang is None:
        _lang = detect_language()
    return _lang


def set_language(code):
    """Wymusza język (testy). Przy angielskim katalog jest wczytywany od nowa."""
    global _lang, _catalog
    if code not in LANGUAGES:
        raise ValueError("Nieznany język: %r" % (code,))
    _lang, _catalog = code, None


def catalog():
    """Słownik polski → angielski z en.json (pusty, gdy pliku nie ma)."""
    global _catalog
    if _catalog is None:
        try:
            with open(os.path.join(_DIR, "en.json"), encoding="utf-8") as f:
                data = json.load(f)
            _catalog = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _catalog = {}
    return _catalog


def tr(text):
    """Tłumaczy tekst na język interfejsu (polski tekst jest kluczem)."""
    if language() == "en":
        return catalog().get(text, text)
    return text
