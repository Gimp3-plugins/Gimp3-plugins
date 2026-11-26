# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive editing tools (GTK-free logic; painting takes a cairo context)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from typing import Any

from warpforge.geometry import Point
from warpforge.mesh import Mesh
from warpforge.puppet import Pin, PuppetRig
from warpforge.state import WarpSession

HANDLE_RADIUS_PX = 4.0
PIN_RADIUS_PX = 6.0


class MeshTool:
    """Drag mesh vertices. Coordinates passed in are preview pixels.

    ``on_change`` fires on every motion (re-render the preview);
    ``on_gesture`` fires once per finished drag with the mesh as it was
    before the drag (record it for undo).
    """

    def __init__(self, session: WarpSession, on_change: Callable[[], None],
                 on_gesture: Callable[[Mesh], None]) -> None:
        self.session = session
        self.on_change = on_change
        self.on_gesture = on_gesture
        self.active: int | None = None
        self.hovered: int | None = None
        self._before: Mesh | None = None
        self._moved = False

    def _mesh(self) -> Mesh:
        return self.session.ensure_mesh()

    def _layer_tolerance(self, tolerance: float) -> float:
        fx, fy = self.session.preview_factors
        return tolerance / min(fx, fy)

    def press(self, x: float, y: float, tolerance: float, extend: bool = False) -> bool:
        mesh = self._mesh()
        index = mesh.nearest_vertex(self.session.to_layer(x, y), self._layer_tolerance(tolerance))
        if index is None:
            return False
        self.active = index
        self._before = mesh.copy()
        self._moved = False
        return True

    def drag(self, x: float, y: float) -> None:
        if self.active is None:
            return
        self._mesh().move_vertex(self.active, self.session.to_layer(x, y),
                                 self.session.settings.clamp_to_bounds)
        self._moved = True
        self.on_change()

    def release(self) -> None:
        if self.active is not None and self._moved and self._before is not None:
            self.on_gesture(self._before)
        self.active = None
        self._before = None

    def hover(self, x: float, y: float, tolerance: float) -> bool:
        index = self._mesh().nearest_vertex(self.session.to_layer(x, y),
                                            self._layer_tolerance(tolerance))
        changed = index != self.hovered
        self.hovered = index
        return changed

    def preview_points(self) -> list[Point]:
        return [self.session.to_preview(x, y) for x, y in self._mesh().vertices]

    def paint(self, cr: Any, screen_px: float) -> None:
        """Draw the mesh. ``screen_px`` is one screen pixel in preview pixels."""
        mesh = self._mesh()
        pts = self.preview_points()
        # dark halo first, then light line: visible on any image
        for width, rgba in ((3 * screen_px, (0, 0, 0, 0.45)), (screen_px, (1, 1, 1, 0.9))):
            cr.set_line_width(width)
            cr.set_source_rgba(*rgba)
            for r in range(mesh.rows + 1):
                for c in range(mesh.columns + 1):
                    x, y = pts[mesh.index(r, c)]
                    if c < mesh.columns:
                        cr.move_to(x, y)
                        cr.line_to(*pts[mesh.index(r, c + 1)])
                    if r < mesh.rows:
                        cr.move_to(x, y)
                        cr.line_to(*pts[mesh.index(r + 1, c)])
            cr.stroke()
        radius = HANDLE_RADIUS_PX * screen_px
        for i, (x, y) in enumerate(pts):
            emphasised = i in (self.active, self.hovered)
            size = radius * (1.6 if emphasised else 1.0)
            cr.rectangle(x - size, y - size, 2 * size, 2 * size)
            fill = (1.0, 0.55, 0.0, 1.0) if emphasised else (1.0, 1.0, 1.0, 1.0)
            cr.set_source_rgba(*fill)
            cr.fill_preserve()
            cr.set_line_width(screen_px)
            cr.set_source_rgba(0, 0, 0, 0.8)
            cr.stroke()


