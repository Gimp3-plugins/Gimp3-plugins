# Flatpak

## User install (simplest, works today)

Flatpak GIMP reads user plug-ins from
`~/.var/app/org.gimp.GIMP/config/GIMP/3.x/plug-ins/`. From the Linux ZIP:

```sh
./install.sh --flatpak
```

or from a source checkout: `python3 tools/install.py --flatpak`.

The Linux ZIP's native library is built on Ubuntu 22.04 (glibc 2.35). The
GIMP Flatpak runtime is newer, so it loads; if it ever does not, WarpForge
falls back to its Python renderer and says so in the status line.

## As a Flatpak extension (draft, not yet built)

`org.gimp.GIMP.Plugin.WarpForge.json` builds the native library with the Rust
SDK extension (the crate has no dependencies, so `--offline` works) and
installs the plug-in plus AppStream metadata into the extension prefix:

```sh
flatpak-builder --user --install build-dir packaging/flatpak/org.gimp.GIMP.Plugin.WarpForge.json
```

**Unverified:** this manifest was written on Windows and has not been run
through `flatpak-builder`. Before using or submitting it to Flathub, check:

- `sdk` must match the runtime of the installed GIMP
  (`flatpak info --show-runtime org.gimp.GIMP` → use the same GNOME version);
- the plug-in path inside the extension (`lib/gimp/3.0/plug-ins`) against the
  `org.gimp.GIMP.Plugin` extension point of the current GIMP Flatpak;
- Flathub additionally needs screenshots in the metainfo.
