"""Run inside GIMP with the installed plug-in directory in plug-in-path."""
import json
from pathlib import Path
import gi

gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

root = Path(__file__).resolve().parents[1]
work = root / 'tests' / 'output' / 'installed-smoke'
work.mkdir(parents=True, exist_ok=True)
settings = work / 'lut-settings.json'
settings.write_text(json.dumps({'bimp3': 1, 'steps': [
    {'type': 'lut', 'settings': {'file': str(root / 'examples' / 'warm-demo.cube'), 'strength': 100.0}},
    {'type': 'changeformat', 'settings': {'format': 4, 'arguments': {'compression': 2}}}
]}), encoding='utf-8')
source = root / 'tests' / 'output' / 'źródło.png'
proc = Gimp.get_pdb().lookup_procedure('plug-in-bimp3')
assert proc is not None
cfg = proc.create_config()
cfg.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
cfg.set_property('settings-file', str(settings))
cfg.set_property('input-files', json.dumps([str(source)]))
cfg.set_property('output-directory', str(work / 'out'))
cfg.set_property('overwrite', True)
returned = proc.run(cfg)
assert returned.index(0) == Gimp.PDBStatusType.SUCCESS, str(returned.index(1)) if returned.length() > 1 else ''
target = work / 'out' / source.name
original = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
output = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(target)))
try:
    assert (output.get_width(), output.get_height()) == (80, 40)
    before = original.get_layers()[0].get_pixel(70, 10).get_rgba()
    after = output.get_layers()[0].get_pixel(70, 10).get_rgba()
    assert after[2] < before[2] - .05, (before, after)
finally:
    original.delete()
    output.delete()
(root / 'tests' / 'installed-result.json').write_text(json.dumps({'gimp': Gimp.version(), 'installed_pdb_lut_export': 'passed'}), encoding='utf-8')
print('INSTALLED_BIMP_LUT_EXPORT_OK')
