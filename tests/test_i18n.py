"""Translation tests: catalog validity/completeness, .pot freshness, language selection, Polish characters in paths.
Usage: python -I test_i18n.py <build_dir>   (needs MSYS2 UCRT64 gettext-tools and, for the UI parts, GIMP's GTK runtime)"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile

B = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSYS = r"C:\msys64\ucrt64\bin"
GIMP = r"C:\gimp3"
fails = 0
def check(c, msg):
    global fails
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails += 1

def tool(name, *args, **kw):
    return subprocess.run([os.path.join(MSYS, name + ".exe"), *args], capture_output=True, text=True, encoding="utf-8", **kw)

def msgids(path):
    txt = open(path, encoding="utf-8").read()
    out = set()
    for block in re.split(r"\n\n", txt):
        m = re.search(r'^msgid ((?:"(?:[^"\\]|\\.)*"\n?)+)', block, re.M)
        if m:
            s = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
            if s: out.add(s)
    return out

# --- 1. catalogs are valid and complete
for lang in ("pl", "en"):
    r = tool("msgfmt", "-c", "--check-format", "--statistics", "-o", os.devnull, os.path.join(ROOT, "po", f"{lang}.po"))
    check(r.returncode == 0 and "fuzzy" not in r.stderr and "untranslated" not in r.stderr, f"{lang}.po: valid, no fuzzy / untranslated entries ({r.stderr.strip()})")

# --- 2. the .pot matches the sources (every _T()/N_()/ps_tr_lang() string is in the catalog and vice versa)
tmp = os.path.join(tempfile.mkdtemp(prefix="pshost_pot_"), "fresh.pot")
files = [os.path.join(ROOT, "src", d, f) for d in ("plugin", "common") for f in sorted(os.listdir(os.path.join(ROOT, "src", d))) if f.endswith(".c")]
r = tool("xgettext", "--from-code=UTF-8", "--language=C", "-k_T", "-kN_", "-kps_tr", "-kps_tr_lang:2", "--msgid-bugs-address=none", "-o", tmp, *files)
fresh, committed = msgids(tmp), msgids(os.path.join(ROOT, "po", "pshost.pot"))
check(fresh == committed, "po/pshost.pot is up to date with the sources" + ("" if fresh == committed else f" (missing: {sorted(fresh - committed)[:3]}, stale: {sorted(committed - fresh)[:3]})"))
check(msgids(os.path.join(ROOT, "po", "pl.po")) == committed and msgids(os.path.join(ROOT, "po", "en.po")) == committed, "pl.po and en.po contain exactly the msgids of the .pot")

# --- 3. Polish translations really use Polish diacritics where expected
pl = open(os.path.join(ROOT, "po", "pl.po"), encoding="utf-8").read()
check("Zarządzaj wtyczkami" in pl and "Wtyczka »%s« nie zostanie użyta: %s." in pl and "Uruchom ponownie GIMP-a" in pl, "pl.po: UTF-8 Polish text (ą, ę, ó, ż, »«) present")

# --- 4. built catalogs exist (gettext layout used by GIMP: locale/<lang>/LC_MESSAGES/pshost.mo)
check(all(os.path.exists(os.path.join(B, "locale", l, "LC_MESSAGES", "pshost.mo")) for l in ("pl", "en")), "build/locale/{pl,en}/LC_MESSAGES/pshost.mo built")

# --- 5. language selection + Polish characters in paths (headless UI)
if os.path.isdir(os.path.join(GIMP, "bin")):
    T = tempfile.mkdtemp(prefix="pshost_i18n_")
    env = dict(os.environ, PATH=os.path.join(GIMP, "bin") + os.pathsep + os.environ["PATH"], XDG_DATA_DIRS=os.path.join(GIMP, "share"),
               PSHOST_RUNNER=os.path.join(B, "pshost_runner.exe"), PSHOST_CONFIG_DIR=os.path.join(T, "cfg"))
    def ui(lang, *dirs, extra=None):
        e = dict(env, **(extra or {}))
        dirs = dirs or (os.path.join(B, "mini"),)
        return subprocess.run([os.path.join(B, "ui_snapshot.exe"), os.path.join(T, "o.png"), lang, *dirs], capture_output=True, text=True, encoding="utf-8", env=e, timeout=180).stdout
    check("lang=0" in ui("en"), "language 'en' -> English")
    check("lang=1" in ui("pl"), "language 'pl' -> Polish")
    check("lang=1" in ui("auto", extra={"LANGUAGE": "pl"}) and "lang=0" in ui("auto", extra={"LANGUAGE": "en"}), "language 'auto' follows LANGUAGE (GIMP/system language)")

    pdir = os.path.join(T, "Wtyczki zażółć gęślą jaźń")
    os.makedirs(pdir)
    shutil.copy(os.path.join(B, "mini", "mini_invert.8bf"), os.path.join(pdir, "filtr ŁÓDŹ żółw.8bf"))
    cfg2 = os.path.join(T, "cfg_pl")                       # clean configuration for this case
    o = ui("pl", pdir, extra={"PSHOST_CONFIG_DIR": cfg2})
    check("items=1 ok=1 warn=0 no=0" in o, "directory and file name with Polish characters: found, tested (probe) and accepted")
    cfg = json.load(open(os.path.join(cfg2, "config.json"), encoding="utf-8"))
    check(cfg["plugins"][0]["path"].endswith("filtr ŁÓDŹ żółw.8bf") and "zażółć" in cfg["directories"][0]["path"], "config.json stores the Polish path as UTF-8")
else:
    print("skip UI parts (GIMP runtime not found)")

print("failures:", fails)
sys.exit(1 if fails else 0)
