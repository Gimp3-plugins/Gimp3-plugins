"""BIMP queue, export settings, preview and durable background jobs.
SPDX-License-Identifier: GPL-2.0-or-later
"""

import copy
import json
from collections import Counter
from pathlib import Path
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GimpUi", "3.0")
from gi.repository import Gtk, GimpUi, Gimp, GLib
from bimp_model import (
    SCHEMAS,
    FORMATS,
    new_step,
    validate_steps,
    plan_outputs,
    dependency_paths,
    path_key,
    save_settings,
    load_settings,
    atomic_json,
)
from bimp_engine import EXPORTERS, validate_runtime, procedure
from bimp_jobs import Job, Worker, new_job_directory
from bimp_presets import PROFILES, export_profile
from bimp_preview import PreviewPane
from bimp_ui import button, choose, scroll, error, edit_step


def combo(items, selected):
    widget = Gtk.ComboBoxText()
    for key, label in items:
        widget.append(key, label)
    widget.set_active_id(selected)
    return widget


class BatchWindow:
    def __init__(self, home=None, restore=True):
        GimpUi.init("bimp3")
        self.home = Path(home) if home else Path(Gimp.directory()) / "bimp3-data"
        self.home.mkdir(parents=True, exist_ok=True)
        self.preferences = self.home / "preferences.json"
        self.loading = True
        self.disposed = False
        self.save_timer = None
        self.worker = None
        self.job = None
        self.busy = self.cancelled = False
        self.steps, self.results = [], []
        self.file_keys = set()
        self.dialog = Gtk.Dialog(title="BIMP 3 — zdjęcia, LUT i przetwarzanie wsadowe")
        self.dialog.set_default_size(1080, 800)
        GimpUi.window_set_transient(self.dialog)
        self.dialog.add_button("Zamknij", Gtk.ResponseType.CLOSE)
        self.dialog.connect("delete-event", self.on_delete)
        self.dialog.connect("destroy", self.on_destroy)
        area = self.dialog.get_content_area()
        area.set_border_width(12)
        area.set_spacing(8)
        self.notebook = Gtk.Notebook()
        area.pack_start(self.notebook, True, True, 0)
        queue = Gtk.Box(spacing=12, homogeneous=True)
        self.notebook.append_page(queue, Gtk.Label(label="Operacje i zdjęcia"))
        self.preview = PreviewPane(self.home)
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preview_box.pack_start(button("Odśwież podgląd zaznaczonego zdjęcia", self.show_preview), False, False, 0)
        preview_box.pack_start(self.preview, True, True, 0)
        self.notebook.append_page(preview_box, Gtk.Label(label="Podgląd PRZED / PO"))
        self.step_store, self.file_store = Gtk.ListStore(str), Gtk.ListStore(str)
        self.step_view, self.file_view = Gtk.TreeView(model=self.step_store), Gtk.TreeView(model=self.file_store)
        self.file_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.step_view.connect("row-activated", lambda *_: self.edit())
        left, right = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6) for _ in range(2)]
        self.edit_widgets = []
        for box, view, label in (
            (left, self.step_view, "Operacje w kolejności"),
            (right, self.file_view, "Zdjęcia wejściowe"),
        ):
            view.append_column(Gtk.TreeViewColumn(label, Gtk.CellRendererText(), text=0))
            box.pack_start(scroll(view, 230), True, True, 0)
            queue.pack_start(box, True, True, 0)
        for box, items in (
            (
                left,
                [
                    ("Dodaj", self.add),
                    ("Edytuj", self.edit),
                    ("Usuń", self.remove_step),
                    ("↑", lambda: self.move(-1)),
                    ("↓", lambda: self.move(1)),
                ],
            ),
            (
                right,
                [
                    ("Pliki…", self.add_files),
                    ("Folder…", self.add_folder),
                    ("Usuń", self.remove_files),
                    ("Podgląd", self.show_preview),
                ],
            ),
        ):
            bar = Gtk.Box(spacing=5)
            for label, callback in items:
                bar.pack_start(button(label, callback), False, False, 0)
            box.pack_start(bar, False, False, 0)
            self.edit_widgets.append(bar)
        self.profiles = combo([(str(i), name) for i, name in enumerate(PROFILES)], "0")
        presetbar = Gtk.Box(spacing=5)
        presetbar.pack_start(self.profiles, True, True, 0)
        presetbar.pack_start(button("Dodaj profil", self.apply_profile), False, False, 0)
        left.pack_start(presetbar, False, False, 0)
        sets = Gtk.Box(spacing=5)
        sets.pack_start(button("Wczytaj zestaw…", self.load), False, False, 0)
        sets.pack_start(button("Zapisz zestaw…", self.save), False, False, 0)
        left.pack_start(sets, False, False, 0)
        self.edit_widgets += [presetbar, sets]
        self.recursive = Gtk.CheckButton(label="Przy dodawaniu folderu uwzględnij podfoldery")
        right.pack_start(self.recursive, False, False, 0)
        self.scan_status = Gtk.Label(xalign=0)
        right.pack_start(self.scan_status, False, False, 0)
        self.output = Gtk.FileChooserButton(title="Katalog wyników", action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.output.connect("file-set", lambda *_: self.schedule_save())
        outrow = Gtk.Box(spacing=8)
        outrow.pack_start(Gtk.Label(label="Katalog wyników:"), False, False, 0)
        outrow.pack_start(self.output, True, True, 0)
        area.pack_start(outrow, False, False, 0)
        self.hierarchy = Gtk.CheckButton(label="Zachowaj podfoldery")
        self.keep_dates = Gtk.CheckButton(label="Zachowaj daty plików")
        self.remove_done = Gtk.CheckButton(label="Usuń udane wpisy z listy")
        row = Gtk.Box(spacing=12)
        for widget in (self.hierarchy, self.keep_dates, self.remove_done):
            row.pack_start(widget, False, False, 0)
            widget.connect("toggled", lambda *_: self.schedule_save())
        area.pack_start(row, False, False, 0)
        settings = Gtk.Grid(column_spacing=12, row_spacing=6, margin=6)
        self.overwrite = combo(
            [("skip", "Pomiń istniejące"), ("replace", "Zastąp wyniki"), ("suffix", "Dodaj przyrostek _2, _3…")], "skip"
        )
        self.metadata = combo(
            [
                ("strip-gps", "Zachowaj metadane, usuń GPS"),
                ("preserve", "Zachowaj metadane"),
                ("strip", "Usuń EXIF / IPTC / XMP"),
            ],
            "strip-gps",
        )
        self.output_color = combo([("preserve", "Zachowaj profil kolorów"), ("srgb", "Konwertuj do sRGB")], "preserve")
        self.color_profile = Gtk.CheckButton(label="Osadź profil ICC w wyniku")
        self.color_profile.set_active(True)
        for rowno, (label, widget) in enumerate(
            (("Kolizje nazw", self.overwrite), ("Metadane", self.metadata), ("Kolory", self.output_color))
        ):
            settings.attach(Gtk.Label(label=label, xalign=0), 0, rowno, 1, 1)
            settings.attach(widget, 1, rowno, 1, 1)
            widget.connect("changed", lambda *_: self.schedule_save())
        settings.attach(self.color_profile, 1, 3, 1, 1)
        self.color_profile.connect("toggled", lambda *_: self.schedule_save())
        expander = Gtk.Expander(label="Eksport: metadane, kolory i kolizje")
        expander.add(settings)
        area.pack_start(expander, False, False, 0)
        self.edit_widgets += [outrow, row, expander]
        actions = Gtk.Box(spacing=6)
        for label, callback in [
            ("Plan zapisu…", self.show_plan),
            ("Wznów zadanie…", self.resume),
            ("Ponów błędne", self.retry),
            ("Zapisz raport…", self.save_report),
        ]:
            actions.pack_start(button(label, callback), False, False, 0)
        self.start_button, self.stop_button = button("Uruchom", self.start), button("Przerwij", self.cancel)
        self.stop_button.set_sensitive(False)
        actions.pack_end(self.start_button, False, False, 0)
        actions.pack_end(self.stop_button, False, False, 0)
        area.pack_start(actions, False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True)
        area.pack_start(self.progress, False, False, 0)
        self.log_buffer = Gtk.TextBuffer()
        area.pack_start(
            scroll(Gtk.TextView(buffer=self.log_buffer, editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR), 100),
            False,
            True,
            0,
        )
        self.scanning = False
        self.loading = False
        if restore:
            self.restore()

    def run(self):
        self.dialog.show_all()
        while True:
            self.dialog.run()
            if not self.busy:
                break
            self.cancel()
        self.persist()
        self.dialog.destroy()

    def on_delete(self, *_):
        if self.busy:
            self.cancel()
            return True
        self.persist()
        return False

    def options(self):
        return {
            "output_directory": self.output.get_filename(),
            "hierarchy": self.hierarchy.get_active(),
            "keep_dates": self.keep_dates.get_active(),
            "overwrite": self.overwrite.get_active_id() == "replace",
            "collision": "suffix" if self.overwrite.get_active_id() == "suffix" else "error",
            "metadata": self.metadata.get_active_id(),
            "color_profile": self.color_profile.get_active(),
            "output_color": self.output_color.get_active_id(),
        }

    def schedule_save(self):
        if self.loading or self.disposed:
            return
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(500, self.persist)

    def persist(self):
        self.save_timer = None
        if self.disposed:
            return GLib.SOURCE_REMOVE
        try:
            atomic_json(
                self.preferences,
                {
                    "version": 1,
                    "steps": self.steps,
                    "inputs": [r[0] for r in self.file_store],
                    "options": self.options(),
                    "recursive": self.recursive.get_active(),
                    "remove_done": self.remove_done.get_active(),
                    "last_job": str(self.job.path) if self.job else None,
                },
            )
        except Exception as exc:
            self.log("Nie zapisano preferencji: " + str(exc))
        return GLib.SOURCE_REMOVE

    def on_destroy(self, *_):
        self.disposed = True
        self.scanning = False
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None

    def restore(self):
        if not self.preferences.exists():
            return
        self.loading = True
        try:
            data = json.loads(self.preferences.read_text(encoding="utf-8"))
            self.steps = validate_steps(data.get("steps", []))
            self.append_files([p for p in data.get("inputs", []) if Path(p).is_file()])
            options = data.get("options", {})
            if options.get("output_directory") and Path(options["output_directory"]).is_dir():
                self.output.set_filename(options["output_directory"])
            self.hierarchy.set_active(options.get("hierarchy", False))
            self.keep_dates.set_active(options.get("keep_dates", False))
            self.recursive.set_active(data.get("recursive", False))
            self.remove_done.set_active(data.get("remove_done", False))
            self.overwrite.set_active_id(
                "suffix" if options.get("collision") == "suffix" else "replace" if options.get("overwrite") else "skip"
            )
            self.metadata.set_active_id(options.get("metadata", "strip-gps"))
            self.output_color.set_active_id(options.get("output_color", "preserve"))
            self.color_profile.set_active(options.get("color_profile", True))
            self.last_job = data.get("last_job")
            if self.last_job:
                self.log("Ostatnie zadanie można wznowić: " + self.last_job)
            self.refresh()
        except Exception as exc:
            self.log("Nie odtworzono preferencji: " + str(exc))
        finally:
            self.loading = False

    def log(self, text):
        self.log_buffer.insert(self.log_buffer.get_end_iter(), text + "\n")

    def selected_step(self):
        model, it = self.step_view.get_selection().get_selected()
        return model.get_path(it).get_indices()[0] if it is not None else None

    def selected_source(self):
        _, paths = self.file_view.get_selection().get_selected_rows()
        return self.file_store[paths[0]][0] if paths else self.file_store[0][0] if len(self.file_store) else None

    def refresh(self):
        self.step_store.clear()
        for step in self.steps:
            s, kind = step["settings"], step["type"]
            extra = (
                ": " + FORMATS[s["format"]].upper()
                if kind == "changeformat"
                else ": " + Path(s["file"]).name + f" ({s['strength']:g}%)"
                if kind == "lut"
                else ""
            )
            self.step_store.append([SCHEMAS[kind][0] + extra])
        self.schedule_save()

    def add(self):
        menu = Gtk.Menu()
        for kind, (label, _) in SCHEMAS.items():
            item = Gtk.MenuItem(label=label)

            def activate(_item, k=kind):
                result = edit_step(self.dialog, new_step(k), self.selected_source(), self.steps, self.home)
                if result:
                    try:
                        validate_steps(self.steps + [result])
                        self.steps.append(result)
                        self.refresh()
                    except Exception as exc:
                        error(self.dialog, exc)

            item.connect("activate", activate)
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(None)

    def edit(self):
        index = self.selected_step()
        if not self.busy and index is not None:
            result = edit_step(self.dialog, self.steps[index], self.selected_source(), self.steps[:index], self.home)
            if result:
                self.steps[index] = result
                self.refresh()

    def remove_step(self):
        index = self.selected_step()
        if index is not None:
            self.steps.pop(index)
            self.refresh()

    def move(self, delta):
        index = self.selected_step()
        if index is not None and 0 <= index + delta < len(self.steps):
            self.steps[index], self.steps[index + delta] = self.steps[index + delta], self.steps[index]
            self.refresh()
            self.step_view.get_selection().select_path(index + delta)

    def append_files(self, files):
        seen = self.file_keys
        for path in files:
            name = str(Path(path).resolve())
            if path_key(name) not in seen:
                self.file_store.append([name])
                seen.add(path_key(name))
        self.schedule_save()

    def add_files(self):
        self.append_files(choose(self.dialog, "Dodaj zdjęcia", multiple=True))

    def add_folder(self):
        if self.scanning:
            self.scanning = False
            return
        folder = choose(self.dialog, "Dodaj folder", Gtk.FileChooserAction.SELECT_FOLDER)
        if not folder:
            return
        self.scanning = True
        self.scan_status.set_text("Skanowanie… Ponowne kliknięcie Folder… przerwie skanowanie.")
        iterator = Path(folder).rglob("*") if self.recursive.get_active() else Path(folder).iterdir()
        extensions = set(EXPORTERS) | {
            "psd",
            "ora",
            "svg",
            "jxl",
            "jp2",
            "j2k",
            "pbm",
            "pgm",
            "ppm",
            "pnm",
            "pdf",
            "dds",
        }

        def scan():
            if not self.scanning or self.busy:
                self.scanning = False
                self.scan_status.set_text("Skanowanie przerwane.")
                return GLib.SOURCE_REMOVE
            found = []
            try:
                for _ in range(100):
                    path = next(iterator)
                    if path.is_file() and path.suffix.lower().lstrip(".") in extensions:
                        found.append(str(path))
            except StopIteration:
                self.scanning = False
            except OSError as exc:
                self.scanning = False
                self.log(str(exc))
            self.append_files(found)
            self.scan_status.set_text(
                f"Na liście: {len(self.file_store)} zdjęć." + (" Skanowanie…" if self.scanning else "")
            )
            return GLib.SOURCE_CONTINUE if self.scanning else GLib.SOURCE_REMOVE

        GLib.idle_add(scan)

    def remove_files(self):
        _, paths = self.file_view.get_selection().get_selected_rows()
        for path in reversed(paths):
            self.file_store.remove(self.file_store.get_iter(path))
        self.file_keys = {path_key(r[0]) for r in self.file_store}
        self.schedule_save()

    def apply_profile(self):
        index = int(self.profiles.get_active_id())
        if not index:
            return
        steps, options = export_profile(index)
        # Preserve creative steps; replace only sizing and export steps.
        self.steps = [s for s in self.steps if s["type"] not in ("resize", "changeformat")] + steps
        self.metadata.set_active_id(options["metadata"])
        self.output_color.set_active_id(options["output_color"])
        self.color_profile.set_active(options["color_profile"])
        self.refresh()

    def protect_write(self, path):
        protected = [r[0] for r in self.file_store] + dependency_paths(self.steps)
        if self.job:
            protected += [e["target"] for e in self.job.entries]
        if path_key(path) in {path_key(p) for p in protected}:
            raise ValueError("Nie można nadpisać zdjęcia, zależności ani wyniku zadania raportem lub zestawem.")

    def load(self):
        path = choose(self.dialog, "Zestaw BIMP 3 lub BIMP 2")
        if path:
            try:
                steps = load_settings(path)
                validate_runtime(steps)
                self.steps = steps
                self.refresh()
            except Exception as exc:
                error(self.dialog, exc)

    def save(self):
        path = choose(self.dialog, "Zapisz zestaw", Gtk.FileChooserAction.SAVE, name="zestaw.bimp3.json")
        if path:
            try:
                self.protect_write(path)
                save_settings(path, self.steps)
            except Exception as exc:
                error(self.dialog, exc)

    def save_report(self):
        path = choose(self.dialog, "Zapisz raport", Gtk.FileChooserAction.SAVE, name="bimp3-raport.json")
        if path:
            try:
                self.protect_write(path)
                atomic_json(path, self.job.report() if self.job else {"results": self.results})
            except Exception as exc:
                error(self.dialog, exc)

    def build_plan(self):
        options = self.options()
        if not options["output_directory"]:
            raise ValueError("Wybierz katalog wyników.")
        validate_runtime(self.steps)
        plans = plan_outputs(
            [r[0] for r in self.file_store],
            options["output_directory"],
            self.steps,
            options["hierarchy"],
            collision=options["collision"],
        )
        for extension in {p.suffix.lower().lstrip(".") for _, p in plans}:
            if extension in EXPORTERS:
                procedure(EXPORTERS[extension])
        return plans, options

    def show_plan(self):
        try:
            plans, options = self.build_plan()
            dialog = Gtk.Dialog(title="Plan zapisu — bez modyfikowania plików", transient_for=self.dialog, modal=True)
            dialog.add_button("Zamknij", Gtk.ResponseType.CLOSE)
            dialog.set_default_size(920, 500)
            store = Gtk.ListStore(str, str, str)
            for source, target in plans:
                status = (
                    "Zastąp"
                    if target.exists() and options["overwrite"]
                    else "Pomiń"
                    if target.exists()
                    else "Nowy plik"
                )
                store.append([str(source), str(target), status])
            view = Gtk.TreeView(model=store)
            for i, label in enumerate(("Źródło", "Wynik", "Działanie")):
                view.append_column(Gtk.TreeViewColumn(label, Gtk.CellRendererText(), text=i))
            dialog.get_content_area().pack_start(scroll(view), True, True, 0)
            dialog.show_all()
            dialog.run()
            dialog.destroy()
        except Exception as exc:
            error(self.dialog, exc)

    def show_preview(self):
        source = self.selected_source()
        if not source:
            error(self.dialog, "Dodaj i zaznacz zdjęcie.")
            return
        self.notebook.set_current_page(1)
        self.preview.request(source, self.steps)

    def launch_job(self, job):
        if self.busy:
            raise ValueError("Poczekaj na zakończenie bieżącego zadania.")
        self.job = job
        self.worker = Worker(job)
        self.worker.start()
        self.busy, self.cancelled = True, False
        self.results = []
        self.index = 0
        self.logged = {}
        self.result_map = {
            i: dict(e) for i, e in enumerate(job.entries) if e["status"] in ("success", "skipped", "error")
        }
        self.statuses = [e["status"] for e in job.entries]
        self.counts = Counter(self.statuses)
        self.active_name = "Uruchamianie procesu GIMP…"
        self.log_buffer.set_text("Zadanie działa w osobnym procesie GIMP.\nDziennik: " + str(job.path) + "\n")
        for widget in self.edit_widgets + [self.start_button]:
            widget.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.dialog.set_response_sensitive(Gtk.ResponseType.CLOSE, False)
        self.persist()
        GLib.timeout_add(150, self.tick)

    def start(self):
        try:
            plans, options = self.build_plan()
            self.run_remove = self.remove_done.get_active()
            self.launch_job(Job.create(new_job_directory(self.home), plans, copy.deepcopy(self.steps), options))
        except Exception as exc:
            error(self.dialog, exc)

    def resume(self):
        if self.busy:
            return
        path = choose(
            self.dialog,
            "Wybierz job.json zapisanego zadania",
            initial=str(self.job.path) if self.job else getattr(self, "last_job", None),
        )
        if path:
            try:
                job = Job(path)
                job.resume_indices()
                self.run_remove = False
                self.launch_job(job)
            except Exception as exc:
                error(self.dialog, exc)

    def retry(self):
        if self.busy:
            return
        if not self.job:
            error(self.dialog, "Brak zakończonego zadania.")
            return
        plans = [(Path(e["source"]), Path(e["target"])) for e in self.job.entries if e["status"] == "error"]
        if not plans:
            error(self.dialog, "Brak błędnych pozycji do ponowienia.")
            return
        try:
            self.run_remove = False
            self.launch_job(
                Job.create(new_job_directory(self.home), plans, self.job.data["steps"], self.job.data["options"])
            )
        except Exception as exc:
            error(self.dialog, exc)

    def cancel(self):
        self.cancelled = True
        if self.worker:
            self.worker.cancel()
        self.stop_button.set_sensitive(False)
        self.progress.set_text("Przerywanie — oczekiwanie na bezpieczne zakończenie operacji…")

    def tick(self):
        code = self.worker.poll()
        for index in self.job.changed:
            entry = self.job.entries[index]
            self.counts[self.statuses[index]] -= 1
            self.statuses[index] = entry["status"]
            self.counts[entry["status"]] += 1
            if entry["status"] == "running":
                self.active_name = Path(entry["source"]).name
            if entry["status"] in ("success", "skipped", "error"):
                self.result_map[index] = dict(entry)
            else:
                self.result_map.pop(index, None)
            if entry["status"] in ("success", "skipped", "error") and self.logged.get(index) != entry["status"]:
                self.log(f"{entry['status']}: {entry['source']} → {entry['target']}\n{entry.get('error', '')}")
                self.logged[index] = entry["status"]
        self.index = sum(self.counts[s] for s in ("success", "skipped", "error"))
        self.progress.set_fraction(self.index / max(1, len(self.job.entries)))
        if code is None:
            if not self.cancelled:
                self.progress.set_text(f"{self.index}/{len(self.job.entries)} — {self.active_name}")
            return GLib.SOURCE_CONTINUE
        self.results = [self.result_map[i] for i in sorted(self.result_map)]
        self.busy = False
        for widget in self.edit_widgets + [self.start_button]:
            widget.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.dialog.set_response_sensitive(Gtk.ResponseType.CLOSE, True)
        finished = self.job.finished or {"status": "error", "error": "Proces zakończył się bez raportu."}
        if code != 0 or finished.get("status") not in ("done", "cancelled", "error"):
            finished = {
                "status": "error",
                "error": f"Proces GIMP zakończył się kodem {code} bez poprawnego raportu końcowego.",
            }
        good = sum(e["status"] == "success" for e in self.results)
        failed = sum(e["status"] == "error" for e in self.results)
        skipped = sum(e["status"] == "skipped" for e in self.results)
        self.progress.set_text(f"{finished['status']}: zapisano {good}, pominięto {skipped}, błędów {failed}")
        if finished.get("error"):
            self.log(finished["error"] + "\nLog: " + str(self.job.directory / "worker.log"))
        if self.run_remove:
            done = {path_key(e["source"]) for e in self.results if e["status"] == "success"}
            remaining = [r[0] for r in self.file_store if path_key(r[0]) not in done]
            self.file_store.clear()
            self.file_keys.clear()
            self.append_files(remaining)
        self.persist()
        return GLib.SOURCE_REMOVE
