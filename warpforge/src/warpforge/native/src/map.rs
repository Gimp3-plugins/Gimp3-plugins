// SPDX-License-Identifier: GPL-3.0-or-later
//! Warp through a source map: per output pixel, interpolate the source
//! position bilinearly from the map's grid and sample the source there.
//!
//! Source positions outside the source region are transparent. Callers pass
//! a region that contains every in-layer position the map can produce, so in
//! effect "outside the layer" is transparent.

use crate::mesh::{sample, Region, RegionMut, Sample};
use crate::parallel::for_each_chunk;
use crate::puppet::Grid;

#[inline]
fn cell(pos: f64, origin: f64, step: f64, nodes: usize) -> (usize, f64) {
    let u = (pos - origin) / step;
    let i = (u.floor().max(0.0) as usize).min(nodes.saturating_sub(2));
    let f = (u - i as f64).clamp(0.0, 1.0);
    (i, f)
}

pub fn map_warp<T: Sample + Send + Sync>(
    src: &Region<T>,
    dst: &mut RegionMut<T>,
    map: &[f64],
    grid: &Grid,
) {
    let (dw, dh) = (dst.width, dst.height);
    let (dx, dy) = (dst.x, dst.y);
    let (sx0, sy0) = (src.x as f64, src.y as f64);
    let (sx1, sy1) = (sx0 + src.width as f64, sy0 + src.height as f64);
    let cols = grid.columns;
    let single_col = cols < 2;
    let single_row = grid.rows < 2;
    let node = |i: usize, j: usize| {
        let o = (j * cols + i) * 2;
        (map[o], map[o + 1])
    };
    for_each_chunk(dst.data, dw * 4, dh, |first_row, band| {
        for (r, row) in band.chunks_mut(dw * 4).enumerate() {
            let cy = (dy + (first_row + r) as i64) as f64 + 0.5;
            let (j, fy) = if single_row { (0, 0.0) } else { cell(cy, grid.y0, grid.step, grid.rows) };
            let j1 = if single_row { 0 } else { j + 1 };
            for (px, out) in row.chunks_mut(4).enumerate() {
                let cx = (dx + px as i64) as f64 + 0.5;
                let (i, fx) = if single_col { (0, 0.0) } else { cell(cx, grid.x0, grid.step, cols) };
                let i1 = if single_col { 0 } else { i + 1 };
                let (a, b, c, d) = (node(i, j), node(i1, j), node(i, j1), node(i1, j1));
                let top = (a.0 + (b.0 - a.0) * fx, a.1 + (b.1 - a.1) * fx);
                let bottom = (c.0 + (d.0 - c.0) * fx, c.1 + (d.1 - c.1) * fx);
                let sx = top.0 + (bottom.0 - top.0) * fy;
                let sy = top.1 + (bottom.1 - top.1) * fy;
                if !(sx >= sx0 && sx <= sx1 && sy >= sy0 && sy <= sy1) {
                    out.fill(T::default()); // also catches NaN
                    continue;
                }
                let rgba = sample(src, sx - 0.5 - sx0, sy - 0.5 - sy0);
                for k in 0..4 {
                    out[k] = T::from_f32(rgba[k]);
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity_map(grid: &Grid) -> Vec<f64> {
        let mut m = Vec::new();
        for j in 0..grid.rows {
            for i in 0..grid.columns {
                m.push(grid.x0 + i as f64 * grid.step);
                m.push(grid.y0 + j as f64 * grid.step);
            }
        }
        m
    }

    #[test]
    fn identity_map_copies_pixels() {
        let (w, h) = (23usize, 17usize);
        let data: Vec<u8> = (0..w * h * 4).map(|i| if i % 4 == 3 { 255 } else { (i * 13 % 251) as u8 }).collect();
        let grid = Grid { x0: 0.5, y0: 0.5, step: 4.0, columns: 7, rows: 6 };
        let map = identity_map(&grid);
        let mut out = vec![0u8; w * h * 4];
        map_warp(
            &Region { data: &data, width: w, height: h, x: 0, y: 0 },
            &mut RegionMut { data: &mut out, width: w, height: h, x: 0, y: 0 },
            &map,
            &grid,
        );
        assert_eq!(out, data);
    }

    #[test]
    fn positions_outside_the_source_are_transparent() {
        let data = vec![1.0f32; 4 * 4 * 4];
        let grid = Grid { x0: 0.5, y0: 0.5, step: 3.0, columns: 2, rows: 2 };
        let mut map = identity_map(&grid);
        for v in map.iter_mut().step_by(2) {
            *v += 10.0; // shift right, past the 4 px wide source
        }
        let mut out = vec![0.5f32; 4 * 4 * 4];
        map_warp(
            &Region { data: &data, width: 4, height: 4, x: 0, y: 0 },
            &mut RegionMut { data: &mut out, width: 4, height: 4, x: 0, y: 0 },
            &map,
            &grid,
        );
        assert!(out.iter().all(|&v| v == 0.0));
    }
}
