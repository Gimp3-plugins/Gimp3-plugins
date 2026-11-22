"""Execute INSIDE GIMP via python-fu-eval. Writes integration-result.json."""

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "bimp3"))
import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
from bimp_model import new_step, save_settings, load_settings, plan_outputs
from bimp_engine import EXPORTERS, process_one, validate_runtime, config_for, procedure, set_argument

Gegl.init(None)
work = BASE / "tests" / "output"
work.mkdir(parents=True, exist_ok=True)
results = {"gimp": Gimp.version(), "checks": [], "failures": []}


def check(name, callback):
    filters = os.environ.get("BIMP_TEST_FILTER", "").split("|")
    if name != "fixture" and filters != [""] and not any(f.casefold() in name.casefold() for f in filters):
        return
    try:
        callback()
        results["checks"].append(name)
        print("PASS", name)
    except Exception:
        results["failures"].append({"name": name, "traceback": traceback.format_exc()})
        print("FAIL", name, traceback.format_exc())


def fixture():
    image = Gimp.Image.new(80, 40, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(image, "fixture", 80, 40, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
    assert image.insert_layer(layer, None, 0)
    Gimp.context_push()
    Gimp.context_set_background(Gegl.Color.new("#cc4422"))
    layer.fill(Gimp.FillType.BACKGROUND)
    Gimp.context_set_foreground(Gegl.Color.new("#2244cc"))
    assert image.select_rectangle(Gimp.ChannelOps.REPLACE, 40, 0, 40, 40)
    assert layer.edit_fill(Gimp.FillType.FOREGROUND)
    assert Gimp.Selection.none(image)
    Gimp.context_pop()
    assert Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(str(work / "źródło.png")), None)
    image.delete()


check("fixture", fixture)
source = work / "źródło.png"


def pipeline():
    resize = new_step("resize")
    resize["settings"].update(
        resize_mode_width=1,
        resize_mode_height=1,
        new_w_px=60,
        new_h_px=60,
        stretch_mode=2,
        change_res=True,
        new_res_x=144,
        new_res_y=144,
    )
    crop = new_step("crop")
    crop["settings"].update(manual=True, new_w=50, new_h=40)
    flip = new_step("fliprotate")
    flip["settings"].update(flip_h=True, flip_v=True, rotate=True, rotation_type=0)
    color = new_step("color")
    curve = work / "curve.txt"
    curve.write_text("# GIMP curves tool settings\n(channel value)\n(curve\n (points 4 0 0 1 0.8))\n# end\n")
    color["settings"].update(brightness=0.1, contrast=0.1, levels_auto=True, curve_file=str(curve))
    blur = new_step("sharpblur")
    blur["settings"]["amount"] = 20
    sharp = new_step("sharpblur")
    sharp["settings"]["amount"] = -20
    text = new_step("watermark")
    text["settings"].update(text="BIMP 3", font="Sans-serif 8px", color="#ffffff", position=4)
    watermark = new_step("watermark")
    watermark["settings"].update(
        mode=False, image_file=str(source), image_sizemode=1, image_size_percent=20, opacity=50, position=8
    )
    user = new_step("userdef")
    user["settings"].update(procedure="gimp-image-flip", arguments={"flip-type": "horizontal"})
    fmt = new_step("changeformat")
    fmt["settings"].update(format=4, arguments={"compression": 2, "include-color-profile": True})
    steps = [resize, crop, flip, color, blur, sharp, text, watermark, user, fmt]
    validate_runtime(steps)
    target = work / "pipeline.png"
    assert process_one(source, target, steps, overwrite=True, keep_dates=True)["status"] == "success"
    assert abs(target.stat().st_mtime - source.stat().st_mtime) < 0.001
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(target)))
    assert (image.get_width(), image.get_height()) == (40, 50)
    image.delete()
    assert process_one(source, target, steps)["status"] == "skipped"


check("all operation groups, Unicode paths, dates, skip existing", pipeline)


