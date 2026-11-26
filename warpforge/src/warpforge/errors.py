# SPDX-License-Identifier: GPL-3.0-or-later
"""Error types shared by all WarpForge modules.

Messages are English and wrapped in ``_()`` so they can be localised later.
"""

from __future__ import annotations


def _(message: str) -> str:
    """Placeholder for gettext; returns the message unchanged."""
    return message


class WarpForgeError(Exception):
    """Base class for user-facing WarpForge errors."""


class NoActiveLayerError(WarpForgeError):
    def __init__(self) -> None:
        super().__init__(_("No active layer. Select a single layer and try again."))


class MultipleLayersError(WarpForgeError):
    def __init__(self, count: int) -> None:
        super().__init__(
            _("WarpForge works on one layer at a time, but {count} are selected.").format(
                count=count
            )
        )


class UnsupportedLayerError(WarpForgeError):
    """The layer exists but cannot be processed (group, indexed, locked...)."""


class EmptyLayerError(WarpForgeError):
    def __init__(self) -> None:
        super().__init__(_("The layer has no pixels to warp."))


class UnsupportedFormatError(WarpForgeError):
    """Pixel data arrived in a format WarpForge cannot handle."""


class InvalidPresetError(WarpForgeError):
    """A preset or stored effect is malformed, from a newer version, or not WarpForge's."""


class OperationCancelledError(WarpForgeError):
    def __init__(self) -> None:
        super().__init__(_("Operation cancelled."))
