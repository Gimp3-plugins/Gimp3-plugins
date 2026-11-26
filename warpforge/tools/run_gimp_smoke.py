#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run tests/gimp/smoke_bridge.py inside headless GIMP 3 (gimp-console).

    python tools/run_gimp_smoke.py [--gimp PATH_TO_gimp-console] [--script FILE]

``--script tests/gimp/nde_probe.py`` re-checks whether GIMP lets a plug-in
attach a warp as a non-destructive filter.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from layout import ROOT

log = logging.getLogger("smoke")

CANDIDATES = [
    "gimp-console-3",
    "gimp-console-3.2",
    "gimp-console",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/GIMP 3/bin/gimp-console-3.exe"),
    r"C:\Program Files\GIMP 3\bin\gimp-console-3.exe",
]


def find_gimp() -> str:
    for candidate in CANDIDATES:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    raise SystemExit("gimp-console not found; pass --gimp")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--gimp", help="path to gimp-console")
    parser.add_argument("--script", default="tests/gimp/smoke_bridge.py",
                        help="script to run inside GIMP (relative to the repository)")
    args = parser.parse_args()
    gimp = args.gimp or find_gimp()
    script = (ROOT / args.script).as_posix()
    env = dict(os.environ, WARPFORGE_SRC=str(ROOT / "src"))
    code = f"exec(open({script!r}, encoding='utf-8').read())"
    cmd = [gimp, "-i", "-n", "--no-splash", "--batch-interpreter=python-fu-eval",
           "-b", code, "--quit"]
    log.info("Running %s", gimp)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    output = proc.stdout + proc.stderr
    lines = [line for line in output.splitlines() if "SMOKE" in line or "Error" in line
             or "Traceback" in line or line.startswith("  ")]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # GIMP's output is not always ASCII
    sys.stdout.write("\n".join(lines) + "\n")
    passed = "RESULT ALL PASSED" in output
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