def format_test(ext, proc_name):
    assert Gimp.get_pdb().lookup_procedure(proc_name), f"Missing exporter {proc_name}"
    fmt = new_step("changeformat")
    from bimp_model import FORMATS

    fmt["settings"]["format"] = FORMATS.index(ext)
    validate_runtime([fmt])
    target = work / ("format." + ext)
    assert process_one(source, target, [fmt], overwrite=True)["status"] == "success"
    loaded = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(target)))
    assert loaded.get_width() == 80 and loaded.get_height() == 40
    loaded.delete()


for ext in ["bmp", "gif", "ico", "jpg", "png", "tga", "tiff", "heif", "webp", "avif", "exr", "xcf"]:
    check("export and reload " + ext, lambda e=ext: format_test(e, EXPORTERS[e]))


def failures():
    old = work / "preserved.png"
    old.write_bytes(b"original destination")
    step = new_step("userdef")
    step["settings"]["procedure"] = "no-such-procedure"
    try:
        process_one(source, old, [step], overwrite=True)
    except (RuntimeError, ValueError):
        pass
    else:
        raise AssertionError("Missing procedure should fail")
    assert old.read_bytes() == b"original destination"
    assert not list(work.glob(".bimp-*"))
    cfg = procedure("file-jpeg-export").create_config()
    for key, value in [("quality", 85), ("no-such-property", 1), ("progressive", "false")]:
        try:
            set_argument(cfg, key, value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid argument accepted: {key}")


check("failure preserves destination, invalid arguments rejected", failures)


def ui():
    from bimp_ui import Form, BatchWindow, procedure_form
    from bimp_model import SCHEMAS
    from gi.repository import GimpUi

    GimpUi.init("bimp3-test")
    window = BatchWindow(home=work / "ui-preferences", restore=False)
    window.steps = [new_step(k) for k in SCHEMAS if k != "userdef"]
    window.refresh()
    window.append_files([str(source)])
    window.dialog.show_all()
    from gi.repository import Gtk, Gdk

    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    native = window.dialog.get_window()
    screenshot = Gdk.pixbuf_get_from_window(
        native, 0, 0, window.dialog.get_allocated_width(), window.dialog.get_allocated_height()
    )
    if screenshot:
        screenshot.savev(str(work / "bimp3-interface.png"), "png", [], [])
    for kind, (_label, fields) in SCHEMAS.items():
        form = Form()
        s = new_step(kind)["settings"]
        for key, field in fields.items():
            form.add(key, field[0], s[key], field[2] if len(field) > 2 else None)
        assert set(form.values()) == set(fields)
    for ext in ["png", "jpg", "webp", "tiff", "heif", "avif"]:
        form = procedure_form(procedure(EXPORTERS[ext]), {})
        config_for(procedure(EXPORTERS[ext]), arguments=form.values())
    form = procedure_form(procedure("gimp-image-flip"), {})
    config_for(procedure("gimp-image-flip"), arguments=form.values())
    window.dialog.destroy()


check("GTK 3 main window and every operation form", ui)


def gtk_batch():
    from bimp_ui import BatchWindow
    from gi.repository import GLib

    window = BatchWindow(home=work / "batch-preferences", restore=False)
    dest = work / "gtk-batch"
    dest.mkdir(exist_ok=True)
    window.output.set_filename(str(dest))
    window.append_files([str(source)])
    fmt = new_step("changeformat")
    fmt["settings"]["format"] = 4
    window.steps = [fmt]
    window.overwrite.set_active_id("replace")
    window.start()
    assert window.busy
    context = GLib.MainContext.default()
    while window.busy:
        context.iteration(True)
    assert len(window.results) == 1 and window.results[0]["status"] == "success"
    window.start()
    window.cancel()
    while window.busy:
        context.iteration(True)
    assert window.results == []
    window.dialog.destroy()


check("GTK batch controls, completion and cancellation", gtk_batch)


def grayscale_and_image_watermark():
    color = new_step("color")
    color["settings"]["grayscale"] = True
    wm = new_step("watermark")
    wm["settings"].update(
        mode=False,
        image_file=str(source),
        image_sizemode=1,
        image_size_percent=25.0,
        opacity=50.0,
        edge_distance=2,
        position=8,
    )
    validate_runtime([color, wm])
    target = work / "gray-watermark.png"
    assert process_one(source, target, [color, wm], overwrite=True)["status"] == "success"
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(target)))
    assert image.get_base_type() == Gimp.ImageBaseType.GRAY
    assert (image.get_width(), image.get_height()) == (80, 40)
    image.delete()


