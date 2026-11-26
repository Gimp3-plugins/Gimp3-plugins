// SPDX-License-Identifier: GPL-3.0-or-later
//! Native kernels for WarpForge, exposed through a stable C ABI and loaded
//! from Python with `ctypes` (see `warpforge/native_backend.py`).
//!
//! All buffers are owned by the caller; nothing is allocated across the
//! boundary, so there is nothing to free.

pub mod geometry;
pub mod map;
pub mod mesh;
pub mod parallel;
pub mod puppet;

use std::ffi::c_void;
use std::panic::{catch_unwind, AssertUnwindSafe};

use geometry::Vec2;
use mesh::{mesh_warp, Region, RegionMut};
use puppet::{Grid, Handle};

/// Bumped whenever an exported signature changes.
pub const ABI_VERSION: u32 = 3;

pub const WF_FORMAT_RGBA_U8: u32 = 0;
pub const WF_FORMAT_RGBA_F32: u32 = 1;

pub const WF_OK: i32 = 0;
pub const WF_ERR_NULL: i32 = -1;
pub const WF_ERR_SIZE: i32 = -2;
pub const WF_ERR_FORMAT: i32 = -3;
pub const WF_ERR_ALIGN: i32 = -4;
pub const WF_ERR_PANIC: i32 = -5;

/// An RGBA image region; `x`/`y` are its origin in layer coordinates.
#[repr(C)]
pub struct WfImage {
    pub data: *mut c_void,
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
}

#[no_mangle]
pub extern "C" fn warpforge_abi_version() -> u32 {
    ABI_VERSION
}

/// One puppet constraint (a pin or a point on a rigid segment).
#[repr(C)]
#[derive(Clone, Copy)]
pub struct WfHandle {
    pub source_x: f64,
    pub source_y: f64,
    pub target_x: f64,
    pub target_y: f64,
    pub radius: f64,
    pub weight: f64,
}

/// A grid of output points: node (i, j) is at (x0 + i*step, y0 + j*step).
#[repr(C)]
#[derive(Clone, Copy)]
pub struct WfGrid {
    pub x0: f64,
    pub y0: f64,
    pub step: f64,
    pub columns: u32,
    pub rows: u32,
}

impl WfGrid {
    fn to_grid(self) -> Option<Grid> {
        let ok = self.columns > 0 && self.rows > 0 && self.step.is_finite() && self.step > 0.0
            && self.x0.is_finite() && self.y0.is_finite();
        ok.then_some(Grid {
            x0: self.x0,
            y0: self.y0,
            step: self.step,
            columns: self.columns as usize,
            rows: self.rows as usize,
        })
    }
}

/// Compute the puppet source map: for every grid node, the source position
/// to sample. `out` receives `2 * columns * rows` doubles, `bounds` the box
/// `[min_x, min_y, max_x, max_y]` of those positions.
///
/// # Safety
/// `handles` must hold `count` items (may be null if `count` is 0), `grid`
/// must be valid, `out` must hold `2 * columns * rows` doubles and `bounds` 4.
#[no_mangle]
pub unsafe extern "C" fn warpforge_puppet_map(
    handles: *const WfHandle,
    count: u32,
    stiffness: f64,
    grid: *const WfGrid,
    out: *mut f64,
    bounds: *mut f64,
) -> i32 {
    if grid.is_null() || out.is_null() || bounds.is_null() || (handles.is_null() && count > 0) {
        return WF_ERR_NULL;
    }
    let Some(grid) = (*grid).to_grid() else { return WF_ERR_SIZE };
    if !stiffness.is_finite() {
        return WF_ERR_SIZE;
    }
    let hs: Vec<Handle> = if count == 0 {
        Vec::new()
    } else {
        std::slice::from_raw_parts(handles, count as usize)
            .iter()
            .map(|h| Handle {
                source: Vec2::new(h.source_x, h.source_y),
                target: Vec2::new(h.target_x, h.target_y),
                radius: h.radius,
                weight: h.weight,
            })
            .collect()
    };
    let out = std::slice::from_raw_parts_mut(out, grid.columns * grid.rows * 2);
    let bounds = std::slice::from_raw_parts_mut(bounds, 4);
    let result = catch_unwind(AssertUnwindSafe(|| {
        puppet::source_map(&hs, stiffness.clamp(0.0, 1.0), &grid, out)
    }));
    match result {
        Ok(bb) => {
            bounds.copy_from_slice(&bb);
            WF_OK
        }
        Err(_) => WF_ERR_PANIC,
    }
}

