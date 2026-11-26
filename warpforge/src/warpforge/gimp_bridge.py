# SPDX-License-Identifier: GPL-3.0-or-later
"""The only module that talks to GIMP.

Every ``Gimp``/``Gegl``/``GimpUi`` call lives here. The rest of WarpForge works
with the plain data types from :mod:`warpforge.state`.

All API names below were verified against the GIMP 3.2.6 typelibs
(``Gimp-3.0``, ``Gegl-0.4``); see ``NOTES.md`` for the details.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
gi.require_version("Gio", "2.0")
from gi.repository import Gegl, Gimp, Gio, GLib  # noqa: E402

from warpforge import __version__  # noqa: E402
from warpforge.errors import (  # noqa: E402
    EmptyLayerError,
    MultipleLayersError,
    NoActiveLayerError,
    OperationCancelledError,
    UnsupportedLayerError,
    WarpForgeError,
    _,
)
from warpforge.render import PREVIEW_MAX_SIDE, preview_scale  # noqa: E402
from warpforge.state import LayerInfo, PixelBuffer, Rect  # noqa: E402

log = logging.getLogger(__name__)

PROC_MAIN = "plug-in-warpforge"
PROC_LAYER = "plug-in-warpforge-layer"
PROC_EDIT = "plug-in-warpforge-edit"
PROC_TOGGLE = "plug-in-warpforge-toggle"
PROC_REMOVE = "plug-in-warpforge-remove"
PROCEDURES = (PROC_MAIN, PROC_LAYER, PROC_EDIT, PROC_TOGGLE, PROC_REMOVE)
ICON_FILE = Path(__file__).resolve().parent / "icons" / "warpforge-24.png"
PARASITE_NAME = "warpforge-effect"
"""On a warped layer: the effect's parameters (preset JSON with an ``effect`` section)."""
SOURCE_PARASITE = "warpforge-source"
"""On an original layer kept for re-editing: a random tag the effect refers to."""

# babl format used for the 8-bit exchange buffers. The trailing quote marks
# perceptual (gamma-encoded) components, i.e. what users see on screen.
FORMAT_RGBA_U8 = "R'G'B'A u8"


@dataclass(frozen=True)
class RunRequest:
    """What the plug-in procedure was called with, minus the GIMP objects' API."""

    image: Any  # Gimp.Image
    drawables: Sequence[Any]  # list[Gimp.Drawable]
    interactive: bool
    procedure: str = PROC_MAIN


RunHandler = Callable[[RunRequest], None]


# --------------------------------------------------------------------------
# Plug-in registration
# --------------------------------------------------------------------------


def run_plugin(handler: RunHandler, argv: list[str]) -> int:
    """Register the WarpForge procedures and hand control to GIMP.

    ``handler`` is called for each invocation. It signals cancellation with
    :class:`OperationCancelledError` and user-facing failures with any other
    :class:`WarpForgeError`.
    """

    # No user data is registered, so GIMP calls this with five arguments.
    def run(procedure: Any, run_mode: Any, image: Any, drawables: Any,
            config: Any, data: Any = None) -> Any:
        interactive = run_mode == Gimp.RunMode.INTERACTIVE
        try:
            handler(RunRequest(image=image, drawables=list(drawables), interactive=interactive,
                               procedure=procedure.get_name()))
        except OperationCancelledError:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        except WarpForgeError as exc:
            log.warning("WarpForge failed: %s", exc)
            if interactive:
                show_message(str(exc))
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc))
            )
        except Exception as exc:  # last-resort guard: never crash GIMP's plug-in host
            log.exception("Unexpected WarpForge error")
            text = _("WarpForge hit an unexpected error: {error}").format(error=exc)
            if interactive:
                show_message(text)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(text)
            )
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    class WarpForgePlugIn(Gimp.PlugIn):  # type: ignore[misc]
        def do_set_i18n(self, name: str) -> tuple[bool, str | None, str | None]:
            return False, None, None

        def do_query_procedures(self) -> list[str]:
            return list(PROCEDURES)

        def do_create_procedure(self, name: str) -> Any:
            Gegl.init(None)
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run)
            procedure.set_image_types("RGB*, GRAY*")
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
            procedure.set_documentation(
                _("Puppet Warp and Mesh Warp"),
                _("Deform a layer with control pins or a mesh, with live preview."),
                name,
            )
            procedure.set_attribution("WarpForge contributors", "WarpForge contributors",
                                      f"2026, version {__version__}")
            labels = {
                PROC_MAIN: _("_WarpForge…"),
                PROC_LAYER: _("WarpForge: Puppet/Mesh Warp"),
                PROC_EDIT: _("WarpForge: Edit Effect…"),
                PROC_TOGGLE: _("WarpForge: Show/Hide Effect"),
                PROC_REMOVE: _("WarpForge: Remove Effect"),
            }
            procedure.set_menu_label(labels[name])
            if ICON_FILE.is_file():
                procedure.set_icon_file(Gio.File.new_for_path(str(ICON_FILE)))
            if name == PROC_MAIN:
                procedure.add_menu_path("<Image>/Filters/Distorts")
            else:
                procedure.add_menu_path("<Layers>/Layers Menu")
            if name in (PROC_TOGGLE, PROC_REMOVE):
                procedure.set_documentation(
                    _("Show or hide a WarpForge effect") if name == PROC_TOGGLE
                    else _("Remove a WarpForge effect"),
                    _("Works on a layer made by WarpForge or on its hidden original."),
                    name,
                )
            return procedure

    return int(Gimp.main(WarpForgePlugIn.__gtype__, argv))