check("grayscale and scaled image watermark", grayscale_and_image_watermark)


def pixel_behavior():
    from bimp_engine import apply_step

    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
    try:
        layer = image.get_layers()[0]
        left = layer.get_pixel(10, 10).get_rgba()
        right = layer.get_pixel(70, 10).get_rgba()
        flip = new_step("fliprotate")
        flip["settings"]["flip_h"] = True
        apply_step(image, flip)
        flipped = layer.get_pixel(10, 10).get_rgba()
        assert all(abs(a - b) < 0.01 for a, b in zip(right, flipped))
        assert abs(left[0] - right[0]) > 0.3
        color = new_step("color")
        color["settings"]["brightness"] = 0.2
        apply_step(image, color)
        brighter = layer.get_pixel(10, 10).get_rgba()
        assert brighter[0] > flipped[0] and brighter[1] > flipped[1]
    finally:
        image.delete()
    # Export a multi-layer image through an exporter that flattens it.
    wm = new_step("watermark")
    wm["settings"].update(mode=False, image_file=str(source), opacity=30.0)
    target = work / "multi-layer.jpg"
    assert process_one(source, target, [wm], overwrite=True)["status"] == "success"
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(target)))
    try:
        assert (image.get_width(), image.get_height()) == (80, 40)
    finally:
        image.delete()


check("actual pixel flip, color change and multilayer JPEG export", pixel_behavior)


def legacy_runtime():
    from bimp_model import import_legacy

    steps = import_legacy("# BIMP 2.6\n[CHANGEFORMAT]\nformat=3\nquality=85\nsmoothing=0.2\nsubsampling=2\ndct=1\n")
    validate_runtime(steps)
    assert process_one(source, work / "legacy.jpg", steps, overwrite=True)["status"] == "success"


check("BIMP 2 JPEG parameters translated and exported", legacy_runtime)


def filesystem_publication():
    import os
    import tempfile
    from unittest.mock import patch
    import bimp_engine

    if os.name != "nt":
        return
    roots = [work]
    removable = os.environ.get("BIMP_TEST_REMOVABLE_ROOT")
    if removable:
        roots.append(Path(removable).resolve(strict=True))
    for root in roots:
        with tempfile.TemporaryDirectory(prefix="bimp3-test-", dir=root) as tmp:
            folder = Path(tmp).resolve()
            # Only our newly created test directory can be cleaned up.
            assert folder.parent == root.resolve() and folder.name.startswith("bimp3-test-")
            target = folder / "wynik.jpg"
            with patch.object(
                bimp_engine.os, "link", side_effect=AssertionError("Windows must not require hard links")
            ):
                assert process_one(source, target, [], overwrite=False)["status"] == "success"
                original = target.read_bytes()
                assert len(original) > 0
                assert process_one(source, target, [], overwrite=False)["status"] == "skipped"
                assert target.read_bytes() == original
                target.write_bytes(b"old output")
                assert process_one(source, target, [], overwrite=True)["status"] == "success"
                assert target.read_bytes() != b"old output"
                target.unlink()
                export = bimp_engine.export_image

                def concurrent_target(image, temporary, arguments):
                    export(image, temporary, arguments)
                    target.write_bytes(b"concurrent output")

                with patch.object(bimp_engine, "export_image", side_effect=concurrent_target):
                    assert process_one(source, target, [], overwrite=False)["status"] == "skipped"
                assert target.read_bytes() == b"concurrent output"
                assert not list(folder.glob(".bimp-*"))
            print("FILESYSTEM_PUBLICATION_OK", str(root))


check("Windows publication without hard links, skip, replace and concurrent target", filesystem_publication)


