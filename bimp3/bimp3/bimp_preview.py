"""Asynchronous before/after preview shared by the main window and LUT editor.
SPDX-License-Identifier: GPL-2.0-or-later
"""

import copy
import threading
import time
from pathlib import Path
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf
from bimp_jobs import preview_server, remove_tree
from bimp_i18n import _

STALE_REQUEST_SECONDS = 600


def prune_preview_requests(queue, older_than=STALE_REQUEST_SECONDS):
    """Remove request folders nobody collected (e.g. after a crash); recent ones may still be in use."""
    queue = Path(queue)
    if not queue.is_dir():
        return
    limit = time.time() - older_than
    for folder in queue.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < limit:
                remove_tree(folder)
        except OSError:
            pass


class PreviewPane(Gtk.Box):
    def __init__(self, home):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.home = Path(home)
        self.server = preview_server(self.home)
        prune_preview_requests(self.server.queue)
        self.worker = None  # Job of the request currently rendered by the preview process.
        self.pending = None
        self.timer = None
        self.disposed = False
        self.active_request = None
        self.source_generation = 0
        self.loaded_source = None
        self.images = [Gtk.Image(), Gtk.Image()]
        row = Gtk.Box(spacing=10, homogeneous=True)
        for title, image in zip((_("PRZED"), _("PO")), self.images):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.pack_start(Gtk.Label(label=title), False, False, 0)
            box.pack_start(image, True, True, 0)
            row.pack_start(box, True, True, 0)
        self.pack_start(row, True, True, 0)
        self.status = Gtk.Label(label=_("Wybierz zdjęcie i odśwież podgląd."), xalign=0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.connect("destroy", self.close)

    def request(self, source, steps, options=None):
        requested = (str(source), copy.deepcopy(steps), dict(options or {}))
        if self.worker and self.active_request == requested and self.pending is None:
            return
        self.pending = requested
        self.show_source(source)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(400, self.launch)
        self.status.set_text(_("Przygotowywanie podglądu…"))

    def show_source(self, source):
        """Display common image types immediately, while GIMP renders in the background."""
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
            # Ask the preview process to stop the outdated render; the poll
            # callback starts the pending request once the old one has ended.
            (self.worker.directory / "cancel").touch()
            return GLib.SOURCE_REMOVE
        source, steps, options = self.pending
        self.pending = None
        try:
            first_start = not self.server.running()
            self.worker = self.server.submit(source, steps, options)
            self.active_request = (source, steps, options)
            if first_start:
                self.status.set_text(_("Uruchamianie procesu podglądu GIMP (tylko za pierwszym razem)…"))
            GLib.timeout_add(100, self.poll)
        except Exception as exc:
            self.worker = None
            self.active_request = None
            self.status.set_text(str(exc))
        return GLib.SOURCE_REMOVE

    def poll(self):
        job = self.worker
        if not job:
            return GLib.SOURCE_REMOVE
        job.refresh()
        finished = job.finished
        if finished is None:
            if self.server.running():
                return GLib.SOURCE_CONTINUE
            job.refresh()
            finished = job.finished or {
                "status": "error",
                "error": _("Proces podglądu GIMP zakończył się nieoczekiwanie."),
            }
        self.worker = None
        self.active_request = None
        try:
            if self.disposed:
                return GLib.SOURCE_REMOVE
            if self.pending:
                if self.timer:
                    GLib.source_remove(self.timer)
                    self.timer = None
                self.launch()
                return GLib.SOURCE_REMOVE
            if finished.get("status") == "done":
                try:
                    for image, filename in zip(self.images, ("before.png", "after.png")):
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                            str(job.directory / filename), 460, 350, True
                        )
                        image.set_from_pixbuf(pixbuf)
                    self.status.set_text(
                        _("Podgląd gotowy. Operacje wykonano na pełnej rozdzielczości; widok jest pomniejszony.")
                    )
                except Exception as exc:
                    self.status.set_text(str(exc))
            else:
                message = finished.get("error") or _("Podgląd przerwany lub proces nie zakończył renderowania.")
                self.status.set_text(message + " " + _("Log:") + " " + str(self.server.queue.parent / "preview-server.log"))
        finally:
            # Pixbufs are in memory now; the request folder is no longer needed.
            remove_tree(job.directory)
        return GLib.SOURCE_REMOVE

    def close(self, *_args):
        self.disposed = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.worker:
            (self.worker.directory / "cancel").touch()
