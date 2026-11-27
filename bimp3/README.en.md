# BIMP 3 — batch image processing for GIMP 3

BIMP 3 applies ordered operations to groups of images: resize, crop, flip and rotate, color adjustments, sharpening and blur, text or image watermarks, renaming and format conversion. It also supports `.cube` 1D/3D LUTs with adjustable strength and before/after preview.

## Install on Windows x64

1. Download `bimp3-v1.1.0-windows-x64.zip` from the [release](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/bimp3-v1.1.0) and extract it.
2. Open PowerShell in the extracted folder and run `./install.ps1`.
3. Restart GIMP and open **File → BIMP 3 — przetwarzanie wsadowe…** (the menu entry keeps its Polish name).

The interface is available in English and Polish. It follows the Windows display language and can be changed in the plug-in window. The installer uses the Python, GTK and GEGL libraries bundled with GIMP (any interface language), verifies the packaged LUT accelerator against its SHA-256 checksum and keeps a backup of a previous installation. No separate Python packages are required. Tested with GIMP 3.2.6 on Windows x64; other GIMP releases and operating systems have not been verified.

## How to use

Drag images or folders into the window (or use the buttons), add operations, choose an output directory, and review the output plan before starting. The before/after preview runs in a persistent background GIMP process. Add **Colours from LUT (.cube)** to load a LUT and set its strength from 0 to 100%; its editor includes an automatically refreshed preview. `examples/` contains two redistributable sample LUTs.

The queue runs in a separate GIMP process. It can skip, replace or suffix colliding output names; export policies control GPS and location tags, metadata and ICC profiles. EXIF orientation is applied before the operations (optional). Results are first written to a temporary file, and input images and operation dependencies are protected from overwriting. Interrupted jobs can be resumed, even after a crash or reboot; a file that crashes GIMP twice is marked as an error. **History and data…** lists past jobs and cleans up old jobs and preview files.

New in 1.1.0:

- resize **only shrink**, and crop that swaps the aspect ratio for portrait photos;
- name patterns such as `{name:lower}`, `{n:03}`, `{exif:%Y-%m-%d}`, `{w}x{h}`, `{folder}`;
- extra output versions (for example a thumbnail or WebP copy) next to the main result;
- maximum file size for JPEG, WebP, HEIF and AVIF (quality is chosen automatically);
- `bimp3-cli.ps1` for processing without the window and for watching a folder.

Single 1D and 3D `.cube` tables are supported, including domain ranges. Combined 1D shaper plus 3D tables are not supported. LUTs are applied in gamma-encoded sRGB; camera-log transforms are not inferred automatically. The preview displays the edited image, not the effects of lossy export compression.

For detailed setup, use, testing, limitations and sources, see [the Polish documentation](README.md) and [CHANGES.md](CHANGES.md).

## Attribution and license

This is a GIMP 3 rewrite of BIMP, originally by Alessandro Francesconi. The original GIMP 2 sources and attribution are retained in [legacy-gimp2/](legacy-gimp2/). BIMP is distributed under GPL-2.0-or-later; a full copy of GPL 3, one permitted license version, is included as [LICENSE-GPL-3.0](LICENSE-GPL-3.0). Existing projects in the repository retain their own licenses.
