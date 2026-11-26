# Changelog

All notable changes to WarpForge. Versions follow [PEP 440](https://peps.python.org/pep-0440/).

## 1.0.0rc2 – 2026-11-26

### Fixed
- `install.sh --flatpak` and `tools/install.py --flatpak` installed into
  `~/.var/app/org.gimp.GIMP/config/GIMP`, but Flathub's GIMP 3.2 uses the
  host's `~/.config/GIMP/3.2`, so the plug-in did not appear. Both now look in
  both places and pick the newest profile.
- `install.sh` no longer falls back to a `3.0` folder when GIMP has never
  been started; it asks to start GIMP once instead.
- The Flatpak extension manifest now targets GIMP's real extension point
  (branch `3`, `plug-ins/`, GNOME SDK 51); it builds and loads.

### Added
- CI runs the headless GIMP test on Linux inside Flathub's GIMP 3.2.8, with
  the release ZIP's installer and as a Flatpak extension.

## 1.0.0rc1 – 2026-11-26

First release candidate: the complete MVP from the project brief.

### Added
- **Puppet Warp**: pins with radius and weight, stiffness (similarity ↔
  rigid Moving Least Squares), rigid segments (linked pins), fold guard,
  pin settings popover, multi-select, restore/remove.
- **Mesh Warp**: 4×4, 6×6, 8×8 or custom 2–32 meshes, fold prevention,
  border constraints, clamp to bounds.
- Live preview (≤ 1024 px) in a background thread; in-dialog undo/redo per
  gesture; zoom, pan, show original.
- Full-resolution apply in float precision, tiled, with progress, as one
  GIMP undo step; output to a new layer (default) or in place; limit to
  selection.
- **Re-editable effects** (fallback for a non-destructive filter, which GIMP
  3.2 does not allow for a warp from a plug-in): parameters stored with the
  warped layer in XCF, *Edit Effect…*, *Show/Hide Effect*, *Remove Effect*.
- **Presets**: JSON export/import, schema v1
  (`data/schemas/warpforge-preset-v1.schema.json`), validation, versioning,
  scaling to another layer size.
- Native Rust kernels (C ABI via `ctypes`, multi-threaded) with a pure-Python
  fallback.
- Installers in the ZIPs (`install.ps1`, `install.sh` with `--flatpak`), a
  draft Flatpak extension manifest, release workflow, icon, sample images.

### Known limitations
- Not a native GIMP non-destructive filter; see README.
- The layer mask is kept, not warped; text layers are warped as pixels.
- Applying cannot be cancelled half-way.
- Interactive use in GIMP's UI, Linux and Flatpak are not yet confirmed by
  hand (see README › Testing status).
