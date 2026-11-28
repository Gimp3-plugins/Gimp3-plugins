# -*- coding: utf-8 -*-
"""
Okno wtyczki Zetmar Kolor (GTK3): podgląd przed/po i zakładki Krzywe, Cz-B,
Duotone, Toning. Podgląd liczymy na zmniejszonej kopii warstwy (GEGL skaluje
przy odczycie). Okno można też zbudować bez GIMP-a (SampleSource,
offscreen=True) – do testów i zrzutów ekranu.
"""

import json
import os
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango  # noqa: E402
import cairo  # noqa: E402

import zk_core  # noqa: E402
from zk_core import Look, CH_RGB  # noqa: E402
from zk_i18n import tr  # noqa: E402

DEBOUNCE_MS = 80
RESP_APPLY = 1
SPLIT_GRAB = 10
PREVIEW_MODES = [("after", tr("Po")), ("before", tr("Przed")), ("split", tr("Podział przed/po"))]
CHANNELS = [(0, "RGB"), (1, tr("Czerwony")), (2, tr("Zielony")), (3, tr("Niebieski"))]
CHANNEL_COLORS = {0: (0.1, 0.1, 0.1), 1: (0.86, 0.12, 0.12), 2: (0.08, 0.63, 0.16),
                  3: (0.12, 0.31, 0.9)}
PICK = ""
LOOK_PATTERNS = ("*.zklook", "*.ZKLOOK")


# --- pomocnicze ------------------------------------------------------------------------

def _pixbuf(rgba8, w, h):
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(rgba8), GdkPixbuf.Colorspace.RGB,
                                           True, 8, w, h, w * 4)


def _message(parent, text, secondary="", kind=Gtk.MessageType.INFO):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                            buttons=Gtk.ButtonsType.OK, text=text)
    if secondary:
        dlg.format_secondary_text(secondary)
    dlg.run()
    dlg.destroy()


def _combo(items, active=None, pick=None):
    combo = Gtk.ComboBoxText()
    if pick is not None:
        combo.append(PICK, pick)
    for nick, label in items:
        combo.append(str(nick), label)
    if active is None or not combo.set_active_id(str(active)):
        combo.set_active(0)
    return combo


def _hint(text):
    lab = Gtk.Label(xalign=0)
    lab.set_markup("<small>%s</small>" % GLib.markup_escape_text(text))
    lab.set_line_wrap(True)
    lab.set_max_width_chars(48)
    return lab


def _rgba(c):
    r, g, b = zk_core.hex_to_rgb(c)
    return Gdk.RGBA(r, g, b, 1.0)


def _hex(rgba):
    return ((int(round(rgba.red * 255)) << 16) | (int(round(rgba.green * 255)) << 8)
            | int(round(rgba.blue * 255)))


# --- źródła obrazu do podglądu --------------------------------------------------------

class ImageSource:
    """Podgląd z warstwy obrazu GIMP-a."""

    def __init__(self, image, layer):
        self.image, self.layer = image, layer

    def fit(self, max_side):
        import zk_gimp
        return zk_gimp.read_scaled(self.image, self.layer, max_side)


class SampleSource:
    """Obrazek testowy (testy bez GIMP-a): tęcza z gradientem jasności i szarości."""

    def fit(self, max_side):
        import struct
        w, h = max_side, max_side * 2 // 3
        px = []
        for y in range(h):
            v = 1.0 - y / float(h - 1)
            for x in range(w):
                if y > h * 0.8:
                    g = x / float(w - 1)
                    px += (g, g, g, 1.0)
                    continue
                r, g, b = zk_core.hue_color(360.0 * x / w)
                s = 0.25 + 0.75 * v
                px += (r * s + (1 - s) * 0.5 * v, g * s + (1 - s) * 0.5 * v,
                       b * s + (1 - s) * 0.5 * v, 1.0)
        return struct.pack("<%df" % len(px), *px), None, w, h


# --- edytor krzywej ----------------------------------------------------------------