unsafe fn run_map<T: mesh::Sample + Send + Sync>(
    src: &WfImage,
    dst: &WfImage,
    map: &[f64],
    grid: &Grid,
) -> i32 {
    let align = std::mem::align_of::<T>();
    if !(src.data as usize).is_multiple_of(align) || !(dst.data as usize).is_multiple_of(align) {
        return WF_ERR_ALIGN;
    }
    let (sw, sh) = (src.width as usize, src.height as usize);
    let (dw, dh) = (dst.width as usize, dst.height as usize);
    let src_region = Region {
        data: std::slice::from_raw_parts(src.data as *const T, sw * sh * 4),
        width: sw,
        height: sh,
        x: src.x as i64,
        y: src.y as i64,
    };
    let mut dst_region = RegionMut {
        data: std::slice::from_raw_parts_mut(dst.data as *mut T, dw * dh * 4),
        width: dw,
        height: dh,
        x: dst.x as i64,
        y: dst.y as i64,
    };
    map::map_warp(&src_region, &mut dst_region, map, grid);
    WF_OK
}

/// Warp `src` into `dst` through a source map from `warpforge_puppet_map`.
///
/// # Safety
/// As `warpforge_mesh_warp`; `map` must hold `2 * columns * rows` doubles.
#[no_mangle]
pub unsafe extern "C" fn warpforge_map_warp(
    src: *const WfImage,
    dst: *const WfImage,
    format: u32,
    map: *const f64,
    grid: *const WfGrid,
) -> i32 {
    if src.is_null() || dst.is_null() || map.is_null() || grid.is_null() {
        return WF_ERR_NULL;
    }
    let (src, dst) = (&*src, &*dst);
    if src.data.is_null() || dst.data.is_null() {
        return WF_ERR_NULL;
    }
    if src.width == 0 || src.height == 0 || dst.width == 0 || dst.height == 0 {
        return WF_ERR_SIZE;
    }
    let Some(grid) = (*grid).to_grid() else { return WF_ERR_SIZE };
    let map = std::slice::from_raw_parts(map, grid.columns * grid.rows * 2);
    let result = catch_unwind(AssertUnwindSafe(|| match format {
        WF_FORMAT_RGBA_U8 => run_map::<u8>(src, dst, map, &grid),
        WF_FORMAT_RGBA_F32 => run_map::<f32>(src, dst, map, &grid),
        _ => WF_ERR_FORMAT,
    }));
    result.unwrap_or(WF_ERR_PANIC)
}

unsafe fn vertices(ptr: *const f64, count: usize) -> Vec<Vec2> {
    std::slice::from_raw_parts(ptr, count * 2)
        .as_chunks::<2>()
        .0
        .iter()
        .map(|p| Vec2::new(p[0], p[1]))
        .collect()
}

unsafe fn run<T: mesh::Sample>(
    src: &WfImage,
    dst: &WfImage,
    src_v: &[Vec2],
    dst_v: &[Vec2],
    columns: usize,
    rows: usize,
) -> i32 {
    let align = std::mem::align_of::<T>();
    if !(src.data as usize).is_multiple_of(align) || !(dst.data as usize).is_multiple_of(align) {
        return WF_ERR_ALIGN;
    }
    let (sw, sh) = (src.width as usize, src.height as usize);
    let (dw, dh) = (dst.width as usize, dst.height as usize);
    let src_region = Region {
        data: std::slice::from_raw_parts(src.data as *const T, sw * sh * 4),
        width: sw,
        height: sh,
        x: src.x as i64,
        y: src.y as i64,
    };
    let mut dst_region = RegionMut {
        data: std::slice::from_raw_parts_mut(dst.data as *mut T, dw * dh * 4),
        width: dw,
        height: dh,
        x: dst.x as i64,
        y: dst.y as i64,
    };
    mesh_warp(&src_region, &mut dst_region, src_v, dst_v, columns, rows);
    WF_OK
}

