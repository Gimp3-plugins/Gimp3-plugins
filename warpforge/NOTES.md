# WarpForge – GIMP 3 API notes

Everything here was verified on **GIMP 3.2.6 (Windows, installer build)** by
introspecting the installed typelibs (`Gimp-3.0`, `GimpUi-3.0`, `Gegl-0.4`) with
GIMP's own Python, by reading the Python plug-ins shipped with GIMP
(`lib/gimp/3.0/plug-ins/foggify/foggify.py`, `spyro-plus`, `python-eval`) and by
running `tests/gimp/smoke_bridge.py` in headless `gimp-console-3`. Nothing was
copied from GIMP 2.10 plug-ins.

Reference docs: <https://developer.gimp.org/api/3.0/libgimp/>,
<https://developer.gimp.org/resource/writing-a-plug-in/>.

## Findings that change the brief (CLAUDE.md)

| Brief says | Reality | Decision |
|---|---|---|
| UI in **GTK 4** | GIMP 3.x is built on **GTK 3.24**; `GimpUi-3.0` requires `Gtk-3.0`. A plug-in cannot load GTK 4 next to it. | UI is GTK 3. Revisit when GIMP moves to GTK 4. |
| NumPy/SciPy as fallback backend | GIMP's bundled Python on Windows (**3.14**, MSYS2 UCRT build) has **no NumPy**, and pip wheels for python.org CPython do not match its ABI. | Runtime has zero third-party Python deps. Heavy math goes to a native library. |
| Rust via **PyO3** | PyO3 extension modules are tied to the interpreter ABI (here `cp314-mingw_x86_64_ucrt_llvm`). | Rust `cdylib` with a plain **C ABI**, loaded with `ctypes`. Verified: an MSVC-built DLL loads in GIMP's Python (`warpforge_abi_version()`, now 3). A pure-Python backend remains as a slow fallback. |
| Menu `Filters > Distort` | The internal menu path is `<Image>/Filters/Distorts`. | Used as is; GIMP shows it as *Filters › Distorts*. |

## Plug-in registration

* Subclass `Gimp.PlugIn`, implement `do_query_procedures`, `do_create_procedure`,
  `do_set_i18n` (returns `(False, None, None)` – no translation catalogue yet).
* `Gimp.ImageProcedure.new(plug_in, name, Gimp.PDBProcType.PLUGIN, run_func)`;
  run func signature `(procedure, run_mode, image, drawables, config, data)`.
* `procedure.set_image_types("RGB*, GRAY*")`,
  `set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)`,
  `set_menu_label`, `add_menu_path`, `set_documentation`, `set_attribution`.
