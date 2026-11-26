# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin tool interaction logic (GTK-free)."""

from __future__ import annotations

import pytest

from tests.test_state import make_layer
from warpforge.editing import PinTool
from warpforge.puppet import PuppetRig
from warpforge.state import WarpMode, WarpSession


class Recorder:
    def __init__(self) -> None:
        self.changes = 0
        self.gestures: list[PuppetRig] = []
        self.selections = 0


@pytest.fixture
def tool() -> tuple[PinTool, Recorder]:
    session = WarpSession(layer=make_layer(width=400, height=200), mode=WarpMode.PUPPET,
                          preview_scale=0.5)
    rec = Recorder()

    def on_change() -> None:
        rec.changes += 1

    def on_selection() -> None:
        rec.selections += 1

    return PinTool(session, on_change, rec.gestures.append, on_selection), rec


def test_click_adds_a_pin_in_layer_coordinates(tool: tuple[PinTool, Recorder]) -> None:
    t, rec = tool
    assert t.press(50, 40, 5)
    t.release()
    rig = t.session.ensure_rig()
    assert len(rig.pins) == 1 and rig.pins[0].target == (100, 80)
    assert rig.pins[0].radius == t.session.settings.pin_radius
    assert t.selected == {rig.pins[0].id}
    assert len(rec.gestures) == 1 and rec.gestures[0].pins == []  # undo removes the pin


def test_add_and_drag_is_one_gesture(tool: tuple[PinTool, Recorder]) -> None:
    t, rec = tool
    t.press(50, 40, 5)
    t.drag(60, 40)
    t.drag(70, 45)
    t.release()
    pin = t.session.ensure_rig().pins[0]
    assert pin.source == pytest.approx((100, 80)) and pin.target == (140, 90)
    assert len(rec.gestures) == 1


def test_dragging_keeps_the_grab_offset(tool: tuple[PinTool, Recorder]) -> None:
    t, _rec = tool
    t.press(50, 40, 5)
    t.release()
    t.press(52, 41, 5)  # grab the pin slightly off-centre
    t.drag(62, 41)
    t.release()
    assert t.session.ensure_rig().pins[0].target == (120, 80)


def test_click_without_moving_records_nothing(tool: tuple[PinTool, Recorder]) -> None:
    t, rec = tool
    t.press(50, 40, 5)
    t.release()
    t.press(50, 40, 5)
    t.release()
    assert len(rec.gestures) == 1


def test_shift_click_toggles_selection(tool: tuple[PinTool, Recorder]) -> None:
    t, _rec = tool
    for x in (20, 60, 100):
        t.press(x, 40, 5)
        t.release()
    a, b, c = (p.id for p in t.session.ensure_rig().pins)
    assert t.selected == {c}
    t.press(20, 40, 5, extend=True)
    assert t.selected == {a, c}
    t.press(100, 40, 5, extend=True)
    assert t.selected == {a}
    assert not t.press(150, 90, 5, extend=True)  # shift on empty canvas: nothing
    assert len(t.session.ensure_rig().pins) == 3 and b not in t.selected


def test_without_add_mode_clicks_deselect(tool: tuple[PinTool, Recorder]) -> None:
    t, _rec = tool
    t.press(50, 40, 5)
    t.release()
    t.add_mode = False
    t.press(150, 90, 5)
    t.release()
    assert t.selected == set() and len(t.session.ensure_rig().pins) == 1


def test_prune_drops_removed_pins(tool: tuple[PinTool, Recorder]) -> None:
    t, _rec = tool
    t.press(50, 40, 5)
    t.release()
    rig = t.session.ensure_rig()
    rig.remove([rig.pins[0].id])
    t.prune_selection()
    assert t.selected == set()


def test_session_edits_follow_the_mode() -> None:
    session = WarpSession(layer=make_layer(), mode=WarpMode.PUPPET)
    pin = session.ensure_rig().add_pin((10, 10), 50, 0.5)
    assert not session.has_edits()
    session.ensure_rig().move_pin(pin.id, (20, 10), clamp_to_bounds=True)
    assert session.has_edits()
    session.mode = WarpMode.MESH
    assert not session.has_edits()
    session.reset()
    assert session.rig is None
