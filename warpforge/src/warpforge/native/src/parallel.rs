// SPDX-License-Identifier: GPL-3.0-or-later
//! Minimal data parallelism over rows with `std::thread::scope` (no dependencies).

/// Split `data` (made of `rows` rows of `row_len` items) into contiguous
/// bands, run `f(first_row, band)` on each band in its own thread and return
/// the results in band order.
pub fn for_each_chunk<T, R, F>(data: &mut [T], row_len: usize, rows: usize, f: F) -> Vec<R>
where
    T: Send,
    R: Send,
    F: Fn(usize, &mut [T]) -> R + Sync,
{
    debug_assert_eq!(data.len(), row_len * rows);
    if rows == 0 || row_len == 0 {
        return Vec::new();
    }
    let threads = std::thread::available_parallelism().map_or(1, |n| n.get()).clamp(1, 16);
    // Small jobs are not worth a thread.
    let threads = threads.min((data.len() / 16_384).max(1)).min(rows);
    if threads == 1 {
        return vec![f(0, data)];
    }
    let rows_per_band = rows.div_ceil(threads);
    std::thread::scope(|scope| {
        let f = &f;
        let handles: Vec<_> = data
            .chunks_mut(rows_per_band * row_len)
            .enumerate()
            .map(|(n, band)| scope.spawn(move || f(n * rows_per_band, band)))
            .collect();
        handles.into_iter().map(|h| h.join().expect("worker thread panicked")).collect()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bands_cover_all_rows_in_order() {
        let (row_len, rows) = (300, 200);
        let mut data = vec![0usize; row_len * rows];
        let firsts = for_each_chunk(&mut data, row_len, rows, |first, band| {
            for (r, row) in band.chunks_mut(row_len).enumerate() {
                row.fill(first + r);
            }
            first
        });
        assert!(firsts.windows(2).all(|w| w[0] < w[1]));
        for (r, row) in data.chunks(row_len).enumerate() {
            assert!(row.iter().all(|&v| v == r));
        }
    }
}