class PinTool:
    """Add, select and drag puppet pins. Coordinates passed in are preview pixels.

    * click on empty canvas: add a pin there (when ``add_mode``), else deselect;
    * click on a pin: select it; Shift+click toggles it in the selection;
    * drag a pin: move it (and its rigid group).

    ``on_gesture`` receives the rig as it was before each finished gesture
    (adding a pin and dragging it in one go is one gesture);
    ``on_selection`` fires when the selection changes.
    """

    def __init__(self, session: WarpSession, on_change: Callable[[], None],
                 on_gesture: Callable[[PuppetRig], None],
                 on_selection: Callable[[], None]) -> None:
        self.session = session
        self.on_change = on_change
        self.on_gesture = on_gesture
        self.on_selection = on_selection
        self.add_mode = True
        self.selected: set[str] = set()
        self.hovered: str | None = None
        self.active: str | None = None
        self._before: PuppetRig | None = None
        self._changed = False
        self._grab = (0.0, 0.0)  # pin target minus pointer, in layer px

    def _rig(self) -> PuppetRig:
        return self.session.ensure_rig()

    def _layer_tolerance(self, tolerance: float) -> float:
        fx, fy = self.session.preview_factors
        return tolerance / min(fx, fy)

    def pin_at(self, x: float, y: float, tolerance: float) -> Pin | None:
        return self._rig().nearest_pin(self.session.to_layer(x, y),
                                       self._layer_tolerance(tolerance))

    def selected_pins(self) -> list[Pin]:
        return [p for p in self._rig().pins if p.id in self.selected]

    def set_selection(self, ids: set[str]) -> None:
        if ids != self.selected:
            self.selected = set(ids)
            self.on_selection()

    def prune_selection(self) -> None:
        """Forget selected pins that no longer exist (after undo, removal...)."""
        existing = {p.id for p in self._rig().pins}
        self.set_selection(self.selected & existing)
        if self.hovered not in existing:
            self.hovered = None

    def press(self, x: float, y: float, tolerance: float, extend: bool = False) -> bool:
        rig = self._rig()
        point = self.session.to_layer(x, y)
        pin = self.pin_at(x, y, tolerance)
        if pin is not None:
            if extend:
                self.set_selection(self.selected ^ {pin.id})
                return True
            if pin.id not in self.selected:
                self.set_selection({pin.id})
            self.active = pin.id
            self._before = rig.copy()
            self._changed = False
            self._grab = (pin.target[0] - point[0], pin.target[1] - point[1])
            return True
        if extend:
            return False
        if not self.add_mode:
            self.set_selection(set())
            return True
        self._before = rig.copy()
        pin = rig.add_pin(point, self.session.settings.pin_radius,
                          self.session.settings.stiffness)
        self.active = pin.id
        self._changed = True
        self._grab = (0.0, 0.0)
        self.set_selection({pin.id})
        self.on_change()
        return True

    def drag(self, x: float, y: float) -> None:
        if self.active is None:
            return
        px, py = self.session.to_layer(x, y)
        self._rig().move_pin(self.active, (px + self._grab[0], py + self._grab[1]),
                             self.session.settings.clamp_to_bounds)
        self._changed = True
        self.on_change()

    def release(self) -> None:
        if self.active is not None and self._changed and self._before is not None:
            self.on_gesture(self._before)
        self.active = None
        self._before = None
        self._changed = False

    def hover(self, x: float, y: float, tolerance: float) -> bool:
        pin = self.pin_at(x, y, tolerance)
        new = None if pin is None else pin.id
        changed = new != self.hovered
        self.hovered = new
        return changed

    def paint(self, cr: Any, screen_px: float) -> None:
        """Draw pins, their influence and rigid links. ``screen_px``: see MeshTool."""
        rig = self._rig()
        to_preview = self.session.to_preview
        fx, fy = self.session.preview_factors
        radius_scale = math.sqrt(fx * fy)

        # influence of the selected pins
        cr.set_dash([4 * screen_px, 4 * screen_px])
        for p in rig.pins:
            if p.id not in self.selected:
                continue
            x, y = to_preview(*p.target)
            cr.arc(x, y, p.radius * radius_scale, 0, 2 * math.pi)
            for width, rgba in ((3 * screen_px, (0, 0, 0, 0.4)), (screen_px, (1, 0.8, 0.2, 0.9))):
                cr.set_line_width(width)
                cr.set_source_rgba(*rgba)
                cr.stroke_preserve()
            cr.new_path()
        cr.set_dash([])

        # where moved pins came from
        cr.set_line_width(screen_px)
        for p in rig.pins:
            if not p.is_moved:
                continue
            sx, sy = to_preview(*p.source)
            tx, ty = to_preview(*p.target)
            cr.set_source_rgba(1, 1, 1, 0.6)
            cr.move_to(sx, sy)
            cr.line_to(tx, ty)
            cr.stroke()
            cr.arc(sx, sy, 2 * screen_px, 0, 2 * math.pi)
            cr.fill()

        # rigid links
        groups: dict[str, list[Pin]] = {}
        for p in rig.pins:
            if p.group is not None:
                groups.setdefault(p.group, []).append(p)
        for members in groups.values():
            for a, b in itertools.pairwise(members):
                for link_width, link_rgba in ((5 * screen_px, (0.0, 0.0, 0.0, 0.5)),
                                              (2.5 * screen_px, (0.3, 0.85, 1.0, 0.95))):
                    cr.set_line_width(link_width)
                    cr.set_source_rgba(*link_rgba)
                    cr.move_to(*to_preview(*a.target))
                    cr.line_to(*to_preview(*b.target))
                    cr.stroke()

        # the pins
        size = PIN_RADIUS_PX * screen_px
        for p in rig.pins:
            x, y = to_preview(*p.target)
            emphasised = p.id in (self.active, self.hovered)
            r = size * (1.3 if emphasised else 1.0)
            cr.arc(x, y, r, 0, 2 * math.pi)
            if p.id in self.selected:
                cr.set_source_rgba(1.0, 0.75, 0.0, 1.0)
            else:
                cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.fill_preserve()
            cr.set_line_width(1.5 * screen_px)
            cr.set_source_rgba(0, 0, 0, 0.85)
            cr.stroke()
            cr.arc(x, y, r * 0.35, 0, 2 * math.pi)
            cr.fill()
