# -*- coding: utf-8 -*-
"""
Buduje paczkę wydania wtyczki: dist/<wtyczka>-v<wersja>.zip

  python tools/build_dist.py lut-cube 1.1.0 [--require-vendor]

Paczka zawiera folder wtyczki i install.ps1 (dla lut-cube także
tools/fetch-numpy.ps1). Nigdy nie trafiają do niej pliki LUT (.cube, .3dl),
__pycache__ ani startup-dir.txt. --require-vendor przerywa, gdy w lut-cube
nie ma dołączonego numpy (lut-cube/vendor, patrz tools/fetch-numpy.ps1).
"""

import argparse
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = ("podpis-zdjecia", "meme-maker", "lut-cube")
SKIP_DIRS = {"__pycache__"}
SKIP_FILES = {"startup-dir.txt"}
SKIP_EXT = (".pyc", ".cube", ".3dl")


def plugin_files(plugin):
    root = os.path.join(REPO, plugin)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name in SKIP_FILES or name.lower().endswith(SKIP_EXT):
                continue
            path = os.path.join(dirpath, name)
            yield path, os.path.relpath(path, REPO).replace(os.sep, "/")


def build(plugin, version, require_vendor=False, out_dir=None):
    if plugin not in PLUGINS:
        raise SystemExit("Nieznana wtyczka: %s (dostępne: %s)" % (plugin, ", ".join(PLUGINS)))
    vendor = os.path.join(REPO, "lut-cube", "vendor", "VENDOR.json")
    if plugin == "lut-cube" and require_vendor and not os.path.isfile(vendor):
        raise SystemExit("Brak lut-cube/vendor – uruchom najpierw tools/fetch-numpy.ps1.")
    out_dir = out_dir or os.path.join(REPO, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s-v%s.zip" % (plugin, version))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, arc in plugin_files(plugin):
            z.write(path, arc)
        z.write(os.path.join(REPO, "install.ps1"), "install.ps1")
        if plugin == "lut-cube":
            z.write(os.path.join(REPO, "tools", "fetch-numpy.ps1"),
                    "tools/fetch-numpy.ps1")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    bad = [n for n in names if n.lower().endswith((".cube", ".3dl"))]
    if bad:
        os.remove(out)
        raise SystemExit("W paczce znalazły się pliki LUT – przerwano: %s" % bad[:5])
    return out, len(names)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Buduje paczkę wydania wtyczki.")
    ap.add_argument("plugin", choices=PLUGINS)
    ap.add_argument("version", help="np. 1.1.0 (bez „v”)")
    ap.add_argument("--require-vendor", action="store_true",
                    help="dla lut-cube: wymagaj dołączonego numpy")
    ap.add_argument("--out", help="folder wynikowy (domyślnie dist/)")
    args = ap.parse_args(argv)
    out, count = build(args.plugin, args.version.lstrip("v"), args.require_vendor,
                       args.out)
    print("Zbudowano %s (%d plików, %.1f MB)" % (out, count,
                                                os.path.getsize(out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
