"""Runs inside a separate GIMP process. SPDX-License-Identifier: GPL-2.0-or-later."""

from pathlib import Path


def run_job(path):
    from gi.repository import Gimp, Gegl
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
            )
        else:
            indices = job.resume_indices()
            options = job.data["options"]
            options["reserved_targets"] = [str(Path(e["target"]).resolve()) for e in job.entries]
            for index in indices:
                checkpoint()
                entry = job.entries[index]
                job.emit({"kind": "entry", "index": index, "result": {"status": "running"}})
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


if __name__ == "__main__":
    run_job(globals()["BIMP_JOB"])