class CurveEditor(Gtk.DrawingArea):
    """Krzywa aktywnego kanału na tle histogramu. Klik: punkt, przeciąganie, PPM/Del: usuń."""

    MARGIN = 8

    def __init__(self, on_changed, on_select):
        super().__init__()
        self.on_changed, self.on_select = on_changed, on_select
        self.look = Look()
        self.channel = CH_RGB
        self.hist = None
        self.log = False
        self.sel = -1
        self.drag = False
        self.set_size_request(300, 300)
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)
        self.connect("key-press-event", self._key)

    def pts(self):
        return self.look.curves[self.channel]

    def set_channel(self, ch):
        self.channel, self.sel = ch, -1
        self._selected()
        self.queue_draw()

    def _rect(self):
        m = self.MARGIN
        return (m, m, max(1, self.get_allocated_width() - 2 * m),
                max(1, self.get_allocated_height() - 2 * m))

    def _to_screen(self, x, y):
        x0, y0, w, h = self._rect()
        return x0 + x * w, y0 + (1.0 - y) * h

    def _to_curve(self, px, py):
        x0, y0, w, h = self._rect()
        return (min(1.0, max(0.0, (px - x0) / w)), min(1.0, max(0.0, 1.0 - (py - y0) / h)))

    def _hit(self, px, py):
        best, best_d = -1, 10.0 ** 2
        for i, (x, y) in enumerate(self.pts()):
            sx, sy = self._to_screen(x, y)
            d = (sx - px) ** 2 + (sy - py) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    def _selected(self):
        p = self.pts()[self.sel] if 0 <= self.sel < len(self.pts()) else None
        self.on_select(p)

    def _changed(self):
        self._selected()
        self.queue_draw()
        self.on_changed()

    # --- rysowanie --------------------------------------------------------------------

    def _draw(self, _w, cr):
        x0, y0, w, h = self._rect()
        cr.set_source_rgb(0.97, 0.97, 0.97)
        cr.rectangle(x0, y0, w, h)
        cr.fill()
        if self.hist is not None:
            bins = self.hist[self.channel]
            vals = [float(v) for v in bins]
            if self.log:
                import math
                vals = [math.log1p(v) for v in vals]
            top = max(vals[1:255] or [1.0]) or 1.0
            cr.set_source_rgba(*CHANNEL_COLORS[self.channel], 0.18)
            cr.move_to(x0, y0 + h)
            for i, v in enumerate(vals):
                cr.line_to(x0 + w * i / 255.0, y0 + h - h * min(1.0, v / top))
            cr.line_to(x0 + w, y0 + h)
            cr.close_path()
            cr.fill()
        cr.set_line_width(1.0)
        cr.set_source_rgb(0.82, 0.82, 0.82)
        for i in range(1, 4):
            cr.move_to(x0 + w * i / 4.0, y0)
            cr.line_to(x0 + w * i / 4.0, y0 + h)
            cr.move_to(x0, y0 + h * i / 4.0)
            cr.line_to(x0 + w, y0 + h * i / 4.0)
        cr.stroke()
        cr.set_dash([4.0, 4.0])
        cr.move_to(x0, y0 + h)
        cr.line_to(x0 + w, y0)
        cr.stroke()
        cr.set_dash([])
        cr.set_source_rgb(0.6, 0.6, 0.6)
        cr.rectangle(x0, y0, w, h)
        cr.stroke()
        # pozostałe kanały – cienko
        for ch in range(4):
            if ch != self.channel and not zk_core.is_identity_curve(self.look.curves[ch]):
                cr.set_source_rgba(*CHANNEL_COLORS[ch], 0.45)
                self._curve_path(cr, self.look.curves[ch])
                cr.set_line_width(1.0)
                cr.stroke()
        cr.set_source_rgb(*CHANNEL_COLORS[self.channel])
        self._curve_path(cr, self.pts())
        cr.set_line_width(2.0)
        cr.stroke()
        for i, (x, y) in enumerate(self.pts()):
            sx, sy = self._to_screen(x, y)
            cr.arc(sx, sy, 4.5, 0, 6.2832)
            if i == self.sel:
                cr.fill()
            else:
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgb(*CHANNEL_COLORS[self.channel])
                cr.set_line_width(1.5)
                cr.stroke()
        return False

    def _curve_path(self, cr, pts):
        m = zk_core._slopes(pts)
        for i in range(257):
            x = i / 256.0
            sx, sy = self._to_screen(x, zk_core._eval(pts, m, x))
            (cr.move_to if i == 0 else cr.line_to)(sx, sy)

    # --- mysz i klawiatura -------------------------------------------------------------

    def _press(self, _w, ev):
        self.grab_focus()
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        pts = self.pts()
        i = self._hit(ev.x, ev.y)
        if ev.button == 3:
            if 0 < i < len(pts) - 1:
                del pts[i]
                self.sel = -1
                self._changed()
            return True
        if ev.button != 1:
            return False
        if i < 0:
            x, y = self._to_curve(ev.x, ev.y)
            i = self._add(x, y)
            if i < 0:
                return True
            self._changed()
        self.sel, self.drag = i, True
        self._selected()
        self.queue_draw()
        return True

    def _add(self, x, y):
        pts = self.pts()
        if len(pts) >= zk_core.MAX_POINTS:
            return -1
        k = 1
        while k < len(pts) and pts[k][0] < x:
            k += 1
        if k >= len(pts) or x - pts[k - 1][0] < zk_core.MIN_GAP or pts[k][0] - x < zk_core.MIN_GAP:
            return -1
        pts.insert(k, [x, y])
        return k

    def _move(self, i, x, y):
        pts = self.pts()
        if i == 0:
            x = 0.0
        elif i == len(pts) - 1:
            x = 1.0
        else:
            x = min(max(x, pts[i - 1][0] + zk_core.MIN_GAP), pts[i + 1][0] - zk_core.MIN_GAP)
        pts[i] = [x, min(1.0, max(0.0, y))]

    def _motion(self, _w, ev):
        if self.drag and 0 <= self.sel < len(self.pts()):
            self._move(self.sel, *self._to_curve(ev.x, ev.y))
            self._changed()
        return True

    def _release(self, _w, ev):
        self.drag = False
        return True

    def _key(self, _w, ev):
        pts = self.pts()
        if not 0 <= self.sel < len(pts):
            return False
        name = Gdk.keyval_name(ev.keyval)
        step = 1.0 / 255.0
        x, y = pts[self.sel]
        if name in ("Delete", "BackSpace"):
            if 0 < self.sel < len(pts) - 1:
                del pts[self.sel]
                self.sel = -1
                self._changed()
            return True
        moves = {"Up": (0, step), "Down": (0, -step), "Left": (-step, 0), "Right": (step, 0)}
        if name in moves:
            dx, dy = moves[name]
            self._move(self.sel, x + dx, y + dy)
            self._changed()
            return True
        return False


