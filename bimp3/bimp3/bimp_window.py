"""BIMP queue, export settings, preview and durable background jobs.
SPDX-License-Identifier: GPL-2.0-or-later
"""

import copy
import json
import queue
import threading
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GimpUi", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GimpUi, Gimp, Gio, GLib
from bimp_i18n import LANGUAGES, _, preferred_language, set_language, status_label, translate_message
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
    variant_targets,
)
from bimp_engine import EXPORTERS, validate_runtime, procedure
from bimp_history import clean_previews, created_label, data_usage, delete_job, human_size, list_jobs, prune_jobs
from bimp_jobs import Job, Worker, new_job_directory, stop_preview_servers
from bimp_presets import PROFILES, export_profile
from bimp_preview import PreviewPane
from bimp_ui import button, choose, scroll, error, edit_step

IMAGE_EXTENSIONS = set(EXPORTERS) | {
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
LOG_LINES = 3000
THUMBNAIL = 48
FILE_PATH, FILE_THUMB, FILE_NAME = range(3)


def combo(items, selected):
    widget = Gtk.ComboBoxText()
    for key, label in items:
        widget.append(key, label)
    widget.set_active_id(selected)
    return widget


class ThumbnailLoader:
    """Loads small previews one at a time in a background thread."""

    def __init__(self, deliver):
        self.deliver = deliver
        self.queue = queue.Queue()
        self.stopped = False
        threading.Thread(target=self.run, daemon=True).start()

    def request(self, path):
        self.queue.put(path)

    def run(self):
        while not self.stopped:
            path = self.queue.get()
            if path is None:
                return
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMBNAIL, THUMBNAIL, True)
                pixbuf = pixbuf.apply_embedded_orientation()
            except GLib.Error:
                continue  # Formats only GIMP can read keep the generic icon.
            GLib.idle_add(self.deliver, path, pixbuf)

    def stop(self):
        self.stopped = True
        self.queue.put(None)


