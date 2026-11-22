import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl
import json
from pathlib import Path

Gegl.init(None)
info = {"version": Gimp.version(), "procedures": {}}
for name in [
    "file-png-export",
    "file-jpeg-export",
    "file-gif-export",
    "file-bmp-export",
    "file-ico-export",
    "file-tga-export",
    "file-tiff-export",
    "file-heif-export",
    "file-webp-export",
    "file-heif-av1-export",
    "file-exr-export",
    "gimp-xcf-save",
]:
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc:
        info["procedures"][name] = [
            {
                "name": p.name,
                "type": p.value_type.name,
                "default": str(proc.create_config().get_property(p.name)),
                "blurb": p.blurb,
            }
            for p in proc.create_config().list_properties()
            if p.name != "procedure"
        ]
image = Gimp.Image.new(32, 24, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(image, "test", 32, 24, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
info["filters"] = {}
for op in ["gegl:gaussian-blur", "gegl:unsharp-mask"]:
    f = Gimp.DrawableFilter.new(layer, op, op)
    info["filters"][op] = [
        {"name": p.name, "type": p.value_type.name, "default": str(f.get_config().get_property(p.name))}
        for p in f.get_config().list_properties()
    ]
    f.delete()
image.delete()
Path(__file__).with_name("probe-result.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print("BIMP_PROBE_OK")