/// Warp `src` into `dst` with a mesh.
///
/// # Safety
/// `src`/`dst` must point to valid `WfImage`s whose `data` holds
/// `width * height * 4` samples of the given format; the vertex arrays must
/// hold `2 * (columns + 1) * (rows + 1)` doubles. `src` and `dst` must not overlap.
#[no_mangle]
pub unsafe extern "C" fn warpforge_mesh_warp(
    src: *const WfImage,
    dst: *const WfImage,
    format: u32,
    src_vertices: *const f64,
    dst_vertices: *const f64,
    columns: u32,
    rows: u32,
) -> i32 {
    if src.is_null() || dst.is_null() || src_vertices.is_null() || dst_vertices.is_null() {
        return WF_ERR_NULL;
    }
    let (src, dst) = (&*src, &*dst);
    if src.data.is_null() || dst.data.is_null() {
        return WF_ERR_NULL;
    }
    if src.width == 0 || src.height == 0 || dst.width == 0 || dst.height == 0 || columns == 0
        || rows == 0
    {
        return WF_ERR_SIZE;
    }
    let (columns, rows) = (columns as usize, rows as usize);
    let count = (columns + 1) * (rows + 1);
    let src_v = vertices(src_vertices, count);
    let dst_v = vertices(dst_vertices, count);
    let result = catch_unwind(AssertUnwindSafe(|| match format {
        WF_FORMAT_RGBA_U8 => run::<u8>(src, dst, &src_v, &dst_v, columns, rows),
        WF_FORMAT_RGBA_F32 => run::<f32>(src, dst, &src_v, &dst_v, columns, rows),
        _ => WF_ERR_FORMAT,
    }));
    result.unwrap_or(WF_ERR_PANIC)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn abi_version_is_exported() {
        assert_eq!(warpforge_abi_version(), ABI_VERSION);
    }

    #[test]
    fn ffi_rejects_bad_input() {
        let mut px = [0u8; 4];
        let img = WfImage { data: px.as_mut_ptr() as *mut c_void, width: 1, height: 1, x: 0, y: 0 };
        let v = [0.0f64, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0];
        unsafe {
            assert_eq!(
                warpforge_mesh_warp(std::ptr::null(), &img, 0, v.as_ptr(), v.as_ptr(), 1, 1),
                WF_ERR_NULL
            );
            assert_eq!(warpforge_mesh_warp(&img, &img, 9, v.as_ptr(), v.as_ptr(), 1, 1),
                       WF_ERR_FORMAT);
            assert_eq!(warpforge_mesh_warp(&img, &img, 0, v.as_ptr(), v.as_ptr(), 0, 1),
                       WF_ERR_SIZE);
            let grid = WfGrid { x0: 0.5, y0: 0.5, step: 0.0, columns: 2, rows: 2 };
            let mut bb = [0.0f64; 4];
            let mut out = [0.0f64; 8];
            assert_eq!(warpforge_puppet_map(std::ptr::null(), 0, 0.5, &grid, out.as_mut_ptr(),
                                            bb.as_mut_ptr()), WF_ERR_SIZE);
            assert_eq!(warpforge_map_warp(&img, &img, 0, std::ptr::null(), &grid), WF_ERR_NULL);
        }
    }

    #[test]
    fn puppet_map_without_handles_is_identity() {
        let grid = WfGrid { x0: 0.5, y0: 0.5, step: 2.0, columns: 3, rows: 2 };
        let mut out = [0.0f64; 12];
        let mut bb = [0.0f64; 4];
        let code = unsafe {
            warpforge_puppet_map(std::ptr::null(), 0, 0.5, &grid, out.as_mut_ptr(), bb.as_mut_ptr())
        };
        assert_eq!(code, WF_OK);
        assert_eq!(out, [0.5, 0.5, 2.5, 0.5, 4.5, 0.5, 0.5, 2.5, 2.5, 2.5, 4.5, 2.5]);
        assert_eq!(bb, [0.5, 0.5, 4.5, 2.5]);
    }
}
