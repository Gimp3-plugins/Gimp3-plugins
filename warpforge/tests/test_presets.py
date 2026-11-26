# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets: JSON round trip, schema validation, versioning, scaling."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_state import make_layer
from warpforge import presets
from warpforge.errors import InvalidPresetError
from warpforge.presets import EffectLink
from warpforge.state import Rect, WarpMode, WarpSession

jsonschema = pytest.importorskip("jsonschema")

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "data" / "schemas"
                     / "warpforge-preset-v1.schema.json").read_text(encoding="utf-8"))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def schema_errors(data: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(SCHEMA)
    return [e.message for e in validator.iter_errors(data)]


def puppet_session() -> WarpSession:
    session = WarpSession(layer=make_layer(width=400, height=300, selection=Rect(10, 20, 30, 40)),
                          mode=WarpMode.PUPPET)
    session.settings.set_stiffness(0.3)
    session.settings.limit_to_selection = True
    rig = session.ensure_rig()
    a = rig.add_pin((100.0, 100.0), 80, 0.3)
    b = rig.add_pin((200.0, 120.0), 60, 0.3)
    c = rig.add_pin((300.0, 250.0), 50, 0.3)
    rig.link([a.id, b.id])
    rig.set_weight([c.id], 2.5)
    rig.move_pin(a.id, (110.0, 90.0), clamp_to_bounds=True)
    rig.move_pin(c.id, (280.0, 240.0), clamp_to_bounds=True)
    return session


def mesh_session() -> WarpSession:
    session = WarpSession(layer=make_layer(width=400, height=300), mode=WarpMode.MESH)
    session.settings.set_mesh_density(6)
    mesh = session.ensure_mesh()
    mesh.move_vertex(mesh.index(3, 3), (215.0, 140.0))
    return session


# -- round trip ------------------------------------------------------------------


@pytest.mark.parametrize("make", [puppet_session, mesh_session], ids=["puppet", "mesh"])
def test_round_trip_keeps_everything(make: Any) -> None:
    session = make()
    preset = presets.from_session(session, name="Zażółć ✓",
                                  effect=EffectLink(presets.OUTPUT_NEW_LAYER, "abc"))
    text = presets.dumps(preset)
    again = presets.loads(text)
    assert presets.dumps(again) == text
    assert again.name == "Zażółć ✓" and again.effect == preset.effect
    target = WarpSession(layer=session.layer)
    presets.apply_to_session(again, target)
    assert target.mode is session.mode
    assert target.settings.stiffness == session.settings.stiffness
    if session.mode is WarpMode.MESH:
        assert target.mesh == session.mesh
        assert target.settings.mesh_columns == 6
    else:
        assert target.rig is not None and session.rig is not None
        assert target.rig.pins == session.rig.pins
        assert target.settings.limit_to_selection is True


@pytest.mark.parametrize("make", [puppet_session, mesh_session], ids=["puppet", "mesh"])
def test_written_presets_follow_the_schema(make: Any) -> None:
    data = presets.to_dict(presets.from_session(make(), effect=EffectLink("in_place")))
    assert schema_errors(data) == []


def test_new_pins_after_loading_get_fresh_ids() -> None:
    preset = presets.loads(presets.dumps(presets.from_session(puppet_session())))
    assert preset.rig is not None
    new = preset.rig.add_pin((5.0, 5.0), 20, 0.5)
    assert new.id not in {p.id for p in preset.rig.pins[:-1]}
    preset.rig.link([new.id, preset.rig.pins[2].id])
    assert len({p.group for p in preset.rig.pins if p.group}) == 2


def test_brief_examples_load(tmp_path: Path) -> None:
    """The two examples from CLAUDE.md (mesh example completed to 7x7 vertices)."""
    for name in ("brief-puppet.json", "brief-mesh.json"):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert schema_errors(json.loads(text)) == []
        preset = presets.loads(text)
        assert preset.width == 1920 and preset.height == 1080


# -- validation (hand-written validator agrees with the schema) ------------------


def valid_puppet() -> dict[str, Any]:
    return presets.to_dict(presets.from_session(puppet_session()))


def valid_mesh() -> dict[str, Any]:
    return presets.to_dict(presets.from_session(mesh_session()))


def broken(base: Any, path: list[Any], value: Any) -> dict[str, Any]:
    data = copy.deepcopy(base())
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data  # type: ignore[no-any-return]


DELETE = object()

INVALID = [
    (valid_puppet, ["warp_type"], "spline"),
    (valid_puppet, ["image_width"], 0),
    (valid_puppet, ["image_height"], 10.5),
    (valid_puppet, ["stiffness"], 1.5),
    (valid_puppet, ["stiffness"], "0.5"),
    (valid_puppet, ["stiffness"], DELETE),
    (valid_puppet, ["pins"], DELETE),
    (valid_puppet, ["pins", 0, "radius"], 0),
    (valid_puppet, ["pins", 0, "weight"], 50),
    (valid_puppet, ["pins", 0, "source"], [1, 2, 3]),
    (valid_puppet, ["pins", 0, "target"], ["a", 2]),
    (valid_puppet, ["pins", 0, "colour"], "red"),
    (valid_puppet, ["pins", 0, "pinned_scale"], 1),
    (valid_puppet, ["pins", 0, "id"], ""),
    (valid_puppet, ["selection_bounds"], [1, 2, 3]),
    (valid_puppet, ["mask", "source"], "channel"),
    (valid_puppet, ["effect"], {"output": "elsewhere"}),
    (valid_puppet, ["extra_field"], 1),
    (valid_puppet, ["name"], 7),
    (valid_mesh, ["mesh", "columns"], 1),
    (valid_mesh, ["mesh", "columns"], 33),
    (valid_mesh, ["mesh", "vertices", 0], [0]),
    (valid_mesh, ["mesh"], DELETE),
]


@pytest.mark.parametrize("base, path, value", INVALID,
                         ids=[".".join(map(str, p)) + "=" + repr(v)[:12] for _b, p, v in INVALID])
def test_invalid_presets_are_rejected_by_both(base: Any, path: list[Any], value: Any) -> None:
    data = broken(base, path, value)
    assert schema_errors(data), "the schema should reject this"
    with pytest.raises(InvalidPresetError):
        presets.from_dict(data)


def test_errors_beyond_the_schema() -> None:
    """Rules JSON Schema cannot express: vertex count, unique ids, finite numbers."""
    data = valid_mesh()
    data["mesh"]["vertices"].pop()
    with pytest.raises(InvalidPresetError, match="49 points"):
        presets.from_dict(data)
    data = valid_puppet()
    data["pins"][1]["id"] = data["pins"][0]["id"]
    with pytest.raises(InvalidPresetError, match="repeats"):
        presets.from_dict(data)
    with pytest.raises(InvalidPresetError):
        presets.loads(presets.dumps(presets.from_session(puppet_session())).replace(
            '"stiffness": 0.3', '"stiffness": NaN'))


# -- versioning --------------------------------------------------------------------


@pytest.mark.parametrize("text, message", [
    ("not json", "not valid JSON"),
    ("[1, 2]", "JSON object"),
    ('{"plugin": "other", "schema_version": 1}', "not a WarpForge preset"),
    ('{"plugin": "warpforge"}', "schema_version"),
    ('{"plugin": "warpforge", "schema_version": 2}', "Update WarpForge"),
])
def test_unreadable_files_get_clear_messages(text: str, message: str) -> None:
    with pytest.raises(InvalidPresetError, match=message):
        presets.loads(text)


def test_migrations_run_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """A future v2 would register MIGRATIONS[1]; simulate v1 -> v2 -> v3."""
    monkeypatch.setattr(presets, "SCHEMA_VERSION", 3)
    seen: list[int] = []

    def step(n: int) -> Any:
        def migrate(data: dict[str, Any]) -> dict[str, Any]:
            seen.append(n)
            return {**data, "schema_version": n + 1}
        return migrate

    monkeypatch.setattr(presets, "MIGRATIONS", {1: step(1), 2: step(2)})
    assert presets.migrate({"plugin": "warpforge", "schema_version": 1})["schema_version"] == 3
    assert seen == [1, 2]


# -- scaling ------------------------------------------------------------------------


def test_scaling_to_another_layer_size() -> None:
    preset = presets.from_session(puppet_session())
    assert preset.rig is not None
    half = preset.scaled(200, 150)
    assert half.rig is not None and half.matches(200, 150)
    pin, original = half.rig.pins[0], preset.rig.pins[0]
    assert pin.target == pytest.approx((original.target[0] / 2, original.target[1] / 2))
    assert pin.radius == pytest.approx(original.radius / 2)
    assert half.selection_bounds == [5, 10, 15, 20]
    assert preset.rig.pins[0] == original  # the original preset is untouched

    mesh = presets.from_session(mesh_session()).scaled(800, 300)
    assert mesh.mesh is not None and mesh.mesh.width == 800
    assert mesh.mesh.vertices[mesh.mesh.index(3, 3)] == pytest.approx((430.0, 140.0))


def test_mismatched_size_is_refused_until_scaled() -> None:
    preset = presets.from_session(mesh_session())
    other = WarpSession(layer=make_layer(width=100, height=100))
    with pytest.raises(InvalidPresetError, match="400×300"):
        presets.apply_to_session(preset, other)
    presets.apply_to_session(preset.scaled(100, 100), other)
    assert other.mesh is not None and other.mesh.width == 100


def test_preset_holds_only_the_active_mode() -> None:
    session = puppet_session()
    session.ensure_mesh()
    data = presets.to_dict(presets.from_session(session))
    assert data["warp_type"] == "puppet" and data["mesh"]["columns"] == 0
    loaded = presets.from_dict(data)
    assert loaded.mesh is None and loaded.rig is not None
