# Instagram Filters for GIMP 3

[Polski](README.pl.md) · **English**

22 Instagram-style filters plus a "Text Border" plug-in. They were originally written for GIMP 2.8 (`gimpfu`) and are ported here to **GIMP 3.x**.

**Filters → Instagram:** 1977, Amaro, Apollo, Brannan, Earlybird, Gotham, Hefe, Hudson, Inkwell, Lofi, Lord Kelvin, Mayfair, Nashville, Poprocket, Rise, Sierra, Sutro, Toaster, Valencia, Walden, Willow, X-Pro II.

**Layer → Text → Add text border…** adds an outline of the chosen width and colour around a text layer.

Each filter creates a layer group named "<Name> Effect" on top of the image and leaves the original layer untouched. Fine-tune the result by changing the opacity of the layers in the group or hiding them.

Tested on GIMP 3.2.6 (Windows 11).

## Installation (Windows)

Download the ZIP from Releases, unpack it and run `install.ps1` (right-click → "Run with PowerShell"). The script finds your GIMP 3.x folder by itself:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Manual install: copy the `instagram-filtry` and `text-border` folders to `%APPDATA%\GIMP\3.2\plug-ins\` (`3.0` instead of `3.2` for GIMP 3.0), then restart GIMP.

Linux/macOS: copy the folders to `~/.config/GIMP/3.x/plug-ins/` and make the scripts executable:
`chmod +x instagram-filtry/instagram-filtry.py text-border/text-border.py`.

## How it works

GIMP 3 no longer ships the `gimpfu` module and its Python API is completely different. Instead of hand-rewriting all 22 filters (which easily changes how they look), the package contains a compatibility layer:

```
instagram-filtry/
  instagram-filtry.py   # GIMP 3 plug-in - registers all the filters
  gimpfu_compat.py      # fakes gimpfu: translates ~50 GIMP 2 pdb.* calls to GIMP 3
  filtry/               # Marco Crippa's original scripts, unchanged
text-border/
  text-border.py        # "Text Border" rewritten natively for GIMP 3
```

To add a new GIMP 2-style filter (using the same `pdb.*` calls), just drop it into `filtry/` and it shows up in the menu.

What the compatibility layer translates:
- **Layer modes** from GIMP 2.8 are mapped to the `*_LEGACY` modes in GIMP 3, so colour blending looks as it used to.
- **Curves, levels and brightness/contrast** are converted from the 0-255 scale to the 0-1 scale used by GIMP 3.
- **Colours** are passed as 8-bit sRGB in `#rrggbb` form.
- **Fill types** are remapped, because GIMP 3 renumbered them.
- **`plug-in-rgb-noise` and `plug-in-mblur`**, which no longer exist, are replaced with the GEGL filters `gegl:noise-rgb` and `gegl:motion-blur-linear`.

## Differences from the GIMP 2 version

- **One Ctrl+Z undoes the whole filter.** In GIMP 2 the scripts disabled undo history, so the effect could not be undone.
- **An active selection no longer breaks the result.** The originals sized new layers from the selection bounds. Now the filter works on the whole image and restores the selection afterwards.
- **Foreground and background colours are left untouched.**
- **An error message instead of a silent failure.** If no layer is selected the filter shows a message, and a failed filter leaves no stray layers behind.
- **Noise and motion blur** come from GEGL. The result is very close but not pixel-identical.
- **Border width may differ by 1 px.** Python 3 divides numbers differently than Python 2, so for some image widths the border comes out 1 px wider.
- **Text Border** clears the selection when done. The original left the outline selected.

## Tests

The integration test runs every filter in headless GIMP and writes a preview grid `podglad.png`:

```
"%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-console-3.2.exe" -i --batch-interpreter python-fu-eval -b "exec(open(r'C:\path\to\repo\tests\gimp_integration.py', encoding='utf-8').read())" --quit
```

The `TEST_PHOTO` and `TEST_OUT` variables point to the test photo and the output folder.

## Credits and license

- Instagram filters: © 2013 Marco Crippa, GNU GPL v2 or later.
- Text Border: © 2016 Rebecca Breu, GNU GPL v3.
- GIMP 3 port and compatibility layer: Marek Zettel, 2026.

Everything is released under the **GNU GPL v3** (see `LICENSE`).
