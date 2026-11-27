"""GTK 3 interface for BIMP. SPDX-License-Identifier: GPL-2.0-or-later."""

import copy
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GimpUi", "3.0")
from gi.repository import Gtk, Gdk, GimpUi, GObject, Gimp

from bimp_model import SCHEMAS, FORMATS
from bimp_engine import (
    AUTOMATIC,
    EXPORTERS,
    SAFE_USER_PROCEDURES,
    config_for,
    procedure,
    validate_runtime,
    watermark_font,
)
from bimp_i18n import _, translate_message


def error(parent, text):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=translate_message(str(text)),
    )
    dialog.run()
    dialog.destroy()


def button(label, callback, tooltip=None):
    widget = Gtk.Button(label=label)
    widget.connect("clicked", lambda _button: callback())
    if tooltip:
        widget.set_tooltip_text(tooltip)
    return widget


def scroll(child, height=260):
    widget = Gtk.ScrolledWindow()
    widget.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    widget.set_min_content_height(height)
    widget.add(child)
    return widget


def choose(parent, title, action=Gtk.FileChooserAction.OPEN, multiple=False, name=None, initial=None, patterns=None):
    dialog = Gtk.FileChooserDialog(title=title, transient_for=parent, action=action)
    dialog.add_buttons(_("Anuluj"), Gtk.ResponseType.CANCEL, _("Wybierz"), Gtk.ResponseType.OK)
    dialog.set_select_multiple(multiple)
    if patterns:
        file_filter = Gtk.FileFilter()
        file_filter.set_name("LUT Cube (*.cube)")
        for pattern in patterns:
            file_filter.add_pattern(pattern)
        dialog.add_filter(file_filter)
    if initial and Path(initial).exists():
        dialog.set_filename(str(initial))
    if action == Gtk.FileChooserAction.SAVE:
        dialog.set_do_overwrite_confirmation(True)
        if name:
            dialog.set_current_name(name)
    result = dialog.get_filenames() if dialog.run() == Gtk.ResponseType.OK else []
    dialog.destroy()
    return result if multiple else result[0] if result else None


class Form:
    """Small typed form; getters return JSON-compatible values."""

    def __init__(self):
        self.grid = Gtk.Grid(column_spacing=16, row_spacing=10, margin=12)
        self.getters = {}
        self.widgets = {}

    def add(self, key, label, value, limits=None, tooltip=None, choices=None):
        row = len(self.getters)
        caption = Gtk.Label(label=_(label), xalign=0)
        caption.set_max_width_chars(42)
        caption.set_line_wrap(True)
        if isinstance(limits, list) or choices:
            widget = Gtk.ComboBoxText()
            items = choices or [(str(i), _(text)) for i, text in enumerate(limits)]
            for nick, text in items:
                widget.append(str(nick), text)
            widget.set_active_id(str(value))
            getter = (lambda: widget.get_active_id()) if choices else (lambda: int(widget.get_active_id()))
        elif isinstance(value, bool):
            widget = Gtk.CheckButton()
            widget.set_active(value)
            getter = widget.get_active
        elif key == "strength":
            widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            widget.set_value(value)
            widget.set_digits(0)
            getter = widget.get_value
        elif isinstance(value, (int, float)):
            low, high = limits or (-1000000, 1000000)
            widget = Gtk.SpinButton.new_with_range(low, high, 1 if isinstance(value, int) else 0.01)
            widget.set_digits(0 if isinstance(value, int) else 3)
            widget.set_value(value)
            getter = widget.get_value_as_int if isinstance(value, int) else widget.get_value
        elif key in ("color", "padding_color"):
            rgba = Gdk.RGBA()
            if not rgba.parse(value):
                raise ValueError(f"Nieprawidłowy kolor: {value}")
            widget = Gtk.ColorButton.new_with_rgba(rgba)

            def get_color():
                return widget.get_rgba().to_string()

            getter = get_color
        elif key == "font":
            from gi.repository import Pango

            description = Pango.FontDescription.from_string(value)
            try:
                selected_font = watermark_font(value)
            except ValueError:
                selected_font = Gimp.context_get_font()
            widget = Gtk.Box(spacing=6)
            chooser = GimpUi.FontChooser.new(_("Wybierz czcionkę GIMP"), None, selected_font)
            size = Gtk.SpinButton.new_with_range(1, 2048, 1)
            size.set_digits(1)
            size.set_value(description.get_size() / Pango.SCALE or 16)
            unit = Gtk.ComboBoxText()
            unit.append("px", "px")
            unit.append("pt", "pt")
            unit.set_active_id("px" if description.get_size_is_absolute() else "pt")
            widget.pack_start(chooser, True, True, 0)
            widget.pack_start(size, False, False, 0)
            widget.pack_start(unit, False, False, 0)

            def get_font():
                font = chooser.get_resource()
                if font is None:
                    raise ValueError("Wybierz czcionkę dostępną w GIMP.")
                suffix = "px" if unit.get_active_id() == "px" else ""
                return f"{font.get_name()} {size.get_value():g}{suffix}"

            getter = get_font
        elif key in ("image_file", "curve_file", "file"):
            widget = Gtk.Box(spacing=6)
            entry = Gtk.Entry(text=value, hexpand=True)

            def select():
                filename = choose(
                    self.grid.get_toplevel(), _(label), patterns=["*.cube", "*.CUBE"] if key == "file" else None
                )
                if filename:
                    entry.set_text(filename)

            widget.pack_start(entry, True, True, 0)
            widget.pack_start(button("…", select), False, False, 0)
            getter = entry.get_text
        else:
            widget = Gtk.Entry(text=value or "")
            getter = widget.get_text
        if tooltip:
            widget.set_tooltip_text(tooltip)
        widget.set_hexpand(True)
        self.grid.attach(caption, 0, row, 1, 1)
        self.grid.attach(widget, 1, row, 1, 1)
        self.getters[key] = getter
        self.widgets[key] = widget

    def values(self):
        return {key: get() for key, get in self.getters.items()}


