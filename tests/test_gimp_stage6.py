"""Stage 6 tests in a real GIMP 3 (gimp-console): dynamic menu procedures (init_procedures), registered-state file,
and the restart mechanism (helper waits for the process to exit, relaunches, never fires on cancelled quit).
Usage: python -I test_gimp_stage6.py <build_dir>"""
import hashlib, json, os, subprocess, sys, tempfile, time

B = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build")
GIMP = r"C:\gimp3"
CONSOLE = os.path.join(GIMP, "bin", "gimp-console-3.2.exe")
PLUG = os.path.join(os.environ.get("APPDATA", ""), "GIMP", "3.2", "plug-ins", "pshost", "pshost.exe")
if not (os.path.exists(CONSOLE) and os.path.exists(PLUG)):
    print("skip stage 6 tests (GIMP or installed plug-in not found)"); sys.exit(0)

fails = 0
def check(c, msg):
    global fails
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails += 1

T = tempfile.mkdtemp(prefix="pshost_s6_")
CFG = os.path.join(T, "cfg")
RUNNER = os.path.join(B, "pshost_runner.exe")
env = dict(os.environ, PATH=os.path.join(GIMP, "bin") + os.pathsep + os.environ["PATH"], XDG_DATA_DIRS=os.path.join(GIMP, "share"),
           PSHOST_CONFIG_DIR=CFG, PSHOST_RUNNER=RUNNER)
subprocess.run([os.path.join(B, "ui_snapshot.exe"), os.path.join(T, "x.png"), "en", os.path.join(B, "mini")], env=env, capture_output=True, timeout=120)
cfg = json.load(open(os.path.join(CFG, "config.json"), encoding="utf-8"))
inv = [p for p in cfg["plugins"] if p["name"] == "PSHost Test invert..."][0]
proc = "pshost-filter-" + hashlib.md5(f'{inv["path"]}|{inv["entry"]}|{inv["name"]}'.encode()).hexdigest()[:12]

def console(scm, extra_env=None):
    e = dict(env, **(extra_env or {}))
    return subprocess.run([CONSOLE, "-i", "--batch-interpreter", "plug-in-script-fu-eval", "--batch", scm, "--quit"], env=e, capture_output=True, text=True, timeout=180)

# --- 1. the dynamic procedure exists and runs (pixels inverted) via the PDB
png = os.path.join(T, "o.png").replace("\\", "/")
scm = f'''(let* ((image (car (gimp-image-new 40 30 RGB))) (layer (car (gimp-layer-new image "L" 40 30 RGBA-IMAGE 100 LAYER-MODE-NORMAL))))
  (gimp-image-insert-layer image layer 0 0) (gimp-context-set-foreground '(51 102 153)) (gimp-drawable-edit-fill layer FILL-FOREGROUND)
  ({proc} RUN-NONINTERACTIVE image (vector layer))
  (file-png-export RUN-NONINTERACTIVE image "{png}" 0 0 0 0 0 0 0 0 0))'''
r = console(scm)
check(os.path.exists(png) and os.path.getsize(png) > 100, f"dynamic procedure {proc} is registered and callable")
if os.path.exists(png):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pngutil import decode_png
    w, h, bpp, rows = decode_png(png)
    check(all(tuple(rows[y][x * bpp:x * bpp + 3]) == (204, 153, 102) for x in range(w) for y in range(h)), "menu procedure result: layer inverted")

# --- 2. registered state written by init_procedures
reg = json.load(open(os.path.join(CFG, "registered.json"), encoding="utf-8"))
mine = [f for f in reg["filters"] if f["proc"] == proc]
check(len(reg["filters"]) == 2 and mine and mine[0]["menu"] == "<Image>/Filters/Photoshop/PSHost Tests" and mine[0]["label"] == "PSHost Test invert...", "registered.json lists the 2 usable filters with menu path and label")

# --- 3. restart helper: waits for the process, then relaunches (marker file)
marker = os.path.join(T, "m1.txt")
victim = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(2.5)"])
helper = subprocess.Popen([RUNNER, "--mode", "restart", "--pid", str(victim.pid), "--exe", "C:\\Windows\\System32\\cmd.exe", "--args", f'/c echo launched> "{marker}"', "--wait-ms", "15000", "--log", os.path.join(T, "h1.log")])
time.sleep(1.0)
check(not os.path.exists(marker), "helper does not relaunch while the old process is still running")
victim.wait(); helper.wait(timeout=20)
check(helper.returncode == 0 and os.path.exists(marker), "helper relaunches after the old process exited")

# --- 4. cancelled quit: the process never exits within wait-ms -> helper gives up, nothing launched
marker = os.path.join(T, "m2.txt")
victim = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(6)"])
helper = subprocess.run([RUNNER, "--mode", "restart", "--pid", str(victim.pid), "--exe", "C:\\Windows\\System32\\cmd.exe", "--args", f'/c echo launched> "{marker}"', "--wait-ms", "1000"], capture_output=True, text=True, timeout=30)
victim.kill()
check(helper.returncode == 124 and not os.path.exists(marker), "cancelled quit: helper times out (124) and does not start GIMP")

# --- 5. pshost-restart procedure inside GIMP: finds the parent process, helper outlives it
marker = os.path.join(T, "m3.txt")
r = console("(pshost-restart RUN-NONINTERACTIVE)", {"PSHOST_GIMP_EXE_OVERRIDE": "C:\\Windows\\System32\\cmd.exe", "PSHOST_GIMP_ARGS": f'/c echo restarted> "{marker}"', "PSHOST_NO_QUIT": "1"})
for _ in range(40):
    if os.path.exists(marker): break
    time.sleep(0.5)
check(os.path.exists(marker), "pshost-restart: helper started from GIMP, waited for its exit and relaunched (outlived GIMP)")
log = open(os.path.join(CFG, "restart.log"), encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(CFG, "restart.log")) else ""
check("RESTART_LAUNCHED" in log and "waiting for pid" in log, "restart.log records waiting + launch")

# --- 6. window: "restart needed" detection and the consent flow (stubbed hooks, headless) ---
def ui(lang, act=None, fresh_cfg=None):
    e = dict(env); 
    if act: e["PSHOST_TEST"] = act
    return subprocess.run([os.path.join(B, "ui_snapshot.exe"), os.path.join(T, "y.png"), lang, os.path.join(B, "mini")], env=e, capture_output=True, text=True, timeout=120).stdout
check("needs_restart=0" in ui("en"), "window: no restart needed when the registered set matches the configuration")
check("needs_restart=1" in ui("pl"), "window: changing the menu language requires a restart")
o = ui("pl", "close-later"); check("restart_calls=0" in o and "dirty_asked=1" in o, "closing with pending changes: asks about unsaved images; answer 'later' does not restart")
o = ui("pl", "close-restart"); check("restart_calls=1" in o and "dirty_asked=1" in o, "answer 'restart now' triggers exactly one restart request")
o = ui("en", "close-restart"); check("restart_calls=0" in o, "no restart request when nothing changed")

print("failures:", fails)
sys.exit(1 if fails else 0)
