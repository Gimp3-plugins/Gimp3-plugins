# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets: the warp's parameters as JSON (``data/schemas/warpforge-preset-v1.schema.json``).

The same format is used for exported preset files and for the copy stored
with a warped layer (which adds an ``effect`` section). GIMP's bundled Python
has no ``jsonschema``, so :func:`validate` checks the schema's rules by hand;
the test suite checks that both agree.

Versioning: every file carries ``schema_version``. :func:`migrate` upgrades
older versions step by step; files from a newer WarpForge are refused with a
clear message instead of being misread.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from warpforge.errors import InvalidPresetError, _
from warpforge.mesh import Mesh
from warpforge.puppet import MAX_PIN_WEIGHT, MIN_PIN_WEIGHT, Pin, PuppetRig
from warpforge.state import MAX_MESH_DIVISIONS, MIN_MESH_DIVISIONS, WarpMode, WarpSession

SCHEMA_VERSION = 1
PLUGIN = "warpforge"
MAX_NAME_LENGTH = 200
OUTPUT_NEW_LAYER = "new_layer"
OUTPUT_IN_PLACE = "in_place"

Json = dict[str, Any]


@dataclass(frozen=True)
class EffectLink:
    """How a stored effect relates to the layers of the image."""

    output: str  # OUTPUT_NEW_LAYER or OUTPUT_IN_PLACE
    source_layer: str | None = None
    """Tag (``warpforge-source`` parasite) of the untouched original layer."""


@dataclass
class Preset:
    warp_type: WarpMode
    width: int
    height: int
    stiffness: float = 0.55
    name: str = ""
    mesh: Mesh | None = None
    rig: PuppetRig | None = None
    limit_to_selection: bool = False
    layer_id: int | None = None
    selection_bounds: list[int] | None = None
    effect: EffectLink | None = None
    extra: Json = field(default_factory=dict)
    """Reserved for fields of future versions that survived a migration."""

    def matches(self, width: int, height: int) -> bool:
        return (self.width, self.height) == (width, height)

    def scaled(self, width: int, height: int) -> Preset:
        """The same warp for a layer of another size (coordinates scale per axis)."""
        if width <= 0 or height <= 0:
            raise ValueError("size must be positive")
        sx, sy = width / self.width, height / self.height
        rig = None
        if self.rig is not None:
            rig = self.rig.copy()
            rig.width, rig.height = width, height
            sr = math.sqrt(sx * sy)
            for p in rig.pins:
                p.source = (p.source[0] * sx, p.source[1] * sy)
                p.target = (p.target[0] * sx, p.target[1] * sy)
                p.radius *= sr
        mesh = None if self.mesh is None else self.mesh.scaled(width, height)
        bounds = None
        if self.selection_bounds is not None:
            x, y, w, h = self.selection_bounds
            bounds = [round(x * sx), round(y * sy), round(w * sx), round(h * sy)]
        return Preset(self.warp_type, width, height, self.stiffness, self.name, mesh, rig,
                      self.limit_to_selection, self.layer_id, bounds, self.effect,
                      dict(self.extra))


# ---------------------------------------------------------------------------
# Session <-> preset
# ---------------------------------------------------------------------------


def from_session(session: WarpSession, name: str = "", effect: EffectLink | None = None
                 ) -> Preset:
    """A preset of the session's *current* mode."""
    layer = session.layer
    sel = layer.selection
    preset = Preset(
        warp_type=session.mode,
        width=layer.width,
        height=layer.height,
        stiffness=session.settings.stiffness,
        name=name,
        limit_to_selection=session.settings.limit_to_selection,
        layer_id=layer.layer_id,
        selection_bounds=None if sel is None else sel.as_list(),
        effect=effect,
    )
    if session.mode is WarpMode.MESH:
        preset.mesh = session.ensure_mesh().copy()
    else:
        preset.rig = session.ensure_rig().copy()
    return preset