def lut_and_regressions():
    from bimp_engine import apply_step, render_preview, watermark_font
    from bimp_lut import native_module

    assert native_module() is not None, "Native LUT accelerator missing"
    cube = work / "inverse.cube"
    cube.write_text(
        "LUT_3D_SIZE 2\n" + "".join(f"{1 - r} {1 - g} {1 - b}\n" for b in range(2) for g in range(2) for r in range(2))
    )
    step = new_step("lut")
    step["settings"].update(file=str(cube), strength=100.0)
    validate_runtime([step])
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
    try:
        before = image.get_layers()[0].get_pixel(10, 10).get_rgba()
        apply_step(image, step)
        after = image.get_layers()[0].get_pixel(10, 10).get_rgba()

        # Gegl.Color.get_rgba returns linear RGB; .cube is applied to gamma sRGB.
        def encode(v):
            return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055

        def decode(v):
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

        assert all(abs(after[c] - decode(1 - encode(before[c]))) < 0.025 for c in range(3)), (before, after)
        assert abs(before[3] - after[3]) < 0.01
        assert "Bold" in watermark_font("Sans-serif Bold Italic 18px").get_name()
    finally:
        image.delete()
    render_preview(source, [step], work / "before-new.png", work / "after-new.png")
    assert (work / "after-new.png").is_file()
    dangerous = new_step("userdef")
    dangerous["settings"].update(procedure="gimp-quit", arguments={"force": False})
    try:
        validate_runtime([dangerous])
    except ValueError:
        pass
    else:
        raise AssertionError("gimp-quit accepted")


check("native Cube LUT pixels, preview, font styles and safe procedures", lut_and_regressions)


def metadata_and_profiles():
    from bimp_engine import prepare_metadata
    from bimp_presets import export_profile

    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
    try:
        metadata = Gimp.Metadata.new()
        assert metadata.try_set_tag_string("Exif.Image.Artist", "BIMP test")
        assert metadata.try_set_tag_string("Exif.GPSInfo.GPSLatitudeRef", "N")
        assert metadata.try_set_tag_string("Exif.GPSInfo.GPSLatitude", "52/1 0/1 0/1")
        assert image.set_metadata(metadata)
        prepare_metadata(image, "strip-gps")
        clean = image.get_metadata()
        assert clean.try_get_tag_string("Exif.Image.Artist") == "BIMP test"
        assert not any("GPS" in tag for tag in clean.get_exif_tags())
        prepare_metadata(image, "strip")
        empty = image.get_metadata()
        # GIMP repopulates intrinsic dimensions/resolution, but source tags vanish.
        assert empty is None or (
            "Exif.Image.Artist" not in empty.get_exif_tags() and not any("GPS" in t for t in empty.get_exif_tags())
        )
    finally:
        image.delete()
    for index in (1, 2, 3):
        steps, options = export_profile(index)
        validate_runtime(steps)
        from bimp_model import FORMATS

        extension = FORMATS[steps[-1]["settings"]["format"]]
        target = work / f"profile-{index}.{extension}"
        assert process_one(source, target, steps, overwrite=True, options=options)["status"] == "success"


check("metadata removal GPS, ICC policies and three export profiles", metadata_and_profiles)


def resumable_worker_and_preview():
    import time
    from bimp_jobs import Job, Worker, new_job_directory
    from bimp_preview import PreviewPane
    from gi.repository import GLib, Gtk

    home = work / "recovery-test"
    options = {"output_directory": str(home / "out"), "overwrite": True, "metadata": "strip-gps", "color_profile": True}
    job = Job.create(new_job_directory(home), [(source, home / "out/result.png")], [], options)
    worker = Worker(job)
    worker.start()
    deadline = time.monotonic() + 120
    while worker.poll() is None:
        assert time.monotonic() < deadline, "Background worker timeout"
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.05)
    restored = Job(job.path)
    assert restored.entries[0]["status"] == "success"
    assert restored.resume_indices() == []
    snapshot = Path(restored.entries[0]["target"]).stat().st_mtime_ns
    # A repeated run recovers from the journal and does not re-export success.
    second = Worker(restored)
    second.start()
    while second.poll() is None:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert Path(restored.entries[0]["target"]).stat().st_mtime_ns == snapshot
    pane = PreviewPane(home)
    pane.request(source, [])
    deadline = time.monotonic() + 120
    context = GLib.MainContext.default()
    while pane.pending or pane.worker or pane.timer:
        context.iteration(True)
        assert time.monotonic() < deadline, "Asynchronous preview timeout"
    assert pane.images[0].get_pixbuf() is not None, pane.status.get_text()
    assert pane.images[1].get_pixbuf() is not None
    pane.destroy()


