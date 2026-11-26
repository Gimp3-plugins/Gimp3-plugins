# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless smoke test of gimp_bridge inside a real GIMP 3 process.

Run with ``python tools/run_gimp_smoke.py`` (it locates gimp-console and
passes this file to the python-fu-eval batch interpreter). Not collected by
pytest: it needs GIMP's own Python and typelibs.
"""

import logging
import os
import sys
import traceback

sys.path.insert(0, os.environ["WARPFORGE_SRC"])
logging.basicConfig(level=logging.INFO, format="SMOKE %(levelname)s %(message)s",
                    stream=sys.stderr)
log = logging.getLogger("smoke")

import gi  # noqa: E402

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp  # noqa: E402

from warpforge import gimp_bridge as gb  # noqa: E402
from warpforge.errors import MultipleLayersError, NoActiveLayerError  # noqa: E402
from warpforge.state import PixelBuffer  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        log.info("PASS %s", name)
    else:
        log.error("FAIL %s %s", name, detail)
        failures.append(name)


def make_image(width, height, precision):
    image = Gimp.Image.new_with_precision(width, height, Gimp.ImageBaseType.RGB, precision)
    layer = Gimp.Layer.new(image, "base", width, height, Gimp.ImageType.RGBA_IMAGE, 100,
                           Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    color = Gegl.Color.new("rgb(0,0,1)")
    Gimp.context_set_foreground(color)
    layer.edit_fill(Gimp.FillType.FOREGROUND)
    return image, layer


def run():
    Gegl.init(None)
    for precision in (Gimp.Precision.U8_NON_LINEAR, Gimp.Precision.FLOAT_LINEAR):
        tag = precision.value_nick
        image, layer = make_image(3000, 1500, precision)

        check(f"{tag}: resolve single layer", gb.resolve_target_layer([layer]) == layer)
        try:
            gb.resolve_target_layer([])
            check(f"{tag}: empty drawables raises", False)
        except NoActiveLayerError:
            check(f"{tag}: empty drawables raises", True)
        try:
            gb.resolve_target_layer([layer, layer])
            check(f"{tag}: multiple drawables raises", False)
        except MultipleLayersError:
            check(f"{tag}: multiple drawables raises", True)

        info = gb.read_layer_info(image, layer)
        check(f"{tag}: info size", (info.width, info.height) == (3000, 1500), info)
        check(f"{tag}: no selection", info.selection is None, info.selection)
        check(f"{tag}: precision", info.precision == tag, info.precision)

        preview, scale = gb.read_preview(layer)
        check(f"{tag}: preview size", (preview.width, preview.height) == (1024, 512),
              (preview.width, preview.height, scale))
        check(f"{tag}: preview pixel blue", preview.pixel(10, 10) == (0, 0, 255, 255),
              preview.pixel(10, 10))

        # write a red square, undoably
        red = PixelBuffer(50, 40, bytes([255, 0, 0, 255]) * (50 * 40))
        with gb.undo_group(image):
            gb.write_pixels(layer, red, x=100, y=200)
        back = gb.read_pixels(layer, gb.Rect(100, 200, 50, 40))
        check(f"{tag}: write/read round trip", back.data == red.data, back.pixel(0, 0))
        outside = gb.read_pixels(layer, gb.Rect(99, 199, 1, 1))
        check(f"{tag}: outside untouched", outside.pixel(0, 0) == (0, 0, 255, 255),
              outside.pixel(0, 0))

        # selection
        image.select_rectangle(Gimp.ChannelOps.REPLACE, 10, 20, 300, 400)
        info = gb.read_layer_info(image, layer)
        check(f"{tag}: selection bounds", info.selection == gb.Rect(10, 20, 300, 400),
              info.selection)
        Gimp.Selection.none(image)

        # layer mask, and resolving the mask to its layer
        mask = layer.create_mask(Gimp.AddMaskType.WHITE)
        layer.add_mask(mask)
        check(f"{tag}: has mask", gb.read_layer_info(image, layer).has_mask)
        check(f"{tag}: mask resolves to layer", gb.resolve_target_layer([mask]) == layer)

        # parasite round trip
        payload = '{"schema_version": 1, "plugin": "warpforge", "name": "zażółć"}'
        gb.store_effect_params(layer, payload)
        check(f"{tag}: parasite round trip", gb.load_effect_params(layer) == payload,
              gb.load_effect_params(layer))
        gb.clear_effect_params(layer)
        check(f"{tag}: parasite cleared", gb.load_effect_params(layer) is None)

        image.delete()


def gradient(width, height):
    data = bytearray()
    for y in range(height):
        for x in range(width):
            data += bytes((x * 255 // (width - 1), y * 255 // (height - 1), 0, 255))
    return PixelBuffer(width, height, bytes(data))


def run_commit():
    from warpforge.plugin import commit_warp
    from warpforge.render import select_backend
    from warpforge.state import WarpMode, WarpSession, WarpSettings

    backend = select_backend()
    log.info("backend in GIMP: %s", backend.name)
    check("native backend loads inside GIMP", backend.name == "native", backend.name)

    for precision in (Gimp.Precision.U8_NON_LINEAR, Gimp.Precision.HALF_LINEAR):
        tag = precision.value_nick
        image, layer = make_image(300, 200, precision)
        gb.write_pixels(layer, gradient(300, 200))
        before = gb.read_pixels(layer).data
        info = gb.read_layer_info(image, layer)

        def session(new_layer, limit, info=info):
            s = WarpSession(layer=info, mode=WarpMode.MESH,
                            settings=WarpSettings(mesh_columns=2, mesh_rows=2,
                                                  output_new_layer=new_layer,
                                                  limit_to_selection=limit))
            s.ensure_mesh().move_vertex(4, (180.0, 120.0))
            return s

        # 1. default: result on a new layer, original untouched and hidden
        target = commit_warp(image, layer, session(True, False), backend)
        check(f"{tag}: new layer created", target != layer and len(image.get_layers()) == 2)
        check(f"{tag}: new layer named", target.get_name().endswith("(WarpForge)"),
              target.get_name())
        check(f"{tag}: original hidden", not layer.get_visible())
        check(f"{tag}: original pixels unchanged", gb.read_pixels(layer).data == before)
        r, g, _b, a = gb.read_pixels(target, gb.Rect(180, 120, 1, 1)).pixel(0, 0)
        check(f"{tag}: moved vertex samples the old centre",
              abs(r - 127) <= 3 and abs(g - 127) <= 3 and a == 255, (r, g, a))
        corner = gb.read_pixels(target, gb.Rect(0, 0, 1, 1)).pixel(0, 0)
        check(f"{tag}: corner stays", corner == (0, 0, 0, 255), corner)
        image.remove_layer(target)
        layer.set_visible(True)

        # 2. in place, limited to a selection: pixels outside it must not change
        image.select_rectangle(Gimp.ChannelOps.REPLACE, 100, 50, 150, 120)
        commit_warp(image, layer, session(False, True), backend)
        after = gb.read_pixels(layer)
        check(f"{tag}: in place keeps one layer", len(image.get_layers()) == 1)
        outside = after.pixel(20, 20) == PixelBuffer(300, 200, before).pixel(20, 20)
        check(f"{tag}: outside selection untouched", outside)
        inside = after.pixel(180, 120)
        check(f"{tag}: inside selection warped", abs(inside[0] - 127) <= 3, inside)
        check(f"{tag}: selection restored", not Gimp.Selection.is_empty(image))
        image.delete()

        # 3. puppet warp on a new layer
        image, layer = make_image(300, 200, precision)
        gb.write_pixels(layer, gradient(300, 200))
        before = gb.read_pixels(layer).data
        info = gb.read_layer_info(image, layer)
        s = WarpSession(layer=info, mode=WarpMode.PUPPET,
                        settings=WarpSettings(output_new_layer=True))
        rig = s.ensure_rig()
        pin = rig.add_pin((100.0, 100.0), 60.0, s.settings.stiffness)
        rig.add_pin((250.0, 150.0), 40.0, s.settings.stiffness)
        rig.move_pin(pin.id, (130.0, 90.0), clamp_to_bounds=True)
        target = commit_warp(image, layer, s, backend)
        check(f"{tag}: puppet new layer", target != layer and len(image.get_layers()) == 2)
        check(f"{tag}: puppet original unchanged", gb.read_pixels(layer).data == before)
        r, g, _b, a = gb.read_pixels(target, gb.Rect(130, 90, 1, 1)).pixel(0, 0)
        # the pin's target shows the gradient at its source (100.5, 100.5)
        check(f"{tag}: puppet pin samples its source",
              abs(r - 100.5 * 255 / 299) <= 3 and abs(g - 100.5 * 255 / 199) <= 3 and a == 255,
              (r, g, a))
        far = gb.read_pixels(target, gb.Rect(290, 10, 1, 1)).pixel(0, 0)
        check(f"{tag}: puppet far pixel unchanged",
              far == PixelBuffer(300, 200, before).pixel(290, 10), far)
        image.delete()


def run_effects():
    """Stored effects: edit, show/hide, XCF round trip, remove (the NDE fallback)."""
    import tempfile
    from pathlib import Path

    from gi.repository import Gio

    from warpforge import presets
    from warpforge.plugin import commit_warp, find_effect, remove_effect, toggle_effect
    from warpforge.render import select_backend
    from warpforge.state import WarpMode, WarpSession, WarpSettings

    backend = select_backend()
    image, layer = make_image(300, 200, Gimp.Precision.U8_NON_LINEAR)
    gb.write_pixels(layer, gradient(300, 200))
    before = gb.read_pixels(layer).data
    info = gb.read_layer_info(image, layer)
    session = WarpSession(layer=info, mode=WarpMode.PUPPET, settings=WarpSettings())
    rig = session.ensure_rig()
    pin = rig.add_pin((100.0, 100.0), 60.0, 0.5)
    rig.add_pin((250.0, 150.0), 40.0, 0.5)
    rig.move_pin(pin.id, (130.0, 90.0), clamp_to_bounds=True)
    result = commit_warp(image, layer, session, backend)

    tag = gb.source_tag(layer)
    check("effect: original tagged", tag is not None)
    check("effect: result not tagged as an original", gb.source_tag(result) is None)
    stored = presets.loads(gb.load_effect_params(result))
    check("effect: parameters stored", stored.rig is not None and stored.rig.pins == rig.pins)
    check("effect: link to original", stored.effect.source_layer == tag)
    ctx = find_effect(image, result)
    check("effect: found from the result", ctx is not None and ctx.source == layer)
    ctx2 = find_effect(image, layer)
    check("effect: found from the original", ctx2 is not None and ctx2.result == result)

    # edit: move the pin further, re-render into the same layer
    rig.move_pin(pin.id, (150.0, 80.0), clamp_to_bounds=True)
    again = commit_warp(image, layer, session, backend, effect_layer=result)
    check("edit: same layer updated", again == result and len(image.get_layers()) == 2)
    r, g, _b, _a = gb.read_pixels(result, gb.Rect(150, 80, 1, 1)).pixel(0, 0)
    check("edit: new pin position applied",
          abs(r - 100.5 * 255 / 299) <= 3 and abs(g - 100.5 * 255 / 199) <= 3, (r, g))
    check("edit: original still untouched", gb.read_pixels(layer).data == before)
    edited = presets.loads(gb.load_effect_params(result))
    check("edit: parameters updated", edited.rig.pins[0].target == (150.0, 80.0))

    # show / hide
    check("toggle: hides", toggle_effect(image, layer) is False)
    check("toggle: original shown", layer.get_visible() and not result.get_visible())
    check("toggle: shows again", toggle_effect(image, result) is True)
    check("toggle: result shown", result.get_visible() and not layer.get_visible())

    # XCF round trip
    path = Path(tempfile.mkdtemp()) / "effect.xcf"
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(str(path)), None)
    loaded = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(path)))
    top = loaded.get_layers()[0]
    ctx3 = find_effect(loaded, top)
    check("xcf: effect survives save and load",
          ctx3 is not None and ctx3.editable and ctx3.preset.rig.pins == edited.rig.pins)
    check("xcf: original pixels survive", ctx3 is not None
          and gb.read_pixels(ctx3.source).data == before)
    loaded.delete()

    # remove
    remove_effect(image, result)
    layers = image.get_layers()
    check("remove: result deleted", len(layers) == 1 and layers[0] == layer)
    check("remove: original visible and untagged",
          layer.get_visible() and gb.source_tag(layer) is None)
    check("remove: nothing left to find", find_effect(image, layer) is None)

    # in place: parameters are kept but the effect is not editable
    session.settings.output_new_layer = False
    commit_warp(image, layer, session, backend)
    ctx4 = find_effect(image, layer)
    check("in place: recorded, not editable", ctx4 is not None and not ctx4.editable)
    remove_effect(image, layer)
    check("in place: remove forgets parameters", gb.load_effect_params(layer) is None)
    image.delete()


def run_procedure():
    """Call the installed plug-in through the PDB (needs tools/install.py first)."""
    proc = Gimp.get_pdb().lookup_procedure(gb.PROC_MAIN)
    if proc is None:
        log.warning("SKIP procedure checks: WarpForge is not installed in this GIMP profile")
        return
    image, layer = make_image(200, 100, Gimp.Precision.U8_NON_LINEAR)
    # A PDB lookup does not expose the icon; GIMP's own registry does.
    pluginrc = os.path.join(Gimp.directory(), "pluginrc")
    with open(pluginrc, encoding="utf-8", errors="replace") as f:
        registry = f.read()
    check("procedure icon registered", "warpforge-24.png" in registry)
    for name in (gb.PROC_EDIT, gb.PROC_TOGGLE, gb.PROC_REMOVE):
        check(f"procedure {name} registered",
              Gimp.get_pdb().lookup_procedure(name) is not None)
    toggle = Gimp.get_pdb().lookup_procedure(gb.PROC_TOGGLE)
    if toggle is not None:
        config = toggle.create_config()
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        config.set_property("image", image)
        config.set_core_object_array("drawables", [layer])
        status = toggle.run(config).index(0)
        check("toggle on a plain layer reports an error, no crash",
              status == Gimp.PDBStatusType.EXECUTION_ERROR, status)
    for drawables in ([layer], [], [layer, layer]):
        config = proc.create_config()
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        config.set_property("image", image)
        config.set_core_object_array("drawables", drawables)
        status = proc.run(config).index(0)
        # Non-interactive runs are refused with a clean error, never a crash.
        check(f"procedure with {len(drawables)} drawables returns an error status",
              status == Gimp.PDBStatusType.EXECUTION_ERROR, status)
    image.delete()


try:
    run()
    run_commit()
    run_effects()
    run_procedure()
except Exception:
    traceback.print_exc()
    failures.append("exception")

log.info("RESULT %s", "FAILED: " + ", ".join(failures) if failures else "ALL PASSED")
