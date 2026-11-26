# SPDX-License-Identifier: GPL-3.0-or-later
"""GIMP-independent data model.

All mutable plug-in state lives in one explicit :class:`WarpSession` object;
there is no module-level state.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from warpforge.errors import UnsupportedFormatError, _
from warpforge.mesh import Mesh
from warpforge.puppet import PuppetRig

MESH_PRESETS: tuple[int, ...] = (4, 6, 8)
MIN_MESH_DIVISIONS = 2
MAX_MESH_DIVISIONS = 32


class WarpMode(enum.Enum):
    PUPPET = "puppet"
    MESH = "mesh"


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in layer pixel space."""

    x: int
    y: int
    width: int
    height: int

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]


@dataclass(frozen=True)
class LayerInfo:
    """Snapshot of the properties of the layer being warped."""

    layer_id: int
    name: str
    width: int
    height: int
    offset_x: int
    offset_y: int
    image_width: int
    image_height: int
    precision: str
    has_alpha: bool
    is_rgb: bool
    has_mask: bool
    is_text_layer: bool
    selection: Rect | None = None
    """Intersection of the selection with the layer, or ``None`` if nothing is selected."""

    @property
    def longest_side(self) -> int:
        return max(self.width, self.height)

    def describe(self) -> str:
        parts = [
            f"{self.name}",
            f"{self.width}×{self.height} px",
            self.precision,
            "RGB" if self.is_rgb else "Grayscale",
        ]
        if self.has_alpha:
            parts.append(_("alpha"))
        if self.has_mask:
            parts.append(_("layer mask"))
        if self.selection is not None:
            s = self.selection
            parts.append(_("selection {w}×{h} at {x},{y}").format(
                w=s.width, h=s.height, x=s.x, y=s.y))
        return " · ".join(parts)


@dataclass(frozen=True)
class PixelBuffer:
    """Interleaved RGBA pixels, row-major, no padding.

    ``dtype`` is ``"u8"`` (preview, display) or ``"f32"`` (full-precision
    commit, native-endian floats). This is the exchange format between
    ``gimp_bridge``, the warp backends and the UI.
    """

    width: int
    height: int
    data: bytes
    channels: int = 4
    dtype: str = "u8"

    def __post_init__(self) -> None:
        if self.dtype not in BYTES_PER_SAMPLE:
            raise UnsupportedFormatError(
                _("Unsupported pixel type {dtype!r}.").format(dtype=self.dtype))
        if self.width <= 0 or self.height <= 0:
            raise UnsupportedFormatError(_("Pixel buffer must not be empty."))
        expected = self.width * self.height * self.channels * self.bytes_per_sample
        if len(self.data) != expected:
            raise UnsupportedFormatError(
                _("Pixel buffer has {got} bytes, expected {expected}.").format(
                    got=len(self.data), expected=expected
                )
            )

    @property
    def bytes_per_sample(self) -> int:
        return BYTES_PER_SAMPLE[self.dtype]

    @property
    def rowstride(self) -> int:
        """Bytes per row."""
        return self.width * self.channels * self.bytes_per_sample

    def samples(self) -> memoryview[Any]:
        """The data as a flat sequence of numbers (ints for u8, floats for f32)."""
        view = memoryview(self.data)
        return view.cast("f") if self.dtype == "f32" else view

    def pixel(self, x: int, y: int) -> tuple[float, ...]:
        start = (y * self.width + x) * self.channels
        return tuple(self.samples()[start : start + self.channels])


BYTES_PER_SAMPLE = {"u8": 1, "f32": 4}


@dataclass
class WarpSettings:
    stiffness: float = 0.55
    pin_radius: float = 180.0
    mesh_columns: int = 4
    mesh_rows: int = 4
    show_mesh: bool = True
    show_original: bool = False
    clamp_to_bounds: bool = True
    limit_to_selection: bool = False
    output_new_layer: bool = True
    """Write the result to a copy of the layer and hide the original."""

    def set_stiffness(self, value: float) -> None:
        self.stiffness = min(1.0, max(0.0, value))

    def set_pin_radius(self, value: float) -> None:
        self.pin_radius = max(1.0, value)

    def set_mesh_density(self, columns: int, rows: int | None = None) -> None:
        rows = columns if rows is None else rows
        for value in (columns, rows):
            if not MIN_MESH_DIVISIONS <= value <= MAX_MESH_DIVISIONS:
                raise ValueError(
                    _("Mesh density must be between {lo} and {hi}.").format(
                        lo=MIN_MESH_DIVISIONS, hi=MAX_MESH_DIVISIONS
                    )
                )
        self.mesh_columns = columns
        self.mesh_rows = rows


@dataclass
class WarpSession:
    """Everything the dialog edits for one invocation of the plug-in."""

    layer: LayerInfo
    mode: WarpMode = WarpMode.PUPPET
    settings: WarpSettings = field(default_factory=WarpSettings)
    preview: PixelBuffer | None = None
    preview_scale: float = 1.0
    """Preview pixels per layer pixel (<= 1.0)."""
    mesh: Mesh | None = None
    """Mesh in layer coordinates; created on demand by :meth:`ensure_mesh`."""
    rig: PuppetRig | None = None
    """Puppet pins in layer coordinates; created on demand by :meth:`ensure_rig`."""

    @property
    def preview_factors(self) -> tuple[float, float]:
        """Exact per-axis preview/layer ratios (the preview size is rounded)."""
        if self.preview is None:
            return self.preview_scale, self.preview_scale
        return (self.preview.width / self.layer.width, self.preview.height / self.layer.height)

    def to_preview(self, x: float, y: float) -> tuple[float, float]:
        fx, fy = self.preview_factors
        return x * fx, y * fy

    def to_layer(self, x: float, y: float) -> tuple[float, float]:
        fx, fy = self.preview_factors
        return x / fx, y / fy

    def ensure_mesh(self) -> Mesh:
        """The current mesh, rebuilt if the density setting changed."""
        s = self.settings
        if self.mesh is None or (self.mesh.columns, self.mesh.rows) != (s.mesh_columns,
                                                                        s.mesh_rows):
            self.mesh = Mesh(s.mesh_columns, s.mesh_rows, self.layer.width, self.layer.height)
        return self.mesh

    def preview_mesh(self) -> Mesh:
        """The mesh scaled to preview pixels."""
        if self.preview is None:
            raise ValueError("no preview")
        return self.ensure_mesh().scaled(self.preview.width, self.preview.height)

    def ensure_rig(self) -> PuppetRig:
        if self.rig is None:
            self.rig = PuppetRig(self.layer.width, self.layer.height)
        return self.rig

    def has_mesh_edits(self) -> bool:
        return self.mesh is not None and not self.mesh.is_identity()

    def has_puppet_edits(self) -> bool:
        return self.rig is not None and not self.rig.is_identity()

    def has_edits(self) -> bool:
        """Whether the current mode would change the layer on Apply."""
        if self.mode is WarpMode.MESH:
            return self.has_mesh_edits()
        return self.has_puppet_edits()

    def reset(self) -> None:
        """Drop all edits but keep the layer, the preview and the chosen mode."""
        self.settings = WarpSettings(limit_to_selection=self.layer.selection is not None)
        self.mesh = None
        self.rig = None