# --- okno --------------------------------------------------------------------------

class ZkWindow:

    def __init__(self, source, look=None, image=None, layers=None, config=None,
                 offscreen=False):
        self.source = source
        self.image, self.layers, self.config = image, layers or [], config
        self.offscreen = offscreen
        self.settings = _load_settings()
        self.look = look.copy() if look is not None else Look()
        self.np_ok = zk_core.get_numpy() is not None
        self.preview_max = 1000 if self.np_ok else 480
        self.split = 0.5
        self._sync = False
        self._update_job = None
        self._busy = False
        self._cancel = False
        self._hold_before = False
        self._drag_split = False
        self.widgets = {}
        self.rows = {}

        t = time.perf_counter()
        self.data, self.mask, self.w, self.h = source.fit(self.preview_max)
        self.before_pb = _pixbuf(zk_core.to_rgba8(self.data), self.w, self.h)
        self.after_pb = self.before_pb
        self.hist = zk_core.histograms(self.data)
        self._read_ms = (time.perf_counter() - t) * 1000
        self._build()
        self._sync_widgets()
        self._update_preview()

    # --- budowa -----------------------------------------------------------------------

    def _build(self):
        self.dialog = dlg = Gtk.Dialog(title=tr("Zetmar Kolor – krzywe, Cz-B, duotone, toning"))
        if self.image is not None:
            from gi.repository import GimpUi
            GimpUi.window_set_transient(dlg)
        dlg.set_default_size(1280, 820)
        dlg.add_button(tr("_Anuluj"), Gtk.ResponseType.CANCEL)
        self.apply_button = dlg.add_button(tr("_Zastosuj"), RESP_APPLY)
        dlg.set_default_response(RESP_APPLY)
        dlg.connect("delete-event", lambda *_: self._busy)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.pack1(self._build_preview(), True, False)
        paned.pack2(self._build_controls(), False, False)
        paned.set_position(800)
        area = dlg.get_content_area()
        area.set_border_width(6)
        area.set_spacing(6)
        area.pack_start(paned, True, True, 0)

        self.progress_box = Gtk.Box(spacing=6)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress_box.pack_start(self.progress, True, True, 0)
        stop = Gtk.Button(label=tr("Przerwij"))
        stop.connect("clicked", self._on_cancel_apply)
        self.progress_box.pack_start(stop, False, False, 0)
        area.pack_start(self.progress_box, False, False, 0)
        self.paned = paned
        if self.offscreen:
            area.remove(paned)
            area.remove(self.progress_box)
            self.offscreen_window = Gtk.OffscreenWindow()
            self.offscreen_window.set_size_request(1280, 820)
            self.offscreen_window.add(paned)
            self.offscreen_window.show_all()
        else:
            dlg.show_all()
        self.progress_box.hide()

    def _build_preview(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar = Gtk.Box(spacing=6)
        bar.pack_start(Gtk.Label(label=tr("Podgląd:")), False, False, 0)
        self.mode_combo = _combo(PREVIEW_MODES, self.settings.get("preview_mode", "split"))
        self.mode_combo.connect("changed", lambda *_: self._on_mode_changed())
        bar.pack_start(self.mode_combo, False, False, 0)
        tip = Gtk.Label(xalign=0)
        tip.set_markup("<small>%s</small>" % GLib.markup_escape_text(
            tr("Przytrzymaj przycisk myszy na podglądzie, żeby zobaczyć oryginał.")))
        bar.pack_start(tip, False, False, 6)
        box.pack_start(bar, False, False, 0)

        self.area = Gtk.DrawingArea()
        self.area.set_size_request(420, 320)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("draw", self._on_draw)
        self.area.connect("button-press-event", self._on_area_press)
        self.area.connect("button-release-event", self._on_area_release)
        self.area.connect("motion-notify-event", self._on_area_motion)
        box.pack_start(self.area, True, True, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(self.status, False, False, 0)
        return box

    def _build_controls(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(440, -1)
        nb = Gtk.Notebook()
        for title, page in ((tr("Krzywe"), self._page_curves()), (tr("Cz-B"), self._page_bw()),
                            (tr("Duotone"), self._page_duotone()),
                            (tr("Toning"), self._page_toning())):
            sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            page.set_border_width(8)
            sw.add(page)
            nb.append_page(sw, Gtk.Label(label=title))
        self.notebook = nb
        box.pack_start(nb, True, True, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self._slider(grid, 0, "overall", tr("Siła ogólna"), 0, 100, "%",
                     tr("0 % = oryginał, 100 % = pełny efekt"))
        grid.attach(Gtk.Label(label=tr("Wynik"), xalign=0), 0, 1, 1, 1)
        out = Gtk.Box(spacing=8)
        self.out_new = Gtk.RadioButton(label=tr("Nowa warstwa z efektem"))
        self.out_inplace = Gtk.RadioButton(label=tr("Na aktywnej warstwie"), group=self.out_new)
        (self.out_inplace if self._initial_output() == "in-place" else self.out_new).set_active(True)
        out.pack_start(self.out_new, False, False, 0)
        out.pack_start(self.out_inplace, False, False, 0)
        grid.attach(out, 1, 1, 3, 1)
        box.pack_start(grid, False, False, 0)

        btns = Gtk.Box(spacing=6)
        for label, cb in ((tr("Zapisz look…"), self._on_save_look),
                          (tr("Wczytaj look…"), self._on_load_look),
                          (tr("Resetuj wszystko"), self._on_reset_all)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            btns.pack_start(b, True, True, 0)
        btns.get_children()[0].set_tooltip_text(
            tr("Plik .zklook – ten sam format co w wersji dla Photoshopa"))
        box.pack_start(btns, False, False, 0)
        return box

    def _initial_output(self):
        if self.config is not None:
            try:
                return self.config.get_property("output")
            except TypeError:
                pass
        return self.settings.get("output", "new-layer")

    def _slider(self, grid, row, key, label, lo, hi, suffix="", tooltip="", swatch=None):
        adj = Gtk.Adjustment(value=lo, lower=lo, upper=hi, step_increment=1, page_increment=10)
        lab = Gtk.Label(label=label, xalign=0)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj,
                          draw_value=False, hexpand=True)
        spin = Gtk.SpinButton(adjustment=adj, digits=0, width_chars=4)
        if tooltip:
            for w in (lab, scale, spin):
                w.set_tooltip_text(tooltip)
        grid.attach(lab, 0, row, 1, 1)
        grid.attach(scale, 1, row, 1, 1)
        grid.attach(spin, 2, row, 1, 1)
        self.rows[key] = [lab, scale, spin]
        if swatch is not None:
            sw = Gtk.DrawingArea()
            sw.set_size_request(22, 16)
            sw.connect("draw", lambda w, cr: self._draw_swatch(w, cr, swatch()))
            adj.connect("value-changed", lambda *_: sw.queue_draw())
            grid.attach(sw, 3, row, 1, 1)
            self.rows[key].append(sw)
        elif suffix:
            grid.attach(Gtk.Label(label=suffix, xalign=0), 3, row, 1, 1)
        adj.connect("value-changed", lambda a: self._on_value(key, int(round(a.get_value()))))
        self.widgets[key] = adj
        return adj

    @staticmethod
    def _draw_swatch(w, cr, rgb):
        cr.set_source_rgb(*rgb)
        cr.rectangle(0, 0, w.get_allocated_width(), w.get_allocated_height())
        cr.fill()
        return False

    def _check(self, key, label):
        chk = Gtk.CheckButton(label=label)
        chk.connect("toggled", lambda c: self._on_value(key, c.get_active()))
        self.widgets[key] = chk
        return chk

    def _preset_combo(self, items, cb):
        combo = _combo(items, pick=tr("— wybierz —"))

        def changed(c):
            nick = c.get_active_id()
            if self._sync or not nick:
                return
            cb(nick)
            self._sync = True
            c.set_active(0)
            self._sync = False
            self._sync_widgets()
            self._schedule_update()
        combo.connect("changed", changed)
        return combo

    def _button(self, label, cb):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_: (cb(), self._sync_widgets(), self._schedule_update()))
        return b

    # --- zakładki -----------------------------------------------------------------------

    def _page_curves(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self._check("curves_on", tr("Krzywe włączone")), False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label=tr("Kanał:")), False, False, 0)
        self.channel_combo = _combo(CHANNELS, 0)
        self.channel_combo.connect("changed", lambda c: self.editor.set_channel(
            int(c.get_active_id())))
        row.pack_start(self.channel_combo, False, False, 0)
        row.pack_start(Gtk.Label(label=tr("Preset:")), False, False, 6)
        row.pack_start(self._preset_combo(zk_core.CURVE_PRESETS, self._curve_preset),
                       True, True, 0)
        box.pack_start(row, False, False, 0)

        self.editor = CurveEditor(self._on_curve_changed, self._on_point_selected)
        self.editor.look = self.look
        self.editor.hist = self.hist
        self.editor.log = bool(self.settings.get("log_hist", False))
        frame = Gtk.AspectFrame(ratio=1.0, obey_child=False, shadow_type=Gtk.ShadowType.NONE)
        frame.add(self.editor)
        box.pack_start(frame, True, True, 0)
        self.point_label = Gtk.Label(xalign=0)
        box.pack_start(self.point_label, False, False, 0)
        box.pack_start(self._check("luma_only", tr("Tylko jasność (krzywa RGB nie zmienia "
                                                   "kolorów)")), False, False, 0)
        log = Gtk.CheckButton(label=tr("Histogram logarytmiczny"))
        log.set_active(self.editor.log)
        log.connect("toggled", self._on_log_toggled)
        box.pack_start(log, False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_start(self._button(tr("Reset kanału"), self._reset_channel), True, True, 0)
        row.pack_start(self._button(tr("Reset wszystkich"), self.look_reset_curves), True, True, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(_hint(tr("Klik: dodaj punkt · przeciągnij: przesuń · prawy klik / Del: "
                                "usuń · strzałki: ±1")), False, False, 0)
        return box

    def _page_bw(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label=tr("Tryb:"), xalign=0), 0, 0, 1, 1)
        self.bw_combo = _combo(zk_core.BW_MODES, 0)
        self.bw_combo.connect("changed", lambda c: self._on_value(
            "bw_mode", int(c.get_active_id())))
        grid.attach(self.bw_combo, 1, 0, 3, 1)
        grid.attach(Gtk.Label(label=tr("Kolor filtru:"), xalign=0), 0, 1, 1, 1)
        grid.attach(self._preset_combo([(n, l) for n, l, _ in zk_core.BW_FILTERS],
                                       lambda n: self.look.apply_bw_filter(n)), 1, 1, 3, 1)
        for i, label in enumerate(zk_core.MIX_LABELS):
            self._slider(grid, 2 + i, "mix%d" % i, label, -200, 300, "%")
        box.pack_start(grid, False, False, 0)

        frame = Gtk.Frame(label=tr("Barwienie (sepia, monochromia)"))
        tg = Gtk.Grid(column_spacing=8, row_spacing=4)
        tg.set_border_width(6)
        self._slider(tg, 0, "tint_hue", tr("Odcień"), 0, 360,
                     swatch=lambda: zk_core.hue_color(self.look.tint_hue))
        self._slider(tg, 1, "tint_sat", tr("Siła barwy"), 0, 100, "%")
        frame.add(tg)
        self.tint_frame = frame
        box.pack_start(frame, False, False, 0)
        box.pack_start(self._button(tr("Reset czerni-bieli"), self.look_reset_bw), False, False, 0)
        box.pack_start(_hint(tr("Suwaki mówią, jak jasny ma być dany kolor w szarości "
                                "(−200…300 %). Sepia ma stały, ciepły odcień. Mikser "
                                "wyznacza też szarość dla duotonu.")), False, False, 0)
        return box

    def _page_duotone(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self._check("duo_on", tr("Duotone włączony")), False, False, 0)
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label=tr("Zestaw:"), xalign=0), 0, 0, 1, 1)
        grid.attach(self._preset_combo([(n, l) for n, l, *_ in zk_core.DUOTONE_PRESETS],
                                       lambda n: self.look.apply_duotone_preset(n)), 1, 0, 3, 1)
        self.duo_buttons = {}
        for row, (key, label) in enumerate((("duo_shadow", tr("Kolor cieni")),
                                            ("duo_highlight", tr("Kolor świateł"))), start=1):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            btn = Gtk.ColorButton()
            btn.set_use_alpha(False)
            btn.connect("color-set", lambda b, key=key: self._on_value(key, _hex(b.get_rgba())))
            self.duo_buttons[key] = btn
            grid.attach(btn, 1, row, 1, 1)
        swap = Gtk.Button(label=tr("Zamień kolory"))
        swap.connect("clicked", lambda *_: self._swap_duotone())
        grid.attach(swap, 2, 1, 2, 2)
        self.gradient = Gtk.DrawingArea()
        self.gradient.set_size_request(-1, 22)
        self.gradient.connect("draw", self._draw_gradient)
        grid.attach(self.gradient, 0, 3, 4, 1)
        self._slider(grid, 4, "duo_mid", tr("Punkt środkowy"), 5, 95, "%",
                     tr("Gdzie wypada połowa przejścia (w lewo = więcej koloru świateł)"))
        self._slider(grid, 5, "duo_amount", tr("Siła"), 0, 100, "%")
        box.pack_start(grid, False, False, 0)
        box.pack_start(self._button(tr("Reset duotonu"), self.look_reset_duotone), False, False, 0)
        box.pack_start(_hint(tr("Duotone przypisuje szarości przejście od koloru cieni do "
                                "koloru świateł. Szarość liczy mikser z zakładki Cz-B.")),
                       False, False, 0)
        return box

    def _page_toning(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self._check("ton_on", tr("Toning włączony")), False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label=tr("Preset:")), False, False, 0)
        row.pack_start(self._preset_combo([(n, l) for n, l, _ in zk_core.TONING_PRESETS],
                                          lambda n: self.look.apply_toning_preset(n)),
                       True, True, 0)
        box.pack_start(row, False, False, 0)
        for title, hue, sat in ((tr("Światła"), "hi_hue", "hi_sat"),
                                (tr("Cienie"), "sh_hue", "sh_sat")):
            frame = Gtk.Frame(label=title)
            g = Gtk.Grid(column_spacing=8, row_spacing=4)
            g.set_border_width(6)
            self._slider(g, 0, hue, tr("Odcień"), 0, 360,
                         swatch=lambda hue=hue: zk_core.hue_color(getattr(self.look, hue)))
            self._slider(g, 1, sat, tr("Nasycenie"), 0, 100, "%")
            frame.add(g)
            box.pack_start(frame, False, False, 0)
        g = Gtk.Grid(column_spacing=8, row_spacing=4)
        self._slider(g, 0, "balance", tr("Balans"), -100, 100, "",
                     tr("Dodatni = więcej świateł, ujemny = więcej cieni"))
        box.pack_start(g, False, False, 0)
        box.pack_start(self._button(tr("Reset tonowania"), self.look_reset_toning), False, False, 0)
        box.pack_start(_hint(tr("Toning działa po czerni-bieli i duotonie. Balans przesuwa "
                                "granicę między cieniami a światłami.")), False, False, 0)
        return box

    # --- model ↔ widżety ---------------------------------------------------------------

    def _sync_widgets(self):
        """Ustawia widżety według self.look (bez wywoływania przeliczeń)."""
        self._sync = True
        try:
            lk = self.look
            for key, w in self.widgets.items():
                if key.startswith("mix"):
                    val = lk.bw_mix[int(key[3:])]
                else:
                    val = getattr(lk, key)
                if isinstance(w, Gtk.Adjustment):
                    w.set_value(val)
                else:
                    w.set_active(bool(val))
            self.bw_combo.set_active_id(str(lk.bw_mode))
            for key, btn in self.duo_buttons.items():
                btn.set_rgba(_rgba(getattr(lk, key)))
            self.editor.look = lk
            self.editor.sel = -1
            self.editor.queue_draw()
            self._on_point_selected(None)
            self._update_sensitivity()
            self.gradient.queue_draw()
        finally:
            self._sync = False

    def _update_sensitivity(self):
        mode = self.look.bw_mode
        self.tint_frame.set_sensitive(mode in (zk_core.BW_SEPIA, zk_core.BW_MONO))
        # Odcień ma sens tylko dla monochromii (sepia ma stały, ciepły odcień).
        for w in self.rows["tint_hue"]:
            w.set_sensitive(mode == zk_core.BW_MONO)

    def _on_value(self, key, value):
        if self._sync:
            return
        if key.startswith("mix"):
            self.look.bw_mix[int(key[3:])] = value
        else:
            setattr(self.look, key, value)
        if key in ("bw_mode",):
            self._update_sensitivity()
        if key.startswith("duo"):
            self.gradient.queue_draw()
        if key == "luma_only" or key == "curves_on":
            self.editor.queue_draw()
        self._schedule_update()

    def _on_curve_changed(self):
        if not self.look.curves_on:
            self.look.curves_on = True
            self._sync = True
            self.widgets["curves_on"].set_active(True)
            self._sync = False
        self._schedule_update()

    def _on_point_selected(self, p):
        if p is None:
            self.point_label.set_text(tr("Wejście: –   Wyjście: –"))
        else:
            self.point_label.set_text(tr("Wejście: %d   Wyjście: %d")
                                      % (round(p[0] * 255), round(p[1] * 255)))

    def _on_log_toggled(self, chk):
        self.editor.log = chk.get_active()
        self.settings["log_hist"] = self.editor.log
        self.editor.queue_draw()

    def _curve_preset(self, nick):
        self.look.apply_curve_preset(nick)

    def _reset_channel(self):
        self.look.curves[self.editor.channel] = zk_core.identity_curve()

    def look_reset_curves(self):
        self.look.reset_curves()

    def look_reset_bw(self):
        self.look.reset_bw()

    def look_reset_duotone(self):
        self.look.reset_duotone()

    def look_reset_toning(self):
        self.look.reset_toning()

    def _swap_duotone(self):
        lk = self.look
        lk.duo_shadow, lk.duo_highlight = lk.duo_highlight, lk.duo_shadow
        self._sync_widgets()
        self._schedule_update()

    def _on_reset_all(self):
        self.look = Look()
        self._sync_widgets()
        self._schedule_update()

    def _draw_gradient(self, w, cr):
        width, height = w.get_allocated_width(), w.get_allocated_height()
        pipe = zk_core.Pipeline(self._duotone_only())
        for x in range(0, width, 2):
            g = x / float(max(1, width - 1))
            cr.set_source_rgb(*pipe.pixel((g, g, g)))
            cr.rectangle(x, 0, 2, height)
            cr.fill()
        return False

    def _duotone_only(self):
        lk = Look()
        lk.duo_on, lk.duo_amount = True, 100
        lk.duo_shadow, lk.duo_highlight = self.look.duo_shadow, self.look.duo_highlight
        lk.duo_mid = self.look.duo_mid
        return lk

    # --- pliki looku ---------------------------------------------------------------------

    def _chooser(self, title, action, accept):
        ch = Gtk.FileChooserNative.new(title, self.dialog, action, accept, tr("_Anuluj"))
        flt = Gtk.FileFilter()
        flt.set_name(tr("Look Zetmar Kolor (*.zklook)"))
        for p in LOOK_PATTERNS:
            flt.add_pattern(p)
        ch.add_filter(flt)
        last = self.settings.get("last_dir")
        if last and os.path.isdir(last):
            ch.set_current_folder(last)
        return ch

    def _on_save_look(self):
        ch = self._chooser(tr("Zapisz look"), Gtk.FileChooserAction.SAVE, tr("_Zapisz"))
        ch.set_do_overwrite_confirmation(True)
        ch.set_current_name(tr("Mój look") + ".zklook")
        if ch.run() == Gtk.ResponseType.ACCEPT:
            path = ch.get_filename()
            if not path.lower().endswith(".zklook"):
                path += ".zklook"
            try:
                zk_core.save_look_file(path, self.look)
                self.settings["last_dir"] = os.path.dirname(path)
                self.status.set_text(tr("Zapisano look: %s") % path)
            except OSError as e:
                _message(self.dialog, tr("Nie udało się zapisać looku"), str(e),
                         Gtk.MessageType.ERROR)
        ch.destroy()

    def _on_load_look(self):
        ch = self._chooser(tr("Wczytaj look"), Gtk.FileChooserAction.OPEN, tr("_Otwórz"))
        if ch.run() == Gtk.ResponseType.ACCEPT:
            path = ch.get_filename()
            try:
                self.look = zk_core.load_look_file(path)
                self.settings["last_dir"] = os.path.dirname(path)
                self._sync_widgets()
                self._schedule_update()
                self.status.set_text(tr("Wczytano look: %s") % path)
            except zk_core.LookError as e:
                _message(self.dialog, tr("Nie udało się wczytać looku"), str(e),
                         Gtk.MessageType.ERROR)
        ch.destroy()

    # --- podgląd ------------------------------------------------------------------------

    def _schedule_update(self):
        if self._update_job is not None:
            GLib.source_remove(self._update_job)
        self._update_job = GLib.timeout_add(DEBOUNCE_MS, self._update_preview)

    def _update_preview(self):
        self._update_job = None
        if self._busy:
            return False
        t = time.perf_counter()
        pipe = zk_core.Pipeline(self.look)
        if pipe.neutral:
            self.after_pb = self.before_pb
        else:
            out = zk_core.apply_rgba(pipe, self.data, self.mask)
            self.after_pb = _pixbuf(zk_core.to_rgba8(out), self.w, self.h)
        ms = (time.perf_counter() - t) * 1000
        self.status.set_text(tr("Podgląd %d×%d px · %d ms · %s") % (
            self.w, self.h, ms, zk_core.backend_name()))
        self.area.queue_draw()
        return False

    def _mode(self):
        return self.mode_combo.get_active_id() or "after"

    def _on_mode_changed(self):
        self.settings["preview_mode"] = self._mode()
        self.area.queue_draw()

    def _image_rect(self):
        aw, ah = max(1, self.area.get_allocated_width()), max(1, self.area.get_allocated_height())
        s = min(aw / float(self.w), ah / float(self.h))
        dw, dh = self.w * s, self.h * s
        return (aw - dw) / 2.0, (ah - dh) / 2.0, dw, dh, s

    def _on_draw(self, area, cr):
        aw, ah = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(0.18, 0.18, 0.18)
        cr.rectangle(0, 0, aw, ah)
        cr.fill()
        x, y, dw, dh, s = self._image_rect()
        mode = self._mode()
        before = self._hold_before or mode == "before"
        self._paint(cr, self.before_pb if before else self.after_pb, x, y, s)
        if mode == "split" and not self._hold_before:
            sx = x + dw * self.split
            cr.save()
            cr.rectangle(x, y, sx - x, dh)
            cr.clip()
            self._paint(cr, self.before_pb, x, y, s)
            cr.restore()
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(2)
            cr.move_to(sx, y)
            cr.line_to(sx, y + dh)
            cr.stroke()
            self._label(cr, x + 8, y + 8, tr("Przed"))
            self._label(cr, x + dw - 8, y + 8, tr("Po"), right=True)
        elif before:
            self._label(cr, x + 8, y + 8, tr("Przed"))
        return False

    @staticmethod
    def _paint(cr, pb, x, y, s):
        cr.save()
        cr.translate(x, y)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    @staticmethod
    def _label(cr, x, y, text, right=False):
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        ext = cr.text_extents(text)
        if right:
            x -= ext.width + 8
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.rectangle(x, y, ext.width + 8, ext.height + 8)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x + 4 - ext.x_bearing, y + 4 - ext.y_bearing)
        cr.show_text(text)

    def _on_area_press(self, area, ev):
        if ev.button != 1:
            return False
        x, y, dw, dh, s = self._image_rect()
        if self._mode() == "split" and abs(ev.x - (x + dw * self.split)) <= SPLIT_GRAB:
            self._drag_split = True
        else:
            self._hold_before = True
        area.queue_draw()
        return True

    def _on_area_motion(self, area, ev):
        if self._drag_split:
            x, y, dw, dh, s = self._image_rect()
            self.split = min(1.0, max(0.0, (ev.x - x) / max(1.0, dw)))
            area.queue_draw()
        return True

    def _on_area_release(self, area, ev):
        self._drag_split = self._hold_before = False
        area.queue_draw()
        return True

    # --- nakładanie -----------------------------------------------------------------------

    def _output(self):
        return "in-place" if self.out_inplace.get_active() else "new-layer"

    def _on_cancel_apply(self, *_):
        self._cancel = True

    def _progress(self, f):
        self.progress.set_fraction(min(1.0, max(0.0, f)))
        self.progress.set_text("%d %%" % round(f * 100))
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        return not self._cancel

    def _set_busy(self, busy):
        self._busy = busy
        self._cancel = False
        self.paned.set_sensitive(not busy)
        self.apply_button.set_sensitive(not busy)
        if busy:
            self.progress.set_fraction(0.0)
            self.progress_box.show_all()
        else:
            self.progress_box.hide()

    def apply(self):
        """Nakłada look na warstwy. True = gotowe (okno do zamknięcia)."""
        import zk_gimp
        from gi.repository import Gimp
        if self.look.is_neutral():
            _message(self.dialog, tr("Ustawienia nie zmieniają obrazu"),
                     tr("Włącz krzywe, czerń-biel, duotone albo toning (albo zwiększ siłę "
                        "ogólną) i spróbuj ponownie."))
            return False
        output = self._output()
        self.settings["output"] = output
        self._set_busy(True)
        try:
            zk_gimp.apply_look(self.image, self.layers, self.look, output, self._progress)
        except zk_gimp.Cancelled:
            self.status.set_text(tr("Przerwano – obraz bez zmian."))
            return False
        except zk_gimp.PluginError as e:
            _message(self.dialog, tr("Nie udało się nałożyć efektu"), str(e),
                     Gtk.MessageType.ERROR)
            return False
        finally:
            self._set_busy(False)
            Gimp.displays_flush()
        if self.config is not None:
            # Wartości dla „Filtry → Powtórz” (wywołanie bez okna).
            self.config.set_property("look", zk_core.look_to_text(self.look))
            self.config.set_property("look-file", None)
            self.config.set_property("output", output)
        return True

    def run(self):
        result = False
        while True:
            resp = self.dialog.run()
            if resp == RESP_APPLY:
                if self.apply():
                    result = True
                    break
                continue
            break
        self.close()
        return result

    def close(self):
        if self._update_job is not None:
            GLib.source_remove(self._update_job)
            self._update_job = None
        if not self.offscreen:
            _save_settings(self.settings)
        self.dialog.destroy()
        if self.offscreen:
            self.offscreen_window.destroy()

    def snapshot(self, path):
        """Zrzut okna (tylko offscreen) do pliku PNG – testy."""
        end = time.perf_counter() + 0.6       # animacje GTK (np. pola wyboru)
        while time.perf_counter() < end:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.02)
        pb = self.offscreen_window.get_pixbuf()
        pb.savev(path, "png", [], [])


