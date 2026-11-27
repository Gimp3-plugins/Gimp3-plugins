"""Executed INSIDE console GIMP by bimp3-cli.ps1: calls the plug-in-bimp3 PDB procedure.

SPDX-License-Identifier: GPL-2.0-or-later
The request and result are JSON files whose paths are passed as Python literals.
"""

import json
from pathlib import Path

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp  # noqa: E402


def run(request_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result = {"success": False, "error": ""}
    try:
        proc = Gimp.get_pdb().lookup_procedure("plug-in-bimp3")
        if proc is None:
            raise RuntimeError("Wtyczka BIMP 3 nie jest zarejestrowana w tym profilu GIMP.")
        config = proc.create_config()
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        for key, value in request["arguments"].items():
            config.set_property(key, value)
        returned = proc.run(config)
        result["success"] = returned.index(0) == Gimp.PDBStatusType.SUCCESS
        if not result["success"] and returned.length() > 1:
            error = returned.index(1)
            result["error"] = getattr(error, "message", None) or str(error)
    except Exception as exc:
        result["error"] = str(exc)
    Path(request["result"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


run(globals()["BIMP_REQUEST"])
