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

# Step 3: highlight recovery compensation brings brightness back
import struct
from gi.repository import Gegl


def mean_g(img, fmt="RGB float"):
    lay = img.get_layers()[0]
    buf = lay.get_buffer()
    e = buf.get_extent()
    w, h = min(800, e.width), min(800, e.height)
    data = buf.get(Gegl.Rectangle.new((e.width - w) // 2, (e.height - h) // 2, w, h), 1.0,
                   fmt, Gegl.AbyssPolicy.CLAMP)
    n = len(data) // 12
    v = struct.unpack("<%df" % (n * 3), data[: n * 12])
    return sum(v[1::3]) / n, max(v)


def load_raw(**props):
    proc = pdb.lookup_procedure("file-raw-heic-raw-load")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(SRC))
    cfg.set_property("half-size", True)
    for k, v in props.items():
        cfg.set_property(k.replace("_", "-"), v)
    r = proc.run(cfg)
    return r.index(1) if r.index(0) == Gimp.PDBStatusType.SUCCESS else None


ref = load_raw(); m_clip, _ = mean_g(ref); ref.delete()
for mode in ("unclip", "blend"):
    im = load_raw(highlight=mode); m_on, _ = mean_g(im); im.delete()
    im = load_raw(highlight=mode, highlight_compensate=False); m_off, _ = mean_g(im); im.delete()
    check("comp %s: brightness ~ clip (u16)" % mode, abs(m_on / m_clip - 1) < 0.08,
          "clip %.4f on %.4f off %.4f" % (m_clip, m_on, m_off))
    check("comp %s: off stays darker" % mode, m_off < m_clip * 0.75)
im = load_raw(highlight="unclip", depth="float")
m_f, mx = mean_g(im); im.delete()
check("comp float keeps highlights above 1.0", mx > 1.0 and abs(m_f / m_clip - 1) < 0.08,
      "mean %.4f max %.3f" % (m_f, mx))

# Step 3: HDR exposure for HEIC (PQ chart, patch 1.0 -> 2.0 at +1 EV)
hp = pdb.lookup_procedure("file-raw-heic-heif-load")
for ev, expect in ((0.0, 1.0), (1.0, 2.0)):
    cfg = hp.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(os.path.abspath("samples/heic/pq.heic")))
    cfg.set_property("hdr-exposure", ev)
    r = hp.run(cfg)
    im = r.index(1)
    g = im.get_layers()[0].get_pixel(int(1.5 * im.get_width() / 3), im.get_height() // 4).get_rgba()[1]
    check("HDR exposure %+.0f EV: reference patch = %.1f" % (ev, expect), abs(g - expect) < 0.02, "%.3f" % g)
    im.delete()
cfg = hp.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("file", Gio.File.new_for_path(os.path.abspath("samples/heic/pq.heic")))
cfg.set_property("hdr-mode", "builtin")
r = hp.run(cfg)
check("HDR builtin mode delegates", r.index(0) == Gimp.PDBStatusType.SUCCESS and
      "sRGB-TRC" in r.index(1).get_color_profile().get_label(), r.index(1).get_color_profile().get_label())

# Step 4: presets from scripts
proc = pdb.lookup_procedure("file-raw-heic-raw-load")
for preset, expect_ok in (("Fast preview", True), ("no such preset", False)):
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(SRC))
    cfg.set_property("preset", preset)
    r = proc.run(cfg)
    if expect_ok:
        im = r.index(1)
        check("preset 'Fast preview' gives half size", r.index(0) == Gimp.PDBStatusType.SUCCESS
              and im.get_width() == 3016, "%dx%d" % (im.get_width(), im.get_height()))
        im.delete()
    else:
        check("unknown preset refused", r.index(0) == Gimp.PDBStatusType.CALLING_ERROR,
              pdb.get_last_error()[:60])

# Step 6: lens corrections from the database shipped in the plug-in folder
def region_mean(img, x, y, size=64):
    buf = img.get_layers()[0].get_buffer()
    data = buf.get(Gegl.Rectangle.new(x, y, size, size), 1.0, "RGB float", Gegl.AbyssPolicy.CLAMP)
    n = len(data) // 12
    v = struct.unpack("<%df" % (n * 3), data[: n * 12])
    return sum(v[1::3]) / n

