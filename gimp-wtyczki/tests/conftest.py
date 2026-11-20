# -*- coding: utf-8 -*-
"""Wspólna konfiguracja pytest: komunikaty testowane po polsku niezależnie od
języka systemu (w CI jest angielski). Testy angielskiego przełączają język jawnie."""

import os

os.environ["GIMP_WTYCZKI_LANG"] = "pl"
