# -*- coding: utf-8 -*-
"""
Operacje na obrazie GIMP-a: odczyt pikseli do podglądu, maska zaznaczenia
i nałożenie looku na warstwę (z cofaniem, zaznaczeniem i postępem).

Piksele czytamy i zapisujemy w formacie babl „R'G'B'A float” – wartości
perceptualne (gamma sRGB), niezależnie od precyzji obrazu (8/16/32 bit,
liniowa czy perceptualna). Zapis na warstwie idzie przez bufor cienia
(shadow) i merge_shadow(): GIMP sam przelicza wynik na precyzję obrazu,
uwzględnia miękkie zaznaczenie i zapisuje krok cofania.
"""

import math
import os

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl  # noqa: E402

import zk_core  # noqa: E402
from zk_i18n import tr  # noqa: E402

FORMAT = "R'G'B'A float"
STRIP_PIXELS = 1 << 21          # ok. 2 Mpx na pasek (32 MB)
LAYER_NAME = "Zetmar Kolor"


class PluginError(Exception):
    """Błąd z komunikatem dla użytkownika."""


class Cancelled(Exception):
    """Użytkownik przerwał nakładanie."""


def settings_dir():
    return os.path.join(Gimp.directory(), "zetmar-kolor")


def needs_rgb_conversion(image):
    return image.get_base_type() != Gimp.ImageBaseType.RGB


def base_type_name(image):
    return {Gimp.ImageBaseType.GRAY: tr("w skali szarości"),
            Gimp.ImageBaseType.INDEXED: tr("indeksowany")}.get(image.get_base_type(), "")


def target_layers(image, drawables):
    """Warstwy z pikselami (bez grup, masek i kanałów)."""
    layers, skipped = [], []
    for d in drawables or []:
        if d.is_layer() and not d.is_group():
            layers.append(d)
        else:
            skipped.append(d.get_name())
    if not layers:
        if skipped:
            raise PluginError(
                tr("Wybrany element (%s) nie jest zwykłą warstwą – efekt można nałożyć "
                   "tylko na warstwę z pikselami, nie na grupę, maskę ani kanał.")
                % ", ".join(skipped))
        raise PluginError(tr("Nie wybrano żadnej warstwy – zaznacz warstwę w oknie Warstwy."))
    return layers


# --- odczyt ------------------------------------------------------------------------

def _get(drawable, x, y, w, h, scale=1.0, fmt=FORMAT):
    rect = Gegl.Rectangle.new(x, y, w, h)
    return drawable.get_buffer().get(rect, scale, fmt, Gegl.AbyssPolicy.CLAMP)


def selection_mask(image, layer, x, y, w, h, scale=1.0):
    """Maska zaznaczenia (Y float 0–1) dla prostokąta warstwy albo None (brak zaznaczenia)."""
    if Gimp.Selection.is_empty(image):
        return None
    _ok, ox, oy = layer.get_offsets()
    rect = Gegl.Rectangle.new(int(round(ox * scale)) + x, int(round(oy * scale)) + y, w, h)
    return image.get_selection().get_buffer().get(rect, scale, "Y float",
                                                  Gegl.AbyssPolicy.NONE)


def read_scaled(image, layer, max_side):
    """Zmniejszona kopia warstwy do podglądu: (piksele, maska, szer., wys.)."""
    W, H = layer.get_width(), layer.get_height()
    scale = min(1.0, float(max_side) / max(W, H))
    w = max(1, int(math.floor(W * scale)))
    h = max(1, int(math.floor(H * scale)))
    return _get(layer, 0, 0, w, h, scale), selection_mask(image, layer, 0, 0, w, h, scale), w, h


# --- nakładanie --------------------------------------------------------------------

def apply_to_layer(image, layer, pipe, output="new-layer", progress=None):
    """
    Nakłada look (zk_core.Pipeline) na warstwę. output: "new-layer" (kopia nad
    warstwą) albo "in-place". progress(ułamek) -> False przerywa (Cancelled).
    Wywołujący otwiera grupę cofania. Zwraca warstwę z wynikiem.
    """
    ok, x, y, w, h = layer.mask_intersect()
    if not ok or w <= 0 or h <= 0:
        raise PluginError(tr("Zaznaczenie nie obejmuje warstwy „%s” – nie ma czego zmieniać.")
                          % layer.get_name())
    if output != "new-layer":
        try:
            shadow = layer.get_shadow_buffer()
            for rect, data in _strips(layer, x, y, w, h, progress):
                shadow.set(rect, FORMAT, zk_core.apply_rgba(pipe, data))
            shadow.flush()
        except BaseException:
            layer.free_shadow()
            raise
        layer.merge_shadow(True)
        layer.update(x, y, w, h)
        return layer

    # Nowa warstwa: liczymy na kopii, która trafia do obrazu dopiero na końcu –
    # przerwanie nie zostawia śladu ani w obrazie, ani w historii cofania.
    target = layer.copy()
    try:
        target.set_name(LAYER_NAME)
        target.set_mode(Gimp.LayerMode.NORMAL)
        target.set_opacity(100.0)
        buf = target.get_buffer()
        for rect, data in _strips(layer, x, y, w, h, progress):
            mask = selection_mask(image, layer, rect.x, rect.y, rect.width, rect.height)
            buf.set(rect, FORMAT, zk_core.apply_rgba(pipe, data, mask))
        buf.flush()
    except BaseException:
        target.delete()
        raise
    image.insert_layer(target, layer.get_parent(), image.get_item_position(layer))
    return target


def _strips(source, x, y, w, h, progress):
    src = source.get_buffer()
    rows = max(1, STRIP_PIXELS // w)
    for y0 in range(y, y + h, rows):
        if progress is not None and progress((y0 - y) / float(h)) is False:
            raise Cancelled()
        rect = Gegl.Rectangle.new(x, y0, w, min(rows, y + h - y0))
        yield rect, src.get(rect, 1.0, FORMAT, Gegl.AbyssPolicy.NONE)
    if progress is not None and progress(1.0) is False:
        raise Cancelled()


def apply_look(image, layers, look, output, progress=None):
    """Nakłada look na wszystkie warstwy jako jeden krok cofania."""
    pipe = zk_core.Pipeline(look)
    image.undo_group_start()
    try:
        for k, layer in enumerate(layers):
            def step(f, k=k):
                return progress((k + f) / len(layers)) if progress else True
            apply_to_layer(image, layer, pipe, output, step)
    finally:
        image.undo_group_end()
