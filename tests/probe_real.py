"""Dev script: run pshost_runner --mode probe on every statically-OK 64-bit filter found under given roots."""
import subprocess, glob, os, re, sys
B = os.path.abspath(sys.argv[1]); roots = sys.argv[2:]
files = []
for r in roots:
    for f in glob.glob(os.path.join(r, "**", "*.8bf"), recursive=True):
        d = subprocess.run([os.path.join(B, "pe8bf_dump.exe"), f], capture_output=True, text=True).stdout
        m = re.search(r"\[OK/none\].*entry=(\S+)", d)
        if m: files.append((f, m.group(1)))
for f, e in files:
    try:
        p = subprocess.run([os.path.join(B, "pshost_runner.exe"), "--mode", "probe", "--plugin", f, "--entry", e, "--timeout-ms", "15000"], capture_output=True, text=True, timeout=40)
        out = " | ".join(l for l in p.stdout.splitlines() if not l.startswith(("CALL", "LOADED")))
        print(os.path.basename(f), "exit=%#x" % (p.returncode & 0xffffffff), out[:260])
    except subprocess.TimeoutExpired:
        print(os.path.basename(f), "HARD TIMEOUT")