def init_ui() -> None:
    """Initialise GimpUi (theme, GTK settings) before any dialog is shown."""
    gi.require_version("GimpUi", "3.0")
    from gi.repository import GimpUi

    GimpUi.init(PROC_MAIN)


def set_transient(window: Any) -> None:
    """Keep a plug-in window above GIMP's main window."""
    from gi.repository import GimpUi

    GimpUi.window_set_transient(window)


def show_message(text: str) -> None:
    Gimp.message(text)


def flush_displays() -> None:
    Gimp.displays_flush()


# --------------------------------------------------------------------------
# Layer access
# --------------------------------------------------------------------------


def resolve_target_layer(drawables: Sequence[Any]) -> Any:
    """Return the single ``Gimp.Layer`` to warp, or raise a user-facing error."""
    if not drawables:
        raise NoActiveLayerError()
    if len(drawables) > 1:
        raise MultipleLayersError(len(drawables))
    drawable = drawables[0]
    if isinstance(drawable, Gimp.LayerMask):
        # The user clicked the mask thumbnail; warp the layer that owns it.
        drawable = Gimp.Layer.from_mask(drawable)
    if not isinstance(drawable, Gimp.Layer):
        raise UnsupportedLayerError(_("WarpForge works on layers, not channels or paths."))
    if drawable.is_group():
        raise UnsupportedLayerError(_("Layer groups cannot be warped. Select a pixel layer."))
    if drawable.get_lock_content():
        raise UnsupportedLayerError(_("The layer's pixels are locked."))
    if drawable.get_width() <= 0 or drawable.get_height() <= 0:
        raise EmptyLayerError()
    return drawable


def read_layer_info(image: Any, layer: Any) -> LayerInfo:
    _ok, off_x, off_y = layer.get_offsets()
    return LayerInfo(
        layer_id=layer.get_id(),
        name=layer.get_name(),
        width=layer.get_width(),
        height=layer.get_height(),
        offset_x=off_x,
        offset_y=off_y,
        image_width=image.get_width(),
        image_height=image.get_height(),
        precision=image.get_precision().value_nick,
        has_alpha=layer.has_alpha(),
        is_rgb=layer.is_rgb(),
        has_mask=layer.get_mask() is not None,
        is_text_layer=layer.is_text_layer(),
        selection=selection_in_layer(image, layer),
    )


def selection_in_layer(image: Any, drawable: Any) -> Rect | None:
    """Selection bounds intersected with the drawable, in drawable coordinates.

    Returns ``None`` when nothing is selected (GIMP then treats the whole
    drawable as selected).
    """
    if Gimp.Selection.is_empty(image):
        return None
    non_empty, x, y, width, height = drawable.mask_intersect()
    if not non_empty:
        return Rect(0, 0, 0, 0)
    return Rect(x, y, width, height)


def read_preview(layer: Any, max_side: int = PREVIEW_MAX_SIDE) -> tuple[PixelBuffer, float]:
    """Read a downscaled RGBA u8 copy of the layer for the interactive preview.

    GEGL does the downscaling (mipmap) in C, so this stays fast for big layers.
    Returns the buffer and the scale factor (preview px per layer px).
    """
    width, height = layer.get_width(), layer.get_height()
    scale = preview_scale(width, height, max_side)
    # floor, so the requested rectangle never reaches past the scaled extent
    pw, ph = max(1, int(width * scale)), max(1, int(height * scale))
    buffer = layer.get_buffer()
    data = buffer.get(Gegl.Rectangle.new(0, 0, pw, ph), scale, FORMAT_RGBA_U8,
                      Gegl.AbyssPolicy.CLAMP)
    return PixelBuffer(pw, ph, bytes(data)), scale


