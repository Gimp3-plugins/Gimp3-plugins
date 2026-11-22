"""UI state and retry scenarios, called from the in-GIMP integration suite."""

from pathlib import Path
from unittest.mock import patch


def preferences_and_retry(work, source):
    from bimp_window import BatchWindow
    from bimp_model import new_step
    from bimp_jobs import Job, fingerprint, new_job_directory

    home = work / "preferences-regression"
    output = home / "out"
    output.mkdir(parents=True, exist_ok=True)
    window = BatchWindow(home=home, restore=False)
    window.append_files([str(source), str(source).upper()])
    assert len(window.file_store) == 1
    window.steps = [new_step("color")]
    window.profiles.set_active_id("1")
    window.apply_profile()
    assert [s["type"] for s in window.steps] == ["color", "resize", "changeformat"]
    window.output.set_filename(str(output))
    window.keep_dates.set_active(True)
    window.remove_done.set_active(True)
    window.metadata.set_active_id("strip")
    window.overwrite.set_active_id("suffix")
    window.persist()
    expected_steps = window.steps
    window.dialog.destroy()
    restored = BatchWindow(home=home)
    try:
        assert restored.steps == expected_steps
        assert len(restored.file_store) == 1
        assert restored.keep_dates.get_active()
        assert restored.remove_done.get_active()
        assert restored.metadata.get_active_id() == "strip"
        assert restored.overwrite.get_active_id() == "suffix"
        plans, options = restored.build_plan()
        assert len(plans) == 1 and plans[0][1].suffix == ".jpg"
        try:
            restored.protect_write(source)
        except ValueError:
            pass
        else:
            raise AssertionError("Source could be overwritten by report")
        second = home / "second.png"
        second.write_bytes(Path(source).read_bytes())
        target = output / "first.jpg"
        target.write_bytes(b"completed output")
        job = Job.create(
            new_job_directory(home), [(source, target), (second, output / "second.jpg")], expected_steps, options
        )
        job.emit(
            {"kind": "entry", "index": 0, "result": {"status": "success", "output_fingerprint": fingerprint(target)}}
        )
        job.emit({"kind": "entry", "index": 1, "result": {"status": "error", "error": "test"}})
        job.refresh()
        restored.job = job
        with patch.object(restored, "launch_job") as launch:
            restored.retry()
            launch.assert_called_once()
            retried = launch.call_args[0][0]
            assert len(retried.entries) == 1 and retried.entries[0]["source"] == str(second)
            assert retried.data["steps"] == expected_steps
    finally:
        restored.dialog.destroy()