check("durable job recovery and asynchronous before-after preview", resumable_worker_and_preview)


def lut_editor_live_preview():
    import time
    from bimp_ui import edit_step
    from bimp_preview import PreviewPane
    from bimp_model import SCHEMAS
    from gi.repository import Gtk, GLib, Gdk

    lut = work / "editor-inverse.cube"
    lut.write_text("LUT_1D_SIZE 2\n1 1 1\n0 0 0\n")
    step = new_step("lut")
    step["settings"].update(file=str(lut), strength=100.0)
    parent = Gtk.Window()
    state = {"stage": 0, "error": None, "deadline": time.monotonic() + 120}

    def walk(widget):
        yield widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                yield from walk(child)

    def monitor():
        dialogs = [w for w in Gtk.Window.list_toplevels() if w.get_title() == SCHEMAS["lut"][0]]
        if not dialogs:
            return GLib.SOURCE_CONTINUE
        dialog = dialogs[0]
        widgets = list(walk(dialog))
        pane = next((w for w in widgets if isinstance(w, PreviewPane)), None)
        if time.monotonic() > state["deadline"]:
            state["error"] = "LUT editor preview timed out: " + (pane.status.get_text() if pane else "no pane")
            dialog.response(Gtk.ResponseType.CANCEL)
            return GLib.SOURCE_REMOVE
        if pane and not pane.worker and not pane.pending and not pane.timer and pane.images[1].get_pixbuf():
            if state["stage"] == 0:
                state["pixels100"] = pane.images[1].get_pixbuf().get_pixels()
                next(w for w in widgets if isinstance(w, Gtk.Scale)).set_value(25)
                state["stage"] = 1
            else:
                if pane.images[1].get_pixbuf().get_pixels() == state["pixels100"]:
                    state["error"] = "LUT strength did not change preview pixels"
                native = dialog.get_window()
                capture = Gdk.pixbuf_get_from_window(
                    native, 0, 0, dialog.get_allocated_width(), dialog.get_allocated_height()
                )
                capture.savev(str(work / "lut-editor.png"), "png", [], [])
                dialog.response(Gtk.ResponseType.OK)
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(100, monitor)
    result = edit_step(parent, step, str(source), [], work / "editor-home")
    parent.destroy()
    assert not state["error"], state["error"]
    assert result and result["settings"]["strength"] == 25


check("LUT editor automatic before-after preview and strength slider", lut_editor_live_preview)


