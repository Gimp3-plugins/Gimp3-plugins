#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GIMP 3 plug-in: Profile Backup / Restore (thin GIMP + GTK 3 layer).

All real work is done in pb_core.py (no GIMP dependency); texts are in
pb_i18n.py. Long operations run in a worker thread; the GTK main loop keeps
the dialog responsive and offers Cancel.
"""

import os
import sys
import threading
import traceback
from pathlib import Path

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, Gtk, GLib, GObject, Pango  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pb_core as core  # noqa: E402
from pb_i18n import tr, detect_language, reason_text, LANGUAGES, LANGUAGE_NAMES  # noqa: E402

PROC_BACKUP = "plug-in-profile-backup"
PROC_RESTORE = "plug-in-profile-restore"
RESPONSE_RELANG = 1001
MAX_SKIPPED_LISTED = 200


# --------------------------------------------------------------------------
# language & settings
# --------------------------------------------------------------------------
def _gimp_dir():
    try:
        return Gimp.directory()
    except Exception:
        return None


def current_language(settings=None):
    settings = settings if settings is not None else core.load_settings()
    lang = settings.get("language")
    if lang in LANGUAGES:
        return lang
    gd = _gimp_dir()
    return detect_language(Path(gd) / "gimprc" if gd else None)


def gimp_version():
    try:
        return Gimp.version()
    except Exception:
        return None


# --------------------------------------------------------------------------
# small GTK helpers
# --------------------------------------------------------------------------
def new_dialog(title, lang, buttons):
    use_header_bar = Gtk.Settings.get_default().get_property("gtk-dialogs-use-header")
    dlg = GimpUi.Dialog(use_header_bar=use_header_bar)
    dlg.set_title(title)
    dlg.set_role("profile-backup")
    for label_key, response in buttons:
        dlg.add_button(tr(label_key, lang), response)
    GimpUi.window_set_transient(dlg)
    return dlg


def message(parent, lang, kind, title, text, details=None):
    # Own button instead of Gtk.ButtonsType.CLOSE: GTK would label it in the
    # system language, not in the language chosen in the plug-in.
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    dlg.add_button(tr("btn_close", lang), Gtk.ResponseType.CLOSE)
    dlg.format_secondary_text(text)
    if details:
        area = dlg.get_message_area()
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(180)
        sw.set_min_content_width(560)
        tv = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(details)
        sw.add(tv)
        area.pack_start(sw, True, True, 0)
        sw.show_all()
    if parent is None:
        GimpUi.window_set_transient(dlg)
    resp = dlg.run()
    dlg.destroy()
    return resp


def ask(parent, lang, title, text, yes_key="btn_yes", no_key="btn_no"):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    dlg.format_secondary_text(text)
    dlg.add_button(tr(no_key, lang), Gtk.ResponseType.NO)
    dlg.add_button(tr(yes_key, lang), Gtk.ResponseType.YES)
    dlg.set_default_response(Gtk.ResponseType.NO)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.YES


def choose_folder(parent, title, lang, start=None):
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent,
                                action=Gtk.FileChooserAction.SELECT_FOLDER)
    dlg.add_button(tr("btn_cancel", lang), Gtk.ResponseType.CANCEL)
    dlg.add_button("_OK", Gtk.ResponseType.OK)
    if start and Path(start).is_dir():
        dlg.set_current_folder(str(start))
    path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
    dlg.destroy()
    return path


def choose_archive(parent, lang, start=None):
    dlg = Gtk.FileChooserDialog(title=tr("dlg_choose_archive", lang), transient_for=parent,
                                action=Gtk.FileChooserAction.OPEN)
    dlg.add_button(tr("btn_cancel", lang), Gtk.ResponseType.CANCEL)
    dlg.add_button("_OK", Gtk.ResponseType.OK)
    flt = Gtk.FileFilter()
    flt.set_name(tr("filter_backups", lang))
    for pat in ("*.zip", "*.zip.001", "*.manifest.json"):
        flt.add_pattern(pat)
    dlg.add_filter(flt)
    if start and Path(start).is_dir():
        dlg.set_current_folder(str(start))
    path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
    dlg.destroy()
    return path


def grid_row(grid, row, label, widget, extra=None):
    lab = Gtk.Label(label=label, xalign=0)
    grid.attach(lab, 0, row, 1, 1)
    widget.set_hexpand(True)
    grid.attach(widget, 1, row, 1 if extra else 2, 1)
    if extra:
        grid.attach(extra, 2, row, 1, 1)
    return lab


def format_error(e, lang):
    if isinstance(e, core.PBError):
        return tr(e.key, lang, **e.params)
    return tr("err_unexpected", lang, error=f"{type(e).__name__}: {e}")


def skipped_text(skipped, lang):
    if not skipped:
        return None
    lines = [tr("report_skipped_header", lang, count=len(skipped))]
    for rel, why in skipped[:MAX_SKIPPED_LISTED]:
        lines.append(f"  {rel} — {reason_text(why, lang)}")
    if len(skipped) > MAX_SKIPPED_LISTED:
        lines.append(f"  … (+{len(skipped) - MAX_SKIPPED_LISTED})")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# progress dialog running a worker thread
# --------------------------------------------------------------------------
def run_with_progress(parent, lang, title, func):
    """Run func(progress, cancel) in a thread; returns (result, exception)."""
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.set_default_size(520, -1)
    cancel_btn = dlg.add_button(tr("btn_cancel", lang), Gtk.ResponseType.CANCEL)
    box = dlg.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    stage_lbl = Gtk.Label(xalign=0)
    detail_lbl = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
    bar = Gtk.ProgressBar(show_text=True)
    for w in (stage_lbl, bar, detail_lbl):
        box.pack_start(w, False, False, 0)

    cancel = threading.Event()
    state = {"fraction": None, "stage": "stage_scanning", "detail": "", "done": False,
             "result": None, "error": None}

    def progress(fraction, stage, detail=""):
        state["fraction"], state["stage"], state["detail"] = fraction, stage, detail

    def worker():
        try:
            state["result"] = func(progress, cancel)
        except BaseException as e:          # reported in the UI thread
            state["error"] = e
            core.get_logger().error("Worker failed: %s\n%s", e, traceback.format_exc())
        finally:
            state["done"] = True

    def tick():
        if state["done"]:
            dlg.response(Gtk.ResponseType.OK)
            return False
        stage = "stage_cancelling" if cancel.is_set() else state["stage"]
        stage_lbl.set_text(tr(stage, lang))
        detail_lbl.set_text(state["detail"] or "")
        if state["fraction"] is None:
            bar.pulse()
            bar.set_text("")
        else:
            bar.set_fraction(max(0.0, min(1.0, state["fraction"])))
            bar.set_text(f"{state['fraction'] * 100:.0f}%")
        return True

    def request_cancel(*_):
        if not state["done"]:
            cancel.set()
            cancel_btn.set_sensitive(False)
        return True                      # keep the window until the worker ends

    dlg.connect("response", lambda d, resp: resp != Gtk.ResponseType.OK and request_cancel())
    dlg.connect("delete-event", request_cancel)
    dlg.show_all()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    GLib.timeout_add(100, tick)
    # dlg.run() returns on any response (Cancel included); keep running the
    # nested loop until the worker has finished and tick() sent OK.
    while not state["done"]:
        dlg.run()
    t.join()
    dlg.destroy()
    return state["result"], state["error"]


# --------------------------------------------------------------------------
# profile chooser widget (shared by both dialogs)
# --------------------------------------------------------------------------
class ProfileChooser:
    def __init__(self, lang, parent_getter, initial=None, on_change=None):
        self.lang = lang
        self.parent_getter = parent_getter
        self.on_change = on_change
        self.candidates = core.detect_profiles(gimp_dir=_gimp_dir())
        self.combo = Gtk.ComboBoxText()
        self.paths = []
        for c in self.candidates:
            self._append(str(c.path), f"{c.path}  [{c.source}]")
        if initial and initial not in self.paths:
            self._append(initial, initial)
        self.other_index = len(self.paths)
        self.combo.append_text(tr("lbl_profile_other", lang))
        if self.paths:
            self.combo.set_active(self.paths.index(initial) if initial in self.paths else 0)
        self.combo.connect("changed", self._changed)

    def _append(self, path, text):
        self.paths.append(path)
        self.combo.insert_text(len(self.paths) - 1, text)

    def _changed(self, combo):
        i = combo.get_active()
        if i == self.other_index:
            path = choose_folder(self.parent_getter(), tr("dlg_choose_profile", self.lang),
                                 self.lang, self.paths[0] if self.paths else None)
            if path:
                if path not in self.paths:
                    self._append(path, path)
                    self.other_index += 1
                combo.set_active(self.paths.index(path))
            else:
                combo.set_active(0 if self.paths else -1)
            return
        if self.on_change:
            self.on_change(self.get())

    def get(self):
        i = self.combo.get_active()
        if 0 <= i < len(self.paths):
            return self.paths[i]
        return None


def language_combo(lang):
    combo = Gtk.ComboBoxText()
    for code in LANGUAGES:
        combo.append(code, LANGUAGE_NAMES[code])
    combo.set_active_id(lang)
    return combo


def size_label_async(label, path, lang):
    """Compute the profile size in a thread, update the label when ready."""
    label.set_text(tr("lbl_profile_size_calc", lang))
    if not path:
        label.set_text(tr("lbl_no_profile", lang))
        return

    def work():
        try:
            n, size = core.profile_size(Path(path))
            text = tr("lbl_profile_size", lang, files=n, size=core.human_size(size))
        except Exception as e:
            text = format_error(e, lang)
        GLib.idle_add(label.set_text, text)

    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------
# BACKUP
# --------------------------------------------------------------------------
def backup_dialog(settings):
    while True:
        lang = current_language(settings)
        dlg = new_dialog(tr("title_backup", lang), lang,
                         [("btn_cancel", Gtk.ResponseType.CANCEL),
                          ("btn_backup", Gtk.ResponseType.OK)])
        dlg.set_default_size(640, -1)
        grid = Gtk.Grid(row_spacing=8, column_spacing=8, border_width=12)
        dlg.get_content_area().pack_start(grid, True, True, 0)
        row = 0

        lang_combo = language_combo(lang)
        grid_row(grid, row, tr("lbl_language", lang), lang_combo)
        lang_combo.connect("changed", lambda c: dlg.response(RESPONSE_RELANG))
        row += 1

        size_lbl = Gtk.Label(xalign=0)
        chooser = ProfileChooser(lang, lambda: dlg, settings.get("last_profile"),
                                 on_change=lambda p: size_label_async(size_lbl, p, lang))
        grid_row(grid, row, tr("lbl_profile", lang), chooser.combo)
        row += 1
        grid.attach(size_lbl, 1, row, 2, 1)
        row += 1
        for legacy in core.detect_legacy_profiles():
            grid.attach(Gtk.Label(label=tr("info_legacy_profile", lang, path=str(legacy)),
                                  xalign=0, wrap=True), 1, row, 2, 1)
            row += 1

        dest_entry = Gtk.Entry()
        dest_entry.set_text(settings.get("last_dest") or str(core.default_backup_dir()))
        browse = Gtk.Button(label=tr("btn_browse", lang))
        grid_row(grid, row, tr("lbl_dest", lang), dest_entry, browse)
        row += 1
        free_lbl = Gtk.Label(xalign=0)
        grid.attach(free_lbl, 1, row, 2, 1)
        row += 1

        def update_free(*_):
            try:
                free_lbl.set_text(tr("lbl_free_space", lang, free=core.human_size(
                    core.free_space(Path(dest_entry.get_text().strip() or "."))) ))
            except OSError:
                free_lbl.set_text("")

        def on_browse(_b):
            p = choose_folder(dlg, tr("dlg_choose_dest", lang), lang, dest_entry.get_text())
            if p:
                dest_entry.set_text(p)

        browse.connect("clicked", on_browse)
        dest_entry.connect("changed", update_free)
        update_free()

        thr = Gtk.SpinButton.new_with_range(1, 1024 * 1024, 50)
        thr.set_value(settings.get("split_threshold_mb", core.DEFAULT_SPLIT_THRESHOLD // core.MB))
        grid_row(grid, row, tr("lbl_threshold", lang), thr)
        row += 1
        part = Gtk.SpinButton.new_with_range(1, 1024 * 1024, 50)
        part.set_value(settings.get("part_size_mb", core.DEFAULT_PART_SIZE // core.MB))
        grid_row(grid, row, tr("lbl_part_size", lang), part)
        row += 1

        seven = core.find_7z()
        use7 = Gtk.CheckButton(label=tr("lbl_use_7z", lang, path=seven) if seven
                               else tr("lbl_no_7z", lang))
        use7.set_sensitive(bool(seven))
        use7.set_active(bool(seven) and settings.get("use_7z", False))
        grid.attach(use7, 0, row, 3, 1)
        row += 1

        dlg.show_all()
        size_label_async(size_lbl, chooser.get(), lang)

        while True:
            resp = dlg.run()
            if resp == RESPONSE_RELANG:
                settings["language"] = lang_combo.get_active_id()
                core.save_settings(settings)
                dlg.destroy()
                break                       # rebuild in the new language
            if resp != Gtk.ResponseType.OK:
                dlg.destroy()
                return Gimp.PDBStatusType.CANCEL
            profile = chooser.get()
            dest = dest_entry.get_text().strip()
            if not profile:
                message(dlg, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                        tr("err_no_profile_found", lang))
                continue
            if not dest:
                message(dlg, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                        tr("err_no_dest", lang))
                continue
            if core.is_relative_to(Path(dest), Path(profile)):
                message(dlg, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                        tr("err_dest_inside_profile", lang, dest=dest, profile=profile))
                continue
            opts = dict(split_threshold=int(thr.get_value()) * core.MB,
                        part_size=int(part.get_value()) * core.MB,
                        use_7z=use7.get_active())
            settings.update(last_profile=profile, last_dest=dest,
                            split_threshold_mb=int(thr.get_value()),
                            part_size_mb=int(part.get_value()), use_7z=use7.get_active())
            core.save_settings(settings)
            status = do_backup(dlg, lang, Path(profile), Path(dest), opts)
            if status is None:              # space warning declined -> back to dialog
                continue
            dlg.destroy()
            return status


def do_backup(parent, lang, profile, dest, opts):
    try:
        _, size = core.profile_size(profile)
    except core.PBError as e:
        message(parent, lang, Gtk.MessageType.ERROR, tr("title_error", lang), format_error(e, lang))
        return None
    ok, free, needed = core.check_free_space(dest, size)
    ignore_space = False
    if not ok:
        if not ask(parent, lang, tr("title_confirm", lang),
                   tr("ask_low_space", lang, free=core.human_size(free),
                      needed=core.human_size(needed)), yes_key="btn_continue"):
            return None
        ignore_space = True

    def job(progress, cancel):
        return core.create_backup(profile, dest, gimp_version=gimp_version(),
                                  ignore_space=ignore_space, progress=progress,
                                  cancel=cancel, **opts)

    rep, err = run_with_progress(parent, lang, tr("title_backup", lang), job)
    if isinstance(err, core.Cancelled):
        message(parent, lang, Gtk.MessageType.INFO, tr("title_report", lang),
                tr("report_cancelled", lang))
        return Gimp.PDBStatusType.CANCEL
    if err is not None:
        message(parent, lang, Gtk.MessageType.ERROR, tr("title_error", lang), format_error(err, lang))
        return Gimp.PDBStatusType.EXECUTION_ERROR
    text = tr("report_backup", lang, files=rep.file_count, size=core.human_size(rep.source_size),
              archive_size=core.human_size(rep.archive_size),
              where="\n  ".join(str(p) for p in rep.outputs))
    text += "\n" + tr("report_excluded", lang, count=len(rep.excluded))
    if rep.log_path:
        text += "\n" + tr("report_log", lang, path=str(rep.log_path))
    message(parent, lang, Gtk.MessageType.WARNING if rep.skipped else Gtk.MessageType.INFO,
            tr("title_report", lang), text, skipped_text(rep.skipped, lang))
    return Gimp.PDBStatusType.SUCCESS


# --------------------------------------------------------------------------
# RESTORE
# --------------------------------------------------------------------------
def show_previous_result(lang):
    """Report the outcome of a restore applied after the last GIMP exit."""
    for c in core.detect_profiles(gimp_dir=_gimp_dir()):
        res = core.pop_restore_result(c.path)
        if not res:
            continue
        if res.get("ok"):
            message(None, lang, Gtk.MessageType.INFO, tr("title_report", lang),
                    tr("report_previous_ok", lang, finished=res.get("finished"),
                       profile=res.get("profile"), safety=res.get("safety") or "-"))
        else:
            err = res.get("error") or ""
            if res.get("error_key"):
                err = tr(res["error_key"], lang, **(res.get("error_params") or {}))
            message(None, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                    tr("report_previous_failed", lang, finished=res.get("finished"), error=err))


def restore_dialog(settings):
    while True:
        lang = current_language(settings)
        show_previous_result(lang)
        dlg = new_dialog(tr("title_restore", lang), lang,
                         [("btn_cancel", Gtk.ResponseType.CANCEL),
                          ("btn_restore", Gtk.ResponseType.OK)])
        dlg.set_default_size(640, -1)
        grid = Gtk.Grid(row_spacing=8, column_spacing=8, border_width=12)
        dlg.get_content_area().pack_start(grid, True, True, 0)
        row = 0

        lang_combo = language_combo(lang)
        grid_row(grid, row, tr("lbl_language", lang), lang_combo)
        lang_combo.connect("changed", lambda c: dlg.response(RESPONSE_RELANG))
        row += 1

        arch_entry = Gtk.Entry()
        browse = Gtk.Button(label=tr("btn_browse", lang))
        grid.attach(Gtk.Label(label=tr("lbl_archive", lang), xalign=0), 0, row, 3, 1)
        row += 1
        # entry + button in their own box so the button keeps its natural width
        arch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        arch_box.pack_start(arch_entry, True, True, 0)
        arch_box.pack_start(browse, False, False, 0)
        grid.attach(arch_box, 0, row, 3, 1)
        row += 1
        browse.connect("clicked", lambda b: (lambda p: p and arch_entry.set_text(p))(
            choose_archive(dlg, lang, settings.get("last_dest") or str(core.default_backup_dir()))))

        # Default target = the profile GIMP is running with (first candidate),
        # NOT the last profile backed up: that one may be a different profile.
        chooser = ProfileChooser(lang, lambda: dlg, settings.get("last_restore_profile"))
        grid_row(grid, row, tr("lbl_target_profile", lang), chooser.combo)
        row += 1

        grid.attach(Gtk.Label(label=tr("lbl_mode", lang), xalign=0), 0, row, 1, 1)
        rb_replace = Gtk.RadioButton.new_with_label_from_widget(None, tr("mode_replace", lang))
        rb_merge = Gtk.RadioButton.new_with_label_from_widget(rb_replace, tr("mode_merge", lang))
        (rb_merge if settings.get("restore_mode") == "merge" else rb_replace).set_active(True)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vb.pack_start(rb_replace, False, False, 0)
        vb.pack_start(rb_merge, False, False, 0)
        grid.attach(vb, 1, row, 2, 1)
        row += 1

        auto = Gtk.CheckButton(label=tr("lbl_auto_apply", lang))
        auto.set_active(settings.get("auto_apply", True))
        grid.attach(auto, 0, row, 3, 1)
        row += 1
        how = Gtk.Label(label=tr("lbl_restore_how", lang), xalign=0, wrap=True)
        how.set_max_width_chars(80)
        grid.attach(how, 0, row, 3, 1)
        row += 1

        pending_btn = None
        prof0 = chooser.get()
        pend = core.read_pending(Path(prof0)) if prof0 else None
        if pend:
            grid.attach(Gtk.Label(label=tr("ask_pending_exists", lang, source=pend.get("source")),
                                  xalign=0, wrap=True), 0, row, 3, 1)
            row += 1
            pending_btn = Gtk.Button(label=tr("btn_cancel_pending", lang))
            pending_btn.connect("clicked", lambda b: (core.cancel_pending(Path(prof0)),
                                                      b.set_sensitive(False)))
            grid.attach(pending_btn, 0, row, 3, 1)
            row += 1

        dlg.show_all()
        while True:
            resp = dlg.run()
            if resp == RESPONSE_RELANG:
                settings["language"] = lang_combo.get_active_id()
                core.save_settings(settings)
                dlg.destroy()
                break
            if resp != Gtk.ResponseType.OK:
                dlg.destroy()
                return Gimp.PDBStatusType.CANCEL
            archive = arch_entry.get_text().strip()
            profile = chooser.get()
            if not archive:
                message(dlg, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                        tr("err_no_archive", lang))
                continue
            if not profile:
                message(dlg, lang, Gtk.MessageType.ERROR, tr("title_error", lang),
                        tr("err_no_profile_found", lang))
                continue
            mode = "merge" if rb_merge.get_active() else "replace"
            settings.update(restore_mode=mode, auto_apply=auto.get_active(),
                            last_restore_profile=profile)
            core.save_settings(settings)
            status = do_restore(dlg, lang, Path(archive), Path(profile), mode,
                                auto.get_active())
            if status is None:
                continue
            dlg.destroy()
            return status


def do_restore(parent, lang, archive, profile, mode, auto_apply):
    # 1. verify (parts, checksums, manifest)
    src, err = run_with_progress(parent, lang, tr("title_restore", lang),
                                 lambda progress, cancel: core.open_backup(
                                     archive, progress=progress, cancel=cancel))
    if isinstance(err, core.Cancelled):
        return None
    if err is not None:
        message(parent, lang, Gtk.MessageType.ERROR, tr("title_error", lang), format_error(err, lang))
        return None
    s = src.summary
    summary = tr("summary_backup", lang, created=s["created"], gimp=s["gimp_version"],
                 series=s["profile_series"], files=s["file_count"],
                 size=core.human_size(s["total_size"] or 0), parts=s["parts"] or 1,
                 source=s["source_path"])
    # 2. confirm
    if not ask(parent, lang, tr("title_confirm", lang),
               tr("ask_confirm_restore", lang, summary=summary, profile=str(profile),
                  mode=tr("mode_" + mode, lang), how=tr("lbl_restore_how", lang)),
               yes_key="btn_restore", no_key="btn_cancel"):
        return None
    # 3. extract + verify next to the profile (live profile untouched)
    rep, err = run_with_progress(parent, lang, tr("title_restore", lang),
                                 lambda progress, cancel: core.prepare_pending_restore(
                                     archive, profile, mode=mode, progress=progress,
                                     cancel=cancel, lang=lang))
    if isinstance(err, core.Cancelled):
        message(parent, lang, Gtk.MessageType.INFO, tr("title_report", lang),
                tr("report_cancelled", lang))
        return Gimp.PDBStatusType.CANCEL
    if err is not None:
        message(parent, lang, Gtk.MessageType.ERROR, tr("title_error", lang), format_error(err, lang))
        return Gimp.PDBStatusType.EXECUTION_ERROR
    # 4. schedule the swap for after GIMP exits
    manual = f'"{sys.executable}" "{Path(core.__file__).resolve()}" apply-pending "{rep.pending_file}"'
    auto_text = tr("report_pending_manual", lang, command=manual)
    if auto_apply:
        try:
            core.spawn_apply_helper(rep.pending_file, os.getppid())
            core.get_logger().info("Apply helper started, waiting for GIMP pid %s",
                                   os.getppid())
            auto_text = tr("report_pending_auto", lang)
        except Exception as e:
            auto_text = tr("err_helper_failed", lang, error=str(e)) + "\n" + auto_text
    text = tr("report_pending", lang, files=rep.restored, auto=auto_text,
              safety=str(rep.safety_copy), staging=str(rep.staging))
    message(parent, lang, Gtk.MessageType.WARNING if rep.skipped else Gtk.MessageType.INFO,
            tr("title_report", lang), text, skipped_text(rep.skipped, lang))
    return Gimp.PDBStatusType.SUCCESS


# --------------------------------------------------------------------------
# procedure entry points
# --------------------------------------------------------------------------
def _fail(procedure, status, text):
    return procedure.new_return_values(status, GLib.Error(text))


def run_backup(procedure, config, data):
    settings = core.load_settings()
    lang = current_language(settings)
    run_mode = config.get_property("run-mode")
    try:
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            profile = config.get_property("profile") or _gimp_dir()
            dest = config.get_property("destination") or str(core.default_backup_dir())
            rep = core.create_backup(Path(profile), Path(dest), gimp_version=gimp_version())
            core.get_logger().info("Non-interactive backup: %s", rep.archive)
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        GimpUi.init("profile-backup")
        status = backup_dialog(settings)
    except Exception as e:
        core.get_logger().error("%s\n%s", e, traceback.format_exc())
        return _fail(procedure, Gimp.PDBStatusType.EXECUTION_ERROR, format_error(e, lang))
    return procedure.new_return_values(status, GLib.Error())


def run_restore(procedure, config, data):
    settings = core.load_settings()
    lang = current_language(settings)
    run_mode = config.get_property("run-mode")
    try:
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            # Prepares the restore only; it is applied after GIMP exits
            # (or by `pb_core.py apply-pending`).
            archive = config.get_property("archive")
            if not archive:
                return _fail(procedure, Gimp.PDBStatusType.CALLING_ERROR,
                             tr("err_no_archive", lang))
            profile = config.get_property("profile") or _gimp_dir()
            mode = config.get_property("mode") or "replace"
            rep = core.prepare_pending_restore(Path(archive), Path(profile), mode=mode,
                                               lang=lang)
            if config.get_property("apply-after-exit"):
                core.spawn_apply_helper(rep.pending_file, os.getppid())
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        GimpUi.init("profile-backup")
        status = restore_dialog(settings)
    except Exception as e:
        core.get_logger().error("%s\n%s", e, traceback.format_exc())
        return _fail(procedure, Gimp.PDBStatusType.EXECUTION_ERROR, format_error(e, lang))
    return procedure.new_return_values(status, GLib.Error())


class ProfileBackup(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC_BACKUP, PROC_RESTORE]

    def do_set_i18n(self, name):
        # (use_gettext, domain, catalog_dir) - like the bundled plug-ins, but
        # gettext is off: translations are handled by pb_i18n.
        return False, None, None

    def do_create_procedure(self, name):
        lang = current_language()
        if name == PROC_BACKUP:
            proc = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_backup, None)
            proc.set_menu_label(tr("menu_backup", lang))
            proc.set_documentation(tr("doc_backup", lang), tr("doc_backup", lang), name)
        elif name == PROC_RESTORE:
            proc = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_restore, None)
            proc.set_menu_label(tr("menu_restore", lang))
            proc.set_documentation(tr("doc_restore", lang), tr("doc_restore", lang), name)
        else:
            return None
        proc.set_attribution("GIMP Profile Backup contributors", "MIT License", "2026")
        proc.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.NO_IMAGE |
                                  Gimp.ProcedureSensitivityMask.DRAWABLE |
                                  Gimp.ProcedureSensitivityMask.DRAWABLES |
                                  Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        proc.add_menu_path("<Image>/File/" + tr("menu_submenu", lang))
        proc.add_enum_argument("run-mode", "Run mode", "The run mode", Gimp.RunMode,
                               Gimp.RunMode.INTERACTIVE, GObject.ParamFlags.READWRITE)
        proc.add_string_argument("profile", "Profile folder",
                                 "Profile folder (empty = GIMP's own)", "",
                                 GObject.ParamFlags.READWRITE)
        if name == PROC_BACKUP:
            proc.add_string_argument("destination", "Destination folder",
                                     "Destination folder (empty = default)", "",
                                     GObject.ParamFlags.READWRITE)
        else:
            proc.add_string_argument("archive", "Backup file",
                                     ".zip, .zip.001 or .manifest.json", "",
                                     GObject.ParamFlags.READWRITE)
            proc.add_string_argument("mode", "Mode", "replace or merge", "replace",
                                     GObject.ParamFlags.READWRITE)
            proc.add_boolean_argument("apply-after-exit", "Apply after exit",
                                      "Swap the profile automatically after GIMP exits",
                                      False, GObject.ParamFlags.READWRITE)
        return proc


Gimp.main(ProfileBackup.__gtype__, sys.argv)