* Return `procedure.new_return_values(Gimp.PDBStatusType.SUCCESS|CANCEL|EXECUTION_ERROR, GLib.Error(msg))`.
* Entry: `Gimp.main(PlugInClass.__gtype__, sys.argv)`.
* Layer context menu root is `<Layers>`; the existing convention (seen in
  installed plug-ins' `pluginrc`) is `<Layers>/Layers Menu`. Both procedures
  were confirmed registered via `Gimp.get_pdb().lookup_procedure(...)`.
* GIMP loads `plug-ins/<name>/<name>.py`; the folder and file name must match.
* UI: call `GimpUi.init(proc_name)` before building windows;
  `GimpUi.window_set_transient(window)` keeps the dialog above GIMP.

## Pixels

* `drawable.get_buffer()` → `Gegl.Buffer`; `drawable.get_shadow_buffer()` for writing.
* `Gegl.Buffer.get(rect, scale, format_name, Gegl.AbyssPolicy)` returns the
  bytes. With `scale < 1` the **rect is in scaled coordinates** and GEGL
  downsamples in C – used for the ≤1024 px preview (3000×1500 → 1024×512, verified).
* `Gegl.Buffer.set(rect, format_name, data)` accepts `bytes`.
* Exchange format: `"R'G'B'A u8"` (babl converts from any precision; verified
  with `u8-non-linear` and `float-linear` images).
* **Pitfall (found by the smoke test):** `drawable.merge_shadow(True)` merges the
  *whole* selected area of the shadow buffer, which starts transparent. A
  partial write therefore wiped the rest of the layer. `write_pixels` now copies
  the original into the shadow first (`Gegl.Buffer.copy(src_rect, abyss, dst, dst_rect)`).
* `merge_shadow` applies the selection as a mask → "limit to selection" for free.
* Then `drawable.update(x, y, w, h)` and `Gimp.displays_flush()`.

## Selection, masks, layer info

* `Gimp.Selection.is_empty(image)`; `drawable.mask_intersect()` →
  `(non_empty, x, y, w, h)` in drawable coordinates. Without a selection it
  reports the whole drawable, so check `is_empty` first.
* `layer.get_mask()` (None if no mask). If the user has the mask thumbnail
  active, `drawables[0]` is a `Gimp.LayerMask`; `Gimp.Layer.from_mask(mask)`
  returns the owning layer.
* `layer.get_offsets()` → `(ok, x, y)`, `image.get_precision().value_nick`
  (e.g. `u8-non-linear`), `is_group()`, `is_text_layer()`, `get_lock_content()`.

## Undo, progress

* `image.undo_group_start()` / `undo_group_end()` – one undo step per commit.
* `merge_shadow(True)` pushes the undo step for pixel changes.
* `Gimp.progress_init(text)`, `Gimp.progress_update(fraction)`, `Gimp.progress_end()`.
* Not verified headless: actually undoing (there is no PDB call to trigger
  Edit › Undo). Covered by the manual test list.

## Committing a warp (stage 2)

Verified by `tests/gimp/smoke_bridge.py` (`run_commit`) in headless GIMP 3.2.6.

* Full precision: tiles are read and written as `"R'G'B'A float"` (or
  `"RGBA float"` for `*-linear` precisions; note `u8-non-linear` also ends in
  `linear`, so test for `-non-linear` first). 16-bit half images round-trip fine.
* Tiled streaming: `Gegl.Buffer.get(rect, 1.0, fmt, CLAMP)` per source footprint,
  `shadow.set(rect, fmt, bytes)` per output tile, then one `shadow.flush()`,
  `merge_shadow(True)`, `update()`. Every pixel is written, so the
  "transparent shadow" pitfall above does not apply here.
* New output layer: `layer.copy()`, `set_name`, `image.insert_layer(copy,
  layer.get_parent(), image.get_item_position(layer))` (lands directly above),
  `layer.set_visible(False)`, `image.set_selected_layers([copy])`. The copy
  keeps the layer mask.
* Ignoring an existing selection: `Gimp.Selection.save(image)` → channel,
  `Gimp.Selection.none(image)`, warp, then
  `image.select_item(Gimp.ChannelOps.REPLACE, channel)`, `image.remove_channel(channel)`.
* All of it inside `undo_group_start/end` → one undo step (still to be
  confirmed by hand: there is no PDB call to trigger Undo).
* The native DLL from `target/release` loads inside GIMP's own process.

## Puppet Warp (stage 3)

No GIMP API is involved beyond what stage 2 already uses: the commit path is
shared (`plugin.commit_warp`), only the tiled renderer differs. Verified in
headless GIMP (8-bit and 16-bit half): new layer, original untouched, pin
target samples its source, far pixels unchanged.

Algorithm (`warpforge/puppet.py`, mirrored in `native/src/puppet.rs`):

* **Inverse** Moving Least Squares (Schaefer et al. 2006), fitted from pin
  targets to pin sources, so each output pixel directly gets the point to
  sample. Weights `weight_i / d^2`. Closed-form similarity and rigid 2×2
  solutions; *stiffness* blends them (0 = similarity, 1 = rigid). No affine
  mode: it is undefined with fewer than 3 pins.
* Exact at pins (MLS interpolates). Plain MLS moves the whole image with one
  pin, which the brief rules out, so the displacement is multiplied by
  `g = 1 − Π(1 − k_i)`, `k_i = (1 − d²/r²)²`: 1 at every pin, 0 beyond every
  radius.
* Fold guard: `|∇k| ≤ 1.54 / r`, so a pin moved by `D` gets an effective
  radius `max(r, 2·D)`. Checked numerically (Jacobian of the map > 0): 0 of
  675 random typical edits fold; folds occur only with contradictory input
  (pins dragged across each other, a rigid segment brushing a differently
  moved pin).
* Rigid segments: linked pins move by the same offset; extra handles every
  12 px (max 32) along the chain between them are interpolated linearly
  between the pins' sources and targets, which is exact for a rigid motion.
* Rendering: the deformation is evaluated on a grid of output points every
  4 px (a *source map*), interpolated bilinearly per pixel. Grid nodes sit at
  `0.5 + k·4` globally, so tiles share nodes and a tiled render equals a
  single pass bit for bit. Each tile reads only the bounding box of its map.
  Source positions outside the layer are transparent.
* The source map is exactly the input `gegl:map-absolute` needs — relevant for
  the stage-4 NDE prototype.

## Performance (Windows, native backend, multi-threaded since stage 3)

* Preview 1024×1024, 8×8 mesh: ~15–18 ms per frame (brief: < 50 ms).
* Preview 1024×1024, 30 pins: ~10–13 ms per frame.
* Full resolution, kernel + tiling only (`tools/benchmark.py`):

  | Size | Mesh 8×8 | Puppet, 30 pins |
  |---|---|---|
  | 1000² | 0.03 s | 0.02 s |
  | 4000² | 0.67 s | 0.45 s |
  | 8000² | 2.9 s | 1.9 s |

  GEGL I/O inside GIMP comes on top.
* Pure-Python fallback: ~0.1–0.5 s for a 320 px preview, so it gets a smaller
  preview; full resolution with it is slow (minutes for large layers).

## Non-destructive effects (stage 4): not possible from a plug-in, fallback used

Prototyped in headless GIMP 3.2.6 (`python tools/run_gimp_smoke.py --script
tests/gimp/nde_probe.py` repeats the checks on any GIMP version):

* `Gimp.DrawableFilter` wraps only operations on GIMP's allow-list
  (`DrawableFilter.operation_get_available()`, 182 entries).
  **`gegl:map-absolute` and `gegl:map-relative` are not on it**:
  `DrawableFilter.new(layer, "gegl:map-absolute", …)` returns NULL
  (PyGObject: "constructor returned NULL"). The stage-1 note that they exist
  was about `Gegl.has_operation` in the plug-in process, which is irrelevant:
  filters run in the core.
* `gegl:displace` (and `gegl:bump-map`) are allowed and take aux drawables,
  but **a filter whose aux input is set with `set_aux_input()` is silently
  not appended**: `append_filter()` returns, `get_filters()` stays empty,
  whether the aux is set before or after appending. Plain filters (e.g.
  `gegl:ripple`) append fine and survive XCF save/load.
* Even if aux inputs worked, the map would live in a layer of the image's
  own precision: a u8 image clamps stored coordinates to 0…1 (verified), so
  8-bit images would get a quantised, gamma-distorted displacement.
* A Python plug-in cannot register a new GEGL operation.

**Decision:** the fallback from the brief, stated plainly in the README.

* By default the warp goes to a new layer; the original stays untouched and
  hidden. The original gets a persistent, undoable parasite
  `warpforge-source` holding a random tag (layer IDs are not stable across
  XCF save/load; parasites are). Copies made by WarpForge drop both
  parasites, so a copy is never mistaken for the original.
* The result layer gets the parasite `warpforge-effect`: the preset JSON
  (schema v1) plus `"effect": {"output": "new_layer", "source_layer": tag}`.
  In-place warps record `"output": "in_place"` and cannot be re-edited (the
  original pixels are gone).
* Opening WarpForge on a result layer (Filters menu, layer menu or
  *WarpForge: Edit Effect…*) loads the parameters, previews from the
  original and re-renders into the same result layer (rebuilt if the
  original changed size; parameters are scaled then).
* *WarpForge: Show/Hide Effect* swaps the visibility of result and original;
  *WarpForge: Remove Effect* deletes the result, shows the original and drops
  its tag. Each is one undo step and also works non-interactively.
* Verified in headless GIMP: edit, toggle, remove, in-place record, and an
  XCF save/load round trip (parameters and original pixels).
* Pitfall: `Gimp.Parasite.new(name, flags, data)` takes **signed** `gint8`
  values; bytes > 127 must be converted.
* Pitfall: GIMP caches the procedure list per plug-in file in `pluginrc`
  and re-queries only when the plug-in's `.py` changes. After adding
  procedures, re-run `tools/install.py` (it rewrites the launcher).

## Presets (stage 4)

* `warpforge/presets.py`; schema `data/schemas/warpforge-preset-v1.schema.json`
  (JSON Schema 2020-12). GIMP's Python has no `jsonschema`, so the module
  validates by hand; `tests/test_presets.py` checks both reject the same
  broken files and that written presets pass the schema.
* Extensions to the brief's example, all optional: `name`, per-pin `group`
  (rigid segments), the `effect` section (stored effects only).
  `image_width`/`image_height` are the dimensions of the *layer* the
  coordinates refer to.
* Versioning: `schema_version` is required; newer versions are refused with
  "Update WarpForge", older ones go through `MIGRATIONS[n]` (none yet).
* Size mismatch: the dialog asks before scaling a preset to the layer
  (per-axis for coordinates, geometric mean for radii).

## Tooling

* `gimp-console-3.exe -i -n --batch-interpreter=python-fu-eval -b "<code>" --quit`
  runs Python inside headless GIMP – used by `tools/run_gimp_smoke.py`.
* GIMP runs `.py` plug-ins with `pythonw.exe` on Windows: no stderr. Set
  `WARPFORGE_LOG_FILE` to get logs.
