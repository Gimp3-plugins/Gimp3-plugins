# Tests for the features added after 1.0 (run in gimp-console, see run-tests.ps1):
# crop / straighten, base tone curve, automatic camera profile, HDR export,
# applying settings to other files, images returned by batch open.
import os
import shutil
import struct

from gi.repository import Gimp, Gio, Gegl

pdb = Gimp.get_pdb()
lines = []
NEF = os.path.abspath(os.path.join("samples", "Nikon-D750.nef"))
CR2 = os.path.abspath(os.path.join("samples", "Canon-EOS_6D.cr2"))
OUT = os.path.abspath(os.path.join("build", "test-out", "features"))
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)


def check(name, ok, detail=""):
    lines.append("%s %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


def mean_g(img):
    lay = img.get_layers()[0]
    buf = lay.get_buffer()
    e = buf.get_extent()
    w, h = min(800, e.width), min(800, e.height)
    data = buf.get(Gegl.Rectangle.new((e.width - w) // 2, (e.height - h) // 2, w, h), 1.0,
                   "RGB float", Gegl.AbyssPolicy.CLAMP)
    n = len(data) // 12
    v = struct.unpack("<%df" % (n * 3), data[: n * 12])
    return sum(v[1::3]) / n


def load_raw(path=NEF, **props):
    proc = pdb.lookup_procedure("file-raw-heic-raw-load")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(path))
    cfg.set_property("half-size", True)
    cfg.set_property("xmp-sidecar", False)
    for k, v in props.items():
        cfg.set_property(k.replace("_", "-"), v)
    r = proc.run(cfg)
    return r.index(1) if r.index(0) == Gimp.PDBStatusType.SUCCESS else None


def setting(img, key):
    par = img.get_parasite("gimp-raw-heic-source")
    txt = bytes(par.get_data()).decode("utf-8").rstrip("\0")
    for l in txt.splitlines():
        if l.startswith(key + "="):
            return l.split("=", 1)[1]
    return None


# --- crop and straighten -------------------------------------------------
full = load_raw()
fw, fh = full.get_width(), full.get_height()
crop = load_raw(crop_x=0.25, crop_y=0.1, crop_width=0.5, crop_height=0.4)
check("crop: size", crop and crop.get_width() == round(fw * 0.5) and crop.get_height() == round(fh * 0.4),
      "%dx%d of %dx%d" % (crop.get_width(), crop.get_height(), fw, fh) if crop else "failed")
# the cut-out shows the same place: compare a pixel
if crop:
    a = full.get_layers()[0].get_pixel(round(fw * 0.25) + 10, round(fh * 0.1) + 10).get_rgba()
    b = crop.get_layers()[0].get_pixel(10, 10).get_rgba()
    check("crop: same pixels", all(abs(x - y) < 1e-4 for x, y in zip(a[:3], b[:3])),
          "%s / %s" % (["%.4f" % x for x in a[:3]], ["%.4f" % x for x in b[:3]]))
    check("crop: stored in the image", setting(crop, "crop") is not None, setting(crop, "crop") or "")
    crop.delete()

rot = load_raw(straighten=5.0)
if rot:
    c = rot.get_layers()[0].get_pixel(0, 0).get_rgba()
    check("straighten: same size, no empty corner",
          rot.get_width() == fw and rot.get_height() == fh and max(c[:3]) > 0.0005,
          "%dx%d corner %.4f" % (rot.get_width(), rot.get_height(), max(c[:3])))
    rot.delete()
else:
    check("straighten: loads", False, pdb.get_last_error())

# --- base tone curve -----------------------------------------------------
m_none = mean_g(full)
tone = load_raw(tone_curve="strong")
m_tone = mean_g(tone) if tone else 0
check("tone curve strong darkens a dark linear image", tone and 0.3 * m_none < m_tone < m_none,
      "%.4f -> %.4f" % (m_none, m_tone))
if tone:
    tone.delete()
full.delete()

# --- automatic camera profile -------------------------------------------
pfolder = os.path.join(OUT, "profiles")
os.makedirs(pfolder)
adobe = os.path.join(os.environ.get("PROGRAMDATA", ""), "Adobe", "CameraRaw", "CameraProfiles",
                     "Adobe Standard", "Nikon D750 Adobe Standard.dcp")
if os.path.exists(adobe):
    shutil.copyfile(adobe, os.path.join(pfolder, "Nikon D750 Adobe Standard.dcp"))
    auto = load_raw(auto_profile=True, profile_folder=Gio.File.new_for_path(pfolder))
    expl = load_raw(camera_profile=Gio.File.new_for_path(adobe))
    plain = load_raw()
    ma, me, mp = mean_g(auto), mean_g(expl), mean_g(plain)
    check("auto profile = explicit DCP", abs(ma - me) < 1e-5, "%.5f / %.5f (built-in %.5f)" % (ma, me, mp))
    for im in (auto, expl, plain):
        im.delete()
else:
    lines.append("SKIP auto profile (no Adobe D750 profile on this machine)")

# --- HDR export: PQ and HLG, HEIC and AVIF, read back ----------------------
pq = os.path.abspath(os.path.join("samples", "heic", "pq.heic"))
hl = pdb.lookup_procedure("file-raw-heic-heif-load")
ex = pdb.lookup_procedure("file-raw-heic-hdr-export")


def load_heif(path):
    cfg = hl.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("file", Gio.File.new_for_path(path))
    r = hl.run(cfg)
    return r.index(1) if r.index(0) == Gimp.PDBStatusType.SUCCESS else None


def patches(img):
    lay = img.get_layers()[0]
    w, h = img.get_width(), img.get_height()
    return [lay.get_pixel(int((i + 0.5) * w / 3), h // 4).get_rgba()[1] for i in range(3)]


src = load_heif(pq)
if src:
    ref = patches(src)
    for ext, transfer in (("heic", "pq"), ("avif", "pq"), ("heic", "hlg")):
        fn = os.path.join(OUT, "out-%s.%s" % (transfer, ext))
        cfg = ex.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("image", src)
        cfg.set_property("file", Gio.File.new_for_path(fn))
        cfg.set_property("transfer", transfer)
        cfg.set_property("quality", 95)
        st = ex.run(cfg).index(0)
        back = load_heif(fn) if st == Gimp.PDBStatusType.SUCCESS else None
        got = patches(back) if back else []
        # HLG reaches only ~3.76x its reference white: brighter values clip
        lim = [min(r, 3.76) if transfer == "hlg" else r for r in ref]
        ok = back is not None and all(abs(g - r) / r < 0.04 for g, r in zip(got, lim))
        check("HDR export %s %s round trip" % (transfer, ext), ok,
              "%s -> %s %s" % (["%.3f" % r for r in ref], ["%.3f" % g for g in got],
                               "" if st == Gimp.PDBStatusType.SUCCESS else pdb.get_last_error()[:50]))
        if back:
            back.delete()
    src.delete()
else:
    lines.append("SKIP HDR export (samples/heic/pq.heic missing)")

# --- batch open returns its images ------------------------------------------
bp = pdb.lookup_procedure("plug-in-raw-heic-batch-open")
cfg = bp.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("files", [NEF, CR2])
cfg.set_property("half-size", True)
r = bp.run(cfg)
imgs = r.get_core_object_array(1) or []
check("batch open returns the images", r.index(0) == Gimp.PDBStatusType.SUCCESS and len(imgs) == 2,
      str(len(imgs)))
for im in imgs:
    im.delete()

# --- apply these settings to other files --------------------------------------
master = load_raw(exposure=1.0, wb_mode="manual", wb_temperature=4000.0, crop_width=0.5)
sp = pdb.lookup_procedure("plug-in-raw-heic-sync-settings")
cfg = sp.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("image", master)
cfg.set_property("files", [CR2])
r = sp.run(cfg)
imgs = r.get_core_object_array(1) or []
ok = r.index(0) == Gimp.PDBStatusType.SUCCESS and len(imgs) == 1
check("sync: one image opened", ok, pdb.get_last_error()[:60] if not ok else "")
if ok:
    im = imgs[0]
    check("sync: settings copied", setting(im, "exposure") == "1" and setting(im, "wb-mode") == "manual"
          and setting(im, "wb-temperature") == "4000",
          "exposure=%s wb=%s %s" % (setting(im, "exposure"), setting(im, "wb-mode"),
                                    setting(im, "wb-temperature")))
    check("sync: crop not copied by default", setting(im, "crop").startswith("0;0;1;1"),
          setting(im, "crop"))
    im.delete()
master.delete()

# a network camera profile stored in the image must not be followed
master = load_raw()
par = master.get_parasite("gimp-raw-heic-source")
txt = bytes(par.get_data()).decode("utf-8").rstrip("\0")
txt += "\ncamera-profile=\\\\example.invalid\\share\\cam.dcp\nprofile-folder=//example.invalid/p\n"
master.attach_parasite(Gimp.Parasite.new("gimp-raw-heic-source", 1, (txt + "\0").encode("utf-8")))
cfg = sp.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("image", master)
cfg.set_property("files", [CR2])
r = sp.run(cfg)
imgs = r.get_core_object_array(1) or []
ok = r.index(0) == Gimp.PDBStatusType.SUCCESS and len(imgs) == 1
check("sync: network profile paths dropped",
      ok and (setting(imgs[0], "camera-profile") or "") == ""
      and (setting(imgs[0], "profile-folder") or "") == "",
      pdb.get_last_error()[:60] if not ok else "")
for im in imgs:
    im.delete()
master.delete()

with open(os.path.join("build", "test-out", "features.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