# --- ustawienia ---------------------------------------------------------------------------

def _settings_path():
    try:
        import zk_gimp
        return os.path.join(zk_gimp.settings_dir(), "settings.json")
    except Exception:  # noqa – poza GIMP-em (testy)
        return None


def _load_settings():
    path = _settings_path()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _save_settings(settings):
    path = _settings_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


# --- wejście z pliku głównego -----------------------------------------------------------------

def _prepare_image(image):
    import zk_gimp
    from gi.repository import Gimp
    if not zk_gimp.needs_rgb_conversion(image):
        return True
    dlg = Gtk.MessageDialog(modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE,
                            text=tr("Obraz nie jest w trybie RGB"))
    dlg.format_secondary_text(tr("Obraz jest %s. Wtyczka działa na obrazach RGB.\n"
                                 "Skonwertować obraz do RGB? (można cofnąć: Ctrl+Z)")
                              % zk_gimp.base_type_name(image))
    dlg.add_button(tr("_Anuluj"), 0)
    dlg.add_button(tr("_Konwertuj do RGB"), 1)
    resp = dlg.run()
    dlg.destroy()
    if resp != 1:
        return False
    image.convert_rgb()
    Gimp.displays_flush()
    return True


def run_dialog(binary, image, drawables, config):
    """Okno dla obrazu GIMP-a. True = efekt nałożony."""
    gi.require_version("GimpUi", "3.0")
    from gi.repository import GimpUi
    import zk_gimp
    GimpUi.init(binary)
    layers = zk_gimp.target_layers(image, drawables)
    if not _prepare_image(image):
        return False
    look = None
    text = (config.get_property("look") or "").strip()
    if text:
        try:
            look = zk_core.look_from_text(text)
        except zk_core.LookError:
            look = None
    win = ZkWindow(ImageSource(image, layers[0]), look, image, layers, config)
    return win.run()
