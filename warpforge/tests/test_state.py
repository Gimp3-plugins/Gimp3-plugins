# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from warpforge.errors import UnsupportedFormatError
from warpforge.state import LayerInfo, PixelBuffer, Rect, WarpMode, WarpSession, WarpSettings


def make_layer(**overrides: object) -> LayerInfo:
    values: dict[str, object] = dict(
        layer_id=12, name="Background", width=1920, height=1080, offset_x=0, offset_y=0,
        image_width=1920, image_height=1080, precision="u8-non-linear", has_alpha=True,
        is_rgb=True, has_mask=False, is_text_layer=False, selection=None,
    )
    values.update(overrides)
    return LayerInfo(**values)  # type: ignore[arg-type]


class TestPixelBuffer:
    def test_valid_buffer(self) -> None:
        buf = PixelBuffer(2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
        assert buf.rowstride == 8
        assert buf.pixel(1, 0) == (5, 6, 7, 8)

    def test_wrong_length_rejected(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            PixelBuffer(2, 2, bytes(15))

    @pytest.mark.parametrize("size", [(0, 5), (5, 0), (-1, 1)])
    def test_empty_rejected(self, size: tuple[int, int]) -> None:
        with pytest.raises(UnsupportedFormatError):
            PixelBuffer(size[0], size[1], b"")


class TestSettings:
    def test_stiffness_is_clamped(self) -> None:
        s = WarpSettings()
        s.set_stiffness(1.7)
        assert s.stiffness == 1.0
        s.set_stiffness(-0.2)
        assert s.stiffness == 0.0

    def test_pin_radius_has_floor(self) -> None:
        s = WarpSettings()
        s.set_pin_radius(0)
        assert s.pin_radius == 1.0

    @pytest.mark.parametrize("n", [4, 6, 8, 2, 32])
    def test_valid_mesh_density(self, n: int) -> None:
        s = WarpSettings()
        s.set_mesh_density(n)
        assert (s.mesh_columns, s.mesh_rows) == (n, n)

    @pytest.mark.parametrize("n", [0, 1, 33])
    def test_invalid_mesh_density(self, n: int) -> None:
        with pytest.raises(ValueError):
            WarpSettings().set_mesh_density(n)

    def test_non_square_mesh(self) -> None:
        s = WarpSettings()
        s.set_mesh_density(6, 4)
        assert (s.mesh_columns, s.mesh_rows) == (6, 4)


class TestLayerInfo:
    def test_describe_mentions_key_facts(self) -> None:
        text = make_layer(has_mask=True, selection=Rect(1, 2, 30, 40)).describe()
        assert "Background" in text
        assert "1920×1080" in text
        assert "layer mask" in text
        assert "selection 30×40 at 1,2" in text

    def test_longest_side(self) -> None:
        assert make_layer(width=300, height=4000).longest_side == 4000


class TestSession:
    def test_coordinate_round_trip(self) -> None:
        session = WarpSession(layer=make_layer(), preview_scale=0.5)
        assert session.to_preview(100, 50) == (50, 25)
        assert session.to_layer(*session.to_preview(123.0, 45.0)) == (123.0, 45.0)

    def test_reset_restores_defaults_and_keeps_selection_flag(self) -> None:
        session = WarpSession(layer=make_layer(selection=Rect(0, 0, 10, 10)))
        session.settings.set_stiffness(0.1)
        session.settings.set_mesh_density(8)
        session.mode = WarpMode.MESH
        session.reset()
        assert session.settings.stiffness == WarpSettings().stiffness
        assert session.settings.mesh_columns == 4
        assert session.settings.limit_to_selection is True
        assert session.mode is WarpMode.MESH  # reset clears edits, not the chosen mode
