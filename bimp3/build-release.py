"""Package the reviewed runtime, documentation, examples and tests atomically.

The package is refused unless tests/integration-result.json comes from a full,
unfiltered, successful run that is newer than every runtime and test source.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

MINIMUM_INTEGRATION_CHECKS = 28


def verified_results(root):
    path = root / "tests" / "integration-result.json"
    if not path.is_file():
        raise RuntimeError("Brak tests/integration-result.json. Uruchom .\test.ps1.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("filter"):
        raise RuntimeError(f"Wynik pochodzi z przebiegu z filtrem BIMP_TEST_FILTER={result['filter']!r}.")
    if result.get("failed") != 0 or result.get("passed", 0) < MINIMUM_INTEGRATION_CHECKS:
        raise RuntimeError(f"Niepełny lub nieudany przebieg testów: {result.get('passed')} OK, {result.get('failed')} błędów.")
    sources = [p for p in (root / "bimp3").glob("*") if p.suffix in (".py", ".c", ".dll")]
    sources += list((root / "tests").glob("*.py"))
    newest = max(p.stat().st_mtime for p in sources)
    if path.stat().st_mtime < newest:
        stale = max(sources, key=lambda p: p.stat().st_mtime)
        raise RuntimeError(f"Wynik testów jest starszy niż {stale.relative_to(root)}. Uruchom ponownie .\test.ps1.")
    return result


def build():
    root = Path(__file__).resolve().parent
    result = verified_results(root)
    runtime = sorted(
        p
        for p in (root / "bimp3").iterdir()
        if p.is_file() and (p.suffix in (".py", ".c", ".dll", ".sha256") or p.name == "LICENSE")
    )
    release = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "gimp": result.get("gimp"),
        "python": result.get("python"),
        "integration_tests": result["passed"],
        "failed": result["failed"],
        "tests_finished_utc": result.get("finished_utc"),
        "runtime_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in runtime},
        "not_verified_here": "instalator (tests/test_install.ps1), Linux/macOS, zdalne CI",
    }
    (root / "tests" / "release-result.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
    files = list(runtime)
    files += list(root.glob("*.md")) + list(root.glob("*.ps1")) + list(root.glob("*.sh"))
    # Top-level Python covers build-release.py and bimp3_cli_runner.py (needed by bimp3-cli.ps1).
    files += list(root.glob("*.py")) + [root / "pyproject.toml", root / "requirements-dev.txt"]
    files += [p for p in (root / "LICENSE-GPL-3.0",) if p.exists()]
    files += [p for p in (root / "examples").iterdir() if p.suffix in (".json", ".cube")]
    files += list((root / "tests").glob("*.py")) + list((root / "tests").glob("*.ps1"))
    files += list((root / "tests").glob("*result.json"))
    files += [p for p in (root / "preview.png", root / "lut-preview.png") if p.exists()]
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