def apply_to_session(preset: Preset, session: WarpSession) -> None:
    """Load a preset into the session. Its size must match the layer (see :meth:`scaled`)."""
    if not preset.matches(session.layer.width, session.layer.height):
        raise InvalidPresetError(_(
            "The preset was made for a {pw}×{ph} px layer, this one is {lw}×{lh} px."
        ).format(pw=preset.width, ph=preset.height, lw=session.layer.width,
                 lh=session.layer.height))
    session.mode = preset.warp_type
    session.settings.set_stiffness(preset.stiffness)
    if session.layer.selection is not None:
        session.settings.limit_to_selection = preset.limit_to_selection
    if preset.mesh is not None:
        session.settings.set_mesh_density(preset.mesh.columns, preset.mesh.rows)
        session.mesh = preset.mesh.copy()
    if preset.rig is not None:
        session.rig = preset.rig.copy()


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_dict(preset: Preset) -> Json:
    data: Json = {
        "schema_version": SCHEMA_VERSION,
        "plugin": PLUGIN,
        "name": preset.name,
        "warp_type": preset.warp_type.value,
        "image_width": preset.width,
        "image_height": preset.height,
        "layer_id": preset.layer_id,
        "selection_bounds": preset.selection_bounds,
        "stiffness": float(preset.stiffness),
    }
    if preset.mesh is not None:
        m = preset.mesh
        data["mesh"] = {"columns": m.columns, "rows": m.rows,
                        "vertices": [[float(x), float(y)] for x, y in m.vertices]}
    else:
        data["mesh"] = {"columns": 0, "rows": 0, "vertices": []}
    if preset.rig is not None:
        data["pins"] = [
            {
                "id": p.id,
                "source": [float(p.source[0]), float(p.source[1])],
                "target": [float(p.target[0]), float(p.target[1])],
                "radius": float(p.radius),
                "weight": float(p.weight),
                "pinned_rotation": p.pinned_rotation,
                "pinned_scale": p.pinned_scale,
                "group": p.group,
            }
            for p in preset.rig.pins
        ]
    data["mask"] = {"enabled": preset.limit_to_selection, "source": "selection"}
    if preset.effect is not None:
        data["effect"] = {"output": preset.effect.output,
                          "source_layer": preset.effect.source_layer}
    return data