class BatchWindow:
    def __init__(self, home=None, restore=True):
        GimpUi.init("bimp3")
        self.home = Path(home) if home else Path(Gimp.directory()) / "bimp3-data"
        self.home.mkdir(parents=True, exist_ok=True)
        self.preferences = self.home / "preferences.json"
        set_language(preferred_language(self.preferences))
        clean_previews(self.home)
        self.loading = True
        self.disposed = False
        self.save_timer = None
        self.worker = None
        self.job = None
        self.last_job = None
        self.language = "auto"
        self.busy = self.cancelled = False
        self.steps, self.results = [], []
        self.file_keys = set()
        self.scan_iterators = []
        self.dialog = Gtk.Dialog(title=_("BIMP 3 — zdjęcia, LUT i przetwarzanie wsadowe"))
        self.dialog.set_default_size(1080, 820)
        GimpUi.window_set_transient(self.dialog)
        self.dialog.add_button(_("Zamknij"), Gtk.ResponseType.CLOSE)
        self.dialog.connect("delete-event", self.on_delete)
        self.dialog.connect("destroy", self.on_destroy)
        area = self.dialog.get_content_area()
        area.set_border_width(12)
        area.set_spacing(8)
        self.notebook = Gtk.Notebook()
        area.pack_start(self.notebook, True, True, 0)
        queue_page = Gtk.Box(spacing=12, homogeneous=True)
        self.notebook.append_page(queue_page, Gtk.Label(label=_("Operacje i zdjęcia")))
        self.preview = PreviewPane(self.home)
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preview_box.pack_start(button(_("Odśwież podgląd zaznaczonego zdjęcia"), self.show_preview), False, False, 0)
        preview_box.pack_start(self.preview, True, True, 0)
        self.notebook.append_page(preview_box, Gtk.Label(label=_("Podgląd PRZED / PO")))
        self.step_store = Gtk.ListStore(str)
        self.file_store = Gtk.ListStore(str, GdkPixbuf.Pixbuf, str)
        self.file_filter = self.file_store.filter_new()
        self.file_filter.set_visible_func(self.file_visible)
        self.step_view = Gtk.TreeView(model=self.step_store)
        self.file_view = Gtk.TreeView(model=self.file_filter)
        self.file_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.step_view.connect("row-activated", lambda *_args: self.edit())
        self.step_view.append_column(Gtk.TreeViewColumn(_("Operacje w kolejności"), Gtk.CellRendererText(), text=0))
        files_column = Gtk.TreeViewColumn(_("Zdjęcia wejściowe — przeciągnij tu pliki lub foldery"))
        thumb_cell, name_cell = Gtk.CellRendererPixbuf(), Gtk.CellRendererText()
        thumb_cell.set_fixed_size(THUMBNAIL + 4, THUMBNAIL + 4)
        files_column.pack_start(thumb_cell, False)
        files_column.add_attribute(thumb_cell, "pixbuf", FILE_THUMB)
        files_column.pack_start(name_cell, True)
        files_column.add_attribute(name_cell, "text", FILE_NAME)
        self.file_view.append_column(files_column)
        self.file_view.set_tooltip_column(FILE_PATH)
        self.file_view.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.file_view.drag_dest_add_uri_targets()
        self.file_view.connect("drag-data-received", self.on_drop)
        self.thumbnails = ThumbnailLoader(self.set_thumbnail)
        left, right = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6) for _index in range(2)]
        left.pack_start(scroll(self.step_view, 230), True, True, 0)
        self.filter_entry = Gtk.SearchEntry(placeholder_text=_("Filtruj listę (nazwa, folder, rozszerzenie)…"))
        self.filter_entry.connect("search-changed", lambda *_args: self.file_filter.refilter())
        right.pack_start(self.filter_entry, False, False, 0)
        right.pack_start(scroll(self.file_view, 230), True, True, 0)
        queue_page.pack_start(left, True, True, 0)
        queue_page.pack_start(right, True, True, 0)
        self.edit_widgets = []
        for box, items in (
            (
                left,
                [
                    (_("Dodaj"), self.add),
                    (_("Edytuj"), self.edit),
                    (_("Usuń"), self.remove_step),
                    ("↑", lambda: self.move(-1)),
                    ("↓", lambda: self.move(1)),
                ],
            ),
            (
                right,
                [
                    (_("Pliki…"), self.add_files),
                    (_("Folder…"), self.add_folder),
                    (_("Usuń"), self.remove_files),
                    (_("Podgląd"), self.show_preview),
                ],
            ),
        ):
            bar = Gtk.Box(spacing=5)
            for label, callback in items:
                bar.pack_start(button(label, callback), False, False, 0)
            box.pack_start(bar, False, False, 0)
            self.edit_widgets.append(bar)
        self.profiles = combo([(str(i), _(name)) for i, name in enumerate(PROFILES)], "0")
        presetbar = Gtk.Box(spacing=5)
        presetbar.pack_start(self.profiles, True, True, 0)
        presetbar.pack_start(button(_("Dodaj profil"), self.apply_profile), False, False, 0)
        left.pack_start(presetbar, False, False, 0)
        sets = Gtk.Box(spacing=5)
        sets.pack_start(button(_("Wczytaj zestaw…"), self.load), False, False, 0)
        sets.pack_start(button(_("Zapisz zestaw…"), self.save), False, False, 0)
        left.pack_start(sets, False, False, 0)
        self.edit_widgets += [presetbar, sets]
        self.recursive = Gtk.CheckButton(label=_("Przy dodawaniu folderu uwzględnij podfoldery"))
        right.pack_start(self.recursive, False, False, 0)
        self.scan_status = Gtk.Label(xalign=0)
        right.pack_start(self.scan_status, False, False, 0)
        self.output = Gtk.FileChooserButton(title=_("Katalog wyników"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.output.connect("file-set", lambda *_args: self.schedule_save())
        outrow = Gtk.Box(spacing=8)
        outrow.pack_start(Gtk.Label(label=_("Katalog wyników:")), False, False, 0)
        outrow.pack_start(self.output, True, True, 0)
        area.pack_start(outrow, False, False, 0)
        self.hierarchy = Gtk.CheckButton(label=_("Zachowaj podfoldery"))
        self.keep_dates = Gtk.CheckButton(label=_("Zachowaj daty plików"))
        self.remove_done = Gtk.CheckButton(label=_("Usuń udane wpisy z listy"))
        row = Gtk.Box(spacing=12)
        for widget in (self.hierarchy, self.keep_dates, self.remove_done):
            row.pack_start(widget, False, False, 0)
            widget.connect("toggled", lambda *_args: self.schedule_save())
        area.pack_start(row, False, False, 0)
        settings = Gtk.Grid(column_spacing=12, row_spacing=6, margin=6)
        self.overwrite = combo(
            [
                ("skip", _("Pomiń istniejące")),
                ("replace", _("Zastąp wyniki")),
                ("suffix", _("Dodaj przyrostek _2, _3…")),
            ],
            "skip",
        )
        self.metadata = combo(
            [
                ("strip-gps", _("Zachowaj metadane, usuń GPS i nazwy miejsc")),
                ("preserve", _("Zachowaj metadane")),
                ("strip", _("Usuń EXIF / IPTC / XMP")),
            ],
            "strip-gps",
        )
        self.output_color = combo(
            [("preserve", _("Zachowaj profil kolorów")), ("srgb", _("Konwertuj do sRGB"))], "preserve"
        )
        self.language_combo = combo([(code, label) for code, label in LANGUAGES.items()], "auto")
        self.language_combo.connect("changed", self.on_language)
        for rowno, (label, widget) in enumerate(
            (
                (_("Kolizje nazw"), self.overwrite),
                (_("Metadane"), self.metadata),
                (_("Kolory"), self.output_color),
                (_("Język interfejsu"), self.language_combo),
            )
        ):
            settings.attach(Gtk.Label(label=label, xalign=0), 0, rowno, 1, 1)
            settings.attach(widget, 1, rowno, 1, 1)
            if widget is not self.language_combo:
                widget.connect("changed", lambda *_args: self.schedule_save())
        self.color_profile = Gtk.CheckButton(label=_("Osadź profil ICC w wyniku"))
        self.color_profile.set_active(True)
        self.auto_orient = Gtk.CheckButton(label=_("Obracaj zdjęcia zgodnie z orientacją EXIF"))
        self.auto_orient.set_active(True)
        for offset, widget in enumerate((self.color_profile, self.auto_orient)):
            settings.attach(widget, 1, 4 + offset, 1, 1)
            widget.connect("toggled", lambda *_args: self.schedule_save())
        expander = Gtk.Expander(label=_("Eksport: metadane, kolory, kolizje i język"))
        expander.add(settings)
        area.pack_start(expander, False, False, 0)
        self.edit_widgets += [outrow, row, expander]
        actions = Gtk.Box(spacing=6)
        for label, callback in [
            (_("Plan zapisu…"), self.show_plan),
            (_("Wznów zadanie…"), self.resume),
            (_("Ponów błędne"), self.retry),
            (_("Zapisz raport…"), self.save_report),
            (_("Historia i dane…"), self.show_history),
        ]:
            actions.pack_start(button(label, callback), False, False, 0)
        self.start_button, self.stop_button = button(_("Uruchom"), self.start), button(_("Przerwij"), self.cancel)
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

    # --- window lifetime -------------------------------------------------

    def run(self):
        self.dialog.show_all()
        while True:
            self.dialog.run()
            if not self.busy:
                break
            self.cancel()
        self.persist()
        self.dialog.destroy()

    def on_delete(self, *_args):
        if self.busy:
            self.cancel()
            return True
        self.persist()
        return False

    def on_destroy(self, *_args):
        self.disposed = True
        self.scanning = False
        self.thumbnails.stop()
        stop_preview_servers()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None

    def on_language(self, *_args):
        if self.loading:
            return
        self.language = self.language_combo.get_active_id()
        self.schedule_save()
        self.log(_("Język zostanie zmieniony po ponownym otwarciu okna BIMP."))

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
            "auto_orient": self.auto_orient.get_active(),
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
                    "inputs": self.inputs(),
                    "options": self.options(),
                    "recursive": self.recursive.get_active(),
                    "remove_done": self.remove_done.get_active(),
                    "last_job": str(self.job.path) if self.job else self.last_job,
                    "language": self.language,
                },
            )
        except Exception as exc:
            self.log(_("Nie zapisano preferencji:") + " " + translate_message(str(exc)))
        return GLib.SOURCE_REMOVE

    def restore(self):
        if not self.preferences.exists():
            return
        self.loading = True
        try:
            data = json.loads(self.preferences.read_text(encoding="utf-8"))
            self.language = data.get("language", "auto") if data.get("language") in LANGUAGES else "auto"
            self.language_combo.set_active_id(self.language)
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
            self.auto_orient.set_active(options.get("auto_orient", True))
            self.last_job = data.get("last_job")
            if self.last_job:
                self.log(_("Ostatnie zadanie można wznowić:") + " " + self.last_job)
            self.refresh()
        except Exception as exc:
            self.log(_("Nie odtworzono preferencji:") + " " + translate_message(str(exc)))
        finally:
            self.loading = False

    def log(self, text):
        self.log_buffer.insert(self.log_buffer.get_end_iter(), text + "\n")
        # Keep the log bounded for very long batches.
        extra = self.log_buffer.get_line_count() - LOG_LINES
        if extra > 0:
            self.log_buffer.delete(self.log_buffer.get_start_iter(), self.log_buffer.get_iter_at_line(extra))

    # --- steps -------------------------------------------------------------

    def selected_step(self):
        model, it = self.step_view.get_selection().get_selected()
        return model.get_path(it).get_indices()[0] if it is not None else None

    def refresh(self):
        self.step_store.clear()
        for step in self.steps:
            s, kind = step["settings"], step["type"]
            extra = ""
            if kind == "changeformat":
                extra = ": " + FORMATS[s["format"]].upper() + (f" ≤ {s['max_kb']} KB" if s.get("max_kb") else "")
            elif kind == "lut":
                extra = ": " + Path(s["file"]).name + f" ({s['strength']:g}%)"
            elif kind == "variant":
                fmt = FORMATS[s["format"] - 1].upper() if s["format"] else _("jak wynik")
                size = f", {s['max_edge']} px" if s["max_edge"] else ""
                extra = f": {s['suffix']} ({fmt}{size})"
            elif kind == "rename":
                extra = ": " + s["pattern"]
            self.step_store.append([_(SCHEMAS[kind][0]) + extra])
        self.schedule_save()

    def add(self):
        menu = Gtk.Menu()
        for kind, (label, _fields) in SCHEMAS.items():
            item = Gtk.MenuItem(label=_(label))

            def activate(_item, k=kind):
                result = edit_step(
                    self.dialog, new_step(k), self.selected_source(), self.steps, self.home, self.options()
                )
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
            result = edit_step(
                self.dialog, self.steps[index], self.selected_source(), self.steps[:index], self.home, self.options()
            )
            if result:
                try:
                    validate_steps(self.steps[:index] + [result] + self.steps[index + 1 :])
                    self.steps[index] = result
                    self.refresh()
                except Exception as exc:
                    error(self.dialog, exc)

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

    # --- input files ---------------------------------------------------------

    def inputs(self):
        return [row[FILE_PATH] for row in self.file_store]

    def file_visible(self, model, it, _data=None):
        text = self.filter_entry.get_text().strip().casefold() if hasattr(self, "filter_entry") else ""
        return not text or text in (model[it][FILE_PATH] or "").casefold()

    def selected_store_paths(self):
        _model, paths = self.file_view.get_selection().get_selected_rows()
        return [self.file_filter.convert_path_to_child_path(p) for p in paths]

    def selected_source(self):
        paths = self.selected_store_paths()
        if paths:
            return self.file_store[paths[0]][FILE_PATH]
        if len(self.file_filter):
            return self.file_filter[0][FILE_PATH]
        return self.file_store[0][FILE_PATH] if len(self.file_store) else None

    def append_files(self, files):
        seen = self.file_keys
        for path in files:
            name = str(Path(path).resolve())
            if path_key(name) not in seen:
                self.file_store.append([name, None, Path(name).name + "\n" + str(Path(name).parent)])
                seen.add(path_key(name))
                self.thumbnails.request(name)
        self.schedule_save()

    def set_thumbnail(self, path, pixbuf):
        if self.disposed:
            return GLib.SOURCE_REMOVE
        for row in self.file_store:
            if row[FILE_PATH] == path:
                row[FILE_THUMB] = pixbuf
                break
        return GLib.SOURCE_REMOVE

    def add_files(self):
        self.append_files(choose(self.dialog, _("Dodaj zdjęcia"), multiple=True))

    def add_folder(self):
        if self.scanning:
            self.scanning = False
            return
        folder = choose(self.dialog, _("Dodaj folder"), Gtk.FileChooserAction.SELECT_FOLDER)
        if folder:
            self.scan_folders([folder])

    def on_drop(self, _widget, context, _x, _y, data, _info, time):
        accepted = self.add_uris(data.get_uris() or [])
        Gtk.drag_finish(context, accepted, False, time)

    def add_uris(self, uris):
        """Dropped files go straight to the list; dropped folders are scanned like Folder…."""
        if self.busy:
            return False
        files, folders = [], []
        for uri in uris:
            parsed = urlparse(uri)
            if parsed.scheme != "file":
                continue
            path = Path(Gio.File.new_for_uri(uri).get_path() or unquote(parsed.path))
            if path.is_dir():
                folders.append(path)
            elif path.is_file() and path.suffix.lower().lstrip(".") in IMAGE_EXTENSIONS:
                files.append(str(path))
        self.append_files(files)
        if folders:
            self.scan_folders(folders)
        return bool(files or folders)

    def scan_folders(self, folders):
        """Scan in small portions from the main loop; another click on Folder… stops it."""
        recursive = self.recursive.get_active()
        self.scan_iterators += [Path(f).rglob("*") if recursive else Path(f).iterdir() for f in folders]
        if self.scanning:
            return
        self.scanning = True
        self.scan_status.set_text(_("Skanowanie… Ponowne kliknięcie Folder… przerwie skanowanie."))

        def scan():
            if not self.scanning or self.busy or self.disposed:
                self.scanning = False
                self.scan_iterators = []
                if not self.disposed:
                    self.scan_status.set_text(_("Skanowanie przerwane."))
                return GLib.SOURCE_REMOVE
            found = []
            try:
                for _count in range(100):
                    path = next(self.scan_iterators[0])
                    if path.is_file() and path.suffix.lower().lstrip(".") in IMAGE_EXTENSIONS:
                        found.append(str(path))
            except StopIteration:
                self.scan_iterators.pop(0)
            except OSError as exc:
                self.scan_iterators.pop(0)
                self.log(str(exc))
            self.append_files(found)
            self.scanning = bool(self.scan_iterators)
            self.scan_status.set_text(
                _("Na liście: {count} zdjęć.").format(count=len(self.file_store))
                + (" " + _("Skanowanie…") if self.scanning else "")
            )
            return GLib.SOURCE_CONTINUE if self.scanning else GLib.SOURCE_REMOVE

        GLib.idle_add(scan)

    def remove_files(self):
        for path in sorted(self.selected_store_paths(), key=lambda p: p.get_indices()[0], reverse=True):
            self.file_store.remove(self.file_store.get_iter(path))
        self.file_keys = {path_key(r[FILE_PATH]) for r in self.file_store}
        self.schedule_save()

    # --- settings ------------------------------------------------------------

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
        protected = self.inputs() + dependency_paths(self.steps, strict=False)
        if self.job:
            protected += [e["target"] for e in self.job.entries]
        if path_key(path) in {path_key(p) for p in protected}:
            raise ValueError("Nie można nadpisać zdjęcia, zależności ani wyniku zadania raportem lub zestawem.")

    def load(self):
        path = choose(self.dialog, _("Zestaw BIMP 3 lub BIMP 2"))
        if path:
            try:
                steps = load_settings(path)
                validate_runtime(steps)
                self.steps = steps
                self.refresh()
            except Exception as exc:
                error(self.dialog, exc)

    def save(self):
        path = choose(self.dialog, _("Zapisz zestaw"), Gtk.FileChooserAction.SAVE, name="zestaw.bimp3.json")
        if path:
            try:
                self.protect_write(path)
                save_settings(path, self.steps)
            except Exception as exc:
                error(self.dialog, exc)

    def save_report(self):
        path = choose(self.dialog, _("Zapisz raport"), Gtk.FileChooserAction.SAVE, name="bimp3-raport.json")
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
            self.inputs(),
            options["output_directory"],
            self.steps,
            options["hierarchy"],
            collision=options["collision"],
        )
        for extension in {p.suffix.lower().lstrip(".") for _source, p in plans}:
            if extension in EXPORTERS:
                procedure(EXPORTERS[extension])
        return plans, options

    def show_plan(self):
        try:
            plans, options = self.build_plan()
            dialog = Gtk.Dialog(
                title=_("Plan zapisu — bez modyfikowania plików"), transient_for=self.dialog, modal=True
            )
            dialog.add_button(_("Zamknij"), Gtk.ResponseType.CLOSE)
            dialog.set_default_size(920, 500)
            store = Gtk.ListStore(str, str, str)
            for source, target in plans:
                status = (
                    _("Zastąp") if target.exists() and options["overwrite"] else _("Pomiń") if target.exists() else _("Nowy plik")
                )
                store.append([str(source), str(target), status])
                for variant in variant_targets(target, self.steps):
                    extra = _("Zastąp") if variant.exists() and options["overwrite"] else (
                        _("Pomiń") if variant.exists() else _("Nowy plik")
                    )
                    store.append(["  ↳ " + _("dodatkowa wersja"), str(variant), extra])
            view = Gtk.TreeView(model=store)
            for i, label in enumerate((_("Źródło"), _("Wynik"), _("Działanie"))):
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
            error(self.dialog, _("Dodaj i zaznacz zdjęcie."))
            return
        self.notebook.set_current_page(1)
        self.preview.request(source, self.steps, {"auto_orient": self.auto_orient.get_active()})

    # --- history ----------------------------------------------------------------

    def show_history(self):
        dialog = Gtk.Dialog(title=_("Historia zadań i dane BIMP"), transient_for=self.dialog, modal=True)
        dialog.add_button(_("Zamknij"), Gtk.ResponseType.CLOSE)
        dialog.set_default_size(900, 520)
        store = Gtk.ListStore(str, str, str, str, str, str)
        view = Gtk.TreeView(model=store)
        view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        for i, label in enumerate((_("Utworzone"), _("Stan"), _("Wyniki"), _("Rozmiar"), _("Folder"))):
            view.append_column(Gtk.TreeViewColumn(label, Gtk.CellRendererText(), text=i))
        usage = Gtk.Label(xalign=0)
        protected = [str(self.job.directory)] if self.job else []

        def reload():
            store.clear()
            for row in list_jobs(self.home):
                counts = row["counts"]
                summary = _("zapisano {ok}, pominięto {skipped}, błędów {errors}, czeka {pending}").format(
                    ok=counts.get("success", 0),
                    skipped=counts.get("skipped", 0),
                    errors=counts.get("error", 0),
                    pending=counts.get("pending", 0) + counts.get("running", 0),
                )
                state = status_label(row["status"]) if not row["error"] else _("uszkodzone")
                store.append(
                    [created_label(row["created"]), state, summary, human_size(row["size"]), row["directory"], row["path"]]
                )
            sizes = data_usage(self.home)
            usage.set_text(
                _("Zadania: {jobs}   Podglądy: {previews}   Profile robocze GIMP: {profiles}").format(
                    jobs=human_size(sizes["jobs"]),
                    previews=human_size(sizes["previews"]),
                    profiles=human_size(sizes["profiles"]),
                )
            )

        def selected():
            model, paths = view.get_selection().get_selected_rows()
            return [(model[p][4], model[p][5]) for p in paths]

        def remove():
            problems = []
            for directory, _job in selected():
                try:
                    delete_job(directory, protected)
                except ValueError as exc:
                    problems.append(translate_message(str(exc)))
            reload()
            if problems:
                error(dialog, "\n".join(problems))

        def prune():
            removed = prune_jobs(self.home, days.get_value_as_int(), protected)
            self.log(_("Usunięto stare zadania: {count}").format(count=removed))
            reload()

        def previews():
            removed = clean_previews(self.home, older_than=0)
            self.log(_("Usunięto pozostałości podglądów: {count}").format(count=removed))
            reload()

        def open_folder():
            for directory, _job in selected()[:1]:
                Gio.AppInfo.launch_default_for_uri(Path(directory).as_uri(), None)

        def resume():
            chosen = selected()
            if chosen and not self.busy:
                dialog.response(Gtk.ResponseType.CLOSE)
                self.resume_job(chosen[0][1])

        days = Gtk.SpinButton.new_with_range(1, 3650, 1)
        days.set_value(30)
        bar = Gtk.Box(spacing=6)
        bar.pack_start(button(_("Usuń zaznaczone"), remove), False, False, 0)
        bar.pack_start(button(_("Wznów zaznaczone"), resume), False, False, 0)
        bar.pack_start(button(_("Otwórz folder"), open_folder), False, False, 0)
        bar.pack_end(button(_("Wyczyść podglądy"), previews), False, False, 0)
        bar.pack_end(button(_("Usuń starsze niż (dni):"), prune), False, False, 0)
        bar.pack_end(days, False, False, 0)
        area = dialog.get_content_area()
        area.set_spacing(6)
        area.pack_start(scroll(view, 360), True, True, 0)
        area.pack_start(usage, False, False, 0)
        area.pack_start(bar, False, False, 0)
        reload()
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # --- jobs ----------------------------------------------------------------------

    def launch_job(self, job):
        if self.busy:
            raise ValueError("Poczekaj na zakończenie bieżącego zadania.")
        self.job = job
        self.worker = Worker(job, profile_pool=self.home / "profiles")
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
        self.active_name = _("Uruchamianie procesu GIMP…")
        self.log_buffer.set_text(
            _("Zadanie działa w osobnym procesie GIMP.") + "\n" + _("Dziennik:") + " " + str(job.path) + "\n"
        )
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
            _("Wybierz job.json zapisanego zadania"),
            initial=str(self.job.path) if self.job else self.last_job,
        )
        if path:
            self.resume_job(path)

    def resume_job(self, path):
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
            error(self.dialog, _("Brak zakończonego zadania."))
            return
        plans = [(Path(e["source"]), Path(e["target"])) for e in self.job.entries if e["status"] == "error"]
        if not plans:
            error(self.dialog, _("Brak błędnych pozycji do ponowienia."))
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
        self.progress.set_text(_("Przerywanie — oczekiwanie na bezpieczne zakończenie operacji…"))

    def tick(self):
        try:
            code = self.worker.poll()
        except Exception as exc:  # Never leave the window locked in the busy state.
            self.log(translate_message(str(exc)))
            code = -1
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
                message = translate_message(entry.get("error", "")) if entry.get("error") else ""
                self.log(f"{status_label(entry['status'])}: {entry['source']} → {entry['target']}\n{message}")
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
        self.progress.set_text(
            _("{status}: zapisano {good}, pominięto {skipped}, błędów {failed}").format(
                status=status_label(finished["status"]), good=good, skipped=skipped, failed=failed
            )
        )
        if finished.get("error"):
            self.log(translate_message(finished["error"]) + "\n" + _("Log:") + " " + str(self.job.directory / "worker.log"))
        if self.run_remove:
            done = {path_key(e["source"]) for e in self.results if e["status"] == "success"}
            remaining = [p for p in self.inputs() if path_key(p) not in done]
            self.file_store.clear()
            self.file_keys.clear()
            self.append_files(remaining)
        self.persist()
        return GLib.SOURCE_REMOVE
