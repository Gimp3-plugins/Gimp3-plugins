# BIMP 3 — batch image processing for GIMP 3

BIMP 3 applies ordered operations to groups of images: resize, crop, flip and rotate, color adjustments, sharpening and blur, text or image watermarks, renaming and format conversion. It also supports `.cube` 1D/3D LUTs with adjustable strength and before/after preview.

## Install on Windows x64

1. Download `bimp3-v1.0.1-windows-x64.zip` from the [release](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/bimp3-v1.0.1) and extract it.
2. Open PowerShell in the extracted folder and run `./install.ps1`.
3. Restart GIMP and open **File → BIMP 3 — przetwarzanie wsadowe…**.

The interface is currently in Polish. The installer uses the Python, GTK and GEGL libraries bundled with GIMP, checks the packaged LUT accelerator and keeps a backup of a previous installation. No separate Python packages are required. Tested with GIMP 3.2.6 on Windows x64; other GIMP releases and operating systems have not been verified.

## How to use

Add operations and input images, choose an output directory, and review **Plan zapisu** (output plan) before starting. **Podgląd PRZED / PO** shows a before/after comparison. Add **Kolory z LUT (.cube)** to load a LUT and set its strength from 0 to 100%; its editor includes an automatically refreshed preview. `examples/` contains two redistributable sample LUTs.

The queue runs in a separate GIMP process. It can skip, replace or suffix colliding output names; export policies control GPS, metadata and ICC profiles. Results are first written to a temporary file, and input images and operation dependencies are protected from overwriting. **Wznów zadanie…** resumes a recorded job, and **Ponów błędne** retries failed entries.

Single 1D and 3D `.cube` tables are supported, including domain ranges. Combined 1D shaper plus 3D tables are not supported. LUTs are applied in gamma-encoded sRGB; camera-log transforms are not inferred automatically. The preview displays the edited image, not the effects of lossy export compression.

For detailed setup, use, testing, limitations and sources, see [the Polish documentation](README.md).

## Attribution and license

This is a GIMP 3 rewrite of BIMP, originally by Alessandro Francesconi. The original GIMP 2 sources and attribution are retained in [legacy-gimp2/](legacy-gimp2/). BIMP is distributed under GPL-2.0-or-later; a full copy of GPL 3, one permitted license version, is included as [LICENSE-GPL-3.0](LICENSE-GPL-3.0). Existing projects in the repository retain their own licenses.
