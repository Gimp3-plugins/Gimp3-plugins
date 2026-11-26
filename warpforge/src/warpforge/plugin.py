# SPDX-License-Identifier: GPL-3.0-or-later
"""Plug-in entry point: wires GIMP requests to the session, the dialog and the commit."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from warpforge import __version__, gimp_bridge, presets
from warpforge.errors import InvalidPresetError, OperationCancelledError, WarpForgeError, _
from warpforge.presets import EffectLink, Preset
from warpforge.render import (
    WarpBackend,
    render_mesh_tiled,
    render_puppet_tiled,
    select_backend,
)
from warpforge.state import PixelBuffer, Rect, WarpMode, WarpSession, WarpSettings

log = logging.getLogger("warpforge")


def configure_logging() -> None:
    """Log to stderr; set WARPFORGE_LOG_FILE to also log to a file.

    GIMP on Windows runs Python plug-ins with pythonw.exe, which has no stderr,
    so a log file is the practical way to debug there.
    """
    level_name = os.environ.get("WARPFORGE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    log_file = os.environ.get("WARPFORGE_LOG_FILE")
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


TiledRenderer = Callable[[Callable[[Rect], PixelBuffer], Callable[[Rect, PixelBuffer], None],
                           Callable[[float], None]], None]
"""render(read_region, write_region, progress) for the full-resolution pass."""


# ---------------------------------------------------------------------------
# Stored effects (the non-destructive fallback, see NOTES.md)
# ---------------------------------------------------------------------------


@dataclass
class EffectContext:
    """A WarpForge effect found in the image."""

    result: Any
    """The layer carrying the effect (the warped pixels and the parameters)."""
    source: Any | None
    """Its untouched original; ``None`` if applied in place or the original is gone."""
    preset: Preset

    @property
    def editable(self) -> bool:
        return self.source is not None


def read_effect(layer: Any) -> Preset | None:
    text = gimp_bridge.load_effect_params(layer)
    if text is None:
        return None
    try:
        return presets.loads(text)
    except InvalidPresetError as exc:
        log.warning("Ignoring unreadable WarpForge effect on %s: %s", layer.get_name(), exc)
        return None


def find_effect(image: Any, layer: Any) -> EffectContext | None:
    """The effect ``layer`` carries, or the effect whose original ``layer`` is."""
    preset = read_effect(layer)
    if preset is not None:
        source = None
        link = preset.effect
        if link is not None and link.output == presets.OUTPUT_NEW_LAYER and link.source_layer:
            source = gimp_bridge.find_source_layer(image, link.source_layer)
        return EffectContext(layer, source, preset)
    tag = gimp_bridge.source_tag(layer)
    if tag is not None:
        for other in gimp_bridge.all_layers(image):
            found = read_effect(other) if other != layer else None
            if found is not None and found.effect is not None and \
                    found.effect.source_layer == tag:
                return EffectContext(other, layer, found)
    return None


def _effects_using(image: Any, tag: str) -> list[Any]:
    result = []
    for layer in gimp_bridge.all_layers(image):
        preset = read_effect(layer)
        if preset is not None and preset.effect is not None and \
                preset.effect.source_layer == tag:
            result.append(layer)
    return result


def toggle_effect(image: Any, layer: Any) -> bool:
    """Show or hide an effect (swapping with its original). Returns the new state."""
    ctx = find_effect(image, layer)
    if ctx is None or ctx.source is None:
        raise WarpForgeError(_(
            "This layer has no WarpForge effect with a kept original to switch to."))
    visible = not ctx.result.get_visible()
    with gimp_bridge.undo_group(image):
        gimp_bridge.show_effect(image, ctx.result, ctx.source, visible)
    gimp_bridge.flush_displays()
    return visible


def remove_effect(image: Any, layer: Any) -> str:
    """Delete an effect layer and bring its original back. Returns what was done."""
    ctx = find_effect(image, layer)
    if ctx is None:
        raise WarpForgeError(_("This layer has no WarpForge effect."))
    with gimp_bridge.undo_group(image):
        if ctx.source is None:
            gimp_bridge.clear_effect_params(ctx.result)
            message = _("The warp was applied in place, so its pixels stay; WarpForge has "
                        "forgotten its parameters. Use Edit › Undo to get the old pixels back.")
        else:
            tag = gimp_bridge.source_tag(ctx.source)
            gimp_bridge.remove_layer(image, ctx.result)
            gimp_bridge.show_effect_original(image, ctx.source)
            if tag is not None and not _effects_using(image, tag):
                gimp_bridge.clear_source_tag(ctx.source)
            message = _("WarpForge effect removed; the original layer is visible again.")
    gimp_bridge.flush_displays()
    log.info(message)
    return message


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def commit_warp(image: Any, layer: Any, session: WarpSession, backend: WarpBackend,
                effect_layer: Any | None = None) -> Any:
    """Render the current mode's warp at full resolution and write it as one undo step.

    ``layer`` is the layer whose pixels are warped. With ``effect_layer`` (an
    existing WarpForge layer whose original ``layer`` is) the effect is
    re-rendered into it; otherwise the result goes to a new layer or, if
    ``output_new_layer`` is off, into ``layer`` itself. The parameters are
    stored with the result so the effect can be edited later.

    Returns the layer that received the result, or ``layer`` itself if there
    is nothing to apply.
    """
    if effect_layer is None and not session.has_edits():
        log.info("No %s edits; nothing to apply.", session.mode.value)
        return layer
    render: TiledRenderer
    if session.mode is WarpMode.MESH:
        mesh = session.ensure_mesh()
        log.info("Committing %dx%d mesh warp with %s backend", mesh.columns, mesh.rows,
                 backend.name)

        def render(read: Any, write: Any, progress: Any) -> None:
            render_mesh_tiled(backend, mesh, read, write, progress=progress)
    else:
        rig = session.ensure_rig()
        stiffness = session.settings.stiffness
        log.info("Committing puppet warp (%d pins, stiffness %.2f) with %s backend",
                 len(rig.pins), stiffness, backend.name)

        def render(read: Any, write: Any, progress: Any) -> None:
            render_puppet_tiled(backend, rig, stiffness, read, write, progress=progress)
    return _commit(image, layer, session, render, effect_layer)


def _commit(image: Any, layer: Any, session: WarpSession, render: TiledRenderer,
            effect_layer: Any | None) -> Any:
    settings = session.settings
    fmt = gimp_bridge.working_format(image)
    log.info("Working format %s", fmt)

    with gimp_bridge.undo_group(image):
        created = False
        if effect_layer is not None:
            if gimp_bridge.same_geometry(effect_layer, layer):
                target = effect_layer
            else:
                target = gimp_bridge.rebuild_output_layer(image, effect_layer, layer)
            gimp_bridge.show_effect(image, target, layer, True)
        elif settings.output_new_layer:
            target = gimp_bridge.create_output_layer(image, layer)
            created = True
        else:
            target = layer
        gimp_bridge.progress_start(_("WarpForge: warping…"))
        try:
            with gimp_bridge.selection_scope(image, keep=settings.limit_to_selection):
                writer = gimp_bridge.ShadowWriter(target, fmt)
                render(lambda rect: gimp_bridge.read_region(layer, rect, fmt), writer.write,
                       gimp_bridge.progress_update)
                writer.commit()
        except BaseException:
            if created:
                gimp_bridge.discard_output_layer(image, layer, target)
            raise
        finally:
            gimp_bridge.progress_end()

        if target is layer:
            link = EffectLink(presets.OUTPUT_IN_PLACE, None)
        else:
            link = EffectLink(presets.OUTPUT_NEW_LAYER, gimp_bridge.ensure_source_tag(layer))
        record = presets.from_session(session, name=target.get_name(), effect=link)
        gimp_bridge.store_effect_params(target, presets.dumps(record))
    gimp_bridge.flush_displays()
    return target


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handle_request(request: gimp_bridge.RunRequest) -> None:
    image = request.image
    layer = gimp_bridge.resolve_target_layer(request.drawables)

    if request.procedure == gimp_bridge.PROC_TOGGLE:
        toggle_effect(image, layer)
        return
    if request.procedure == gimp_bridge.PROC_REMOVE:
        message = remove_effect(image, layer)
        if request.interactive:
            gimp_bridge.show_message(message)
        return

    # Opening WarpForge on a WarpForge layer edits its effect.
    effect = find_effect(image, layer) if read_effect(layer) is not None else None
    if request.procedure == gimp_bridge.PROC_EDIT and (effect is None or not effect.editable):
        raise WarpForgeError(
            _("This layer has no editable WarpForge effect. Select a layer made by WarpForge "
              "with 'Output to a new layer' (its hidden original must still exist)."))
    if not request.interactive:
        raise WarpForgeError(_("WarpForge can only be run interactively for now."))

    note = ""
    if effect is not None and not effect.editable:
        note = (_("This layer was warped in place, so that warp cannot be edited; a new warp "
                  "is applied on top.") if effect.preset.effect is None
                or effect.preset.effect.output == presets.OUTPUT_IN_PLACE
                else _("The original of this WarpForge layer is gone; a new warp is applied "
                       "on top."))
        effect = None
    source = effect.source if effect is not None else layer
    info = gimp_bridge.read_layer_info(image, source)
    log.info("WarpForge %s on layer %s%s", __version__, info.describe(),
             " (editing effect)" if effect else "")
    if info.is_text_layer:
        log.info("Text layer: WarpForge works on its pixels; the result is a normal layer.")

    backend = select_backend()
    preview, scale = gimp_bridge.read_preview(source, backend.preview_max_side)
    session = WarpSession(
        layer=info,
        mode=WarpMode.PUPPET,
        preview=preview,
        preview_scale=scale,
        settings=WarpSettings(limit_to_selection=info.selection is not None),
    )
    if effect is not None:
        stored = effect.preset
        if not stored.matches(info.width, info.height):
            note = _("The original changed size since the warp was applied; the pins or mesh "
                     "were scaled from {w}×{h} px.").format(w=stored.width, h=stored.height)
            stored = stored.scaled(info.width, info.height)
        presets.apply_to_session(stored, session)
        session.settings.output_new_layer = True

    gimp_bridge.init_ui()
    from warpforge.dialog import WarpDialog  # GTK is only needed interactively

    dialog = WarpDialog(session, backend, editing=effect is not None, note=note)
    gimp_bridge.set_transient(dialog.dialog)
    if not dialog.run():
        raise OperationCancelledError()
    commit_warp(image, source, session, backend,
                effect_layer=effect.result if effect is not None else None)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    return gimp_bridge.run_plugin(handle_request, list(sys.argv if argv is None else argv))