def dumps(preset: Preset) -> str:
    return json.dumps(to_dict(preset), indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def loads(text: str) -> Preset:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise InvalidPresetError(_("The preset is not valid JSON: {error}").format(
            error=exc)) from exc
    return from_dict(data)


def from_dict(data: Any) -> Preset:
    data = migrate(data)
    validate(data)
    width, height = data["image_width"], data["image_height"]
    mode = WarpMode(data["warp_type"])
    preset = Preset(
        warp_type=mode,
        width=width,
        height=height,
        stiffness=float(data["stiffness"]),
        name=data.get("name", ""),
        limit_to_selection=bool(data.get("mask", {}).get("enabled", False)),
        layer_id=data.get("layer_id"),
        selection_bounds=data.get("selection_bounds"),
    )
    if mode is WarpMode.MESH:
        m = data["mesh"]
        preset.mesh = Mesh(m["columns"], m["rows"], width, height,
                           [(float(x), float(y)) for x, y in m["vertices"]])
    else:
        rig = PuppetRig(width, height)
        numbers = [0]
        for item in data["pins"]:
            rig.pins.append(Pin(
                id=item["id"],
                source=(float(item["source"][0]), float(item["source"][1])),
                target=(float(item["target"][0]), float(item["target"][1])),
                radius=float(item["radius"]),
                weight=float(item.get("weight", 1.0)),
                pinned_rotation=bool(item.get("pinned_rotation", False)),
                pinned_scale=bool(item.get("pinned_scale", False)),
                group=item.get("group"),
            ))
            numbers += [int(n) for n in re.findall(r"\d+", item["id"])]
            if item.get("group"):
                numbers += [int(n) for n in re.findall(r"\d+", item["group"])]
        rig._next_id = max(numbers) + 1  # new pins never reuse an id
        rig.unlink([])  # drop one-pin groups a hand-edited file may contain
        preset.rig = rig
    effect = data.get("effect")
    if effect is not None:
        preset.effect = EffectLink(effect["output"], effect.get("source_layer"))
    return preset


# ---------------------------------------------------------------------------
# Versioning and validation
# ---------------------------------------------------------------------------

Migration = Callable[[Json], Json]
MIGRATIONS: dict[int, Migration] = {}
"""``MIGRATIONS[n]`` turns a version-``n`` dict into version ``n + 1``."""


def migrate(data: Any) -> Json:
    """Bring a parsed preset up to :data:`SCHEMA_VERSION`."""
    if not isinstance(data, dict):
        raise InvalidPresetError(_("A preset must be a JSON object."))
    if data.get("plugin") != PLUGIN:
        raise InvalidPresetError(_("This is not a WarpForge preset."))
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InvalidPresetError(_("The preset has no valid schema_version."))
    if version > SCHEMA_VERSION:
        raise InvalidPresetError(_(
            "The preset uses schema version {found}; this WarpForge reads up to {max}. "
            "Update WarpForge to load it.").format(found=version, max=SCHEMA_VERSION))
    result: Json = data
    while version < SCHEMA_VERSION:
        result = MIGRATIONS[version](result)
        version = result["schema_version"]
    return result


_TOP_KEYS = {"schema_version", "plugin", "name", "warp_type", "image_width", "image_height",
             "layer_id", "selection_bounds", "stiffness", "mesh", "pins", "mask", "effect"}
_PIN_KEYS = {"id", "source", "target", "radius", "weight", "pinned_rotation", "pinned_scale",
             "group"}


def _fail(where: str, problem: str) -> None:
    raise InvalidPresetError(_("Invalid preset: {where} {problem}.").format(
        where=where, problem=problem))


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _check_point(where: str, v: Any) -> None:
    if not (isinstance(v, list) and len(v) == 2 and all(_is_number(c) for c in v)):
        _fail(where, _("must be a pair of numbers [x, y]"))


def _check_keys(where: str, obj: Json, allowed: set[str]) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        _fail(where, _("has unknown fields: {names}").format(names=", ".join(unknown)))


def validate(data: Json) -> None:
    """Raise :class:`InvalidPresetError` unless ``data`` follows schema version 1."""
    _check_keys("the preset", data, _TOP_KEYS)
    for key in ("schema_version", "plugin", "warp_type", "image_width", "image_height",
                "stiffness"):
        if key not in data:
            _fail(f"'{key}'", _("is missing"))
    if data["schema_version"] != SCHEMA_VERSION:
        _fail("'schema_version'", _("must be {v}").format(v=SCHEMA_VERSION))
    if data["warp_type"] not in ("puppet", "mesh"):
        _fail("'warp_type'", _("must be \"puppet\" or \"mesh\""))
    for key in ("image_width", "image_height"):
        if not (_is_int(data[key]) and data[key] >= 1):
            _fail(f"'{key}'", _("must be a positive integer"))
    if not (_is_number(data["stiffness"]) and 0 <= data["stiffness"] <= 1):
        _fail("'stiffness'", _("must be a number from 0 to 1"))
    name = data.get("name", "")
    if not isinstance(name, str) or len(name) > MAX_NAME_LENGTH:
        _fail("'name'", _("must be text of at most {n} characters").format(n=MAX_NAME_LENGTH))
    if data.get("layer_id") is not None and not _is_int(data["layer_id"]):
        _fail("'layer_id'", _("must be an integer or null"))
    bounds = data.get("selection_bounds")
    if bounds is not None and not (isinstance(bounds, list) and len(bounds) == 4
                                   and all(_is_int(v) for v in bounds)):
        _fail("'selection_bounds'", _("must be null or [x, y, width, height]"))

    mesh = data.get("mesh")
    if mesh is not None:
        if not isinstance(mesh, dict):
            _fail("'mesh'", _("must be an object"))
        _check_keys("'mesh'", mesh, {"columns", "rows", "vertices"})
        for key in ("columns", "rows", "vertices"):
            if key not in mesh:
                _fail(f"'mesh.{key}'", _("is missing"))
        for key in ("columns", "rows"):
            if not (_is_int(mesh[key]) and 0 <= mesh[key] <= MAX_MESH_DIVISIONS):
                _fail(f"'mesh.{key}'", _("must be an integer from 0 to {n}").format(
                    n=MAX_MESH_DIVISIONS))
        if not isinstance(mesh["vertices"], list):
            _fail("'mesh.vertices'", _("must be a list"))
        for i, v in enumerate(mesh["vertices"]):
            _check_point(f"'mesh.vertices[{i}]'", v)
    if data["warp_type"] == "mesh":
        if mesh is None:
            _fail("'mesh'", _("is required for a mesh warp"))
        assert isinstance(mesh, dict)
        c, r = mesh["columns"], mesh["rows"]
        if c < MIN_MESH_DIVISIONS or r < MIN_MESH_DIVISIONS:
            _fail("'mesh'", _("needs at least {n} columns and rows").format(
                n=MIN_MESH_DIVISIONS))
        if len(mesh["vertices"]) != (c + 1) * (r + 1):
            _fail("'mesh.vertices'", _("must hold (columns + 1) × (rows + 1) = {n} points"
                                       ).format(n=(c + 1) * (r + 1)))

    pins = data.get("pins")
    if pins is not None:
        if not isinstance(pins, list):
            _fail("'pins'", _("must be a list"))
        seen: set[str] = set()
        for i, pin in enumerate(pins):
            where = f"'pins[{i}]'"
            if not isinstance(pin, dict):
                _fail(where, _("must be an object"))
            _check_keys(where, pin, _PIN_KEYS)
            for key in ("id", "source", "target", "radius"):
                if key not in pin:
                    _fail(f"'pins[{i}].{key}'", _("is missing"))
            if not (isinstance(pin["id"], str) and pin["id"]):
                _fail(f"'pins[{i}].id'", _("must be non-empty text"))
            if pin["id"] in seen:
                _fail(f"'pins[{i}].id'", _("repeats the id {id!r}").format(id=pin["id"]))
            seen.add(pin["id"])
            _check_point(f"'pins[{i}].source'", pin["source"])
            _check_point(f"'pins[{i}].target'", pin["target"])
            if not (_is_number(pin["radius"]) and pin["radius"] > 0):
                _fail(f"'pins[{i}].radius'", _("must be a positive number"))
            weight = pin.get("weight", 1.0)
            if not (_is_number(weight) and MIN_PIN_WEIGHT <= weight <= MAX_PIN_WEIGHT):
                _fail(f"'pins[{i}].weight'", _("must be a number from {lo} to {hi}").format(
                    lo=MIN_PIN_WEIGHT, hi=MAX_PIN_WEIGHT))
            for key in ("pinned_rotation", "pinned_scale"):
                if key in pin and not isinstance(pin[key], bool):
                    _fail(f"'pins[{i}].{key}'", _("must be true or false"))
            if pin.get("group") is not None and not isinstance(pin["group"], str):
                _fail(f"'pins[{i}].group'", _("must be text or null"))
    if data["warp_type"] == "puppet" and pins is None:
        _fail("'pins'", _("is required for a puppet warp"))

    mask = data.get("mask")
    if mask is not None:
        if not isinstance(mask, dict):
            _fail("'mask'", _("must be an object"))
        _check_keys("'mask'", mask, {"enabled", "source"})
        if "enabled" in mask and not isinstance(mask["enabled"], bool):
            _fail("'mask.enabled'", _("must be true or false"))
        if "source" in mask and mask["source"] != "selection":
            _fail("'mask.source'", _("must be \"selection\""))

    effect = data.get("effect")
    if effect is not None:
        if not isinstance(effect, dict):
            _fail("'effect'", _("must be an object"))
        _check_keys("'effect'", effect, {"output", "source_layer"})
        if effect.get("output") not in (OUTPUT_NEW_LAYER, OUTPUT_IN_PLACE):
            _fail("'effect.output'", _("must be \"new_layer\" or \"in_place\""))
        if effect.get("source_layer") is not None and not isinstance(effect["source_layer"],
                                                                     str):
            _fail("'effect.source_layer'", _("must be text or null"))
