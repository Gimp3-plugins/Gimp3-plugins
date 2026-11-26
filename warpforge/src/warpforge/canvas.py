# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK 3 preview canvas: shows the preview with zoom and pan and hosts an editing tool.

GIMP 3 ships GTK 3 (GimpUi-3.0 depends on Gtk-3.0), so this is GTK 3 code.
"Image coordinates" here are preview pixels; tools convert to layer pixels.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
import cairo  # noqa: E402
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from warpforge.state import PixelBuffer  # noqa: E402

log = logging.getLogger(__name__)

ZOOM_MIN = 0.1
ZOOM_MAX = 16.0
ZOOM_STEP = 1.2
CHECK_SIZE = 8


class CanvasTool(Protocol):
    """An editing tool driven by the canvas. Coordinates are preview pixels.

    ``tolerance`` is a hit radius in preview pixels that corresponds to a fixed
    distance on screen, whatever the zoom.
    """

    def press(self, x: float, y: float, tolerance: float, extend: bool = False) -> bool: ...
    def drag(self, x: float, y: float) -> None: ...
    def release(self) -> None: ...
    def hover(self, x: float, y: float, tolerance: float) -> bool: ...
    def paint(self, cr: Any, screen_px: float) -> None: ...


HIT_RADIUS_PX = 10.0


def pixbuf_from_pixels(pixels: PixelBuffer) -> Any:
    """Wrap RGBA u8 bytes in a GdkPixbuf (conversion to cairo happens in C)."""
    if pixels.dtype != "u8":
        raise ValueError("the canvas shows 8-bit previews only")
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(pixels.data), GdkPixbuf.Colorspace.RGB, True, 8,
        pixels.width, pixels.height, pixels.rowstride,
    )