cr2 = os.path.abspath(os.path.join("samples", "Canon-EOS_6D.cr2"))
lp = pdb.lookup_procedure("file-raw-heic-raw-load")
means = {}
for vig in (False, True):
    cfg = lp.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(cr2))
    cfg.set_property("half-size", True)
    cfg.set_property("lens-vignetting", vig)
    r = lp.run(cfg)
    im = r.index(1)
    w, h = im.get_width(), im.get_height()
    means[vig] = (region_mean(im, 8, 8), region_mean(im, w // 2 - 32, h // 2 - 32))
    im.delete()
corner_gain = means[True][0] / means[False][0]
centre_gain = means[True][1] / means[False][1]
check("lensfun vignetting brightens corners", corner_gain > centre_gain * 1.03,
      "corner x%.3f centre x%.3f" % (corner_gain, centre_gain))

# Step 7: Apple HDR gain map (iPhone 13 Pro sample, MIT, johncf/apple-hdr-heic)
apple = os.path.abspath(os.path.join("samples", "heic-apple", "apple-hdr-sample.heic"))
if os.path.exists(apple):
    hp = pdb.lookup_procedure("file-raw-heic-heif-load")
    imgs = {}
    for mode in ("linear", "builtin"):
        cfg = hp.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("file", Gio.File.new_for_path(apple))
        cfg.set_property("hdr-mode", mode)
        r = hp.run(cfg)
        imgs[mode] = r.index(1) if r.index(0) == Gimp.PDBStatusType.SUCCESS else None
    hdr, sdr = imgs["linear"], imgs["builtin"]
    check("Apple HDR loads as float linear",
          hdr is not None and hdr.get_precision() == Gimp.Precision.FLOAT_LINEAR,
          str(hdr.get_precision()) if hdr else pdb.get_last_error())
    if hdr and sdr:
        def px(img):
            buf = img.get_layers()[0].get_buffer()
            e = buf.get_extent()
            data = buf.get(Gegl.Rectangle.new(0, 0, e.width, e.height), 1.0,
                           "RGB float", Gegl.AbyssPolicy.CLAMP)
            n = len(data) // 12
            return struct.unpack("<%df" % (n * 3), data[: n * 12])
        a, b = px(hdr), px(sdr)
        ratios = [a[i] / b[i] for i in range(1, len(a), 3 * 7) if b[i] > 0.02]
        mx = max(a)
        check("Apple HDR exceeds SDR white", mx > 1.2, "max %.2f" % mx)
        check("Apple HDR gain within [1, headroom]",
              min(ratios) > 0.97 and max(ratios) < 8.1 and max(ratios) > 1.3,
              "gain %.2f .. %.2f" % (min(ratios), max(ratios)))
    for im in imgs.values():
        if im:
            im.delete()

# Step 8: develop RAW files straight to a folder
import shutil
outdir = os.path.abspath(os.path.join("build", "test-out", "export"))
shutil.rmtree(outdir, ignore_errors=True)
os.makedirs(outdir)
srcs = [os.path.abspath(os.path.join("samples", f))
        for f in ("Nikon-D750.nef", "Canon-EOS_6D.cr2", "Olympus-E-M10_Mark_II.orf")]
ep = pdb.lookup_procedure("plug-in-raw-heic-batch-export")
for fmt in ("jpeg", "tiff16", "jpeg"):
    cfg = ep.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("files", srcs)
    cfg.set_property("output-folder", Gio.File.new_for_path(outdir))
    cfg.set_property("format", fmt)
    cfg.set_property("half-size", True)
    st = ep.run(cfg).index(0)
    check("export %s status" % fmt, st == Gimp.PDBStatusType.SUCCESS, pdb.get_last_error()[:60])
names = sorted(os.listdir(outdir))
check("export files written (3 jpg, 3 tif, 3 jpg -2)",
      len([n for n in names if n.endswith(".jpg")]) == 6 and
      len([n for n in names if n.endswith(".tif")]) == 3 and
      "Nikon-D750-2.jpg" in names, " ".join(names))
# re-open one result: 16-bit TIFF with a colour profile
tif = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(os.path.join(outdir, "Nikon-D750.tif")))
check("exported TIFF is 16-bit, half size",
      tif is not None and "U16" in str(tif.get_precision().value_nick).upper() and tif.get_width() == 3016,
      "%s %dx%d" % (tif.get_precision().value_nick, tif.get_width(), tif.get_height()) if tif else "")
if tif:
    tif.delete()

with open(os.path.join("build", "test-out", "regressions.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
