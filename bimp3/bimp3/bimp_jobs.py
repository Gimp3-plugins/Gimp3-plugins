"""Durable job manifests, append-only recovery journal and background GIMP runner.
SPDX-License-Identifier: GPL-2.0-or-later
"""

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from bimp_model import atomic_json, dependency_paths, path_key, validate_steps, variant_targets


def fingerprint(path):
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        raise ValueError(f"Plik nie istnieje lub został przeniesiony: {path}") from None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def process_identity(pid):
    """Creation stamp of a running process, "unknown" if alive but unreadable, None if not running.

    os.kill(pid, 0) is not a liveness test on Windows: signal 0 is CTRL_C_EVENT,
    which fails for unknown PIDs and "succeeds" for exited ones.
    """
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return "unknown" if ctypes.get_last_error() == 5 else None  # 5: access denied
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return "unknown"
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return "unknown"
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, IndexError, ValueError):
        return "unknown"


def lock_owner_alive(owner):
    """True only when the recorded process still runs and was not replaced by PID reuse."""
    identity = process_identity(owner.get("pid"))
    if identity is None:
        return False
    started = owner.get("started")
    return started in (None, "unknown") or identity == "unknown" or identity == started


def write_exclusive_json(path, data):
    """Create a complete JSON file atomically, failing with FileExistsError if it exists."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".bimp-lock-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "nt":
            os.rename(name, path)  # never replaces an existing file on Windows
        else:
            os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Job:
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        if self.data.get("bimp3_job") != 1:
            raise ValueError("Nieobsługiwana wersja zadania.")
        validate_steps(self.data["steps"])
        self.entries = copy.deepcopy(self.data["entries"])
        self.offset = 0
        self.changed = set()
        self.finished = None
        self.refresh()

    @classmethod
    def create(cls, directory, plans, steps, options, mode="batch", source=None):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        entries = [
            {"source": str(s), "target": str(t), "fingerprint": fingerprint(s), "status": "pending"} for s, t in plans
        ]
        atomic_json(
            directory / "job.json",
            {
                "bimp3_job": 1,
                "created": datetime.now(timezone.utc).isoformat(),
                "steps": steps,
                "options": options,
                "mode": mode,
                "source": str(source) if source else None,
                "dependencies": [{"path": str(p), "fingerprint": fingerprint(p)} for p in dependency_paths(steps)],
                "entries": entries,
            },
        )
        return cls(directory / "job.json")

    @property
    def directory(self):
        return self.path.parent

    def emit(self, event):
        event["time"] = datetime.now(timezone.utc).isoformat()
        journal = self.directory / "events.jsonl"
        if journal.exists() and journal.stat().st_size:
            with journal.open("rb+") as stream:
                stream.seek(-1, 2)
                if stream.read(1) != b"\n":
                    stream.seek(0, 2)
                    stream.write(b"\n")
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def refresh(self, reset=True):
        """Read new journal events; `changed` lists entries updated since the last reset."""
        if reset:
            self.changed = set()
        journal = self.directory / "events.jsonl"
        if not journal.exists():
            return
        with journal.open("rb") as stream:
            stream.seek(self.offset)
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line or not line.endswith(b"\n"):
                    self.offset = start
                    break
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    self.offset = stream.tell()
                    continue
                if event.get("kind") == "entry":
                    index = event.get("index")
                    if type(index) is int and 0 <= index < len(self.entries):
                        self.entries[index].update(event["result"])
                        self.changed.add(index)
                elif event.get("kind") == "finished":
                    self.finished = event
                self.offset = stream.tell()

    def validate(self):
        if self.data.get("mode") not in ("batch", "preview"):
            raise ValueError("Nieprawidłowy tryb zadania.")
        options = self.data["options"]
        for flag in ("overwrite", "keep_dates", "color_profile"):
            if flag in options and type(options[flag]) is not bool:
                raise ValueError(f"Nieprawidłowa opcja zadania: {flag}")
        if options.get("metadata", "strip-gps") not in ("preserve", "strip-gps", "strip"):
            raise ValueError("Nieprawidłowa polityka metadanych.")
        if options.get("output_color", "preserve") not in ("preserve", "srgb"):
            raise ValueError("Nieprawidłowa przestrzeń wyjściowa.")
        if self.data["mode"] == "batch" and not options.get("output_directory"):
            raise ValueError("Zadanie nie zawiera katalogu wyników.")
        for dependency in self.data.get("dependencies", []):
            if fingerprint(dependency["path"]) != dependency["fingerprint"]:
                raise ValueError(f"Zależność zadania uległa zmianie: {dependency['path']}")
        protected = {path_key(e["source"]) for e in self.entries} | {
            path_key(p) for p in dependency_paths(self.data["steps"])
        }
        targets = set()
        root = Path(self.data["options"].get("output_directory", self.directory)).resolve()
        for entry in self.entries:
            if not Path(entry["source"]).is_absolute() or not Path(entry["target"]).is_absolute():
                raise ValueError("Ścieżki zadania muszą być bezwzględne.")
            source, target = Path(entry["source"]), Path(entry["target"]).resolve()
            if fingerprint(source) != entry["fingerprint"]:
                raise ValueError(f"Plik źródłowy zmienił się od utworzenia zadania: {source}")
            for output in (target, *variant_targets(target, self.data["steps"])):
                output = output.resolve()
                if not output.is_relative_to(root) or path_key(output) in protected or path_key(output) in targets:
                    raise ValueError(f"Niebezpieczna lub powtórzona ścieżka wyniku: {output}")
                targets.add(path_key(output))

    def resume_indices(self, retry_errors=True):
        self.validate()
        indices = []
        for index, entry in enumerate(self.entries):
            status = entry.get("status", "pending")
            if status == "success":
                target = Path(entry["target"])
                outputs = {str(target): entry.get("output_fingerprint")}
                outputs.update(entry.get("variant_fingerprints", {}))
                present = {path: Path(path).exists() for path in outputs}
                if all(present.values()) and all(fingerprint(path) == fp for path, fp in outputs.items()):
                    continue
                changed = [path for path, fp in outputs.items() if present[path] and fingerprint(path) != fp]
                if changed:
                    raise ValueError(f"Wynik ukończonego zadania został zmieniony: {changed[0]}")
            elif status == "skipped":
                continue
            elif status == "error" and not retry_errors:
                continue
            indices.append(index)
        return indices

    def report(self):
        self.refresh()
        return {
            "bimp3_report": 1,
            "created": self.data["created"],
            "job": str(self.path),
            "finished": self.finished,
            "results": self.entries,
        }


class FileLock:
    """Exclusive lock file naming its owner process; locks of dead owners are stale."""

    def __init__(self, path):
        self.path = Path(path)
        self.token = uuid.uuid4().hex

    def owner(self):
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return owner if isinstance(owner, dict) else None

    def busy(self):
        """True when another live process holds the lock."""
        owner = self.owner()
        return owner is not None and owner.get("token") != self.token and lock_owner_alive(owner)

    def acquire(self, pid=None):
        if self.path.exists():
            if self.busy():
                return False
            # Left by a crash, reboot or killed process, or an incomplete older lock.
            self.path.unlink(missing_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_exclusive_json(self.path, self.record(pid or os.getpid()))
        except FileExistsError:
            return False
        return True

    def record(self, pid):
        return {"pid": pid, "token": self.token, "started": process_identity(pid)}

    def transfer(self, pid):
        """Name the background process as the owner, so the lock survives this GUI."""
        atomic_json(self.path, self.record(pid))

    def release(self):
        owner = self.owner()
        if owner is not None and owner.get("token") == self.token:
            self.path.unlink(missing_ok=True)


def acquire_profile(pool, prefix, limit=8):
    """Reuse a warm GIMP profile (its plug-in cache makes later starts fast).

    Each profile is used by one GIMP process at a time; concurrent windows get
    the next numbered profile, so the pool stays bounded.
    """
    pool = Path(pool)
    for number in range(1, limit + 1):
        profile = pool / f"{prefix}-{number}"
        lock = FileLock(pool / f"{prefix}-{number}.lock")
        if lock.acquire():
            return profile, lock
    raise RuntimeError("Wszystkie profile robocze GIMP są zajęte. Zamknij inne okna BIMP.")


def launch_gimp(executable, script_globals, profile, log):
    """Start console GIMP with an isolated profile that loads only bundled plug-ins."""
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    config = '(plug-in-path "${gimp_plug_in_dir}/plug-ins")\n(check-updates no)\n'
    (profile / "gimprc").write_text(config, encoding="utf-8")
    worker_script = Path(__file__).with_name("bimp_worker.py").resolve()
    namespace = {"__name__": "__main__", **script_globals}
    # repr() keeps every path a Python literal; nothing is interpolated as code.
    command = (
        f"import sys; sys.path.insert(0,{str(worker_script.parent)!r}); "
        f"exec(compile(open({str(worker_script)!r},encoding='utf-8').read(),{str(worker_script)!r},'exec'), "
        f"{namespace!r})"
    )
    env = os.environ.copy()
    env["GIMP3_DIRECTORY"] = str(profile)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(Path(executable).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.Popen(
        [
            str(executable),
            "--new-instance",
            "--no-data",
            "--no-splash",
            "--console-messages",
            "--batch-interpreter=python-fu-eval",
            "-b",
            command,
            "--quit",
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class Worker:
    def __init__(self, job, executable=None, profile_directory=None, profile_pool=None):
        self.job = job
        self.process = None
        self.log = None
        self.executable = executable or find_gimp()
        self.lock = self.job.directory / ".worker.lock"
        self.job_lock = FileLock(self.lock)
        self.token = self.job_lock.token
        self.profile_directory = profile_directory
        self.profile_pool = profile_pool
        self.profile_lock = None

    def clear_stale_lock(self):
        """Remove a lock left by a crash, reboot or killed process; keep a live one."""
        if self.lock.exists() and self.job_lock.busy():
            raise RuntimeError("To zadanie już działa w innym procesie.")
        self.lock.unlink(missing_ok=True)

    def start(self):
        self.job.validate()
        self.clear_stale_lock()
        if not self.job_lock.acquire():
            raise RuntimeError("To zadanie już działa w innym procesie.")
        try:
            self._launch()
        except Exception:
            if self.log and not self.log.closed:
                self.log.close()
            self.release_lock()
            raise

    def _launch(self):
        self.job.finished = None
        self.job.emit({"kind": "finished", "status": "running"})
        cancel = self.job.directory / "cancel"
        cancel.unlink(missing_ok=True)
        if self.profile_pool:
            profile, self.profile_lock = acquire_profile(self.profile_pool, "batch")
        else:
            profile = Path(self.profile_directory) if self.profile_directory else self.job.directory / "worker-profile"
        self.log = (self.job.directory / "worker.log").open("ab", buffering=0)
        try:
            self.process = launch_gimp(self.executable, {"BIMP_JOB": str(self.job.path)}, profile, self.log)
            self.job_lock.transfer(self.process.pid)
            if self.profile_lock:
                self.profile_lock.transfer(self.process.pid)
        except Exception:
            self.log.close()
            self.release_lock()
            raise

    def poll(self):
        self.job.refresh()
        if self.process is None:
            return None
        result = self.process.poll()
        if result is not None:
            # The worker may have written its last events after the refresh above;
            # keep the changes already collected for the caller.
            self.job.refresh(reset=False)
            if self.log and not self.log.closed:
                self.log.close()
                self.release_lock()
        return result

    def release_lock(self):
        self.job_lock.release()
        if self.profile_lock:
            self.profile_lock.release()

    def cancel(self):
        (self.job.directory / "cancel").touch()


class PreviewServer:
    """One long-lived GIMP process rendering preview requests from a queue folder.

    Starting GIMP takes seconds; a warm process answers slider changes quickly.
    Each request is an ordinary preview Job; the newest request supersedes older
    ones. The process exits when asked, when idle, or when its parent is gone.
    """

    IDLE_SECONDS = 300

    def __init__(self, home, executable=None):
        self.home = Path(home)
        # One queue per BIMP process: two open BIMP windows never share requests or stop files.
        self.queue = self.home / "previews" / f"queue-{os.getpid()}"
        self.executable = executable or find_gimp()
        self.process = None
        self.log = None
        self.profile_lock = None
        self.stopping = False

    def running(self):
        if self.process is None:
            return False
        if self.process.poll() is None:
            return True
        self.process = None
        if self.log and not self.log.closed:
            self.log.close()
        if self.profile_lock:
            self.profile_lock.release()
            self.profile_lock = None
        return False

    def ensure_started(self):
        if self.stopping and self.process is not None:
            # A stop was requested (window closed); let that process end before reuse.
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.stopping = False
        if self.running():
            return
        self.queue.mkdir(parents=True, exist_ok=True)
        (self.queue / "stop").unlink(missing_ok=True)
        profile, self.profile_lock = acquire_profile(self.home / "profiles", "preview")
        log = self.queue.parent / "preview-server.log"
        too_big = log.exists() and log.stat().st_size > 5 * 1024 * 1024
        self.log = log.open("wb" if too_big else "ab", buffering=0)
        parent = os.getpid()
        try:
            self.process = launch_gimp(
                self.executable,
                {
                    "BIMP_QUEUE": str(self.queue),
                    "BIMP_PARENT": parent,
                    "BIMP_PARENT_STARTED": process_identity(parent),
                    "BIMP_IDLE_SECONDS": self.IDLE_SECONDS,
                },
                profile,
                self.log,
            )
            self.profile_lock.transfer(self.process.pid)
        except Exception:
            self.log.close()
            self.profile_lock.release()
            self.profile_lock = None
            raise

    def submit(self, source, steps, options=None):
        """Queue a preview and return its Job; older unfinished requests are cancelled."""
        self.ensure_started()
        for previous in self.queue.glob("*/job.json"):
            (previous.parent / "cancel").touch()
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:6]
        return Job.create(self.queue / name, [], steps, options or {}, mode="preview", source=source)

    def stop(self):
        if self.running():
            self.queue.mkdir(parents=True, exist_ok=True)
            (self.queue / "stop").touch()
            self.stopping = True


_servers = {}


def preview_server(home):
    """Main window and LUT editors of one data folder share one preview process."""
    key = path_key(home)
    if key not in _servers:
        _servers[key] = PreviewServer(home)
    return _servers[key]


def stop_preview_servers():
    for server in _servers.values():
        server.stop()


def remove_tree(path):
    """Delete a BIMP data folder; files still open elsewhere are left for the next cleanup."""
    shutil.rmtree(path, ignore_errors=True)


def find_gimp():
    folder = Path(sys.executable).parent
    for name in (
        "gimp-console-3.exe",
        "gimp-console-3.2.exe",
        "gimp-console-3.0.exe",
        "gimp-console-3.0",
        "gimp-console-3.2",
    ):
        candidate = folder / name
        if candidate.is_file():
            return candidate
        found = shutil.which(name)
        if found:
            return Path(found)
    raise RuntimeError("Nie znaleziono konsolowego GIMP do pracy w tle.")


def new_job_directory(home):
    return Path(home) / "jobs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:10])