class PreviewCanvas(Gtk.DrawingArea):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(520, 380)
        self.set_can_focus(True)
        self.add_events(
            Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self._original: Any = None
        self._result: Any = None
        self._image_size = (1, 1)
        self._zoom = 1.0  # relative to "fit in window"
        self._pan = (0.0, 0.0)  # offset from the centred position, screen px
        self._pan_start: tuple[float, float, float, float] | None = None
        self._tool_dragging = False
        self.space_pan = False  # set by the dialog while Space is held
        self.show_original = False
        self.show_overlay = True
        self.tool: CanvasTool | None = None
        self.on_double_click: Callable[[float, float, float, float, float], None] | None = None
        """Called as (image_x, image_y, tolerance, widget_x, widget_y)."""
        self._checker = self._make_checker()

        self.connect("draw", self._on_draw)
        self.connect("scroll-event", self._on_scroll)
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event", self._on_motion)

    # -- public API -------------------------------------------------------

    def set_original(self, pixels: PixelBuffer) -> None:
        self._original = pixbuf_from_pixels(pixels)
        self._image_size = (pixels.width, pixels.height)
        self.queue_draw()

    def set_result(self, pixels: PixelBuffer | None) -> None:
        """The warped preview; ``None`` shows the original."""
        self._result = None if pixels is None else pixbuf_from_pixels(pixels)
        self.queue_draw()

    def reset_view(self) -> None:
        self._zoom, self._pan = 1.0, (0.0, 0.0)
        self.queue_draw()

    @property
    def view_scale(self) -> float:
        """Screen pixels per preview pixel."""
        return self._transform()[2]

    def view_to_image(self, x: float, y: float) -> tuple[float, float]:
        ox, oy, s = self._transform()
        return (x - ox) / s, (y - oy) / s

    # -- geometry ---------------------------------------------------------

    def _fit_scale(self) -> float:
        w, h = self._image_size
        aw, ah = max(1, self.get_allocated_width()), max(1, self.get_allocated_height())
        return min(aw / w, ah / h) * 0.95

    def _transform(self) -> tuple[float, float, float]:
        """Return (origin_x, origin_y, scale) mapping image px to widget px."""
        s = self._fit_scale() * self._zoom
        w, h = self._image_size
        ox = (self.get_allocated_width() - w * s) / 2 + self._pan[0]
        oy = (self.get_allocated_height() - h * s) / 2 + self._pan[1]
        return ox, oy, s

    # -- drawing ----------------------------------------------------------

    @staticmethod
    def _make_checker() -> Any:
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, CHECK_SIZE * 2, CHECK_SIZE * 2)
        cr = cairo.Context(surface)
        cr.set_source_rgb(0.6, 0.6, 0.6)
        cr.paint()
        cr.set_source_rgb(0.8, 0.8, 0.8)
        cr.rectangle(0, 0, CHECK_SIZE, CHECK_SIZE)
        cr.rectangle(CHECK_SIZE, CHECK_SIZE, CHECK_SIZE, CHECK_SIZE)
        cr.fill()
        pattern = cairo.SurfacePattern(surface)
        pattern.set_extend(cairo.EXTEND_REPEAT)
        return pattern

    def _on_draw(self, _widget: Any, cr: Any) -> bool:
        cr.set_source_rgb(0.18, 0.18, 0.18)
        cr.paint()
        pixbuf = self._original if self.show_original or self._result is None else self._result
        if pixbuf is None:
            return False
        ox, oy, s = self._transform()
        w, h = self._image_size

        cr.save()
        cr.rectangle(ox, oy, w * s, h * s)
        cr.set_source(self._checker)
        cr.fill()
        cr.translate(ox, oy)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        if s >= 2.0:
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        if self.tool is not None and self.show_overlay and not self.show_original:
            cr.save()
            self.tool.paint(cr, 1.0 / s)
            cr.restore()
        cr.restore()
        return False

    # -- interaction ------------------------------------------------------

    def _on_scroll(self, _widget: Any, event: Any) -> bool:
        if event.direction == Gdk.ScrollDirection.UP:
            factor = ZOOM_STEP
        elif event.direction == Gdk.ScrollDirection.DOWN:
            factor = 1 / ZOOM_STEP
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _ok, _dx, dy = event.get_scroll_deltas()
            if dy == 0:
                return False
            factor = ZOOM_STEP ** (-dy)
        else:
            return False
        self._zoom_at(event.x, event.y, factor)
        return True

    def _zoom_at(self, x: float, y: float, factor: float) -> None:
        """Zoom keeping the image point under (x, y) fixed on screen."""
        ix, iy = self.view_to_image(x, y)
        self._zoom = min(ZOOM_MAX, max(ZOOM_MIN, self._zoom * factor))
        ox, oy, s = self._transform()
        self._pan = (self._pan[0] + x - (ox + ix * s), self._pan[1] + y - (oy + iy * s))
        self.queue_draw()

    def _tool_active(self) -> bool:
        return self.tool is not None and self.show_overlay and not self.show_original

    def _on_press(self, _widget: Any, event: Any) -> bool:
        self.grab_focus()
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            if event.button == 1 and self._tool_active() and self.on_double_click is not None:
                if self._tool_dragging and self.tool is not None:
                    # A popup may take the button release; end the drag now.
                    self._tool_dragging = False
                    self.tool.release()
                ix, iy = self.view_to_image(event.x, event.y)
                self.on_double_click(ix, iy, HIT_RADIUS_PX / self.view_scale, event.x, event.y)
                return True
            return False
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False  # ignore triple-click events
        if event.button == 2 or (event.button == 1 and self.space_pan):
            self._pan_start = (event.x, event.y, self._pan[0], self._pan[1])
            return True
        if event.button == 1 and self._tool_active():
            assert self.tool is not None
            ix, iy = self.view_to_image(event.x, event.y)
            extend = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
            if self.tool.press(ix, iy, HIT_RADIUS_PX / self.view_scale, extend):
                self._tool_dragging = True
                self.queue_draw()
                return True
        return False

    def _on_release(self, _widget: Any, event: Any) -> bool:
        if self._pan_start is not None:
            self._pan_start = None
            return True
        if self._tool_dragging and self.tool is not None:
            self._tool_dragging = False
            self.tool.release()
            self.queue_draw()
            return True
        return False

    def _on_motion(self, _widget: Any, event: Any) -> bool:
        if self._pan_start is not None:
            sx, sy, px, py = self._pan_start
            self._pan = (px + event.x - sx, py + event.y - sy)
            self.queue_draw()
            return True
        ix, iy = self.view_to_image(event.x, event.y)
        if self._tool_dragging and self.tool is not None:
            self.tool.drag(ix, iy)
            self.queue_draw()
            return True
        if self._tool_active():
            assert self.tool is not None
            if self.tool.hover(ix, iy, HIT_RADIUS_PX / self.view_scale):
                self.queue_draw()
        return False
