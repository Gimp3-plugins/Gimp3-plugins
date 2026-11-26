// SPDX-License-Identifier: GPL-3.0-or-later
//! Puppet warp: inverse Moving Least Squares with a radial falloff.
//!
//! A line-by-line port of `warpforge/puppet.py::inverse_point`; see that
//! module for the maths. The Python tests compare both implementations.

use crate::geometry::Vec2;
use crate::parallel::for_each_chunk;

pub const FOLD_GUARD: f64 = 2.0;
const COINCIDENT: f64 = 1e-12;

#[derive(Clone, Copy, Debug)]
pub struct Handle {
    pub source: Vec2,
    pub target: Vec2,
    pub radius: f64,
    pub weight: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct Prepared {
    q: Vec2,
    p: Vec2,
    weight: f64,
    inv_r2: f64,
}

pub fn prepare(handles: &[Handle]) -> Vec<Prepared> {
    handles
        .iter()
        .map(|h| {
            let moved = (h.target.x - h.source.x).hypot(h.target.y - h.source.y);
            let radius = h.radius.max(FOLD_GUARD * moved).max(1e-6);
            Prepared { q: h.target, p: h.source, weight: h.weight, inv_r2: 1.0 / (radius * radius) }
        })
        .collect()
}

/// The source point that the warped image shows at (x, y).
#[inline]
pub fn inverse_point(prepared: &[Prepared], stiffness: f64, x: f64, y: f64) -> Vec2 {
    if prepared.is_empty() {
        return Vec2::new(x, y);
    }
    let mut rest = 1.0;
    for h in prepared {
        let t = ((h.q.x - x).powi(2) + (h.q.y - y).powi(2)) * h.inv_r2;
        if t < 1.0 {
            let k = (1.0 - t) * (1.0 - t);
            rest *= 1.0 - k;
        }
    }
    let g = 1.0 - rest;
    if g <= 0.0 {
        return Vec2::new(x, y);
    }

    let (mut sw, mut swqx, mut swqy, mut swpx, mut swpy) = (0.0, 0.0, 0.0, 0.0, 0.0);
    let (mut sqp, mut sqxp, mut sqq) = (0.0, 0.0, 0.0);
    for h in prepared {
        let (qx, qy) = (h.q.x - x, h.q.y - y);
        let (px, py) = (h.p.x - x, h.p.y - y);
        let d2 = qx * qx + qy * qy;
        if d2 < COINCIDENT {
            return Vec2::new(h.p.x, h.p.y);
        }
        let w = h.weight / d2;
        sw += w;
        swqx += w * qx;
        swqy += w * qy;
        swpx += w * px;
        swpy += w * py;
        sqp += w * (qx * px + qy * py);
        sqxp += w * (qx * py - qy * px);
        sqq += w * (qx * qx + qy * qy);
    }
    let (cqx, cqy) = (swqx / sw, swqy / sw);
    let (cpx, cpy) = (swpx / sw, swpy / sw);
    let a_sum = sqp - sw * (cqx * cpx + cqy * cpy);
    let b_sum = sqxp - sw * (cqx * cpy - cqy * cpx);
    let mu = sqq - sw * (cqx * cqx + cqy * cqy);
    let norm = a_sum.hypot(b_sum);
    let (a, b) = if mu <= 1e-12 || norm <= 1e-12 {
        (1.0, 0.0)
    } else {
        (
            (1.0 - stiffness) * a_sum / mu + stiffness * a_sum / norm,
            (1.0 - stiffness) * b_sum / mu + stiffness * b_sum / norm,
        )
    };
    let (ux, uy) = (-cqx, -cqy);
    let fx = ux * a - uy * b + cpx;
    let fy = ux * b + uy * a + cpy;
    Vec2::new(x + g * fx, y + g * fy)
}

/// Node (i, j) of the grid is at (x0 + i*step, y0 + j*step).
#[derive(Clone, Copy, Debug)]
pub struct Grid {
    pub x0: f64,
    pub y0: f64,
    pub step: f64,
    pub columns: usize,
    pub rows: usize,
}

/// Fill `out` (2 doubles per node, row-major) and return the bounding box
/// `[min_x, min_y, max_x, max_y]` of the source positions.
pub fn source_map(handles: &[Handle], stiffness: f64, grid: &Grid, out: &mut [f64]) -> [f64; 4] {
    let prepared = prepare(handles);
    let row_len = grid.columns * 2;
    let boxes = for_each_chunk(out, row_len, grid.rows, |first_row, chunk| {
        let mut bb = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
        for (r, row) in chunk.chunks_mut(row_len).enumerate() {
            let y = grid.y0 + (first_row + r) as f64 * grid.step;
            for (i, node) in row.chunks_mut(2).enumerate() {
                let s = inverse_point(&prepared, stiffness, grid.x0 + i as f64 * grid.step, y);
                node[0] = s.x;
                node[1] = s.y;
                bb = [bb[0].min(s.x), bb[1].min(s.y), bb[2].max(s.x), bb[3].max(s.y)];
            }
        }
        bb
    });
    boxes.into_iter().fold(
        [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY],
        |a, b| [a[0].min(b[0]), a[1].min(b[1]), a[2].max(b[2]), a[3].max(b[3])],
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn handle(sx: f64, sy: f64, tx: f64, ty: f64, r: f64) -> Handle {
        Handle { source: Vec2::new(sx, sy), target: Vec2::new(tx, ty), radius: r, weight: 1.0 }
    }

    #[test]
    fn pins_map_exactly_and_far_points_stay() {
        let hs = [handle(50.0, 50.0, 60.0, 45.0, 30.0), handle(120.0, 80.0, 120.0, 80.0, 30.0)];
        let p = prepare(&hs);
        let s = inverse_point(&p, 0.5, 60.0, 45.0);
        assert!((s.x - 50.0).abs() < 1e-9 && (s.y - 50.0).abs() < 1e-9);
        let far = inverse_point(&p, 0.5, 300.0, 300.0);
        assert_eq!((far.x, far.y), (300.0, 300.0));
    }

    #[test]
    fn single_pin_translates_its_neighbourhood() {
        let p = prepare(&[handle(40.0, 40.0, 50.0, 40.0, 100.0)]);
        // right at the pin the whole offset applies; MLS of one handle is a translation
        let s = inverse_point(&p, 1.0, 50.0, 41.0);
        assert!((s.x - 40.0).abs() < 0.05, "{s:?}");
    }

    #[test]
    fn map_bounds_cover_values() {
        let hs = [handle(10.0, 10.0, 14.0, 12.0, 20.0)];
        let grid = Grid { x0: 0.5, y0: 0.5, step: 4.0, columns: 20, rows: 17 };
        let mut out = vec![0.0; 20 * 17 * 2];
        let bb = source_map(&hs, 0.3, &grid, &mut out);
        for n in out.chunks(2) {
            assert!(n[0] >= bb[0] && n[0] <= bb[2] && n[1] >= bb[1] && n[1] <= bb[3]);
        }
        let last = out.len() - 2; // far corner (76.5, 64.5) stays
        assert_eq!((out[last], out[last + 1]), (76.5, 64.5));
    }
}
