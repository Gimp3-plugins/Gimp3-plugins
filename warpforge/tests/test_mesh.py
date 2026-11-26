# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import random

import pytest

from warpforge.geometry import signed_area
from warpforge.history import EditHistory
from warpforge.mesh import Mesh, triangulate


@pytest.mark.parametrize("n", [4, 6, 8])
def test_regular_grid_matches_preset_format(n: int) -> None:
    mesh = Mesh(n, n, 1920, 1080)
    assert len(mesh.vertices) == (n + 1) ** 2
    assert mesh.vertices[0] == (0.0, 0.0)
    assert mesh.vertices[1] == pytest.approx((1920 / n, 0.0))
    assert mesh.vertices[-1] == (1920.0, 1080.0)
    assert mesh.is_identity()
    assert mesh.is_valid()


def test_triangulation_covers_cells_with_positive_orientation() -> None:
    mesh = Mesh(3, 2, 300, 200)
    tris = triangulate(3, 2)
    assert len(tris) == 2 * 3 * 2
    v = mesh.vertices
    assert all(signed_area(v[a], v[b], v[c]) > 0 for a, b, c in tris)
    total = sum(signed_area(v[a], v[b], v[c]) for a, b, c in tris) / 2
    assert total == pytest.approx(300 * 200)


def test_corners_never_move() -> None:
    mesh = Mesh(4, 4, 400, 400)
    for corner in (0, 4, 20, 24):
        assert mesh.move_vertex(corner, (123.0, 77.0)) == mesh.source_vertices()[corner]


def test_border_vertices_slide_along_their_border() -> None:
    mesh = Mesh(4, 4, 400, 400)
    top = mesh.index(0, 2)
    assert mesh.move_vertex(top, (230.0, 50.0)) == (230.0, 0.0)
    left = mesh.index(2, 0)
    assert mesh.move_vertex(left, (-40.0, 180.0)) == (0.0, 180.0)
    right = mesh.index(3, 4)
    assert mesh.move_vertex(right, (999.0, 310.0)) == (400.0, 310.0)


def test_clamp_to_bounds() -> None:
    mesh = Mesh(2, 2, 100, 100)
    centre = mesh.index(1, 1)
    clamped = mesh.move_vertex(centre, (50.0, -20.0), clamp_to_bounds=True)
    assert clamped[1] >= 0.0
    # Without clamping the vertex may leave the layer, but folding is still prevented.
    free = Mesh(2, 2, 100, 100)
    moved = free.move_vertex(centre, (50.0, -20.0), clamp_to_bounds=False)
    assert free.is_valid()
    assert moved[1] > 0.0  # it cannot pass the top border without flipping triangles


def test_drag_never_inverts_triangles() -> None:
    rng = random.Random(42)
    mesh = Mesh(6, 6, 600, 600)
    for _ in range(500):
        index = rng.randrange(len(mesh.vertices))
        x, y = mesh.vertices[index]
        mesh.move_vertex(index, (x + rng.uniform(-250, 250), y + rng.uniform(-250, 250)))
        assert mesh.is_valid(), mesh.inverted_triangles()


def test_extreme_drag_is_shortened_not_rejected() -> None:
    mesh = Mesh(2, 2, 100, 100)
    centre = mesh.index(1, 1)
    result = mesh.move_vertex(centre, (500.0, 50.0), clamp_to_bounds=False)
    assert 50.0 < result[0] < 100.0
    assert mesh.is_valid()


def test_scaled_keeps_relative_positions() -> None:
    mesh = Mesh(2, 2, 200, 100)
    mesh.move_vertex(4, (120.0, 60.0))
    small = mesh.scaled(100, 50)
    assert small.vertices[4] == pytest.approx((60.0, 30.0))
    assert small.vertices[-1] == (100.0, 50.0)


def test_nearest_vertex() -> None:
    mesh = Mesh(2, 2, 100, 100)
    assert mesh.nearest_vertex((52.0, 48.0), 5.0) == 4
    assert mesh.nearest_vertex((25.0, 25.0), 5.0) is None


def test_invalid_construction() -> None:
    with pytest.raises(ValueError):
        Mesh(0, 4, 10, 10)
    with pytest.raises(ValueError):
        Mesh(2, 2, 10, 10, vertices=[(0.0, 0.0)])


def test_history_undo_redo() -> None:
    mesh = Mesh(2, 2, 100, 100)
    history: EditHistory[list[tuple[float, float]]] = EditHistory()
    history.record(mesh.vertices)
    mesh.move_vertex(4, (60.0, 60.0))
    history.record(mesh.vertices)
    mesh.move_vertex(4, (70.0, 40.0))

    previous = history.undo(mesh.vertices)
    assert previous is not None and previous[4] == (60.0, 60.0)
    mesh.vertices = previous
    first = history.undo(mesh.vertices)
    assert first is not None and first[4] == (50.0, 50.0)
    mesh.vertices = first
    assert history.undo(mesh.vertices) is None
    again = history.redo(mesh.vertices)
    assert again is not None and again[4] == (60.0, 60.0)
    assert history.can_redo


def test_history_record_clears_redo_and_respects_limit() -> None:
    history: EditHistory[int] = EditHistory(limit=3)
    for i in range(5):
        history.record(i)
    assert history.undo(99) == 4
    history.record(7)
    assert not history.can_redo
    states = []
    while (s := history.undo(0)) is not None:
        states.append(s)
    assert states == [7, 3, 2]