def procedure_form(proc, arguments):
    form = Form()
    arguments = dict(arguments)
    if proc.get_name() == "file-tiff-export":
        arguments.setdefault("include-thumbnail", False)
    cfg = config_for(proc, arguments=arguments)
    for spec in cfg.list_properties():
        if spec.name in AUTOMATIC or not spec.flags & GObject.ParamFlags.WRITABLE:
            continue
        value = cfg.get_property(spec.name)
        choices, limits = None, None
        type_name = spec.value_type.name
        if GObject.type_name(spec.__gtype__) == "GimpParamChoice":
            choice = Gimp.param_spec_choice_get_choice(spec)
            choices = [(nick, choice.get_label(nick)) for nick in choice.list_nicks()]
        elif GObject.type_is_a(spec.value_type, GObject.TYPE_ENUM):
            choices = [(v.value_nick, v.value_nick) for v in spec.value_type.pytype.__enum_values__.values()]
            value = value.value_nick
        elif type_name in ("gint", "guint", "gint64", "guint64", "gdouble", "gfloat"):
            limits = (max(spec.minimum, -1e12), min(spec.maximum, 1e12))
        elif type_name == "GeglColor":
            value = value.get_string() if value else "black"
        elif type_name == "GFile":
            value = value.get_path() if value else ""
        elif type_name == "GimpFont":
            value = value.get_name() if value else "Sans-serif"
        elif type_name not in ("gboolean", "gchararray"):
            raise ValueError(
                f"Procedura wymaga parametru {spec.name} typu {type_name}, którego ten edytor nie obsługuje."
            )
        form.add(spec.name, spec.nick, value, limits, spec.blurb, choices)
    return form


def exporter_name(kind, settings):
    """PDB procedure whose parameters the step edits; None when it has none."""
    if kind == "changeformat":
        return EXPORTERS[FORMATS[settings["format"]]]
    if kind == "variant":
        return EXPORTERS[FORMATS[settings["format"] - 1]] if settings["format"] else None
    return settings["procedure"]


