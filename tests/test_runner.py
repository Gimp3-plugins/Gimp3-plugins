"""Integration tests for pshost_runner against the synthetic mini filters. Usage: python -I test_runner.py <build_dir>"""
import os, subprocess, sys, tempfile, struct

B = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build")
RUN = os.path.join(B, "pshost_runner.exe")
fails = 0
def check(c, msg):
    global fails
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails += 1

def runner(args, timeout=30):
    p = subprocess.run([RUN] + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode & 0xFFFFFFFF, p.stdout

T = tempfile.mkdtemp(prefix="pshost_t_")
W, H = 40, 37
src = bytearray()
for y in range(H):
    for x in range(W):
        src += bytes([(x * 6) & 255, (y * 7) & 255, (x + y) & 255, (x * y) & 255])
fin, fout, fmask = (os.path.join(T, n) for n in ("in.raw", "out.raw", "mask.raw"))
open(fin, "wb").write(src)

def run_variant(variant, extra=()):
    plug = os.path.join(B, "mini", f"mini_{variant}.8bf")
    return runner(["--mode", "run", "--plugin", plug, "--entry", "PluginMain", "--width", str(W), "--height", str(H), "--in", fin, "--out", fout, *extra])

def inverted_ok(out, mask=None):
    for i in range(W * H):
        m = 255 if mask is None else mask[i]
        for c in range(3):
            exp = (255 - src[i*4+c]) if m == 255 else src[i*4+c]
            if out[i*4+c] != exp: return False
        if out[i*4+3] != src[i*4+3]: return False
    return True

for v in ("invert", "tiled"):
    rc, out = run_variant(v)
    check(rc == 0 and "RUN_OK" in out, f"{v}: exit 0")
    check(inverted_ok(open(fout, "rb").read()), f"{v}: RGB inverted, alpha preserved")

mask = bytes(255 if (i % W) < W // 2 else 0 for i in range(W * H))
open(fmask, "wb").write(mask)
rc, _ = run_variant("invert", ["--mask", fmask])
check(rc == 0 and inverted_ok(open(fout, "rb").read(), mask), "invert with selection mask: only selected half changed")

p1, p2 = os.path.join(T, "p1.bin"), os.path.join(T, "p2.bin")
rc, _ = run_variant("invert", ["--params-out", p1])
rc2, _ = run_variant("invert", ["--params-in", p1, "--params-out", p2])
check(rc == 0 and rc2 == 0 and struct.unpack("<i", open(p1, "rb").read())[0] == 1 and struct.unpack("<i", open(p2, "rb").read())[0] == 2, "parameters round trip (1 -> 2)")

rc, out = runner(["--mode", "probe", "--plugin", os.path.join(B, "mini", "mini_invert.8bf"), "--entry", "PluginMain"])
check(rc == 0 and "PROBE_PREPARE_OK unsupported=0" in out, "probe invert OK, nothing unsupported")

rc, out = runner(["--mode", "probe", "--plugin", os.path.join(B, "mini", "mini_crash.8bf"), "--entry", "PluginMain"])
check(rc == 0xC0DE0001 and "CRASH" in out, "crashing plug-in is contained (exit 0xC0DE0001)")

rc, out = runner(["--mode", "probe", "--plugin", os.path.join(B, "mini", "mini_hang.8bf"), "--entry", "PluginMain", "--timeout-ms", "1500"])
check(rc == 124 and "TIMEOUT" in out, "hanging plug-in is killed by watchdog (exit 124)")

rc, out = runner(["--mode", "probe", "--plugin", os.path.join(B, "mini", "mini_missingdep.8bf"), "--entry", "PluginMain"])
check(rc == 3 and "LOAD_FAILED win32=126" in out, "missing dependency -> cannot load (win32=126)")
dump = subprocess.run([os.path.join(B, "pe8bf_dump.exe"), os.path.join(B, "mini", "mini_missingdep.8bf")], capture_output=True, text=True).stdout
check("NO/missing-dep:absent_dep.dll" in dump, "static check names the missing DLL")
dump = subprocess.run([os.path.join(B, "pe8bf_dump.exe"), os.path.join(B, "mini", "mini_invert.8bf")], capture_output=True, text=True).stdout
check("OK/none" in dump and "json" in dump, "static check: mini_invert OK via JSON PiPL")

rc, out = runner(["--mode", "probe", "--plugin", os.path.join(B, "mini", "mini_invert.8bf"), "--entry", "NoSuchEntry"])
check(rc == 4, "missing entry point -> exit 4")


# --- pshost_check: combined static + dynamic verdicts, PL/EN messages ---
def run_check(lang, variant):
    plug = os.path.join(B, "mini", f"mini_{variant}.8bf")
    p = subprocess.run([os.path.join(B, "pshost_check.exe"), "--lang", lang, "--runner", RUN, "--timeout-ms", "3000", plug], capture_output=True, text=True, encoding="utf-8")
    return p.stdout
o = run_check("pl", "invert"); check("zostanie użyta w GIMP-ie" in o and o.startswith("OK	none"), "check PL: invert -> OK + zdanie po polsku")
o = run_check("en", "invert"); check("will be used in GIMP" in o, "check EN: invert -> OK + English sentence")
o = run_check("pl", "crash"); check(o.startswith("NO	probe-crash") and "uległa awarii" in o, "check PL: crash -> NO probe-crash")
o = run_check("en", "hang"); check(o.startswith("NO	probe-timeout") and "did not respond" in o, "check EN: hang -> NO probe-timeout")
o = run_check("pl", "missingdep"); check(o.startswith("NO	missing-dep") and "absent_dep.dll" in o, "check PL: missing dep named")
o = run_check("en", "invert"); check("passed the basic test" in o, "caveat line present")

# --- manager window model (headless, needs GIMP's GTK runtime) ---
GIMP = r"C:\gimp3"
if os.path.isdir(os.path.join(GIMP, "bin")):
    cfgdir = os.path.join(T, "cfg"); png = os.path.join(T, "ui.png")
    env = dict(os.environ, PATH=os.path.join(GIMP, "bin") + os.pathsep + os.environ["PATH"], XDG_DATA_DIRS=os.path.join(GIMP, "share"),
               PSHOST_CONFIG_DIR=cfgdir, PSHOST_RUNNER=RUN)
    def ui(lang, *dirs):
        return subprocess.run([os.path.join(B, "ui_snapshot.exe"), png, lang, *dirs], capture_output=True, text=True, env=env, timeout=120).stdout
    o = ui("en", os.path.join(B, "mini"))
    check("items=5 ok=2 warn=0 no=3 dirs=1 ignored=0 needs_restart=1 png=yes" in o, "UI: scanning mini dir -> 2 usable, 3 rejected")
    cfg = open(os.path.join(cfgdir, "config.json"), encoding="utf-8").read()
    import re
    has = lambda k, v: re.search(r'"%s"\s*:\s*"%s"' % (k, v), cfg) is not None
    check(has("verdict", "NO") and has("reason", "probe-crash") and has("reason", "missing-dep") and has("language", "en"), "UI: config.json written with verdicts/reasons")
    o = ui("pl", os.path.join(B, "mini"))   # same dir again: no duplicate, config reloaded
    check("items=5" in o and "dirs=1" in o, "UI: config reload, directory not duplicated")
    def ui_act(act):
        e = dict(env, PSHOST_TEST=act)
        return subprocess.run([os.path.join(B, "ui_snapshot.exe"), png, "en", os.path.join(B, "mini")], capture_output=True, text=True, env=e, timeout=120).stdout
    o = ui_act("remove-rejected"); check("items=2 ok=2 warn=0 no=0" in o and "ignored=3" in o, "UI: 'Remove rejected' drops the 3 rejected entries and remembers them")
    o = ui_act("rescan"); check("items=2" in o and "ignored=3" in o, "UI: rescan does not bring removed entries back")
    o = ui_act("restore"); check("items=5" in o and "ignored=0" in o, "UI: 'Restore removed' + rescan brings them back")
else:
    print("skip UI tests (GIMP runtime not found)")

print("failures:", fails)
sys.exit(1 if fails else 0)
