// SPDX-License-Identifier: GPL-3.0-or-later
//! Mesh warp kernel.
//!
//! The mesh is a grid of `columns x rows` cells, each split into two
//! triangles exactly like `warpforge/mesh.py::triangulate`. Every target
//! triangle is rasterised over the output; each covered pixel centre is
//! mapped by the triangle's affine map back to the source image and sampled
//! bilinearly with premultiplied alpha (no dark fringes at transparent edges).
//! Pixels covered by no triangle become fully transparent.
//!
//! Both images are *regions* of the layer: `x`/`y` give the region's origin
//! in layer coordinates, so the caller can stream big layers tile by tile.

use crate::geometry::{signed_area, Affine, Vec2};

pub trait Sample: Copy + Default {
    fn to_f32(self) -> f32;
    fn from_f32(v: f32) -> Self;
}

impl Sample for u8 {
    #[inline]
    fn to_f32(self) -> f32 {
        self as f32 / 255.0
    }
    #[inline]
    fn from_f32(v: f32) -> Self {
        (v * 255.0 + 0.5).clamp(0.0, 255.0) as u8
    }
}

impl Sample for f32 {
    #[inline]
    fn to_f32(self) -> f32 {
        self
    }
    #[inline]
    fn from_f32(v: f32) -> Self {
        v
    }
}

/// An RGBA region of a layer.
pub struct Region<'a, T> {
    pub data: &'a [T],
    pub width: usize,
    pub height: usize,
    pub x: i64,
    pub y: i64,
}

pub struct RegionMut<'a, T> {
    pub data: &'a mut [T],
    pub width: usize,
    pub height: usize,
    pub x: i64,
    pub y: i64,
}

/// Same triangle order and orientation as the Python model.
pub fn triangulate(columns: usize, rows: usize) -> Vec<[usize; 3]> {
    let stride = columns + 1;
    let mut tris = Vec::with_capacity(columns * rows * 2);
    for r in 0..rows {
        for c in 0..columns {
            let a = r * stride + c;
            let b = a + 1;
            let d = a + stride;
            tris.push([a, b, d + 1]);
            tris.push([a, d + 1, d]);
        }
    }
    tris
}

/// Bilinear, premultiplied sample at continuous position (u, v) in region pixels,
/// where integer coordinates are pixel centres. Positions are clamped to the region.
#[inline]
pub(crate) fn sample<T: Sample>(src: &Region<T>, u: f64, v: f64) -> [f32; 4] {
    let max_x = (src.width - 1) as f64;
    let max_y = (src.height - 1) as f64;
    let u = u.clamp(0.0, max_x);
    let v = v.clamp(0.0, max_y);
    let x0 = u.floor() as usize;
    let y0 = v.floor() as usize;
    let x1 = (x0 + 1).min(src.width - 1);
    let y1 = (y0 + 1).min(src.height - 1);
    let fx = (u - x0 as f64) as f32;
    let fy = (v - y0 as f64) as f32;
    let taps = [
        (x0, y0, (1.0 - fx) * (1.0 - fy)),
        (x1, y0, fx * (1.0 - fy)),
        (x0, y1, (1.0 - fx) * fy),
        (x1, y1, fx * fy),
    ];
    let mut acc = [0.0f32; 4];
    for (x, y, w) in taps {
        if w == 0.0 {
            continue;
        }
        let i = (y * src.width + x) * 4;
        let a = src.data[i + 3].to_f32() * w;
        acc[0] += src.data[i].to_f32() * a;
        acc[1] += src.data[i + 1].to_f32() * a;
        acc[2] += src.data[i + 2].to_f32() * a;
        acc[3] += a;
    }
    if acc[3] > 1e-12 {
        acc[0] /= acc[3];
        acc[1] /= acc[3];
        acc[2] /= acc[3];
    } else {
        acc = [0.0; 4];
    }
    acc
}

