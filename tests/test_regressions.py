# Regression tests for fixed bugs (run in gimp-console, see run-tests.ps1).
import os
from gi.repository import Gimp, Gio

pdb = Gimp.get_pdb()
lines = []
SRC = os.path.abspath(os.path.join("samples", "Nikon-D750.nef"))


def check(name, ok, detail=""):
    lines.append("%s %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def load(path=SRC):
    return Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))


def run(proc_name, **props):
    proc = pdb.lookup_procedure(proc_name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    for k, v in props.items():
        if k == "drawables":
            cfg.set_core_object_array("drawables", v)
        else:
            cfg.set_property(k.replace("_", "-"), v)
    r = proc.run(cfg)
    return r.index(0)


# B1: re-develop (replace) keeps the layer's effects, mask, mode, opacity, offsets
img = load()
lay = img.get_layers()[0]
run("plug-in-raw-heic-quick-adjust", image=img, drawables=[lay], exposure=0.7)
lay.set_mode(Gimp.LayerMode.MULTIPLY)
lay.set_opacity(55.0)
lay.set_name("my edit")
lay.add_mask(lay.create_mask(Gimp.AddMaskType.WHITE))
before = lay.get_pixel(100, 100).get_rgba()
st = run("plug-in-raw-heic-redevelop", image=img, exposure=1.0)
lay2 = img.get_layers()[0]
after = lay2.get_pixel(100, 100).get_rgba()
check("B1 redevelop status", st == Gimp.PDBStatusType.SUCCESS, str(st))
check("B1 same layer kept", lay2.get_id() == lay.get_id())
check("B1 effects kept", len(lay2.get_filters() or []) == 1, str(len(lay2.get_filters() or [])))
check("B1 mode/opacity/name kept",
      lay2.get_mode() == Gimp.LayerMode.MULTIPLY and abs(lay2.get_opacity() - 55) < 0.1
      and lay2.get_name() == "my edit")
check("B1 mask kept", lay2.get_mask() is not None)
check("B1 pixels changed (+1 EV)", after[1] > before[1] * 1.5, "%.4f -> %.4f" % (before[1], after[1]))

# B1: size change resizes layer and canvas
st = run("plug-in-raw-heic-redevelop", image=img, half_size=True)
lay3 = img.get_layers()[0]
check("B1 half size resizes layer+canvas",
      lay3.get_width() == img.get_width() == 3016 and lay3.get_height() == img.get_height() == 2016,
      "%dx%d / %dx%d" % (lay3.get_width(), lay3.get_height(), img.get_width(), img.get_height()))

# B1: an active selection must not limit the replacement, and is restored
img.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 50, 50)
px_out_before = lay3.get_pixel(1000, 1000).get_rgba()
st = run("plug-in-raw-heic-redevelop", image=img, half_size=True, exposure=-1.0)
px_out_after = img.get_layers()[0].get_pixel(1000, 1000).get_rgba()
bounds = Gimp.Selection.bounds(img)
check("B1 pixels outside the selection replaced", px_out_after[1] < px_out_before[1] * 0.75,
      "%.4f -> %.4f" % (px_out_before[1], px_out_after[1]))
check("B1 selection restored", bounds[1] and bounds[4] == 50 and bounds[5] == 50, str(bounds))
img.delete()

# Security: a network path stored in the image is refused non-interactively
img = load()
par = img.get_parasite("gimp-raw-heic-source")
txt = bytes(par.get_data()).decode("utf-8").rstrip("\0")
txt = "\n".join(("source=\\\\\\\\example.invalid\\\\share\\\\x.nef" if l.startswith("source=") else l)
                for l in txt.splitlines())
img.attach_parasite(Gimp.Parasite.new("gimp-raw-heic-source", 1, (txt + "\0").encode("utf-8")))
st = run("plug-in-raw-heic-redevelop", image=img)
err = pdb.get_last_error()
check("UNC path refused (non-interactive)", st == Gimp.PDBStatusType.EXECUTION_ERROR, err[:70])
img.delete()

# B7: thumbnail reports the size after the camera's default crop
proc = pdb.lookup_procedure("file-raw-heic-raw-load-thumb")
cfg = proc.create_config()
cfg.set_property("file", Gio.File.new_for_path(os.path.abspath(os.path.join("samples", "Canon-EOS_6D.cr2"))))
cfg.set_property("thumb-size", 128)
r = proc.run(cfg)
check("B7 thumbnail full size = cropped size", (r.index(2), r.index(3)) == (5472, 3648),
      "%dx%d" % (r.index(2), r.index(3)))

with open(os.path.join("build", "test-out", "regressions.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
