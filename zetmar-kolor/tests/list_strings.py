# -*- coding: utf-8 -*-
"""Wypisuje teksty tr("…") wtyczki, których brakuje w en.json (do tłumaczenia)."""

import ast
import json
import os
import re
import sys

PLUGIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plug-ins", "zetmar-kolor")
PAT = re.compile(r'tr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)')
LIT = re.compile(r'"(?:[^"\\]|\\.)*"')


def strings():
    out = []
    for name in sorted(os.listdir(PLUGIN)):
        if name.endswith(".py") and name != "zk_i18n.py":
            with open(os.path.join(PLUGIN, name), encoding="utf-8") as f:
                src = f.read()
            for m in PAT.finditer(src):
                text = "".join(ast.literal_eval(s) for s in LIT.findall(m.group(1)))
                if text not in out:
                    out.append(text)
    return out


if __name__ == "__main__":
    with open(os.path.join(PLUGIN, "en.json"), encoding="utf-8") as f:
        en = json.load(f)
    missing = [t for t in strings() if t not in en]
    sys.stdout.reconfigure(encoding="utf-8")
    for t in missing:
        print(json.dumps(t, ensure_ascii=False))
    print(len(missing), "missing")
