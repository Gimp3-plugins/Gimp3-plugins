# -*- coding: utf-8 -*-
"""Pomocnicze okna dialogowe i widżety GTK dla wtyczki LUT."""

import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GdkPixbuf, GLib  # noqa: E402
from lut_i18n import tr  # noqa: E402


# --- pomocnicze ----------------------------------------------------------------

def _pixbuf(rgba8, w, h):
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(rgba8),
                                           GdkPixbuf.Colorspace.RGB, True, 8,
                                           w, h, w * 4)


def _message(parent, text, secondary="", kind=Gtk.MessageType.INFO):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=kind, buttons=Gtk.ButtonsType.OK,
                            text=text)
    if secondary:
        dlg.format_secondary_text(secondary)
    dlg.run()
    dlg.destroy()


def _ask(parent, text, secondary, buttons, kind=Gtk.MessageType.QUESTION):
    """buttons: [(etykieta, odpowiedź), …]. Zwraca odpowiedź."""
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=kind, buttons=Gtk.ButtonsType.NONE,
                            text=text)
    if secondary:
        dlg.format_secondary_text(secondary)
    for label, resp in buttons:
        dlg.add_button(label, resp)
    resp = dlg.run()
    dlg.destroy()
    return resp


def _ask_text(parent, title, label, value=""):
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.add_buttons(tr("_Anuluj"), Gtk.ResponseType.CANCEL, tr("_OK"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(6)
    box.set_border_width(12)
    box.add(Gtk.Label(label=label, xalign=0))
    entry = Gtk.Entry(text=value, activates_default=True, width_chars=40)
    box.add(entry)
    dlg.show_all()
    resp = dlg.run()
    text = entry.get_text().strip()
    dlg.destroy()
    return text if resp == Gtk.ResponseType.OK else None


LUT_PATTERNS = ("*.cube", "*.CUBE", "*.3dl", "*.3DL", "*.png", "*.PNG")


def _choose(parent, title, action, settings, multiple=False, cube_filter=True,
            patterns=None, filter_name=None, save_name=None):
    """
    Natywne okno wyboru plików/folderu. Zwraca listę ścieżek.
    Domyślny filtr: pliki LUT (.cube, .3dl, Hald .png). Dla zapisu podaj
    save_name (proponowana nazwa pliku).
    """
    if action == Gtk.FileChooserAction.SELECT_FOLDER:
        accept = tr("_Wybierz")
    elif action == Gtk.FileChooserAction.SAVE:
        accept = tr("_Zapisz")
    else:
        accept = tr("_Otwórz")
    chooser = Gtk.FileChooserNative.new(title, parent, action, accept, tr("_Anuluj"))
    chooser.set_select_multiple(multiple)
    if action != Gtk.FileChooserAction.SELECT_FOLDER and (cube_filter or patterns):
        flt = Gtk.FileFilter()
        flt.set_name(filter_name or "LUT (.cube, .3dl, Hald .png)")
        for pattern in patterns or LUT_PATTERNS:
            flt.add_pattern(pattern)
        chooser.add_filter(flt)
    if action == Gtk.FileChooserAction.SAVE:
        chooser.set_do_overwrite_confirmation(True)
        if save_name:
            chooser.set_current_name(save_name)
    last = settings.get("last_dir")
    if last and os.path.isdir(last):
        chooser.set_current_folder(last)
    paths = []
    if chooser.run() == Gtk.ResponseType.ACCEPT:
        paths = [p for p in chooser.get_filenames() if p]
    chooser.destroy()
    if paths:
        first = paths[0]
        settings["last_dir"] = (first if action == Gtk.FileChooserAction.SELECT_FOLDER
                                else os.path.dirname(first))
    return paths


def _combo(items, active):
    combo = Gtk.ComboBoxText()
    for nick, label in items:
        combo.append(nick, label)
    if not combo.set_active_id(active):
        combo.set_active(0)
    return combo
