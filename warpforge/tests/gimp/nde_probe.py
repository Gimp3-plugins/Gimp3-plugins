# SPDX-License-Identifier: GPL-3.0-or-later
"""Can a plug-in attach a displacement-map warp as a GIMP non-destructive filter?

Run with ``python tools/run_gimp_smoke.py --script tests/gimp/nde_probe.py``.
Not a pass/fail test of WarpForge: it records what the running GIMP allows,
so the decision in NOTES.md ("Non-destructive effects") can be re-checked on
newer GIMP versions. "RESULT ALL PASSED" means a true NDE warp looks possible.
"""

import logging
import sys
import traceback

logging.basicConfig(level=logging.INFO, format="SMOKE %(levelname)s %(message)s",
                    stream=sys.stderr)
log = logging.getLogger("nde-probe")

import gi  # noqa: E402

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp  # noqa: E402

findings = {}


def note(name, value):
    findings[name] = value
    log.info("%s: %s", name, value)


try:
    Gegl.init(None)
    note("GIMP version", Gimp.version())
    available = set(Gimp.DrawableFilter.operation_get_available())
    for op in ("gegl:map-absolute", "gegl:map-relative", "gegl:displace"):
        note(f"{op} allowed as a filter", op in available)

    image = Gimp.Image.new_with_precision(64, 32, Gimp.ImageBaseType.RGB,
                                          Gimp.Precision.FLOAT_LINEAR)
    layer = Gimp.Layer.new(image, "src", 64, 32, Gimp.ImageType.RGBA_IMAGE, 100,
                           Gimp.LayerMode.NORMAL)
    aux = Gimp.Layer.new(image, "map", 64, 32, Gimp.ImageType.RGBA_IMAGE, 100,
                         Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    image.insert_layer(aux, None, 1)

    plain = Gimp.DrawableFilter.new(layer, "gegl:ripple", "probe")
    layer.append_filter(plain)
    note("plain filter appended", len(layer.get_filters()) == 1)
    plain.delete()

    for op in ("gegl:displace", "gegl:bump-map"):
        try:
            f = Gimp.DrawableFilter.new(layer, op, "probe")
            f.set_aux_input("aux", aux)
            layer.append_filter(f)
            appended = any(x.get_operation_name() == op for x in layer.get_filters())
            note(f"{op} with an aux drawable appended", appended)
            if appended:
                f.delete()
        except Exception as exc:  # report whatever GIMP does
            note(f"{op} with an aux drawable appended", f"error {exc!r}")
    image.delete()
except Exception:
    traceback.print_exc()

possible = findings.get("gegl:map-absolute allowed as a filter") is True or \
    findings.get("gegl:displace with an aux drawable appended") is True
log.info("RESULT %s", "ALL PASSED" if possible else
         "FAILED: no way to attach a displacement-map filter from a plug-in")
