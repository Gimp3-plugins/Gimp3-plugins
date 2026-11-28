"""Real GTK panel inside GIMP, on a synthetic test image only."""
from pathlib import Path
from array import array
import os
import sys
import json
import traceback
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl
ROOT = Path(os.environ['ZETMAR_MASKI_TEST_ROOT'])
sys.path.insert(0, str(ROOT/'plug-ins'/'zetmar-maski'))
from zm_ui import Panel
from zm_gimp import apply
from zm_core import Settings
Gegl.init(None)
image = Gimp.Image.new_with_precision(600, 400, Gimp.ImageBaseType.RGB, Gimp.Precision.FLOAT_LINEAR)
layer = Gimp.Layer.new(image, 'Zdjęcie testowe — jasność i kolor', 600, 400, Gimp.ImageType.RGBA_IMAGE, 100., Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
pixels = array('f')
for y in range(400):
    for x in range(600):
        if y < 250:
            v = .3+.7*x/599
            rgb = (v*.55, v*.75, v)
        else:
            v = .1+.7*x/599
            rgb = (v*.7, v, v*.4)
        pixels.extend((*rgb, 1.))
buf = layer.get_buffer()
buf.set(Gegl.Rectangle.new(0, 0, 600, 400), "R'G'B'A float", pixels.tobytes())
buf.flush()
proc = Gimp.get_pdb().lookup_procedure('python-fu-zetmar-maski')
cfg = proc.create_config()
report = {}
try:
    panel = Panel(image, layer, cfg)
    accepted = panel.run()
    report['accepted'] = accepted
    if accepted:
        settings = Settings(**{key: cfg.get_property(key.replace('_', '-')) for key in Settings.__dataclass_fields__})
        apply(image, layer, settings, cfg.get_property('output'), cfg.get_property('name'))
        report['settings'] = settings.__dict__
        report['output'] = cfg.get_property('output')
        report['layers'] = len(image.get_layers())
        report['channels'] = len(image.get_channels())
        report['mask'] = image.get_layers()[0].get_mask() is not None
except Exception:
    report['error'] = traceback.format_exc()
finally:
    (ROOT/'work'/'ui-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    image.delete()