def cleanup_and_collision_guards():
    import warnings
    import bimp_engine
    from unittest.mock import patch

    original = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.name.startswith(".bimp-"):
            raise PermissionError("simulated cleanup denial")
        return original(path, *args, **kwargs)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with (
            patch.object(Path, "unlink", fail_cleanup),
            patch.object(bimp_engine.Gimp, "context_pop", wraps=Gimp.context_pop) as restored,
        ):
            assert process_one(source, work / "cleanup-success.png", [], overwrite=True)["status"] == "success"
            assert restored.call_count == 1
    wm = new_step("watermark")
    wm["settings"].update(mode=False, image_file=str(source))
    try:
        process_one(work / "pipeline.png" if (work / "pipeline.png").exists() else source, source, [wm], overwrite=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Dependency overwrite allowed")


check("cleanup warning cannot skip context restoration and dependencies stay protected", cleanup_and_collision_guards)


def registration():
    proc = Gimp.get_pdb().lookup_procedure("plug-in-bimp3")
    assert proc, "Plugin not registered"
    settings = work / "batch.json"
    fmt = new_step("changeformat")
    fmt["settings"]["format"] = 4
    save_settings(settings, [fmt])
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("settings-file", str(settings))
    cfg.set_property("input-files", json.dumps([str(source)]))
    cfg.set_property("output-directory", str(work / "via-pdb"))
    cfg.set_property("overwrite", True)
    returned = proc.run(cfg)
    assert returned.index(0) == Gimp.PDBStatusType.SUCCESS, (
        str(returned.index(1)) if returned.length() > 1 else "No error text"
    )
    assert (work / "via-pdb" / source.name).is_file()


check("plugin discovery and real noninteractive PDB invocation", registration)
sys.path.insert(0, str(BASE / "tests"))
from ui_scenarios import preferences_and_retry

check(
    "preferences restore, export profile, write plan and retry only failed entries",
    lambda: preferences_and_retry(work, source),
)


def watermark_fonts():
    from bimp_engine import watermark_font, apply_step
    from bimp_ui import Form
    from bimp_jobs import Job, Worker, new_job_directory
    from gi.repository import GimpUi
    import time

    GimpUi.init("bimp3-test")
    descriptions = [
        "Arial Rounded MT Bold Italic 16px",
        "Arial Regular 24px",
        "Arial Bold Italic 18px",
        "Arial Rounded MT Bold Regular 18px",
    ]
    for description in descriptions:
        selected = watermark_font(description)
        form = Form()
        form.add("font", "Czcionka", description)
        chosen = form.values()["font"]
        assert watermark_font(chosen).get_name() == selected.get_name(), (description, chosen)
        image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(str(source)))
        try:
            step = new_step("watermark")
            step["settings"].update(text="Example watermark", font=chosen, color="#ffffff")
            validate_runtime([step])
            apply_step(image, step)
            layer = image.get_layers()[0]
            assert layer.get_font().get_name() == selected.get_name()
        finally:
            image.delete()
        form.grid.destroy()
    job = Job.create(
        new_job_directory(work / "font-worker"),
        [(source, work / "font-worker" / "result.png")],
        [
            dict(
                type="watermark",
                settings=dict(
                    new_step("watermark")["settings"], text="Example watermark", font="Arial Rounded MT Bold Italic 16px"
                ),
            )
        ],
        {"output_directory": str(work / "font-worker"), "overwrite": True},
    )
    worker = Worker(job)
    worker.start()
    deadline = time.monotonic() + 90
    while worker.poll() is None:
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert job.entries[0]["status"] == "success", (
        job.entries,
        (job.directory / "worker.log").read_text(encoding="utf-8", errors="replace"),
    )
    try:
        watermark_font("ZupelnieNieznanaCzcionka 16px")
    except ValueError:
        pass
    else:
        raise AssertionError("Missing font should not silently use an unrelated family")


check("watermark GIMP font chooser and installed font styles", watermark_fonts)


def repeated_photo_preview():
    import time
    from bimp_preview import PreviewPane
    from gi.repository import GLib

    chosen = Path(os.environ.get("BIMP_PREVIEW_TEST_IMAGE", str(source)))
    cube = Path(os.environ.get("BIMP_PREVIEW_TEST_LUT", str(BASE / "examples" / "warm-demo.cube")))
    step = new_step("lut")
    step["settings"].update(file=str(cube), strength=100.0)
    pane = PreviewPane(work / "preview-request-regression")
    pane.request(chosen, [step])
    pane.request(chosen, [step])
    GLib.source_remove(pane.timer)
    pane.timer = None
    pane.launch()
    original_worker = pane.worker
    pane.request(chosen, [step])
    assert pane.worker is original_worker and pane.pending is None
    changed = new_step("lut")
    changed["settings"].update(file=str(cube), strength=35.0)
    pane.request(chosen, [changed])
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 120
    while pane.images[0].get_pixbuf() is None:
        context.iteration(True)
        assert time.monotonic() < deadline, "Source image did not appear"
    while pane.pending or pane.worker or pane.timer:
        context.iteration(True)
        assert time.monotonic() < deadline, pane.status.get_text()
    assert pane.images[1].get_pixbuf() is not None, pane.status.get_text()
    assert pane.status.get_text().startswith("Podgląd gotowy"), pane.status.get_text()
    pane.destroy()


check("repeated photo preview requests with LUT", repeated_photo_preview)
results["passed"] = len(results["checks"])
results["failed"] = len(results["failures"])
(BASE / "tests" / "integration-result.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("BIMP_INTEGRATION_RESULT", results["passed"], results["failed"])
if results["failed"]:
    raise RuntimeError("BIMP integration tests failed; see integration-result.json")
