"""Dev helper: run one filter through pshost_runner with its UI for a few seconds and report how it ended.
Usage: python -I try_plugin.py <build_dir> <plugin.8bf> <entry> [seconds]"""
import os, subprocess, sys, tempfile
B, plug, entry = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
secs = int(sys.argv[4]) if len(sys.argv) > 4 else 15
T = tempfile.mkdtemp(prefix="pshost_try_"); W, H = 640, 480
raw = bytearray()
for y in range(H):
    for x in range(W): raw += bytes([x * 255 // W, y * 255 // H, (x + y) * 255 // (W + H), 255])
fi, fo = os.path.join(T, "i.raw"), os.path.join(T, "o.raw"); open(fi, "wb").write(raw)
p = subprocess.run([os.path.join(B, "pshost_runner.exe"), "--mode", "run", "--plugin", plug, "--entry", entry, "--width", str(W), "--height", str(H),
                    "--in", fi, "--out", fo, "--ui", "1", "--timeout-ms", str(secs * 1000)], capture_output=True, text=True, timeout=secs + 30)
code = p.returncode & 0xFFFFFFFF
print("exit=%#x (%s)" % (code, {0: "finished OK", 124: "still running at timeout = no crash", 0xC0DE0001: "CRASH", 2: "plug-in error", 7: "cancelled"}.get(code, "?")))
print("\n".join(l for l in p.stdout.splitlines() if not l.startswith("CALL")))
