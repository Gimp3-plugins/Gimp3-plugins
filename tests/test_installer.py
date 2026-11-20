"""Installer tests (silent, isolated: uses /GIMPDATA so the real GIMP user directory is never touched).
Usage: python -I test_installer.py <build_dir>   -- builds the installer with ISCC first."""
import os, shutil, subprocess, sys, tempfile, time, winreg

B = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISCC = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Inno Setup 6", "ISCC.exe")
VER = "0.8.0"
if not os.path.exists(ISCC):
    print("skip installer tests (Inno Setup 6 not found)"); sys.exit(0)

fails = 0
def check(c, msg):
    global fails
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails += 1

r = subprocess.run([ISCC, "/Q", f"/DAppVersion={VER}", f"/DBuildDir={B}", os.path.join(ROOT, "installer", "PSHost.iss")], capture_output=True, text=True)
SETUP = os.path.join(ROOT, "installer", "output", f"PSHost-Setup-{VER}.exe")
check(r.returncode == 0 and os.path.exists(SETUP), f"installer compiles: PSHost-Setup-{VER}.exe ({os.path.getsize(SETUP) // 1024 if os.path.exists(SETUP) else 0} KB)")

T = tempfile.mkdtemp(prefix="pshost_inst_")
DATA = os.path.join(T, "AppData", "GIMP", "3.2")
PLUG = os.path.join(DATA, "plug-ins", "pshost")
UNINS = os.path.join(os.environ["LOCALAPPDATA"], "PSHost", "unins000.exe")
KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{D65CF174-798E-4A08-9E8C-B837FE95990B}_is1"

ENV = dict(os.environ, PSHOST_GIMP_PROCESS="gimp-fake-*")
def setup(*args, lang="english"):
    return subprocess.run([SETUP, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LANG={lang}", f"/LOG={os.path.join(T, 'setup.log')}", *args], capture_output=True, text=True, timeout=180, env=ENV)
def reg(root, path, name):
    try:
        with winreg.OpenKey(root, path) as k: return winreg.QueryValueEx(k, name)[0]
    except OSError: return None

# --- install (no administrator rights needed: runs as the current user)
p = setup(f"/GIMPDATA={DATA}")
files = [os.path.join(PLUG, f) for f in ("pshost.exe", "pshost_runner.exe", r"locale\pl\LC_MESSAGES\pshost.mo", r"locale\en\LC_MESSAGES\pshost.mo")]
check(p.returncode == 0 and all(os.path.exists(f) for f in files), "silent install: pshost.exe, pshost_runner.exe, locale/{pl,en} installed in <GIMP data>/plug-ins/pshost")
check(reg(winreg.HKEY_CURRENT_USER, r"Software\PSHost", "DataDir") == DATA and reg(winreg.HKEY_CURRENT_USER, KEY, "DisplayName") is not None, "per-user registry entries (HKCU) written, no HKLM needed")
check(os.path.exists(UNINS) and not os.path.exists(os.path.join(PLUG, "unins000.exe")), "uninstaller lives outside the GIMP plug-in folder")
check(not os.path.exists(os.path.join(PLUG, "..", "..", "..", "pshost", "config.json")), "installer does not create configuration or add any Photoshop plug-ins")

# --- upgrade over an existing installation
p = setup(f"/GIMPDATA={DATA}")
check(p.returncode == 0 and all(os.path.exists(f) for f in files), "installing again (upgrade) succeeds")

# --- GIMP running -> refuses to install/uninstall (a harmless process named like GIMP)
fake = os.path.join(T, "gimp-fake-3.2.exe"); shutil.copy(r"C:\Windows\System32\PING.EXE", fake)
dummy = subprocess.Popen([fake, "-n", "40", "127.0.0.1"], stdout=subprocess.DEVNULL)
try:
    time.sleep(1)
    p = setup(f"/GIMPDATA={os.path.join(T, 'Other', 'GIMP', '3.2')}")
    check(p.returncode != 0 and not os.path.exists(os.path.join(T, "Other")), "install is refused while GIMP is running (nothing written)")
    u = subprocess.run([UNINS, "/VERYSILENT", "/SUPPRESSMSGBOXES"], capture_output=True, timeout=120, env=ENV)
    check(u.returncode != 0 and os.path.exists(files[0]), "uninstall is refused while GIMP is running (files kept)")
finally:
    dummy.kill(); dummy.wait()

# --- uninstall keeps the settings unless /PURGE
cfgdir = os.path.join(DATA, "pshost"); os.makedirs(cfgdir, exist_ok=True)
open(os.path.join(cfgdir, "config.json"), "w").write("{}")
u = subprocess.run([UNINS, "/VERYSILENT", "/SUPPRESSMSGBOXES"], capture_output=True, timeout=120, env=ENV)
time.sleep(1)
check(u.returncode == 0 and not any(os.path.exists(f) for f in files) and not os.path.exists(PLUG), "uninstall removes the plug-in files and its folder")
check(os.path.exists(os.path.join(cfgdir, "config.json")), "silent uninstall keeps config.json (settings are not deleted without /PURGE)")
check(reg(winreg.HKEY_CURRENT_USER, r"Software\PSHost", "DataDir") is None and reg(winreg.HKEY_CURRENT_USER, KEY, "DisplayName") is None, "registry entries removed by the uninstaller")

p = setup(f"/GIMPDATA={DATA}", "/LANG=polish") if False else setup(f"/GIMPDATA={DATA}", lang="polish")
check(p.returncode == 0 and os.path.exists(files[0]), "Polish installer language installs correctly")
u = subprocess.run([UNINS, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/PURGE"], capture_output=True, timeout=120, env=ENV)
time.sleep(1)
check(u.returncode == 0 and not os.path.exists(cfgdir), "uninstall with /PURGE also deletes the PSHost settings")

# --- detection of the real GIMP 3 (registry): checked through the setup log, without installing anything
import re
fake2 = os.path.join(T, "gimp-fake-9.exe"); shutil.copy(r"C:\Windows\System32\PING.EXE", fake2)
d2 = subprocess.Popen([fake2, "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL)
try:
    time.sleep(1)
    subprocess.run([SETUP, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={os.path.join(T, 'detect.log')}"], capture_output=True, timeout=120, env=ENV)
finally:
    d2.kill(); d2.wait()
log = open(os.path.join(T, "detect.log"), encoding="utf-8", errors="replace").read()
m = re.search(r"GIMP 3 detected: dir=(.*) version=(\S+) userdata=(.*)", log)
check(m is not None and m.group(3).strip().endswith("GIMP\\" + m.group(2)),
      "GIMP 3 detected from the registry; user-data dir derived from gimp-3.x.exe" + (f" ({m.group(2)}, {m.group(1)})" if m else " (NOT detected)"))
check(not os.path.exists(UNINS), "detection test installed nothing")

# --- GIMP 3 not installed (simulated): silent setup stops with an error and installs nothing
p = setup("/NOGIMPDETECT")
check(p.returncode != 0 and not os.path.exists(UNINS), "no GIMP 3 found: silent setup aborts cleanly (nothing installed)")

print("failures:", fails)
sys.exit(1 if fails else 0)