/// Warp `src` into `dst`. `src_vertices`/`dst_vertices` hold
/// `(columns + 1) * (rows + 1)` points in layer coordinates.
pub fn mesh_warp<T: Sample>(
    src: &Region<T>,
    dst: &mut RegionMut<T>,
    src_vertices: &[Vec2],
    dst_vertices: &[Vec2],
    columns: usize,
    rows: usize,
) {
    dst.data.fill(T::default());
    let (dx0, dy0) = (dst.x as f64, dst.y as f64);
    let (dx1, dy1) = (dx0 + dst.width as f64, dy0 + dst.height as f64);
    const EPS: f64 = 1e-7;

    for tri in triangulate(columns, rows) {
        let d = [dst_vertices[tri[0]], dst_vertices[tri[1]], dst_vertices[tri[2]]];
        let s = [src_vertices[tri[0]], src_vertices[tri[1]], src_vertices[tri[2]]];
        let area = signed_area(d[0], d[1], d[2]);
        let Some(map) = Affine::from_triangles(d, s) else { continue };

        let min_x = d.iter().map(|p| p.x).fold(f64::INFINITY, f64::min).max(dx0);
        let max_x = d.iter().map(|p| p.x).fold(f64::NEG_INFINITY, f64::max).min(dx1);
        let min_y = d.iter().map(|p| p.y).fold(f64::INFINITY, f64::min).max(dy0);
        let max_y = d.iter().map(|p| p.y).fold(f64::NEG_INFINITY, f64::max).min(dy1);
        if min_x >= max_x || min_y >= max_y {
            continue;
        }
        // pixel (px, py) has its centre at (px + 0.5, py + 0.5)
        let px0 = (min_x - 0.5).ceil().max(dx0) as i64;
        let px1 = (max_x - 0.5).floor().min(dx1 - 1.0) as i64;
        let py0 = (min_y - 0.5).ceil().max(dy0) as i64;
        let py1 = (max_y - 0.5).floor().min(dy1 - 1.0) as i64;

        for py in py0..=py1 {
            let cy = py as f64 + 0.5;
            let row = ((py - dst.y) as usize) * dst.width;
            for px in px0..=px1 {
                let cx = px as f64 + 0.5;
                let p = Vec2::new(cx, cy);
                let w0 = signed_area(p, d[1], d[2]) / area;
                let w1 = signed_area(d[0], p, d[2]) / area;
                let w2 = 1.0 - w0 - w1;
                if w0 < -EPS || w1 < -EPS || w2 < -EPS {
                    continue;
                }
                let sp = map.apply(cx, cy);
                let rgba = sample(src, sp.x - 0.5 - src.x as f64, sp.y - 0.5 - src.y as f64);
                let o = (row + (px - dst.x) as usize) * 4;
                for k in 0..4 {
                    dst.data[o + k] = T::from_f32(rgba[k]);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grid(columns: usize, rows: usize, w: f64, h: f64) -> Vec<Vec2> {
        let mut v = Vec::new();
        for r in 0..=rows {
            for c in 0..=columns {
                v.push(Vec2::new(w * c as f64 / columns as f64, h * r as f64 / rows as f64));
            }
        }
        v
    }

    /// R = x, G = y of the pixel centre: bilinear sampling of it is exact,
    /// so the output reveals exactly which source point was sampled.
    fn coordinate_image(w: usize, h: usize) -> Vec<f32> {
        let mut data = Vec::with_capacity(w * h * 4);
        for y in 0..h {
            for x in 0..w {
                data.extend_from_slice(&[x as f32 + 0.5, y as f32 + 0.5, 0.0, 1.0]);
            }
        }
        data
    }

    #[test]
    fn identity_mesh_copies_the_image() {
        let (w, h) = (37usize, 23usize);
        let src_data: Vec<u8> = (0..w * h * 4).map(|i| (i * 7 % 251) as u8).collect();
        let mut src_data = src_data;
        for px in src_data.chunks_mut(4) {
            px[3] = 255;
        }
        let v = grid(4, 4, w as f64, h as f64);
        let src = Region { data: &src_data, width: w, height: h, x: 0, y: 0 };
        let mut out = vec![0u8; w * h * 4];
        let mut dst = RegionMut { data: &mut out, width: w, height: h, x: 0, y: 0 };
        mesh_warp(&src, &mut dst, &v, &v, 4, 4);
        assert_eq!(out, src_data);
    }

    #[test]
    fn global_affine_mesh_maps_through_inverse() {
        let (w, h) = (64usize, 48usize);
        let img = coordinate_image(w, h);
        let src_v = grid(2, 2, w as f64, h as f64);
        // target = shift by (6, 4) and scale 0.8 around the origin
        let dst_v: Vec<Vec2> =
            src_v.iter().map(|p| Vec2::new(p.x * 0.8 + 6.0, p.y * 0.8 + 4.0)).collect();
        let src = Region { data: &img, width: w, height: h, x: 0, y: 0 };
        let mut out = vec![0f32; w * h * 4];
        let mut dst = RegionMut { data: &mut out, width: w, height: h, x: 0, y: 0 };
        mesh_warp(&src, &mut dst, &src_v, &dst_v, 2, 2);
        let (px, py) = (30usize, 20usize);
        let o = (py * w + px) * 4;
        let ex = ((px as f64 + 0.5) - 6.0) / 0.8;
        let ey = ((py as f64 + 0.5) - 4.0) / 0.8;
        assert!((out[o] as f64 - ex).abs() < 1e-4, "{} vs {}", out[o], ex);
        assert!((out[o + 1] as f64 - ey).abs() < 1e-4);
        // outside the shrunken mesh: transparent
        let o = (w + 1) * 4;
        assert_eq!(out[o + 3], 0.0);
    }

    #[test]
    fn tiles_match_a_single_pass() {
        let (w, h) = (50usize, 40usize);
        let img = coordinate_image(w, h);
        let src_v = grid(3, 3, w as f64, h as f64);
        let mut dst_v = src_v.clone();
        dst_v[5] = Vec2::new(dst_v[5].x + 5.0, dst_v[5].y - 3.0);
        let src = Region { data: &img, width: w, height: h, x: 0, y: 0 };
        let mut full = vec![0f32; w * h * 4];
        mesh_warp(&src, &mut RegionMut { data: &mut full, width: w, height: h, x: 0, y: 0 },
                  &src_v, &dst_v, 3, 3);
        let (tx, ty, tw, th) = (17usize, 9usize, 20usize, 25usize);
        let mut tile = vec![0f32; tw * th * 4];
        mesh_warp(&src,
                  &mut RegionMut { data: &mut tile, width: tw, height: th, x: tx as i64, y: ty as i64 },
                  &src_v, &dst_v, 3, 3);
        for y in 0..th {
            for x in 0..tw {
                for k in 0..4 {
                    assert_eq!(tile[(y * tw + x) * 4 + k], full[((y + ty) * w + x + tx) * 4 + k]);
                }
            }
        }
    }
}
