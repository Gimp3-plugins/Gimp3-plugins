#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the WarpForge dialog outside GIMP and save a PNG of it.

Run with GIMP's bundled Python (it has PyGObject + GTK 3):

    "<GIMP>/bin/python.exe" tools/render_dialog_screenshot.py docs/screenshots/dialog.png
        [--mesh] [--plain]

Default is Puppet Warp with a few pins; ``--mesh`` shows Mesh Warp, ``--plain``
leaves the warp unedited.

Useful as a quick check that the dialog constructs without errors.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from warpforge.dialog import WarpDialog  # noqa: E402
from warpforge.render import select_backend  # noqa: E402
from warpforge.state import (  # noqa: E402
    LayerInfo,
    PixelBuffer,
    Rect,
    WarpMode,
    WarpSession,
    WarpSettings,
)


def synthetic_preview(width: int, height: int) -> PixelBuffer:
    rows = bytearray()
    for y in range(height):
        for x in range(width):
            check = ((x // 40) + (y // 40)) % 2
            rows += bytes((
                int(255 * x / width), int(255 * y / height), 200 if check else 90, 255))
    return PixelBuffer(width, height, bytes(rows))


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dialog.png")
    layer = LayerInfo(layer_id=2, name="Portrait", width=1920, height=1280, offset_x=0,
                      offset_y=0, image_width=1920, image_height=1280,
                      precision="u8-non-linear", has_alpha=True, is_rgb=True, has_mask=True,
                      is_text_layer=False, selection=Rect(200, 150, 900, 700))
    mode = WarpMode.MESH if "--mesh" in sys.argv else WarpMode.PUPPET
    session = WarpSession(layer=layer, mode=mode, preview=synthetic_preview(768, 512),
                          preview_scale=0.4, settings=WarpSettings(limit_to_selection=True,
                                                                   mesh_columns=6, mesh_rows=6,
                                                                   pin_radius=260.0))
    edited = "--plain" not in sys.argv
    if edited and mode is WarpMode.MESH:
        mesh = session.ensure_mesh()
        mesh.move_vertex(mesh.index(2, 2), (820.0, 330.0))
        mesh.move_vertex(mesh.index(3, 4), (1100.0, 760.0))
        mesh.move_vertex(mesh.index(4, 2), (560.0, 900.0))
    dialog = WarpDialog(session, select_backend())
    if edited and mode is WarpMode.PUPPET:
        rig = session.ensure_rig()
        a = rig.add_pin((700.0, 400.0), 260.0, 0.55)
        b = rig.add_pin((1000.0, 420.0), 260.0, 0.55)
        c = rig.add_pin((1300.0, 900.0), 300.0, 0.55)
        rig.add_pin((500.0, 1000.0), 220.0, 0.55)
        rig.link([a.id, b.id])
        rig.move_pin(a.id, (760.0, 300.0), True)
        rig.move_pin(c.id, (1180.0, 760.0), True)
        dialog.pin_tool.set_selection({c.id})
    dialog.dialog.show_all()
    dialog._request_preview()
    dialog._update_status()

    def capture() -> bool:
        window = dialog.dialog.get_window()
        w, h = window.get_width(), window.get_height()
        pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, w, h)
        pixbuf.savev(str(out), "png", [], [])
        Gtk.main_quit()
        return False

    GLib.timeout_add(1200, capture)
    Gtk.main()
    dialog.dialog.destroy()
    sys.stderr.write(f"saved {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
