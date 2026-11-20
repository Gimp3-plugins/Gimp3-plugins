"""Dev helper: run every statically-OK real filter through try_plugin for a few seconds; prints one line each."""
import glob, os, re, subprocess, sys
B = os.path.abspath(sys.argv[1]); secs = sys.argv[2]; roots = sys.argv[3:]
HERE = os.path.dirname(os.path.abspath(__file__))
for r in roots:
    for f in sorted(glob.glob(os.path.join(r, "**", "*.8bf"), recursive=True)):
        d = subprocess.run([os.path.join(B, "pe8bf_dump.exe"), f], capture_output=True, text=True).stdout
        m = re.search(r"\[OK/none\].*entry=(\S+)", d)
        if not m: continue
        try:
            o = subprocess.run([sys.executable, "-I", os.path.join(HERE, "try_plugin.py"), B, f, m.group(1), secs], capture_output=True, text=True, timeout=int(secs) + 60).stdout
        except subprocess.TimeoutExpired:
            o = "HARD TIMEOUT\n"
        lines = o.splitlines()
        uns = [l.replace("UNSUPPORTED ", "") for l in lines if l.startswith("UNSUPPORTED")]
        print("%-28s %s | unsupported: %s" % (os.path.basename(f)[:28], lines[0] if lines else "?", "; ".join(sorted(set(uns)))[:150] or "-"))
