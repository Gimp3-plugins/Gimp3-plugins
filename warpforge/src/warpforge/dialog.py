# SPDX-License-Identifier: GPL-3.0-or-later
"""The WarpForge dialog (GTK 3).

Puppet Warp (pins) and Mesh Warp editing with a live preview rendered off the
main thread, in-dialog undo/redo per gesture (kept separately for each mode),
and saving/loading presets as JSON files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from warpforge import presets  # noqa: E402
from warpforge.canvas import PreviewCanvas  # noqa: E402
from warpforge.editing import MeshTool, PinTool  # noqa: E402
from warpforge.errors import InvalidPresetError, _  # noqa: E402
from warpforge.history import EditHistory  # noqa: E402
from warpforge.mesh import Mesh  # noqa: E402
from warpforge.preview import PreviewWorker  # noqa: E402
from warpforge.puppet import (  # noqa: E402
    MAX_PIN_WEIGHT,
    MIN_PIN_RADIUS,
    MIN_PIN_WEIGHT,
    PuppetRig,
)
from warpforge.render import (  # noqa: E402
    WarpBackend,
    render_mesh_preview,
    render_puppet_preview,
)
from warpforge.state import (  # noqa: E402
    MAX_MESH_DIVISIONS,
    MESH_PRESETS,
    MIN_MESH_DIVISIONS,
    PixelBuffer,
    WarpMode,
    WarpSession,
)

log = logging.getLogger(__name__)

RESPONSE_SAVE_PRESET = 1
RESPONSE_LOAD_PRESET = 2
PARAM_GESTURE_MS = 700
"""Slider changes within this time form one undo step."""

PreviewJob = tuple[Mesh | PuppetRig, float]


class WarpDialog:
    def __init__(self, session: WarpSession, backend: WarpBackend, editing: bool = False,
                 note: str = "") -> None:
        """``editing``: the session was loaded from an existing WarpForge effect.

        ``note`` is shown under the layer description (e.g. why a stored effect
        could not be loaded).
        """
        self.session = session
        self.editing = editing
        self._message = ""
        self.backend = backend
        self.mesh_history: EditHistory[Mesh] = EditHistory()
        self.pin_history: EditHistory[PuppetRig] = EditHistory()
        self._updating = False
        self._last_render_ms = 0.0
        self._param_snapshot: PuppetRig | None = None
        self._param_timer: int | None = None
        self._popover_pin: str | None = None
        self._popover_snapshot: PuppetRig | None = None
        self.worker: PreviewWorker[PreviewJob, PixelBuffer] = PreviewWorker(
            self._render_preview, self._on_preview_ready, GLib.idle_add)

        title = _("WarpForge – Edit Effect") if editing else _("WarpForge")
        self.dialog = Gtk.Dialog(title=title, modal=True)
        self.dialog.set_default_size(940, 800)
        self.dialog.connect("key-press-event", self._on_key_press)
        self.dialog.connect("key-release-event", self._on_key_release)

        self._build_action_area()
        content = self.dialog.get_content_area()
        content.set_spacing(8)
        for side in ("start", "end", "top", "bottom"):
            getattr(content, f"set_margin_{side}")(10)

        content.pack_start(self._build_mode_row(), False, False, 0)

        self.info_label = Gtk.Label(label=session.layer.describe(), xalign=0.0)
        self.info_label.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(self.info_label, False, False, 0)
        if note:
            note_label = Gtk.Label(label=note, xalign=0.0)
            note_label.set_line_wrap(True)
            content.pack_start(note_label, False, False, 0)

        self.canvas = PreviewCanvas()
        self.canvas.on_double_click = self._on_canvas_double_click
        frame = Gtk.Frame()
        frame.add(self.canvas)
        content.pack_start(frame, True, True, 0)

        self.status_label = Gtk.Label(xalign=0.0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(self.status_label, False, False, 0)

        content.pack_start(self._build_parameters(), False, False, 0)
        content.pack_start(self._build_tool_row(), False, False, 0)

        self.mesh_tool = MeshTool(session, self._request_preview, self._record_mesh_gesture)
        self.pin_tool = PinTool(session, self._request_preview, self._record_pin_gesture,
                                self._on_pin_selection)
        self._build_pin_popover()
        if session.preview is not None:
            self.canvas.set_original(session.preview)
        self._sync_mode()

    # -- construction -----------------------------------------------------

    def _build_action_area(self) -> None:
        self.save_preset_button = self.dialog.add_button(_("Save preset…"),
                                                         RESPONSE_SAVE_PRESET)
        self.load_preset_button = self.dialog.add_button(_("Load preset…"),
                                                         RESPONSE_LOAD_PRESET)
        self.save_preset_button.set_tooltip_text(
            _("Save the pins or the mesh of the current mode as a JSON file."))
        self.load_preset_button.set_tooltip_text(
            _("Load pins or a mesh from a WarpForge JSON preset."))
        self.dialog.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.apply_button = self.dialog.add_button(_("_Apply"), Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)

    def _build_mode_row(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label=_("Mode:")), False, False, 0)
        self.puppet_button = Gtk.RadioButton.new_with_mnemonic(None, _("_Puppet Warp"))
        self.mesh_button = Gtk.RadioButton.new_with_mnemonic_from_widget(
            self.puppet_button, _("_Mesh Warp"))
        self.mesh_button.set_active(self.session.mode is WarpMode.MESH)
        for button, mode in ((self.puppet_button, WarpMode.PUPPET),
                             (self.mesh_button, WarpMode.MESH)):
            button.set_mode(False)  # render as toggle buttons
            button.connect("toggled", self._on_mode_toggled, mode)
            row.pack_start(button, False, False, 0)
        return row

    def _build_parameters(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        settings = self.session.settings

        grid.attach(Gtk.Label(label=_("Stiffness:"), xalign=1.0), 0, 0, 1, 1)
        self.stiffness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.stiffness.set_value(settings.stiffness * 100)
        self.stiffness.set_hexpand(True)
        self.stiffness.set_tooltip_text(
            _("0%: regions may stretch and shrink. 100%: regions only move and rotate."))
        self.stiffness.connect("format-value", lambda _s, v: f"{v:.0f}%")
        self.stiffness.connect("value-changed", self._on_stiffness)
        grid.attach(self.stiffness, 1, 0, 2, 1)

        grid.attach(Gtk.Label(label=_("Pin radius:"), xalign=1.0), 0, 1, 1, 1)
        upper = max(10, self.session.layer.longest_side)
        self.radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, MIN_PIN_RADIUS,
                                               upper, 1)
        self.radius.set_value(min(settings.pin_radius, upper))
        self.radius.set_tooltip_text(
            _("Reach of new pins and of the selected pins. Beyond it the image stays put."))
        self.radius.connect("format-value", lambda _s, v: f"{v:.0f} px")
        self.radius.connect("value-changed", self._on_radius)
        grid.attach(self.radius, 1, 1, 2, 1)

        grid.attach(Gtk.Label(label=_("Mesh density:"), xalign=1.0), 0, 2, 1, 1)
        density = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.density_buttons: list[Any] = []
        group = None
        for n in MESH_PRESETS:
            button = Gtk.RadioButton.new_with_label_from_widget(group, f"{n}×{n}")
            if group is None:
                group = button
            button.set_mode(False)
            button.connect("toggled", self._on_density_preset, n)
            density.pack_start(button, False, False, 0)
            self.density_buttons.append(button)
        self.custom_density = Gtk.RadioButton.new_with_label_from_widget(group, _("Custom"))
        self.custom_density.set_mode(False)
        density.pack_start(self.custom_density, False, False, 0)
        self.density_spin = Gtk.SpinButton.new_with_range(
            MIN_MESH_DIVISIONS, MAX_MESH_DIVISIONS, 1)
        self.density_spin.set_value(settings.mesh_columns)
        self.density_spin.connect("value-changed", self._on_density_custom)
        density.pack_start(self.density_spin, False, False, 0)
        self.show_overlay = Gtk.CheckButton.new_with_label(_("Show mesh"))
        self.show_overlay.set_active(settings.show_mesh)
        self.show_overlay.connect("toggled", self._on_show_overlay)
        density.pack_start(self.show_overlay, False, False, 12)
        grid.attach(density, 1, 2, 2, 1)
        self._select_density_button(settings.mesh_columns)

        options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.limit_selection = Gtk.CheckButton.new_with_label(_("Limit to selection"))
        self.limit_selection.set_active(settings.limit_to_selection)
        self.limit_selection.set_sensitive(self.session.layer.selection is not None)
        self.limit_selection.connect("toggled", lambda b: setattr(
            self.session.settings, "limit_to_selection", b.get_active()))
        options.pack_start(self.limit_selection, False, False, 0)
        self.clamp = Gtk.CheckButton.new_with_label(_("Clamp to bounds"))
        self.clamp.set_tooltip_text(_("Keep pins and mesh vertices inside the layer."))
        self.clamp.set_active(settings.clamp_to_bounds)
        self.clamp.connect("toggled", lambda b: setattr(
            self.session.settings, "clamp_to_bounds", b.get_active()))
        options.pack_start(self.clamp, False, False, 0)
        self.new_layer = Gtk.CheckButton.new_with_label(_("Output to a new layer"))
        self.new_layer.set_tooltip_text(
            _("Keep the original layer untouched (hidden) and put the result above it."))
        self.new_layer.set_active(settings.output_new_layer)
        if self.editing:
            self.new_layer.set_sensitive(False)
            self.new_layer.set_tooltip_text(
                _("Editing an effect updates its WarpForge layer; the original stays as is."))
        self.new_layer.connect("toggled", lambda b: setattr(
            self.session.settings, "output_new_layer", b.get_active()))
        options.pack_start(self.new_layer, False, False, 0)
        grid.attach(options, 1, 3, 2, 1)
        return grid

    def _build_tool_row(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_pin_button = Gtk.ToggleButton.new_with_label(_("Add pins"))
        self.add_pin_button.set_active(True)
        self.add_pin_button.set_tooltip_text(
            _("When on, clicking the image adds a pin. Off: clicking only selects."))
        self.add_pin_button.connect("toggled", self._on_add_mode)
        self.remove_pin_button = Gtk.Button.new_with_label(_("Remove pin"))
        self.remove_pin_button.set_tooltip_text(_("Remove the selected pins (Delete)."))
        self.remove_pin_button.connect("clicked", lambda _b: self.remove_selected_pins())
        self.link_button = Gtk.Button.new_with_label(_("Link pins"))
        self.link_button.set_tooltip_text(
            _("Link the selected pins into a rigid segment that keeps its length and "
              "angle (Ctrl+L). Shift+click selects several pins."))
        self.link_button.connect("clicked", lambda _b: self.toggle_link())
        for widget in (self.add_pin_button, self.remove_pin_button, self.link_button):
            row.pack_start(widget, False, False, 0)
        self.reset_button = Gtk.Button.new_with_label(_("Reset"))
        self.reset_button.connect("clicked", self._on_reset)
        row.pack_start(self.reset_button, False, False, 0)
        self.original_button = Gtk.ToggleButton.new_with_label(_("Show original"))
        self.original_button.set_tooltip_text(_("Hold Space to peek at the original."))
        self.original_button.connect("toggled", self._on_show_original)
        row.pack_start(self.original_button, False, False, 0)
        self.undo_button = Gtk.Button.new_from_icon_name("edit-undo", Gtk.IconSize.BUTTON)
        self.undo_button.set_tooltip_text(_("Undo (Ctrl+Z)"))
        self.undo_button.connect("clicked", lambda _b: self.undo())
        self.redo_button = Gtk.Button.new_from_icon_name("edit-redo", Gtk.IconSize.BUTTON)
        self.redo_button.set_tooltip_text(_("Redo (Ctrl+Shift+Z)"))
        self.redo_button.connect("clicked", lambda _b: self.redo())
        row.pack_start(self.undo_button, False, False, 0)
        row.pack_start(self.redo_button, False, False, 0)
        fit = Gtk.Button.new_with_label(_("Fit view"))
        fit.connect("clicked", lambda _b: self.canvas.reset_view())
        row.pack_end(fit, False, False, 0)
        return row

    def _build_pin_popover(self) -> None:
        self.popover = Gtk.Popover()
        self.popover.set_relative_to(self.canvas)
        self.popover.connect("closed", self._on_popover_closed)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(grid, f"set_margin_{side}")(8)
        self.popover_title = Gtk.Label(xalign=0.0)
        grid.attach(self.popover_title, 0, 0, 2, 1)
        grid.attach(Gtk.Label(label=_("Radius (px):"), xalign=1.0), 0, 1, 1, 1)
        self.pin_radius_spin = Gtk.SpinButton.new_with_range(
            MIN_PIN_RADIUS, max(10, 2 * self.session.layer.longest_side), 1)
        self.pin_radius_spin.connect("value-changed", self._on_pin_radius_spin)
        grid.attach(self.pin_radius_spin, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label=_("Weight:"), xalign=1.0), 0, 2, 1, 1)
        self.pin_weight_spin = Gtk.SpinButton.new_with_range(MIN_PIN_WEIGHT, MAX_PIN_WEIGHT, 0.1)
        self.pin_weight_spin.set_digits(1)
        self.pin_weight_spin.set_tooltip_text(
            _("How strongly this pin holds the image compared with the other pins."))
        self.pin_weight_spin.connect("value-changed", self._on_pin_weight_spin)
        grid.attach(self.pin_weight_spin, 1, 2, 1, 1)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        restore = Gtk.Button.new_with_label(_("Restore position"))
        restore.connect("clicked", lambda _b: self._popover_action("restore"))
        remove = Gtk.Button.new_with_label(_("Remove"))
        remove.connect("clicked", lambda _b: self._popover_action("remove"))
        self.popover_unlink = Gtk.Button.new_with_label(_("Unlink"))
        self.popover_unlink.connect("clicked", lambda _b: self._popover_action("unlink"))
        for b in (restore, remove, self.popover_unlink):
            buttons.pack_start(b, False, False, 0)
        grid.attach(buttons, 0, 3, 2, 1)
        grid.show_all()
        self.popover.add(grid)

    # -- preview ----------------------------------------------------------

    def _render_preview(self, job: PreviewJob) -> PixelBuffer:
        """Runs on the worker thread."""
        assert self.session.preview is not None
        model, stiffness = job
        if isinstance(model, Mesh):
            return render_mesh_preview(self.backend, self.session.preview, model)
        return render_puppet_preview(self.backend, self.session.preview, model, stiffness)

    def _request_preview(self) -> None:
        if self.session.preview is None:
            return
        if not self.session.has_edits():
            self.canvas.set_result(None)
            self.canvas.queue_draw()
            return
        model: Mesh | PuppetRig = (self.session.ensure_mesh().copy()
                                   if self.session.mode is WarpMode.MESH
                                   else self.session.ensure_rig().copy())
        self.worker.submit((model, self.session.settings.stiffness))

    def _on_preview_ready(self, generation: int, pixels: PixelBuffer | None,
                          error: Exception | None, seconds: float) -> None:
        if error is not None:
            log.error("Preview failed: %s", error)
            self.status_label.set_text(_("Preview failed: {error}").format(error=error))
            return
        if generation != self.worker.latest:
            return  # a newer frame is on its way
        if self.session.has_edits():
            self.canvas.set_result(pixels)
        self._last_render_ms = seconds * 1000
        self._update_status()

    def _update_status(self) -> None:
        preview = self.session.preview
        if preview is None:
            return
        text = _("Preview {w}×{h} px ({pct:.0f}% of layer), {backend} renderer").format(
            w=preview.width, h=preview.height, pct=self.session.preview_factors[0] * 100,
            backend=self.backend.name)
        if self._last_render_ms:
            text += _(", last frame {ms:.0f} ms").format(ms=self._last_render_ms)
        if self._message:
            text = self._message + " · " + text
        if self.session.mode is WarpMode.MESH:
            text += _(". Drag vertices; scroll zooms, middle-drag or Space+drag pans.")
        else:
            pins = len(self.session.ensure_rig().pins)
            text += _(". {n} pins. Click adds a pin, drag warps, Shift+click selects "
                      "several, double-click edits a pin.").format(n=pins)
        self.status_label.set_text(text)

    # -- history ----------------------------------------------------------

    def _record_mesh_gesture(self, before: Mesh) -> None:
        self.mesh_history.record(before)
        self._sync_history_buttons()

    def _record_pin_gesture(self, before: PuppetRig) -> None:
        self._flush_param_gesture()
        self.pin_history.record(before)
        self._sync_history_buttons()
        self._sync_pin_buttons()
        self._update_status()

    def _restore_mesh(self, mesh: Mesh | None) -> None:
        if mesh is None:
            return
        self.session.mesh = mesh
        self.session.settings.set_mesh_density(mesh.columns, mesh.rows)
        self._select_density_button(mesh.columns)
        self._after_model_change()

    def _restore_rig(self, rig: PuppetRig | None) -> None:
        if rig is None:
            return
        self.session.rig = rig
        self.pin_tool.prune_selection()
        self._after_model_change()

    def _after_model_change(self) -> None:
        self._sync_history_buttons()
        self._sync_pin_buttons()
        self._request_preview()
        self._update_status()
        self.canvas.queue_draw()

    def undo(self) -> None:
        if self.session.mode is WarpMode.MESH:
            self._restore_mesh(self.mesh_history.undo(self.session.ensure_mesh().copy()))
        else:
            self._flush_param_gesture()
            self._restore_rig(self.pin_history.undo(self.session.ensure_rig().copy()))

    def redo(self) -> None:
        if self.session.mode is WarpMode.MESH:
            self._restore_mesh(self.mesh_history.redo(self.session.ensure_mesh().copy()))
        else:
            self._flush_param_gesture()
            self._restore_rig(self.pin_history.redo(self.session.ensure_rig().copy()))

    def _history(self) -> EditHistory[Any]:
        return self.mesh_history if self.session.mode is WarpMode.MESH else self.pin_history

    def _sync_history_buttons(self) -> None:
        history = self._history()
        self.undo_button.set_sensitive(history.can_undo or self._param_snapshot is not None)
        self.redo_button.set_sensitive(history.can_redo)

    def _pin_edit(self) -> PuppetRig:
        """Start a discrete pin edit: record the rig as it is now, return it."""
        self._flush_param_gesture()
        rig = self.session.ensure_rig()
        self.pin_history.record(rig.copy())
        return rig

    def _begin_param_gesture(self) -> None:
        """Coalesce a burst of slider changes into one undo step."""
        if self._param_snapshot is None:
            self._param_snapshot = self.session.ensure_rig().copy()
            self._param_timer = GLib.timeout_add(PARAM_GESTURE_MS, self._on_param_timer)

    def _on_param_timer(self) -> bool:
        self._param_timer = None
        self._flush_param_gesture()
        return False  # one-shot

    def _flush_param_gesture(self) -> None:
        if self._param_timer is not None:
            GLib.source_remove(self._param_timer)
            self._param_timer = None
        snapshot, self._param_snapshot = self._param_snapshot, None
        if snapshot is not None and snapshot != self.session.rig:
            self.pin_history.record(snapshot)
        self._sync_history_buttons()

    # -- pins -------------------------------------------------------------

    def _on_pin_selection(self) -> None:
        selected = self.pin_tool.selected_pins()
        if len(selected) == 1:
            self._updating = True
            try:
                self.radius.set_value(selected[0].radius)
            finally:
                self._updating = False
        self._sync_pin_buttons()
        self.canvas.queue_draw()

    def _sync_pin_buttons(self) -> None:
        puppet = self.session.mode is WarpMode.PUPPET
        selected = self.pin_tool.selected_pins()
        self.remove_pin_button.set_sensitive(puppet and bool(selected))
        linked = len(selected) >= 1 and all(p.group is not None for p in selected) and \
            len({p.group for p in selected}) == 1
        self.link_button.set_label(_("Unlink pins") if linked else _("Link pins"))
        self.link_button.set_sensitive(puppet and (linked or len(selected) >= 2))
        self.add_pin_button.set_sensitive(puppet)

    def remove_selected_pins(self) -> None:
        ids = set(self.pin_tool.selected)
        if not ids:
            return
        self._pin_edit().remove(ids)
        self.pin_tool.prune_selection()
        self._after_model_change()

    def select_all_pins(self) -> None:
        self.pin_tool.set_selection({p.id for p in self.session.ensure_rig().pins})

    def toggle_link(self) -> None:
        selected = self.pin_tool.selected_pins()
        if not selected:
            return
        groups = {p.group for p in selected}
        if len(groups) == 1 and None not in groups:
            self._pin_edit().unlink(p.id for p in selected)
        elif len(selected) >= 2:
            self._pin_edit().link(p.id for p in selected)
        else:
            return
        self._after_model_change()

    def _on_add_mode(self, button: Any) -> None:
        self.pin_tool.add_mode = button.get_active()

    def _on_stiffness(self, scale: Any) -> None:
        self.session.settings.set_stiffness(scale.get_value() / 100)
        if self.session.mode is WarpMode.PUPPET:
            self._request_preview()

    def _on_radius(self, scale: Any) -> None:
        self.session.settings.set_pin_radius(scale.get_value())
        if self._updating or self.session.mode is not WarpMode.PUPPET:
            return
        ids = self.pin_tool.selected
        if ids:
            self._begin_param_gesture()
            self.session.ensure_rig().set_radius(ids, scale.get_value())
            self._sync_history_buttons()
            self._request_preview()
            self.canvas.queue_draw()

    def _on_canvas_double_click(self, x: float, y: float, tolerance: float,
                                wx: float, wy: float) -> None:
        if self.session.mode is not WarpMode.PUPPET:
            return
        pin = self.pin_tool.pin_at(x, y, tolerance)
        if pin is None:
            return
        self._flush_param_gesture()
        self.pin_tool.set_selection({pin.id})
        self._popover_pin = pin.id
        self._popover_snapshot = self.session.ensure_rig().copy()
        self._updating = True
        try:
            self.popover_title.set_markup(
                "<b>{}</b>".format(GLib.markup_escape_text(_("Pin {id}").format(
                    id=pin.id.removeprefix("pin-")))))
            self.pin_radius_spin.set_value(pin.radius)
            self.pin_weight_spin.set_value(pin.weight)
        finally:
            self._updating = False
        self.popover_unlink.set_visible(pin.group is not None)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(wx), int(wy), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _on_pin_radius_spin(self, spin: Any) -> None:
        if self._updating or self._popover_pin is None:
            return
        self.session.ensure_rig().set_radius([self._popover_pin], spin.get_value())
        self._request_preview()
        self.canvas.queue_draw()

    def _on_pin_weight_spin(self, spin: Any) -> None:
        if self._updating or self._popover_pin is None:
            return
        self.session.ensure_rig().set_weight([self._popover_pin], spin.get_value())
        self._request_preview()

    def _popover_action(self, action: str) -> None:
        pin_id = self._popover_pin
        if pin_id is None:
            return
        self._commit_popover_snapshot()
        rig = self._pin_edit()
        if action == "restore":
            rig.restore([pin_id])
        elif action == "remove":
            rig.remove([pin_id])
        elif action == "unlink":
            rig.unlink([pin_id])
        self._popover_pin = None
        self.popover.popdown()
        self.pin_tool.prune_selection()
        self._after_model_change()

    def _commit_popover_snapshot(self) -> None:
        snapshot, self._popover_snapshot = self._popover_snapshot, None
        if snapshot is not None and snapshot != self.session.rig:
            self.pin_history.record(snapshot)
            self._sync_history_buttons()

    def _on_popover_closed(self, _popover: Any) -> None:
        self._commit_popover_snapshot()
        self._popover_pin = None

    # -- handlers ---------------------------------------------------------

    def _on_mode_toggled(self, button: Any, mode: WarpMode) -> None:
        if button.get_active():
            self._flush_param_gesture()
            self.session.mode = mode
            self._sync_mode()

    def _sync_mode(self) -> None:
        mesh_mode = self.session.mode is WarpMode.MESH
        self.radius.set_sensitive(not mesh_mode)
        self.stiffness.set_sensitive(not mesh_mode)  # mesh warp has no stiffness
        for widget in [*self.density_buttons, self.custom_density, self.density_spin]:
            widget.set_sensitive(mesh_mode)
        self.show_overlay.set_label(_("Show mesh") if mesh_mode else _("Show pins"))
        self.canvas.tool = self.mesh_tool if mesh_mode else self.pin_tool
        self.canvas.show_overlay = self.session.settings.show_mesh
        self.reset_button.set_tooltip_text(
            _("Put the mesh back to a regular grid.") if mesh_mode else
            _("Put all pins back where they were placed; press again to remove them."))
        self._sync_history_buttons()
        self._sync_pin_buttons()
        self._request_preview()
        self._update_status()
        self.canvas.queue_draw()

    def _select_density_button(self, n: int) -> None:
        self._updating = True
        try:
            if n in MESH_PRESETS:
                self.density_buttons[MESH_PRESETS.index(n)].set_active(True)
            else:
                self.custom_density.set_active(True)
            self.density_spin.set_value(n)
        finally:
            self._updating = False

    def _change_density(self, n: int) -> None:
        settings = self.session.settings
        if (settings.mesh_columns, settings.mesh_rows) == (n, n):
            return
        if self.session.has_mesh_edits() and not self._confirm(
                _("Changing the mesh density discards the current mesh edits. Continue?")):
            self._select_density_button(settings.mesh_columns)
            return
        self.mesh_history.record(self.session.ensure_mesh().copy())
        settings.set_mesh_density(n)
        self.session.ensure_mesh()
        self._select_density_button(n)
        self._after_model_change()

    def _on_density_preset(self, button: Any, n: int) -> None:
        if button.get_active() and not self._updating:
            self._change_density(n)

    def _on_density_custom(self, spin: Any) -> None:
        if not self._updating:
            self._change_density(int(spin.get_value()))

    def _on_show_overlay(self, button: Any) -> None:
        self.session.settings.show_mesh = button.get_active()
        self.canvas.show_overlay = button.get_active()
        self.canvas.queue_draw()

    def _on_reset(self, _button: Any) -> None:
        if self.session.mode is WarpMode.MESH:
            if self.session.has_mesh_edits():
                mesh = self.session.ensure_mesh()
                self.mesh_history.record(mesh.copy())
                mesh.reset()
        else:
            rig = self.session.ensure_rig()
            if not rig.is_identity():
                self._pin_edit().restore()
            elif rig.pins:
                self._pin_edit().remove([p.id for p in rig.pins])
                self.pin_tool.prune_selection()
        self.original_button.set_active(False)
        self._after_model_change()

    def _on_show_original(self, button: Any) -> None:
        self.session.settings.show_original = button.get_active()
        self.canvas.show_original = button.get_active()
        self.canvas.queue_draw()

    def _confirm(self, question: str) -> bool:
        box = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.OK_CANCEL, text=question)
        try:
            return bool(box.run() == Gtk.ResponseType.OK)
        finally:
            box.destroy()

    def _typing(self) -> bool:
        """Whether keyboard focus is in a text field (keys belong to it)."""
        return isinstance(self.dialog.get_focus(), Gtk.Editable)

    def _on_key_press(self, _widget: Any, event: Any) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        key = Gdk.keyval_to_lower(event.keyval)
        puppet = self.session.mode is WarpMode.PUPPET
        if self._typing() and key not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if key == Gdk.KEY_space:
            if not self.canvas.space_pan:
                self.canvas.space_pan = True
                self.original_button.set_active(True)
            return True
        if ctrl and key == Gdk.KEY_z:
            self.redo() if shift else self.undo()
            return True
        if ctrl and key == Gdk.KEY_y:
            self.redo()
            return True
        if puppet and ctrl and key == Gdk.KEY_a:
            self.select_all_pins()
            return True
        if puppet and ctrl and key == Gdk.KEY_l:
            self.toggle_link()
            return True
        if puppet and key in (Gdk.KEY_Delete, Gdk.KEY_BackSpace, Gdk.KEY_KP_Delete):
            self.remove_selected_pins()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.apply_button.get_sensitive():
            self.dialog.response(Gtk.ResponseType.OK)
            return True
        return False

    def _on_key_release(self, _widget: Any, event: Any) -> bool:
        if event.keyval == Gdk.KEY_space:
            self.canvas.space_pan = False
            self.original_button.set_active(False)
            return True
        return False

    # -- presets ----------------------------------------------------------

    def _choose_file(self, save: bool) -> Path | None:
        action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
        chooser = Gtk.FileChooserDialog(
            title=_("Save WarpForge Preset") if save else _("Load WarpForge Preset"),
            transient_for=self.dialog, action=action)
        chooser.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL,
                            _("_Save") if save else _("_Open"), Gtk.ResponseType.ACCEPT)
        json_filter = Gtk.FileFilter()
        json_filter.set_name(_("WarpForge presets (*.json)"))
        json_filter.add_pattern("*.json")
        chooser.add_filter(json_filter)
        if save:
            chooser.set_do_overwrite_confirmation(True)
            safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in self.session.layer.name)
            chooser.set_current_name(f"{safe or 'layer'}-{self.session.mode.value}.json")
        try:
            if chooser.run() != Gtk.ResponseType.ACCEPT:
                return None
            filename = chooser.get_filename()
            return Path(filename) if filename else None
        finally:
            chooser.destroy()

    def save_preset(self) -> None:
        path = self._choose_file(save=True)
        if path is None:
            return
        if path.suffix.lower() != ".json":
            path = path.with_name(path.name + ".json")
        self._flush_param_gesture()
        preset = presets.from_session(self.session, name=path.stem)
        try:
            path.write_text(presets.dumps(preset), encoding="utf-8")
        except OSError as exc:
            self._error(_("Could not save the preset: {error}").format(error=exc))
            return
        log.info("Saved preset %s", path)
        self._message = _("Saved preset {name}").format(name=path.name)
        self._update_status()

    def load_preset(self) -> None:
        path = self._choose_file(save=False)
        if path is None:
            return
        try:
            preset = presets.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            self._error(_("Could not read the preset: {error}").format(error=exc))
            return
        except InvalidPresetError as exc:
            self._error(str(exc))
            return
        layer = self.session.layer
        if not preset.matches(layer.width, layer.height):
            if not self._confirm(_(
                    "This preset was made for a {pw}×{ph} px layer; this layer is {w}×{h} px. "
                    "Scale the preset to fit?").format(pw=preset.width, ph=preset.height,
                                                       w=layer.width, h=layer.height)):
                return
            preset = preset.scaled(layer.width, layer.height)
        self.apply_preset(preset)
        self._message = _("Loaded preset {name}").format(name=preset.name or path.name)
        self._update_status()

    def apply_preset(self, preset: presets.Preset) -> None:
        """Load a preset of the layer's size; one undo step in the preset's mode."""
        self._flush_param_gesture()
        if preset.warp_type is WarpMode.MESH:
            self.mesh_history.record(self.session.ensure_mesh().copy())
        else:
            self.pin_history.record(self.session.ensure_rig().copy())
        presets.apply_to_session(preset, self.session)
        self._updating = True
        try:
            self.stiffness.set_value(self.session.settings.stiffness * 100)
            self.limit_selection.set_active(self.session.settings.limit_to_selection)
        finally:
            self._updating = False
        self._select_density_button(self.session.settings.mesh_columns)
        target = self.mesh_button if preset.warp_type is WarpMode.MESH else self.puppet_button
        target.set_active(True)
        self.pin_tool.prune_selection()
        self._sync_mode()
        self._after_model_change()

    def _error(self, text: str) -> None:
        log.warning("%s", text)
        box = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.CLOSE, text=text)
        try:
            box.run()
        finally:
            box.destroy()

    # -- running ----------------------------------------------------------

    def run(self) -> bool:
        """Show the dialog modally. Returns True if the user chose Apply."""
        self.dialog.show_all()
        try:
            while True:
                response = self.dialog.run()
                if response == RESPONSE_SAVE_PRESET:
                    self.save_preset()
                    continue
                if response == RESPONSE_LOAD_PRESET:
                    self.load_preset()
                    continue
                return bool(response == Gtk.ResponseType.OK)
        finally:
            self._flush_param_gesture()
            self.worker.close()
            self.dialog.destroy()
