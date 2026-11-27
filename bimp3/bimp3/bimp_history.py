"""Job history and cleanup of the BIMP data folder. No GTK; safe to unit test.
SPDX-License-Identifier: GPL-2.0-or-later
"""

from collections import Counter
from datetime import datetime, timezone
import time
from pathlib import Path

from bimp_jobs import FileLock, Job, remove_tree


def folder_size(path):
    total = 0
    for item in Path(path).rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def job_running(directory):
    return FileLock(Path(directory) / ".worker.lock").busy()


def list_jobs(home):
    """Newest first: one row per job folder, including damaged ones."""
    rows = []
    jobs = Path(home) / "jobs"
    if not jobs.is_dir():
        return rows
    for directory in sorted((p.resolve() for p in jobs.iterdir() if p.is_dir()), reverse=True):
        row = {
            "path": str(directory / "job.json"),
            "directory": str(directory),
            "created": directory.name[:15],
            "status": "?",
            "counts": {},
            "entries": 0,
            "size": folder_size(directory),
            "running": job_running(directory),
            "error": "",
        }
        try:
            job = Job(directory / "job.json")
            row["created"] = job.data.get("created", row["created"])
            row["status"] = (job.finished or {}).get("status", "pending")
            row["counts"] = dict(Counter(e.get("status", "pending") for e in job.entries))
            row["entries"] = len(job.entries)
        except Exception as exc:  # Damaged folders are still listed so that they can be removed.
            row["error"] = str(exc)
        if row["running"]:
            row["status"] = "running"
        rows.append(row)
    return rows


def delete_job(directory, protected=()):
    """Delete one job folder unless it is running or protected (e.g. the job shown in the window)."""
    directory = Path(directory).resolve()
    if directory.parent.name != "jobs":
        raise ValueError(f"To nie jest folder zadania BIMP: {directory}")
    if any(Path(p).resolve() == directory for p in protected):
        raise ValueError("Tego zadania nie można teraz usunąć: jest otwarte w oknie BIMP.")
    if job_running(directory):
        raise ValueError("Zadanie jest w trakcie przetwarzania.")
    remove_tree(directory)


def prune_jobs(home, older_than_days, protected=()):
    """Delete finished job folders older than the given number of days; returns how many."""
    limit = time.time() - older_than_days * 86400
    removed = 0
    jobs = Path(home) / "jobs"
    if not jobs.is_dir():
        return 0
    for directory in jobs.iterdir():
        try:
            if directory.is_dir() and directory.stat().st_mtime < limit:
                delete_job(directory, protected)
                removed += 1
        except (OSError, ValueError):
            pass
    return removed


def clean_previews(home, older_than=600):
    """Remove leftover preview requests and folders written by older BIMP versions."""
    previews = Path(home) / "previews"
    removed = 0
    if not previews.is_dir():
        return 0
    limit = time.time() - older_than
    queues = [q for q in previews.glob("queue*") if q.is_dir()]
    candidates = [request for q in queues for request in q.iterdir()]
    # Up to the first GIMP 3 release every preview kept a folder and a profile.
    candidates += list((previews / "jobs").glob("*")) if (previews / "jobs").is_dir() else []
    candidates += list(previews.glob("profile-*"))
    for folder in candidates:
        try:
            if folder.is_dir() and folder.stat().st_mtime < limit:
                remove_tree(folder)
                removed += 1
        except OSError:
            pass
    for folder in [*queues, previews / "jobs"]:
        try:
            if folder.is_dir() and not any(folder.iterdir()) and folder.stat().st_mtime < limit:
                folder.rmdir()
        except OSError:
            pass
    return removed


def data_usage(home):
    home = Path(home)
    return {name: folder_size(home / name) for name in ("jobs", "previews", "profiles")}


def human_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


def created_label(value):
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(value)
