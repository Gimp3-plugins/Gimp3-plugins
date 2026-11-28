"""GIMP 3 adapter. SPDX-License-Identifier: MIT."""
from array import array
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl
from zm_core import Engine, dumps

FORMAT = "R'G'B'A float"


def target(image, drawables):
    if image.get_base_type() != Gimp.ImageBaseType.RGB:
        raise ValueError('Zmień tryb obrazu na RGB: Obraz → Tryb → RGB.')
    if len(drawables) != 1 or not drawables[0].is_layer() or drawables[0].is_group():
        raise ValueError('Zaznacz dokładnie jedną warstwę ze zdjęciem (nie grupę, maskę ani kanał).')
    return drawables[0]


def selection_bytes(image, layer, x, y, w, h, scale=1.):
    if Gimp.Selection.is_empty(image):
        return None
    _, ox, oy = layer.get_offsets()
    rect = Gegl.Rectangle.new(x + round(ox*scale), y + round(oy*scale), w, h)
    return image.get_selection().get_buffer().get(rect, scale, 'Y float', Gegl.AbyssPolicy.NONE)


def preview(image, layer, size=640):
    scale = min(1., size/max(layer.get_width(), layer.get_height()))
    w, h = max(1, int(layer.get_width()*scale)), max(1, int(layer.get_height()*scale))
    rgba = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), scale, FORMAT, Gegl.AbyssPolicy.NONE)
    return rgba, selection_bytes(image, layer, 0, 0, w, h, scale), w, h


def apply(image, layer, settings, output, name='Zetmar Maski'):
    if output not in ('new-layer', 'layer-mask', 'channel', 'selection'):
        raise ValueError('Nieznany rodzaj wyniku.')
    if output == 'layer-mask' and layer.get_mask() is not None:
        raise ValueError('Warstwa ma już maskę. Wybierz nową warstwę lub kanał; istniejąca maska nie zostanie zastąpiona.')
    w, h = layer.get_width(), layer.get_height()
    engine = Engine(settings)
    # Compute outside the image before committing a single undo group.
    scratch = Gegl.Buffer.new('Y float', 0, 0, w, h)
    source = layer.get_buffer()
    rows = max(1, 65536 // w)
    Gimp.progress_init('Zetmar Maski — obliczanie maski…')
    try:
        for y in range(0, h, rows):
            rect = Gegl.Rectangle.new(0, y, w, min(rows, h-y))
            rgba = source.get(rect, 1., FORMAT, Gegl.AbyssPolicy.NONE)
            sel = selection_bytes(image, layer, 0, y, w, rect.height) if settings.selection else None
            scratch.set(rect, 'Y float', engine.mask(rgba, sel))
            Gimp.progress_update((y+rect.height)/h * 0.9)
        scratch.flush()
        image.undo_group_start()
        added_layer = added_channel = added_mask = None
        try:
            if output in ('channel', 'selection'):
                dest = Gimp.Channel.new(image, name, image.get_width(), image.get_height(), 50., Gegl.Color.new('red'))
                image.insert_channel(dest, None, 0)
                added_channel = dest
                dest.set_visible(False)
                # Channel starts black. Copy clipped layer region at its image offset.
                _, ox, oy = layer.get_offsets()
                dx, dy = max(0, ox), max(0, oy)
                cw = min(w+ox, image.get_width())-dx
                ch = min(h+oy, image.get_height())-dy
                if cw > 0 and ch > 0:
                    buf = dest.get_buffer()
                    for y in range(0, ch, rows):
                        rh = min(rows, ch-y)
                        data = scratch.get(Gegl.Rectangle.new(dx-ox, dy-oy+y, cw, rh), 1., 'Y float', Gegl.AbyssPolicy.NONE)
                        buf.set(Gegl.Rectangle.new(dx, dy+y, cw, rh), 'Y float', data)
                    buf.flush()
            else:
                dest_layer = layer
                if output == 'new-layer':
                    dest_layer = layer.copy()
                    dest_layer.set_name(name)
                    image.insert_layer(dest_layer, layer.get_parent(), image.get_item_position(layer))
                    added_layer = dest_layer
                dest = dest_layer.create_mask(Gimp.AddMaskType.WHITE)
                # A copied original mask is multiplied with the new mask.
                old = dest_layer.get_mask()
                buf = dest.get_buffer()
                for y in range(0, h, rows):
                    rect = Gegl.Rectangle.new(0, y, w, min(rows, h-y))
                    data = scratch.get(rect, 1., 'Y float', Gegl.AbyssPolicy.NONE)
                    if old is not None:
                        a, b = array('f'), array('f')
                        a.frombytes(bytes(data))
                        b.frombytes(bytes(old.get_buffer().get(rect, 1., 'Y float', Gegl.AbyssPolicy.NONE)))
                        data = array('f', (x*z for x, z in zip(a, b))).tobytes()
                    buf.set(rect, 'Y float', data)
                buf.flush()
                if old is not None:
                    dest_layer.remove_mask(Gimp.MaskApplyMode.DISCARD)
                dest_layer.add_mask(dest)
                added_mask = dest if output == 'layer-mask' else None
                dest_layer.set_edit_mask(False)
                image.set_selected_layers([dest_layer])
            dest.update(0, 0, dest.get_width(), dest.get_height())
            dest.attach_parasite(Gimp.Parasite.new('zetmar-maski-settings', Gimp.PARASITE_PERSISTENT, dumps(settings).encode()))
            if output == 'selection':
                image.select_item(Gimp.ChannelOps.REPLACE, dest)
                image.remove_channel(dest)
                added_channel = None
            Gimp.progress_update(1.)
        except Exception:
            if added_layer is not None:
                image.remove_layer(added_layer)
            if added_channel is not None:
                image.remove_channel(added_channel)
            if added_mask is not None:
                layer.remove_mask(Gimp.MaskApplyMode.DISCARD)
            raise
        finally:
            image.undo_group_end()
    finally:
        Gimp.progress_end()
    Gimp.displays_flush()
