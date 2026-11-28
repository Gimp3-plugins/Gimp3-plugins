#!/usr/bin/env python3
"""Build the release packages into dist/.

    python build-release.py

dist/zetmar-kolor-v<VER>.zip         plug-in + install.ps1 + docs
dist/zetmar-kolor-v<VER>-manual.zip  only the zetmar-kolor/ folder (copy into plug-ins)
dist/SHA256SUMS-v<VER>.txt
"""
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "plug-ins" / "zetmar-kolor"
FILES = ["zetmar-kolor.py", "zk_core.py", "zk_gimp.py", "zk_ui.py", "zk_i18n.py", "en.json"]
EXECUTABLE = {"zetmar-kolor.py"}


def version() -> str:
    m = re.search(r'^PLUGIN_VERSION = "([^"]+)"', (PLUGIN / "zk_core.py").read_text("utf-8"), re.M)
    return m.group(1)


def add(zf: zipfile.ZipFile, src: Path, arc: str):
    data = src.read_bytes()
    if src.suffix in (".py", ".md", ".txt", ".json", ""):
        data = data.replace(b"\r\n", b"\n")
    zi = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if src.name in EXECUTABLE else 0o644
    zi.external_attr = (0o100000 | mode) << 16
    zf.writestr(zi, data)


def main() -> int:
    ver = version()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    base = f"zetmar-kolor-v{ver}"
    full = dist / f"{base}.zip"
    manual = dist / f"{base}-manual.zip"
    with zipfile.ZipFile(full, "w") as zf:
        for f in FILES:
            add(zf, PLUGIN / f, f"{base}/plug-ins/zetmar-kolor/{f}")
        for f in ["install.ps1", "README.md", "README.en.md", "CHANGES.md", "LICENSE"]:
            add(zf, ROOT / f, f"{base}/{f}")
    with zipfile.ZipFile(manual, "w") as zf:
        for f in FILES:
            add(zf, PLUGIN / f, f"zetmar-kolor/{f}")
        add(zf, ROOT / "LICENSE", "zetmar-kolor/LICENSE")
    sums = dist / f"SHA256SUMS-v{ver}.txt"
    sums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                            for p in (full, manual)), encoding="utf-8", newline="\n")
    for p in (full, manual, sums):
        print(p, p.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