def edit_step(parent, step, preview_source=None, prefix_steps=None, home=None, options=None):
    step = copy.deepcopy(step)
    kind = step["type"]
    dialog = Gtk.Dialog(title=_(SCHEMAS[kind][0]), transient_for=parent, modal=True)
    dialog.add_buttons(_("Anuluj"), Gtk.ResponseType.CANCEL, _("Zapisz"), Gtk.ResponseType.OK)
    dialog.set_default_size(640, 600)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    form = Form()
    for key, field in SCHEMAS[kind][1].items():
        form.add(key, field[0], step["settings"][key], field[2] if len(field) > 2 else None)
    box.pack_start(form.grid, False, False, 0)
    if kind == "lut":
        from bimp_preview import PreviewPane

        preview = PreviewPane(home or Path(Gimp.directory()) / "bimp3-data")
        source = [preview_source]
        box.pack_start(
            Gtk.Label(label=_("LUT w kodowaniu sRGB. Siła 0% zachowuje oryginalne kolory."), xalign=0),
            False,
            False,
            0,
        )

        def update_preview(*_args):
            values = form.values()
            if source[0] and Path(values["file"]).is_file():
                preview.request(source[0], list(prefix_steps or []) + [{"type": "lut", "settings": values}], options)

        def pick_source():
            selected = choose(dialog, _("Zdjęcie do podglądu LUT"))
            if selected:
                source[0] = selected
                preview.show_source(selected)
                if not Path(form.values()["file"]).is_file():
                    preview.status.set_text(_("Zdjęcie wczytane. Wybierz plik LUT .cube, aby zobaczyć efekt."))
                update_preview()

        box.pack_start(button(_("Wybierz zdjęcie do podglądu…"), pick_source), False, False, 0)
        box.pack_start(preview, True, True, 0)
        form.widgets["strength"].connect("value-changed", update_preview)
        form.widgets["file"].get_children()[0].connect("changed", update_preview)
        dialog.set_default_size(1020, 820)
        update_preview()
    advanced = [None]
    advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    if kind in ("changeformat", "userdef", "variant"):

        def load_arguments(initial=False):
            try:
                name = exporter_name(kind, form.values())
                for child in advanced_box.get_children():
                    advanced_box.remove(child)
                if name is None:
                    advanced[0] = (None, None)
                    return
                args = step["settings"].get("arguments", {}) if initial else {}
                new_form = procedure_form(procedure(name), args)
                advanced_box.pack_start(new_form.grid, False, False, 0)
                advanced[0] = (name, new_form)
                advanced_box.show_all()
            except Exception as exc:
                advanced[0] = None
                error(dialog, exc)

        box.pack_start(button(_("Wczytaj parametry procedury"), load_arguments), False, False, 0)
        if kind == "userdef":

            def pick_procedure():
                picker = Gtk.Dialog(title=_("Procedury GIMP 3"), transient_for=dialog, modal=True)
                picker.add_buttons(_("Anuluj"), Gtk.ResponseType.CANCEL, _("Wybierz"), Gtk.ResponseType.OK)
                picker.set_default_size(580, 500)
                store = Gtk.ListStore(str)
                names = [n for n in SAFE_USER_PROCEDURES if Gimp.get_pdb().lookup_procedure(n)]
                for name in sorted(names):
                    if name.startswith(("plug-in-bimp3", "file-", "gimp-xcf")):
                        continue
                    proc = Gimp.get_pdb().lookup_procedure(name)
                    if any(p.name in ("image", "drawable", "drawables") for p in proc.get_arguments()):
                        store.append([name])
                view = Gtk.TreeView(model=store)
                view.append_column(
                    Gtk.TreeViewColumn(_("Nazwa (pisz, aby wyszukać)"), Gtk.CellRendererText(), text=0)
                )
                view.set_search_column(0)
                picker.get_content_area().pack_start(scroll(view), True, True, 0)
                picker.show_all()
                if picker.run() == Gtk.ResponseType.OK:
                    model, it = view.get_selection().get_selected()
                    if it is not None:
                        form.widgets["procedure"].set_text(model[it][0])
                picker.destroy()
                if form.values()["procedure"]:
                    load_arguments()

            box.pack_start(button(_("Przeglądaj procedury GIMP…"), pick_procedure), False, False, 0)
        box.pack_start(advanced_box, False, False, 0)
        if kind in ("changeformat", "variant") or step["settings"].get("procedure"):
            load_arguments(True)
        if kind in ("changeformat", "variant"):
            form.widgets["format"].connect("changed", lambda _widget: load_arguments())
    dialog.get_content_area().pack_start(scroll(box), True, True, 0)
    dialog.show_all()
    result = None
    while dialog.run() == Gtk.ResponseType.OK:
        try:
            settings = form.values()
            if kind in ("changeformat", "userdef", "variant"):
                name = exporter_name(kind, settings)
                if advanced[0] is None or advanced[0][0] != name:
                    raise ValueError("Wczytaj parametry wybranego formatu lub procedury przed zapisaniem.")
                settings["arguments"] = advanced[0][1].values() if advanced[0][1] else {}
            step["settings"] = settings
            validate_runtime([step])
            result = step
            break
        except Exception as exc:
            error(dialog, exc)
    dialog.destroy()
    return result


def __getattr__(name):
    if name == "BatchWindow":
        from bimp_window import BatchWindow

        return BatchWindow
    raise AttributeError(name)
