"""Runs inside a separate GIMP process. SPDX-License-Identifier: GPL-2.0-or-later."""

from pathlib import Path

MAX_CRASH_ATTEMPTS = 2


def run_job(path):
    from gi.repository import Gegl
    from bimp_jobs import Job, fingerprint
    from bimp_engine import process_one, validate_runtime, render_preview, Cancelled

    Gegl.init(None)
    job = Job(path)

    def checkpoint():
        if (job.directory / "cancel").exists():
            raise Cancelled("Zadanie przerwane przez użytkownika.")

    try:
        checkpoint()
        validate_runtime(job.data["steps"])
        if job.data["mode"] == "preview":
            render_preview(
                job.data["source"],
                job.data["steps"],
                job.directory / "before.png",
                job.directory / "after.png",
                checkpoint,
                options=job.data["options"],
            )
        else:
            indices = job.resume_indices()
            options = job.data["options"]
            options["reserved_targets"] = [str(Path(e["target"]).resolve()) for e in job.entries]
            for index in indices:
                checkpoint()
                entry = job.entries[index]
                attempts = entry.get("attempts", 0)
                if entry.get("status") == "running" and attempts >= MAX_CRASH_ATTEMPTS:
                    # The worker died while processing this file every time; do not loop forever.
                    job.emit(
                        {
                            "kind": "entry",
                            "index": index,
                            "result": {
                                "status": "error",
                                "error": f"Proces GIMP przerwał pracę na tym pliku {attempts} razy; plik pominięto. "
                                "Użyj „Ponów błędne”, aby spróbować ponownie.",
                            },
                        }
                    )
                    continue
                job.emit({"kind": "entry", "index": index, "result": {"status": "running", "attempts": attempts + 1}})
                try:
                    if fingerprint(entry["source"]) != entry["fingerprint"]:
                        raise ValueError("Źródło zmieniło się po rozpoczęciu zadania.")
                    result = process_one(
                        entry["source"],
                        entry["target"],
                        job.data["steps"],
                        options.get("overwrite", False),
                        options.get("keep_dates", False),
                        options,
                        checkpoint,
                    )
                    result["error"] = ""
                    if result["status"] == "success":
                        result["output_fingerprint"] = fingerprint(result["target"])
                        result["variant_fingerprints"] = {
                            v["target"]: fingerprint(v["target"])
                            for v in result.get("variants", [])
                            if v["status"] == "success"
                        }
                except Cancelled:
                    job.emit({"kind": "entry", "index": index, "result": {"status": "pending"}})
                    raise
                except Exception as exc:
                    result = {"status": "error", "error": str(exc)}
                job.emit({"kind": "entry", "index": index, "result": result})
        job.emit({"kind": "finished", "status": "done"})
    except Cancelled:
        job.emit({"kind": "finished", "status": "cancelled"})
    except Exception as exc:
        job.emit({"kind": "finished", "status": "error", "error": str(exc)})
        raise


def run_server(queue, parent, parent_started, idle_seconds):
    """Render preview requests until stopped, idle, or the BIMP window process is gone."""
    import time
    from bimp_jobs import lock_owner_alive

    queue = Path(queue)
    owner = {"pid": parent, "started": parent_started}
    last_work = time.monotonic()
    last_parent_check = 0.0
    while not (queue / "stop").exists():
        now = time.monotonic()
        if now - last_parent_check > 1.0:
            if not lock_owner_alive(owner):
                break
            last_parent_check = now
        pending = []
        try:
            pending = sorted(p for p in queue.glob("*/job.json") if not (p.parent / "served").exists())
        except OSError:
            pass
        if not pending:
            if now - last_work > idle_seconds:
                break
            time.sleep(0.05)
            continue
        for path in pending:
            try:
                run_job(path)
            except Exception as exc:  # The request journal already holds the error.
                print("BIMP preview request failed:", path, exc, flush=True)
            try:
                (path.parent / "served").touch()
            except OSError:
                pass  # The client may already have removed a cancelled request.
        last_work = time.monotonic()


if __name__ == "__main__":
    if "BIMP_QUEUE" in globals():
        run_server(
            globals()["BIMP_QUEUE"],
            globals()["BIMP_PARENT"],
            globals()["BIMP_PARENT_STARTED"],
            globals()["BIMP_IDLE_SECONDS"],
        )
    else:
        run_job(globals()["BIMP_JOB"])
