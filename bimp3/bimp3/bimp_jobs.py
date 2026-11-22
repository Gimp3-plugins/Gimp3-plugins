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
import uuid

from bimp_model import atomic_json, dependency_paths, path_key, validate_steps


def fingerprint(path):
    stat = Path(path).stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


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

    def refresh(self):
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
            if not target.is_relative_to(root) or path_key(target) in protected or path_key(target) in targets:
                raise ValueError(f"Niebezpieczna lub powtórzona ścieżka wyniku: {target}")
            targets.add(path_key(target))

    def resume_indices(self, retry_errors=True):
        self.validate()
        indices = []
        for index, entry in enumerate(self.entries):
            status = entry.get("status", "pending")
            if status == "success":
                target = Path(entry["target"])
                if target.exists() and fingerprint(target) == entry.get("output_fingerprint"):
                    continue
                if target.exists():
                    raise ValueError(f"Wynik ukończonego zadania został zmieniony: {target}")
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


class Worker:
    def __init__(self, job, executable=None, profile_directory=None):
        self.job = job
        self.process = None
        self.log = None
        self.executable = executable or find_gimp()
        self.lock = self.job.directory / ".worker.lock"
        self.token = uuid.uuid4().hex
        self.profile_directory = profile_directory

    def start(self):
        self.job.validate()
        if self.lock.exists():
            try:
                owner = json.loads(self.lock.read_text(encoding="utf-8"))
                os.kill(int(owner["pid"]), 0)
            except ProcessLookupError:
                self.lock.unlink()
            except (ValueError, KeyError):
                raise RuntimeError("Nieprawidłowa blokada zadania.")
            else:
                raise RuntimeError("To zadanie już działa w innym procesie.")
        fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "token": self.token}, stream)
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
        profile = Path(self.profile_directory) if self.profile_directory else self.job.directory / "worker-profile"
        profile.mkdir(parents=True, exist_ok=True)
        # Only bundled GIMP plug-ins are loaded, not third-party user scripts.
        config = '(plug-in-path "${gimp_plug_in_dir}/plug-ins")\n(check-updates no)\n'
        (profile / "gimprc").write_text(config, encoding="utf-8")
        worker_script = Path(__file__).with_name("bimp_worker.py").resolve()
        command = f"import sys; sys.path.insert(0,{str(worker_script.parent)!r}); exec(compile(open({str(worker_script)!r},encoding='utf-8').read(),{str(worker_script)!r},'exec'), {{'__name__':'__main__','BIMP_JOB':{str(self.job.path)!r}}})"
        env = os.environ.copy()
        env["GIMP3_DIRECTORY"] = str(profile)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PATH"] = str(Path(self.executable).parent) + os.pathsep + env.get("PATH", "")
        self.log = (self.job.directory / "worker.log").open("ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                [
                    str(self.executable),
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
                stdout=self.log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            atomic_json(self.lock, {"pid": self.process.pid, "token": self.token})
        except Exception:
            self.log.close()
            self.release_lock()
            raise

    def poll(self):
        self.job.refresh()
        if self.process is None:
            return None
        result = self.process.poll()
        if result is not None and self.log and not self.log.closed:
            self.log.close()
            self.release_lock()
        return result

    def release_lock(self):
        if self.lock.exists():
            owner = json.loads(self.lock.read_text(encoding="utf-8"))
            if owner.get("token") == self.token:
                self.lock.unlink()

    def cancel(self):
        (self.job.directory / "cancel").touch()


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
