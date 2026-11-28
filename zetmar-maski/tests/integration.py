"""Executed inside an isolated gimp-console instance by test.ps1."""
from pathlib import Path
from array import array
import json
import sys
import traceback
import os
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio

ROOT = Path(os.environ['ZETMAR_MASKI_TEST_ROOT'])
sys.path.insert(0, str(ROOT / 'plug-ins' / 'zetmar-maski'))
from zm_core import Settings
from zm_gimp import apply, preview, target
Gegl.init(None)
results = []


def check(name, fn):
    try:
        fn()
        results.append({'test': name, 'pass': True})
        print('PASS:', name)
    except Exception:
        error = traceback.format_exc()
        results.append({'test': name, 'pass': False, 'error': error})
        print('FAIL:', name, error)


def fixture(precision=Gimp.Precision.FLOAT_LINEAR, offset=(0, 0)):
    image = Gimp.Image.new_with_precision(16, 8, Gimp.ImageBaseType.RGB, precision)
    layer = Gimp.Layer.new(image, 'Test gradient', 16, 8, Gimp.ImageType.RGBA_IMAGE, 100., Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    layer.set_offsets(*offset)
    rgba = array('f', (c for y in range(8) for x in range(16) for c in (x/15, x/15, x/15, 1.)))
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, 16, 8), "R'G'B'A float", rgba.tobytes())
    buf.flush()
    return image, layer


def read(drawable):
    a = array('f')
    a.frombytes(bytes(drawable.get_buffer().get(Gegl.Rectangle.new(0, 0, drawable.get_width(), drawable.get_height()), 1., 'Y float', Gegl.AbyssPolicy.NONE)))
    return list(a)


def registered():
    assert Gimp.get_pdb().lookup_procedure('python-fu-zetmar-maski') is not None


def outputs(output, precision):
    image, layer = fixture(precision)
    try:
        source = bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, 16, 8), 1., "R'G'B'A float", Gegl.AbyssPolicy.NONE))
        apply(image, layer, Settings(feather=0), output)
        if output == 'new-layer':
            assert len(image.get_layers()) == 2
            dest = image.get_layers()[0].get_mask()
        elif output == 'layer-mask':
            dest = layer.get_mask()
        elif output == 'channel':
            dest = image.get_channels()[0]
            assert not dest.get_visible()
        else:
            dest = image.get_selection()
            assert not image.get_channels()
        values = read(dest)
        assert max(values[:8]) < .01, values[:16]
        assert min(values[8:16]) > .99, values[:16]
        assert bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, 16, 8), 1., "R'G'B'A float", Gegl.AbyssPolicy.NONE)) == source
        assert image.get_precision() == precision
    finally:
        image.delete()


def offset_selection():
    image, layer = fixture(offset=(4, 2))
    try:
        image.select_rectangle(Gimp.ChannelOps.REPLACE, 12, 2, 2, 3)
        apply(image, layer, Settings(low=0), 'channel')
        values = read(image.get_channels()[0])
        assert values[2*16+12] > .99
        assert values[2*16+11] < .01
        assert values[5*16+12] < .01
    finally:
        image.delete()


def existing_mask():
    image, layer = fixture()
    try:
        old = layer.create_mask(Gimp.AddMaskType.WHITE)
        layer.add_mask(old)
        buf = old.get_buffer()
        buf.set(Gegl.Rectangle.new(0, 0, 16, 8), 'Y float', array('f', [.5]*128).tobytes())
        buf.flush()
        try:
            apply(image, layer, Settings(), 'layer-mask')
        except ValueError:
            pass
        else:
            raise AssertionError('Existing mask was not protected')
        apply(image, layer, Settings(low=0), 'new-layer')
        assert abs(read(image.get_layers()[0].get_mask())[0]-.5) < .01
        assert abs(read(layer.get_mask())[0]-.5) < .01
    finally:
        image.delete()


def pdb_run():
    image, layer = fixture()
    try:
        proc = Gimp.get_pdb().lookup_procedure('python-fu-zetmar-maski')
        config = proc.create_config()
        config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
        config.set_property('image', image)
        config.set_core_object_array('drawables', [layer])
        config.set_property('output', 'channel')
        result = proc.run(config)
        assert result.index(0) == Gimp.PDBStatusType.SUCCESS, [result.index(i) for i in range(result.length())]
        assert len(image.get_channels()) == 1
    finally:
        image.delete()


def preview_matches():
    image, layer = fixture()
    try:
        from zm_core import Engine
        rgba, sel, w, h = preview(image, layer)
        assert (w, h) == (16, 8)
        a = array('f')
        a.frombytes(Engine(Settings()).mask(rgba, sel))
        apply(image, layer, Settings(), 'channel')
        assert max(abs(x-y) for x, y in zip(a, read(image.get_channels()[0]))) < .005
    finally:
        image.delete()


def xcf_roundtrip():
    image, layer = fixture()
    loaded = None
    try:
        apply(image, layer, Settings(), 'new-layer')
        file = Gio.File.new_for_path(str(ROOT / 'work' / 'test-mask.xcf'))
        assert Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, file)
        loaded = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, file)
        assert loaded.get_layers()[0].get_mask() is not None
        assert loaded.get_layers()[0].get_mask().get_parasite('zetmar-maski-settings') is not None
    finally:
        if loaded:
            loaded.delete()
        image.delete()


check('PDB registration', registered)
for precision in (Gimp.Precision.U8_NON_LINEAR, Gimp.Precision.U16_LINEAR, Gimp.Precision.FLOAT_LINEAR):
    for output in ('new-layer', 'layer-mask', 'channel', 'selection'):
        check(f'{output} / {precision.value_nick}', lambda o=output, p=precision: outputs(o, p))
check('Offset and selection clipping', offset_selection)
check('Existing mask protection and combination', existing_mask)
check('Noninteractive PDB execution', pdb_run)
check('Preview matches full-size mask', preview_matches)
check('XCF mask and metadata roundtrip', xcf_roundtrip)
(ROOT / 'work' / 'integration.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(f'{sum(r["pass"] for r in results)}/{len(results)} PASS')
