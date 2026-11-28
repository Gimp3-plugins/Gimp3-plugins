"""Polish GTK3 mask panel. SPDX-License-Identifier: MIT."""
from array import array
from pathlib import Path
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GimpUi', '3.0')
from gi.repository import Gtk, GimpUi, Gdk, GdkPixbuf, GLib
from zm_core import Settings, Engine, PRESETS, dumps, loads
from zm_gimp import preview


class Panel:
    def __init__(self, image, layer, config):
        GimpUi.init('zetmar-maski')
        self.config = config
        self.pending = 0
        self.loading = False
        self.pick = False
        self.rgba, self.selection, self.w, self.h = preview(image, layer)
        self.pixels = array('f')
        self.pixels.frombytes(bytes(self.rgba))
        self.win = Gtk.Dialog(title='Zetmar Maski — jasność i kolor', use_header_bar=True)
        self.win.add_button('Anuluj', Gtk.ResponseType.CANCEL)
        self.win.add_button('Utwórz maskę', Gtk.ResponseType.OK)
        self.win.set_default_response(Gtk.ResponseType.OK)
        self.win.set_resizable(True)
        self.win.set_default_size(1040, 640)
        self.win.connect('response', self.validate_response)
        content = self.win.get_content_area()
        content.set_border_width(16)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        content.pack_start(root, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.pack_start(left, True, True, 0)
        title = Gtk.Label(xalign=0)
        title.set_markup('<b>Podgląd maski</b>')
        left.pack_start(title, False, False, 0)
        self.view = Gtk.ComboBoxText()
        for text in ('Czarno-biała maska', 'Czerwona nakładka — obszar wybrany', 'Oryginalne zdjęcie'):
            self.view.append_text(text)
        self.view.set_active(0)
        self.view.connect('changed', self.changed)
        left.pack_start(self.view, False, False, 0)
        frame = Gtk.Frame()
        self.event = Gtk.EventBox()
        self.picture = Gtk.Image()
        self.event.add(self.picture)
        self.event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.event.connect('button-press-event', self.clicked)
        frame.add(self.event)
        left.pack_start(frame, True, True, 0)
        self.hint = Gtk.Label(label='Białe obszary maski przepuszczają korektę, czarne ją ukrywają.', xalign=0)
        self.hint.set_line_wrap(True)
        left.pack_start(self.hint, False, False, 0)
        source = Gtk.Label(label=f'Źródło: {layer.get_name()}\nPodgląd {self.w} × {self.h} px · wynik w pełnej rozdzielczości', xalign=0)
        source.set_line_wrap(True)
        source.get_style_context().add_class('dim-label')
        left.pack_start(source, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        scroll.set_min_content_width(330)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_margin_end(10)
        scroll.add(right)
        root.pack_start(scroll, False, False, 0)
        self.controls = {}
        self.heading(right, '1. Zakres jasności')
        self.preset = Gtk.ComboBoxText()
        self.preset.append_text('Własne ustawienia')
        for name in PRESETS:
            self.preset.append_text(name)
        self.preset.set_active(0)
        self.preset.connect('changed', self.choose_preset)
        right.pack_start(self.preset, False, False, 0)
        self.slider(right, 'low', 'Początek zakresu')
        self.slider(right, 'high', 'Koniec zakresu')
        self.slider(right, 'feather', 'Łagodność przejścia')
        expander = Gtk.Expander(label='2. Maska koloru (opcjonalnie)')
        expander.set_expanded(config.get_property('color-enabled'))
        color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        expander.add(color_box)
        right.pack_start(expander, False, False, 0)
        self.check(color_box, 'color_enabled', 'Włącz maskę koloru (część wspólna)')
        color_row = Gtk.Box(spacing=8)
        self.color = Gtk.ColorButton()
        self.color.set_title('Kolor maski')
        self.color.set_use_alpha(False)
        self.color.connect('color-set', self.changed)
        color_row.pack_start(self.color, False, False, 0)
        self.picker = Gtk.ToggleButton(label='Pobierz ze zdjęcia')
        self.picker.connect('toggled', self.picker_toggled)
        color_row.pack_start(self.picker, True, True, 0)
        color_box.pack_start(color_row, False, False, 0)
        self.slider(color_box, 'tolerance', 'Tolerancja koloru')
        self.slider(color_box, 'color_softness', 'Łagodność koloru')
        self.heading(right, '3. Maska i wynik')
        self.check(right, 'invert', 'Odwróć maskę')
        self.check(right, 'selection', 'Ogranicz do bieżącego zaznaczenia')
        self.controls['selection'].set_tooltip_text('Brak zaznaczenia oznacza całą warstwę. Odwrócenie maski odbywa się przed ograniczeniem do zaznaczenia.')
        self.output = Gtk.ComboBoxText()
        for nick, text in [('new-layer', 'Nowa warstwa z maską'), ('layer-mask', 'Maska aktywnej warstwy'),
                           ('channel', 'Kanał'), ('selection', 'Zaznaczenie')]:
            self.output.append(nick, text)
        self.output.set_active_id(config.get_property('output'))
        right.pack_start(self.output, False, False, 0)
        self.name = Gtk.Entry(text=config.get_property('name') or 'Zetmar Maski')
        self.name.set_placeholder_text('Nazwa wyniku')
        right.pack_start(self.name, False, False, 0)
        note = Gtk.Label(label='Na nowej warstwie użyj np. Ekspozycji lub Krzywych.', xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(38)
        right.pack_start(note, False, False, 0)
        self.output.set_tooltip_text('Nowa warstwa to kopia zdjęcia z maską. Istniejąca maska kopii jest mnożona przez nową. Maska aktywnej warstwy wymaga warstwy bez maski.')
        row = Gtk.Box(spacing=8)
        for label, save in [('Wczytaj preset…', False), ('Zapisz preset…', True)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', self.preset_file, save)
            row.pack_start(button, True, True, 0)
        right.pack_start(row, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        right.pack_start(self.status, False, False, 0)
        self.set_settings(Settings(**{k: config.get_property(k.replace('_', '-')) for k in Settings.__dataclass_fields__}))
        self.win.show_all()
        self.render()

    @staticmethod
    def heading(box, text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f'<b>{text}</b>')
        label.set_margin_top(6)
        box.pack_start(label, False, False, 0)

    def slider(self, box, key, text):
        box.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_digits(0)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect('value-changed', self.changed)
        self.controls[key] = scale
        box.pack_start(scale, False, False, 0)

    def check(self, box, key, text):
        widget = Gtk.CheckButton(label=text)
        widget.connect('toggled', self.changed)
        self.controls[key] = widget
        box.pack_start(widget, False, False, 0)

    def settings(self):
        values = {k: (v.get_active() if isinstance(v, Gtk.CheckButton) else v.get_value()/100)
                  for k, v in self.controls.items()}
        color = self.color.get_rgba()
        return Settings(**values, red=color.red, green=color.green, blue=color.blue)

    def set_settings(self, settings):
        self.loading = True
        for key, widget in self.controls.items():
            value = getattr(settings, key)
            if isinstance(widget, Gtk.CheckButton):
                widget.set_active(value)
            else:
                widget.set_value(value * 100)
        color = Gdk.RGBA()
        color.red, color.green, color.blue, color.alpha = settings.red, settings.green, settings.blue, 1.
        self.color.set_rgba(color)
        self.loading = False
        self.changed()

    def changed(self, *args):
        if self.loading:
            return
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(150, self.render)

    def choose_preset(self, widget):
        value = PRESETS.get(widget.get_active_text())
        if value:
            self.loading = True
            for key, v in zip(('low', 'high', 'feather'), value):
                self.controls[key].set_value(v*100)
            self.loading = False
            self.changed()

    def picker_toggled(self, widget):
        self.pick = widget.get_active()
        if self.pick:
            self.view.set_active(2)
        self.hint.set_text('Kliknij kolor na zdjęciu w podglądzie.' if self.pick else
                           'Białe obszary maski przepuszczają korektę, czarne ją ukrywają.')

    def clicked(self, widget, event):
        if not self.pick or event.button != 1:
            return
        allocation = widget.get_allocation()
        x = int(event.x - (allocation.width-self.w)/2)
        y = int(event.y - (allocation.height-self.h)/2)
        if not 0 <= x < self.w or not 0 <= y < self.h:
            return
        i = (y*self.w+x)*4
        color = Gdk.RGBA()
        color.red, color.green, color.blue = [min(1., max(0., v)) for v in self.pixels[i:i+3]]
        color.alpha = 1.
        self.color.set_rgba(color)
        self.controls['color_enabled'].set_active(True)
        self.picker.set_active(False)
        self.view.set_active(1)
        self.changed()

    def render(self):
        self.pending = 0
        try:
            settings = self.settings()
            mask = array('f')
            mask.frombytes(Engine(settings).mask(self.rgba, self.selection))
            mode = self.view.get_active()
            rgb = bytearray()
            for n, v in enumerate(mask):
                if mode == 0:
                    c = round(v*255)
                    rgb.extend((c, c, c))
                else:
                    i = n*4
                    x, y = n % self.w, n // self.w
                    checker = .25 if (x//12+y//12) % 2 else .4
                    alpha = min(1., max(0., self.pixels[i+3]))
                    colors = [min(1., max(0., c))*alpha + checker*(1-alpha) for c in self.pixels[i:i+3]]
                    opacity = v*.6 if mode == 1 else 0.
                    rgb.extend(round(255*(c*(1-opacity) + (opacity if j == 0 else 0.))) for j, c in enumerate(colors))
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgb)), GdkPixbuf.Colorspace.RGB,
                                                    False, 8, self.w, self.h, self.w*3)
            self.picture.set_from_pixbuf(pixbuf)
            coverage = sum(mask)/len(mask)*100
            self.status.set_text(f'Średnie pokrycie maski: {coverage:.1f}%')
            self.win.set_response_sensitive(Gtk.ResponseType.OK, True)
        except Exception as exc:
            self.status.set_text(str(exc))
            self.win.set_response_sensitive(Gtk.ResponseType.OK, False)
        return False

    def validate_response(self, win, response):
        if response == Gtk.ResponseType.OK:
            try:
                self.settings()
            except ValueError as exc:
                self.status.set_text(str(exc))
                win.stop_emission_by_name('response')

    def preset_file(self, button, save):
        chooser = Gtk.FileChooserDialog(title='Zapisz preset' if save else 'Wczytaj preset', transient_for=self.win,
                                        action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
        chooser.add_buttons('Anuluj', Gtk.ResponseType.CANCEL, 'Zapisz' if save else 'Wczytaj', Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        if save:
            chooser.set_current_name('maska.zmask.json')
        file_filter = Gtk.FileFilter()
        file_filter.set_name('Presety masek (*.json)')
        file_filter.add_pattern('*.json')
        chooser.add_filter(file_filter)
        try:
            if chooser.run() == Gtk.ResponseType.OK:
                path = Path(chooser.get_filename())
                if save:
                    path.write_text(dumps(self.settings()), encoding='utf-8')
                else:
                    with path.open('r', encoding='utf-8-sig') as stream:
                        self.set_settings(loads(stream.read(16385)))
                    self.preset.set_active(0)
        except Exception as exc:
            self.status.set_text(str(exc))
        finally:
            chooser.destroy()

    def run(self):
        try:
            if self.win.run() != Gtk.ResponseType.OK:
                return False
            for key, value in self.settings().__dict__.items():
                self.config.set_property(key.replace('_', '-'), value)
            self.config.set_property('output', self.output.get_active_id())
            self.config.set_property('name', self.name.get_text().strip() or 'Zetmar Maski')
            return True
        finally:
            if self.pending:
                GLib.source_remove(self.pending)
            self.win.destroy()


def dialog(image, layer, config):
    return Panel(image, layer, config).run()
