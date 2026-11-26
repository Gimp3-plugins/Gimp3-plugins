// SPDX-License-Identifier: GPL-3.0-or-later
//! 2-D helpers. Coordinates are layer pixels, y down.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec2 {
    pub x: f64,
    pub y: f64,
}

impl Vec2 {
    pub const fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }
}

/// Twice the signed area of triangle abc (positive = clockwise on screen).
#[inline]
pub fn signed_area(a: Vec2, b: Vec2, c: Vec2) -> f64 {
    (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
}

/// An affine map taking target-space points to source-space points,
/// fitted so that the three target vertices land on the three source vertices.
#[derive(Clone, Copy, Debug)]
pub struct Affine {
    // src = (a*x + b*y + c, d*x + e*y + f)
    pub a: f64,
    pub b: f64,
    pub c: f64,
    pub d: f64,
    pub e: f64,
    pub f: f64,
}

impl Affine {
    /// `None` if the target triangle is degenerate.
    pub fn from_triangles(dst: [Vec2; 3], src: [Vec2; 3]) -> Option<Self> {
        let area = signed_area(dst[0], dst[1], dst[2]);
        if area.abs() < 1e-12 {
            return None;
        }
        // Barycentric weights are affine in (x, y):
        // w0 = ((y1 - y2) x + (x2 - x1) y + (x1 y2 - x2 y1)) / area, etc.
        let (p0, p1, p2) = (dst[0], dst[1], dst[2]);
        let w = [
            ((p1.y - p2.y) / area, (p2.x - p1.x) / area, (p1.x * p2.y - p2.x * p1.y) / area),
            ((p2.y - p0.y) / area, (p0.x - p2.x) / area, (p2.x * p0.y - p0.x * p2.y) / area),
            ((p0.y - p1.y) / area, (p1.x - p0.x) / area, (p0.x * p1.y - p1.x * p0.y) / area),
        ];
        let mut m = Affine { a: 0.0, b: 0.0, c: 0.0, d: 0.0, e: 0.0, f: 0.0 };
        for i in 0..3 {
            m.a += w[i].0 * src[i].x;
            m.b += w[i].1 * src[i].x;
            m.c += w[i].2 * src[i].x;
            m.d += w[i].0 * src[i].y;
            m.e += w[i].1 * src[i].y;
            m.f += w[i].2 * src[i].y;
        }
        Some(m)
    }

    #[inline]
    pub fn apply(&self, x: f64, y: f64) -> Vec2 {
        Vec2::new(self.a * x + self.b * y + self.c, self.d * x + self.e * y + self.f)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn affine_maps_vertices_exactly() {
        let dst = [Vec2::new(0.0, 0.0), Vec2::new(10.0, 2.0), Vec2::new(3.0, 9.0)];
        let src = [Vec2::new(5.0, 5.0), Vec2::new(20.0, 4.0), Vec2::new(1.0, 30.0)];
        let m = Affine::from_triangles(dst, src).unwrap();
        for i in 0..3 {
            let p = m.apply(dst[i].x, dst[i].y);
            assert!((p.x - src[i].x).abs() < 1e-9 && (p.y - src[i].y).abs() < 1e-9);
        }
    }

    #[test]
    fn degenerate_triangle_has_no_affine() {
        let line = [Vec2::new(0.0, 0.0), Vec2::new(1.0, 1.0), Vec2::new(2.0, 2.0)];
        assert!(Affine::from_triangles(line, line).is_none());
    }
}
