# Flatpak

## User install (simplest, works today)

Flathub's GIMP 3.2 keeps its profile in the host's `~/.config/GIMP/3.2/`
(verified in CI with GIMP 3.2.8); older Flatpak builds used
`~/.var/app/org.gimp.GIMP/config/GIMP/3.x/`. `--flatpak` looks in both and
picks the newest profile, so start GIMP once before installing. From the
Linux ZIP:

```sh
./install.sh --flatpak
```

or from a source checkout: `python3 tools/install.py --flatpak`.

The Linux ZIP's native library is built on Ubuntu 22.04 (glibc 2.35). The
GIMP Flatpak runtime is newer, so it loads; if it ever does not, WarpForge
falls back to its Python renderer and says so in the status line.

## As a Flatpak extension

`org.gimp.GIMP.Plugin.WarpForge.json` builds the native library with the Rust
SDK extension (the crate has no dependencies, so `--offline` works) and
installs the plug-in plus AppStream metadata into the extension prefix:

```sh
flatpak-builder --user --install build-dir packaging/flatpak/org.gimp.GIMP.Plugin.WarpForge.json
```

CI (`.github/workflows/warpforge-linux-gimp.yml`, job `extension`) builds and
installs it with `flatpak-builder` against Flathub's GIMP 3.2.8 and runs the
headless smoke test with only the extension installed – the procedures,
the icon and the native library all load.

The manifest follows GIMP's `org.gimp.GIMP.Plugin` extension point (version
`3`, `plug-ins` merged from every extension, see Flathub's `org.gimp.GIMP.json`):
branch `3`, prefix `/app/extensions/WarpForge`, files in `plug-ins/warpforge/`.
`sdk` must follow GIMP's runtime (GNOME 51 for GIMP 3.2.8:
`flatpak info --show-runtime org.gimp.GIMP`). For a Flathub submission the
metainfo still needs screenshots.