def read_pixels(layer: Any, rect: Rect | None = None) -> PixelBuffer:
    """Read full-resolution RGBA u8 pixels from ``rect`` (default: whole layer)."""
    rect = rect or Rect(0, 0, layer.get_width(), layer.get_height())
    buffer = layer.get_buffer()
    data = buffer.get(Gegl.Rectangle.new(rect.x, rect.y, rect.width, rect.height), 1.0,
                      FORMAT_RGBA_U8, Gegl.AbyssPolicy.NONE)
    return PixelBuffer(rect.width, rect.height, bytes(data))


def write_pixels(layer: Any, pixels: PixelBuffer, x: int = 0, y: int = 0) -> None:
    """Write pixels through the shadow buffer so the change is undoable.

    ``merge_shadow`` merges the whole selected area of the shadow buffer (the
    whole layer if nothing is selected) and applies the selection as a mask,
    which is how "limit to selection" is honoured on commit. The shadow buffer
    starts out transparent, so the original pixels are copied in first;
    otherwise a partial write would erase everything around it.
    """
    shadow = layer.get_shadow_buffer()
    full = Gegl.Rectangle.new(0, 0, layer.get_width(), layer.get_height())
    if (x, y, pixels.width, pixels.height) != (0, 0, layer.get_width(), layer.get_height()):
        layer.get_buffer().copy(full, Gegl.AbyssPolicy.NONE, shadow, full)
    shadow.set(Gegl.Rectangle.new(x, y, pixels.width, pixels.height), FORMAT_RGBA_U8,
               pixels.data)
    shadow.flush()
    layer.merge_shadow(True)
    layer.update(x, y, pixels.width, pixels.height)


def working_format(image: Any) -> str:
    """Full-precision babl format for committing a warp.

    Floats keep 16/32-bit layers lossless. Interpolation happens in the image's
    own space: linear images in linear light, perceptual ones in gamma space.
    """
    nick = image.get_precision().value_nick  # e.g. "u8-non-linear", "half-linear"
    linear = nick.endswith("-linear") and not nick.endswith("-non-linear")
    return "RGBA float" if linear else "R'G'B'A float"


def read_region(layer: Any, rect: Rect, format_name: str) -> PixelBuffer:
    """Read a float RGBA region at full resolution."""
    data = layer.get_buffer().get(Gegl.Rectangle.new(rect.x, rect.y, rect.width, rect.height),
                                  1.0, format_name, Gegl.AbyssPolicy.CLAMP)
    return PixelBuffer(rect.width, rect.height, bytes(data), dtype="f32")


class ShadowWriter:
    """Collects tiles in the layer's shadow buffer; ``commit`` makes one undo step.

    The caller must write every pixel of the layer (tiled rendering does),
    because ``merge_shadow`` merges the whole selected area.
    """

    def __init__(self, layer: Any, format_name: str) -> None:
        self.layer = layer
        self.format_name = format_name
        self.shadow = layer.get_shadow_buffer()

    def write(self, rect: Rect, pixels: PixelBuffer) -> None:
        self.shadow.set(Gegl.Rectangle.new(rect.x, rect.y, rect.width, rect.height),
                        self.format_name, pixels.data)

    def commit(self) -> None:
        self.shadow.flush()
        self.layer.merge_shadow(True)
        self.layer.update(0, 0, self.layer.get_width(), self.layer.get_height())


def _plain_copy(layer: Any) -> Any:
    """``layer.copy()`` without WarpForge's bookkeeping parasites."""
    copy = layer.copy()
    for name in (SOURCE_PARASITE, PARASITE_NAME):
        if copy.get_parasite(name) is not None:
            copy.detach_parasite(name)
    return copy


def create_output_layer(image: Any, layer: Any) -> Any:
    """Duplicate ``layer`` above itself, hide the original, select the copy."""
    copy = _plain_copy(layer)
    copy.set_name(_("{name} (WarpForge)").format(name=layer.get_name()))
    image.insert_layer(copy, layer.get_parent(), image.get_item_position(layer))
    layer.set_visible(False)
    image.set_selected_layers([copy])
    return copy


def same_geometry(a: Any, b: Any) -> bool:
    return bool((a.get_width(), a.get_height(), a.get_offsets()[1:])
                == (b.get_width(), b.get_height(), b.get_offsets()[1:]))


