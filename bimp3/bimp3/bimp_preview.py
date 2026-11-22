"""Asynchronous before/after preview shared by the main window and LUT editor.
SPDX-License-Identifier: GPL-2.0-or-later
"""

import copy
import threading
import uuid
from pathlib import Path
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf
from bimp_jobs import Job, Worker, new_job_directory


class PreviewPane(Gtk.Box):
    def __init__(self, home):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.home = Path(home)
        self.profile_directory = self.home / "previews" / ("profile-" + uuid.uuid4().hex[:10])
        self.worker = None
        self.pending = None
        self.timer = None
        self.disposed = False
        self.active_request = None
        self.source_generation = 0
        self.loaded_source = None
        self.images = [Gtk.Image(), Gtk.Image()]
        row = Gtk.Box(spacing=10, homogeneous=True)
        for title, image in zip(("PRZED", "PO"), self.images):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.pack_start(Gtk.Label(label=title), False, False, 0)
            box.pack_start(image, True, True, 0)
            row.pack_start(box, True, True, 0)
        self.pack_start(row, True, True, 0)
        self.status = Gtk.Label(label="Wybierz zdjęcie i odśwież podgląd.", xalign=0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.connect("destroy", self.close)

    def request(self, source, steps):
        requested = (str(source), copy.deepcopy(steps))
        if self.worker and self.active_request == requested and self.pending is None:
            return
        self.pending = requested
        self.show_source(source)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(400, self.launch)
        self.status.set_text("Przygotowywanie podglądu…")

    def show_source(self, source):
        """Display common image types immediately, while GIMP starts in the background."""
        filename = str(source)
        if filename == self.loaded_source:
            return
        self.loaded_source = filename
        self.source_generation += 1
        generation = self.source_generation
        for image in self.images:
            image.clear()

        def load():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(filename, 460, 350, True)
                pixbuf = pixbuf.apply_embedded_orientation()
            except GLib.Error:
                # Some GIMP formats require their own loader; the worker will
                # provide a full explanation if it also cannot load them.
                return

            def show():
                if not self.disposed and generation == self.source_generation:
                    self.images[0].set_from_pixbuf(pixbuf)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(show)

        threading.Thread(target=load, daemon=True).start()

    def launch(self):
        self.timer = None
        if self.disposed or not self.pending:
            return GLib.SOURCE_REMOVE
        if self.worker:
            if self.worker.poll() is None:
                self.worker.cancel()
                return GLib.SOURCE_REMOVE
            # Let the existing poll callback reap the process and schedule
            # the pending request. Replacing it here races the old callback.
            return GLib.SOURCE_REMOVE
        source, steps = self.pending
        self.pending = None
        try:
            job = Job.create(new_job_directory(self.home / "previews"), [], steps, {}, mode="preview", source=source)
            self.worker = Worker(job, profile_directory=self.profile_directory)
            self.active_request = (source, steps)
            self.worker.start()
            GLib.timeout_add(150, self.poll)
        except Exception as exc:
            self.worker = None
            self.active_request = None
            self.status.set_text(str(exc))
        return GLib.SOURCE_REMOVE

    def poll(self):
        if not self.worker:
            return GLib.SOURCE_REMOVE
        exit_code = self.worker.poll()
        if exit_code is None:
            return GLib.SOURCE_CONTINUE
        job = self.worker.job
        self.worker = None
        self.active_request = None
        if self.disposed:
            return GLib.SOURCE_REMOVE
        if self.pending:
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None
            self.launch()
            return GLib.SOURCE_REMOVE
        if exit_code == 0 and job.finished and job.finished["status"] == "done":
            try:
                for image, filename in zip(self.images, ("before.png", "after.png")):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(job.directory / filename), 460, 350, True)
                    image.set_from_pixbuf(pixbuf)
                self.status.set_text(
                    "Podgląd gotowy. Operacje wykonano na pełnej rozdzielczości; widok jest pomniejszony."
                )
            except Exception as exc:
                self.status.set_text(str(exc))
        else:
            message = (job.finished or {}).get("error", "Podgląd przerwany lub proces nie zakończył renderowania.")
            self.status.set_text(message + f" Log: {job.directory / 'worker.log'}")
        return GLib.SOURCE_REMOVE

    def close(self, *_):
        self.disposed = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.worker:
            self.worker.cancel()
