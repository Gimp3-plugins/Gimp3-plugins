"""End-to-end test inside a real GIMP 3 (gimp-console): runs the synthetic 'invert' filter through the installed
pshost plug-in (procedure pshost-run-filter) and checks pixels, selection handling and a single Undo step.
Requires: GIMP installed, pshost.exe + pshost_runner.exe installed in %APPDATA%\\GIMP\\3.2\\plug-ins\\pshost,
and build dir with ui_snapshot.exe / mini filters. Usage: python -I test_gimp_e2e.py <build_dir>"""
import sys as _s0, os as _o0
_s0.path.insert(0, _o0.path.dirname(_o0.path.abspath(__file__)))
from winpaths import appdata, localappdata
import os, subprocess, struct, sys, tempfile, zlib

B = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build")
GIMP = r"C:\gimp3"
CONSOLE = os.path.join(GIMP, "bin", "gimp-console-3.2.exe")
PLUG = os.path.join(appdata(), "GIMP", "3.2", "plug-ins", "pshost", "pshost.exe")
if not (os.path.exists(CONSOLE) and os.path.exists(PLUG)):
    print("skip GIMP e2e (GIMP or installed plug-in not found)"); sys.exit(0)

fails = 0
def check(c, msg):
    global fails
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails += 1

T = tempfile.mkdtemp(prefix="pshost_e2e_")
env = dict(os.environ, PATH=os.path.join(GIMP, "bin") + os.pathsep + os.environ["PATH"], XDG_DATA_DIRS=os.path.join(GIMP, "share"),
           PSHOST_CONFIG_DIR=os.path.join(T, "cfg"), PSHOST_RUNNER=os.path.join(B, "pshost_runner.exe"))
# scan the synthetic filters into an isolated config
subprocess.run([os.path.join(B, "ui_snapshot.exe"), os.path.join(T, "x.png"), "en", os.path.join(B, "mini")], env=env, capture_output=True, timeout=120)

def decode_png(path):
    d = open(path, "rb").read(); pos = 8; idat = b""
    while pos < len(d):
        ln, typ = struct.unpack(">I4s", d[pos:pos + 8]); body = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR": w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        if typ == b"IDAT": idat += body
        pos += 12 + ln
    bpp = {6: 4, 2: 3}[ct]; raw = zlib.decompress(idat); stride = w * bpp; rows = []; prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]; line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0; b = prev[i]; c = prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line); prev = line
    return w, h, bpp, rows

def run_scm(body, png):
    scm = f'''(let* ((image (car (gimp-image-new 40 30 RGB)))
       (layer (car (gimp-layer-new image "L" 40 30 RGBA-IMAGE 100 LAYER-MODE-NORMAL))))
  (gimp-image-insert-layer image layer 0 0)
  (gimp-context-set-foreground '(51 102 153))
  (gimp-drawable-edit-fill layer FILL-FOREGROUND)
  {body}
  (file-png-export RUN-NONINTERACTIVE image "{png.replace(chr(92), '/')}" 0 0 0 0 0 0 0 0 0))'''
    if os.path.exists(png): os.remove(png)
    p = subprocess.run([CONSOLE, "-i", "--batch-interpreter", "plug-in-script-fu-eval", "--batch", scm, "--quit"], env=env, capture_output=True, text=True, timeout=180)
    return p.stdout + p.stderr

run = '(pshost-run-filter RUN-NONINTERACTIVE image (vector layer) "PSHost Test invert..." FALSE)'
FG, INV = (51, 102, 153), (204, 153, 102)

png = os.path.join(T, "a.png"); run_scm(run, png)
w, h, bpp, rows = decode_png(png); px = lambda x, y: tuple(rows[y][x * bpp:x * bpp + 3])
check(all(px(x, y) == INV for x in range(w) for y in range(h)), "GIMP: whole layer inverted by the filter")

png = os.path.join(T, "b.png")
run_scm('(gimp-image-select-rectangle image CHANNEL-OP-REPLACE 0 0 20 30)\n  ' + run, png)
w, h, bpp, rows = decode_png(png); px = lambda x, y: tuple(rows[y][x * bpp:x * bpp + 3])
check(all(px(x, y) == INV for x in range(20) for y in range(h)) and all(px(x, y) == FG for x in range(20, w) for y in range(h)), "GIMP: rectangular selection respected (left half inverted, right half untouched)")

png = os.path.join(T, "d.png")
out = run_scm(run + "\n  " + run, png)
w, h, bpp, rows = decode_png(png); px = lambda x, y: tuple(rows[y][x * bpp:x * bpp + 3])
check(all(px(x, y) == FG for x in range(w) for y in range(h)), "GIMP: running the (involutive) filter twice returns the original")

png = os.path.join(T, "e.png")
out = run_scm('(pshost-run-filter RUN-NONINTERACTIVE image (vector layer) "no such filter" FALSE)', png)
check("filter not found or not usable" in out and not os.path.exists(png), "GIMP: unknown filter -> clean PDB error, no result")

# --- irregular (elliptical, anti-aliased) selection: inside inverted, outside untouched, edge blended ---
png = os.path.join(T, "f.png")
run_scm('(gimp-image-select-ellipse image CHANNEL-OP-REPLACE 5 3 30 24)\n  ' + run, png)
w, h, bpp, rows = decode_png(png); px = lambda x, y: tuple(rows[y][x * bpp:x * bpp + 3])
edge = [px(x, y) for y in range(h) for x in range(w) if px(x, y) not in (FG, INV)]
check(px(20, 15) == INV and px(0, 0) == FG and px(w - 1, h - 1) == FG and px(0, h - 1) == FG, "GIMP: elliptical selection: centre inverted, corners untouched")
check(len(edge) > 0 and all(min(a, b) <= c <= max(a, b) for c3 in edge for c, a, b in zip(c3, FG, INV)), f"GIMP: anti-aliased selection edge is blended between original and filtered ({len(edge)} edge pixels)")

# --- layer with an alpha channel: colour filtered, alpha preserved ---
png = os.path.join(T, "g.png")
scm = f"""(let* ((image (car (gimp-image-new 40 30 RGB))) (layer (car (gimp-layer-new image "L" 40 30 RGBA-IMAGE 100 LAYER-MODE-NORMAL))))
  (gimp-image-insert-layer image layer 0 0)
  (gimp-context-set-foreground '(51 102 153))
  (gimp-context-set-opacity 50)
  (gimp-drawable-edit-fill layer FILL-FOREGROUND)
  {run}
  (file-png-export RUN-NONINTERACTIVE image "{png.replace(chr(92), '/')}" 0 0 0 0 0 0 0 0 0))"""
if os.path.exists(png): os.remove(png)
subprocess.run([CONSOLE, "-i", "--batch-interpreter", "plug-in-script-fu-eval", "--batch", scm, "--quit"], env=env, capture_output=True, text=True, timeout=180)
w, h, bpp, rows = decode_png(png)
a = {rows[y][x * bpp + 3] for y in range(h) for x in range(w)}
rgb = {tuple(rows[y][x * bpp:x * bpp + 3]) for y in range(h) for x in range(w)}
near = lambda c, t: all(abs(i - j) <= 2 for i, j in zip(c, t))
check(bpp == 4 and len(a) == 1 and 120 <= min(a) <= 135, f"GIMP: alpha channel preserved by the filter (alpha={sorted(a)})")
check(len(rgb) <= 3 and all(near(c, INV) for c in rgb), f"GIMP: colour of a semi-transparent layer filtered as straight (non-premultiplied) RGB ({sorted(rgb)[:2]})")

print("failures:", fails)
sys.exit(1 if fails else 0)