def rebuild_output_layer(image: Any, old: Any, source: Any) -> Any:
    """Replace an effect layer whose size no longer matches its original."""
    copy = _plain_copy(source)
    copy.set_name(old.get_name())
    image.insert_layer(copy, old.get_parent(), image.get_item_position(old))
    image.remove_layer(old)
    image.set_selected_layers([copy])
    return copy


def show_effect(image: Any, result: Any, source: Any, visible: bool) -> None:
    """Show the effect layer and hide its original, or the other way round."""
    result.set_visible(visible)
    source.set_visible(not visible)
    image.set_selected_layers([result if visible else source])


def remove_layer(image: Any, layer: Any) -> None:
    image.remove_layer(layer)


def discard_output_layer(image: Any, original: Any, copy: Any) -> None:
    image.remove_layer(copy)
    original.set_visible(True)
    image.set_selected_layers([original])


@contextmanager
def selection_scope(image: Any, keep: bool) -> Iterator[None]:
    """Run the block with the selection as is (``keep``) or temporarily removed.

    ``merge_shadow`` always clips to the selection, so "do not limit to the
    selection" means stashing it in a channel and restoring it afterwards.
    """
    if keep or Gimp.Selection.is_empty(image):
        yield
        return
    saved = Gimp.Selection.save(image)
    Gimp.Selection.none(image)
    try:
        yield
    finally:
        image.select_item(Gimp.ChannelOps.REPLACE, saved)
        image.remove_channel(saved)


# --------------------------------------------------------------------------
# Undo, progress
# --------------------------------------------------------------------------


@contextmanager
def undo_group(image: Any) -> Iterator[None]:
    """Group all changes inside the block into one undo step."""
    image.undo_group_start()
    try:
        yield
    finally:
        image.undo_group_end()


def progress_start(text: str) -> None:
    Gimp.progress_init(text)


def progress_update(fraction: float) -> None:
    Gimp.progress_update(min(1.0, max(0.0, fraction)))


def progress_end() -> None:
    Gimp.progress_end()


# --------------------------------------------------------------------------
# Effect bookkeeping (parasites): the fallback for a non-destructive filter
# --------------------------------------------------------------------------
#
# GIMP 3.2 does not let a plug-in attach a parametric warp as a filter (see
# NOTES.md). Instead the warped layer carries the parameters and points to
# its untouched, hidden original through a random tag. Both parasites are
# persistent (saved in XCF) and undoable.


def _attach_text(layer: Any, name: str, text: str) -> None:
    flags = Gimp.PARASITE_PERSISTENT | Gimp.PARASITE_UNDOABLE
    # The binding exposes parasite data as gint8, so bytes must be signed.
    data = [b - 256 if b > 127 else b for b in text.encode("utf-8")]
    layer.attach_parasite(Gimp.Parasite.new(name, flags, data))


def _read_text(layer: Any, name: str) -> str | None:
    parasite = layer.get_parasite(name)
    if parasite is None:
        return None
    return bytes(v & 0xFF for v in parasite.get_data()).decode("utf-8", errors="replace")


def _detach(layer: Any, name: str) -> None:
    if layer.get_parasite(name) is not None:
        layer.detach_parasite(name)


def store_effect_params(layer: Any, payload: str) -> None:
    """Attach the effect's JSON to the layer; persisted in XCF and undoable."""
    _attach_text(layer, PARASITE_NAME, payload)


def load_effect_params(layer: Any) -> str | None:
    return _read_text(layer, PARASITE_NAME)


def clear_effect_params(layer: Any) -> None:
    _detach(layer, PARASITE_NAME)


def source_tag(layer: Any) -> str | None:
    return _read_text(layer, SOURCE_PARASITE)


def ensure_source_tag(layer: Any) -> str:
    """Tag ``layer`` as an original that an effect refers to; returns the tag."""
    tag = source_tag(layer)
    if tag is None:
        tag = uuid.uuid4().hex
        _attach_text(layer, SOURCE_PARASITE, tag)
    return tag


def clear_source_tag(layer: Any) -> None:
    _detach(layer, SOURCE_PARASITE)


def all_layers(image: Any) -> list[Any]:
    """Every layer of the image, including those inside groups, top to bottom."""
    result: list[Any] = []
    stack = list(reversed(image.get_layers()))
    while stack:
        layer = stack.pop()
        result.append(layer)
        if layer.is_group():
            stack.extend(reversed(layer.get_children()))
    return result


def find_source_layer(image: Any, tag: str) -> Any | None:
    for layer in all_layers(image):
        if source_tag(layer) == tag:
            return layer
    return None


def show_effect_original(image: Any, source: Any) -> None:
    source.set_visible(True)
    image.set_selected_layers([source])
