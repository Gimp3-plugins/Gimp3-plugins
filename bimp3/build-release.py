"""Package the reviewed runtime, documentation, examples and tests atomically."""

from hashlib import sha256
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build():
    root = Path(__file__).resolve().parent
    files = [
        p
        for p in (root / "bimp3").iterdir()
        if p.is_file() and (p.suffix in (".py", ".c", ".dll") or p.name == "LICENSE")
    ]
    files += list(root.glob("*.md")) + list(root.glob("*.ps1"))
    files += [root / "build-release.py", root / "pyproject.toml", root / "requirements-dev.txt"]
    files += [p for p in (root / "examples").iterdir() if p.suffix in (".json", ".cube")]
    files += list((root / "tests").glob("*.py")) + list((root / "tests").glob("*.ps1"))
    # Results, screenshots and GIMP profiles can contain local paths and images.
    # The release includes sources and repeatable tests, never machine logs.
    files += [root / "LICENSE-GPL-3.0"]
    archive = root / "bimp3-gimp3.zip"
    temporary = root / ".bimp3-release.zip.tmp"
    manifest = {str(p.relative_to(root)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in files}
    with ZipFile(temporary, "w", ZIP_DEFLATED) as package:
        for file in sorted(files):
            package.write(file, file.relative_to(root))
        package.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    with ZipFile(temporary) as package:
        if package.testzip() is not None:
            raise RuntimeError("Uszkodzone archiwum.")
        for filename, checksum in manifest.items():
            if sha256(package.read(filename)).hexdigest() != checksum:
                raise RuntimeError(f"Błąd sumy kontrolnej: {filename}")
    os.replace(temporary, archive)
    print(f"ZIP OK: {archive}, {len(files)} plików, {archive.stat().st_size} bajtów")


if __name__ == "__main__":
    build()
