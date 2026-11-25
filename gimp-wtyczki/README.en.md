# GIMP 3 plug-ins (Python)

*[Polski](README.md)*

Free, open-source plug-ins for GIMP 3.x written in Python. They work fully offline: no accounts, no API keys, no data collection. Tested on GIMP 3.2.6 (Windows 11).

| Plug-in | Menu | What it does | Package |
|---|---|---|---|
| **Signature** (`podpis-zdjecia/`, [license](LICENSE): MIT) | Filters → Signature | a text signature or a logo as a new layer, 9 positions, size in % of the image, saved templates | [v1.2.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/podpis-zdjecia-v1.2.0) |
| **Meme Maker** (`meme-maker/`) | Filters → Memes | top and bottom text with an outline, text bar, live preview, JPG/PNG export. [Docs](meme-maker/README.en.md) | [v1.2.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/meme-maker-v1.2.0) |
| **LUTs (.cube)** (`lut-cube/`) | Filters → LUT | `.cube`, `.3dl` and Hald LUTs with a library, before/after preview, strength, presets, batch mode and your own look. [Docs](lut-cube/README.en.md) | [v1.2.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/lut-cube-v1.2.0) |

This folder is part of the [Gimp3-plugins](../README.md) repository. Run the commands below (installation, tests) from the `gimp-wtyczki` folder. Without parameters `install.ps1` installs all plug-ins that lie next to the script; pick one with `-Plugin podpis-zdjecia`, `-Plugin meme-maker` or `-Plugin lut-cube`.

## Language (Polish / English)

All three plug-ins are available in **Polish and English**. The interface language follows GIMP's interface language automatically (anything that is not Polish gets English). To force a language set the environment variable `GIMP_WTYCZKI_LANG=en` (or `pl`) before starting GIMP. Texts are translated at run time from `en.json` in each plug-in folder (the Polish text is the key), so a missing entry simply shows the Polish text. GIMP caches the menu labels of plug-ins; after switching the language reinstall the plug-ins (`install.ps1`) or touch the plug-in `.py` file so GIMP re-reads them. Dialogs and messages change immediately.

## Signature

Adds a signature on a photo as a **new layer at the very top of the stack**. The plug-in has two modes:

- **Filters → Signature → Text signature…** (`python-fu-podpis-tekst`) creates an editable text layer.
- **Filters → Signature → Signature from image…** (`python-fu-podpis-obraz`) inserts a logo or handwriting from a PNG, JPG, WebP, SVG or any other file GIMP can load.

Everything is one undo operation, so a single Ctrl+Z removes the signature. Existing layers stay untouched.

### Installation (Windows)

The easiest way: download `podpis-zdjecia-vX.Y.Z.zip` from the [Releases](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/podpis-zdjecia-v1.2.0), unpack it and run `install.ps1` (right click → "Run with PowerShell"), or copy the `podpis-zdjecia` folder by hand:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
# or a chosen version:
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Version 3.0
```

Manually: copy the whole `podpis-zdjecia` folder to `%APPDATA%\GIMP\3.2\plug-ins\podpis-zdjecia\podpis-zdjecia.py` (for GIMP 3.0 use `3.0` instead of `3.2`). The folder must have the same name as the `.py` file. Restart GIMP afterwards. Linux/macOS: `~/.config/GIMP/3.x/plug-ins/podpis-zdjecia/`, the file must be executable (`chmod +x`).

### Parameters

#### Common

| id | Description | Default |
|---|---|---|
| `opacity` | Opacity 0–100 % | 70 |
| `position` | 9 positions: `top-left` … `bottom-right` | `bottom-right` |
| `margin-percent` | Margin as % of the image's shorter side | 3.0 |
| `margin` | Margin in px. **0 means the percentage is used** | 0 |
| `layer-name` | Name of the new layer | Signature |
| `template` | Load a saved template (name); its settings replace those from the dialog | empty |
| `save-template` | After a successful signature, save the current settings under this name | empty |

The margin does not apply on an axis where the position is "middle".

#### Signature templates

If you use several signatures (e.g. different brands, text and logo), save each as a template: type a name in **Save as template** and add the signature. Next time type that name in **Load template** (case-insensitive). The dialog shows the list of saved templates. A text template remembers the text, font, size, color and alignment; an image template remembers the file and scale; both remember opacity, position, margin and layer name. Templates are stored in `%APPDATA%\GIMP\3.2\podpis-zdjecia\szablony.json`.

#### Text signature

| id | Description | Default |
|---|---|---|
| `text` | The signature text (a multi-line field in the dialog) | "© " + the real name from the system account (or just "©") |
| `font` | Font | the current font from GIMP's context (usually Sans-serif) |
| `size-mode` | `percent` (% of image width) or `pixels` | `percent` |
| `font-size-percent` | 0.5–50 % of the image width | 4.0 |
| `font-size-px` | 4–2000 px | 48 |
| `color` | Text color | white |
| `justify` | `auto` / `left` / `center` / `right` | `auto` |

The percentage mode makes the signature look the same relative to the frame on a 1200 px and a 6000 px photo. `justify = auto` takes the alignment from the position's column: the left column gives left alignment, the middle one centered, the right one right.

#### Signature from image

| id | Description | Default |
|---|---|---|
| `file` | The signature file | (required) |
| `scale-mode` | `percent-width` or `original` | `percent-width` |
| `scale-percent` | Signature width as % of the photo width | 15.0 |

Proportions are preserved. When shrinking the plug-in uses LoHalo interpolation, when enlarging NoHalo. If the signature does not fit the photo together with the margin it is shrunk proportionally and GIMP shows a warning.

### Calling from the PDB / a script (Python)

```python
proc = Gimp.get_pdb().lookup_procedure("python-fu-podpis-tekst")
cfg = proc.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
cfg.set_property("image", image)
cfg.set_core_object_array("drawables", image.get_selected_drawables())
cfg.set_property("text", "© Jane Doe")
cfg.set_property("position", "bottom-right")
proc.run(cfg)
```

### Tests

- Pure functions (position, margins, sizes, templates), no GIMP needed: `python -m pytest tests`
- Integration test in a real GIMP (headless, the plug-in must be installed), run from the `gimp-wtyczki` folder:
  ```
  "%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-console-3.2.exe" -i --batch-interpreter python-fu-eval -b "exec(open(r'tests/gimp_integration.py', encoding='utf-8').read())" --quit
  ```

### Known limitations

- **Space around the text.** A text layer has internal spacing above and below the letters (font metrics), so the visual bottom margin may come out slightly larger than set.
- **Size (px/%) and scale fields.** The inactive field is greyed out but not hidden. The same holds for the margin px/% fields; the label "Margin (px, 0 = use %)" says which one applies.
- **Error messages.** The plug-in returns `EXECUTION_ERROR` with a `GLib.Error` and GIMP shows that text itself. An extra `Gimp.message()` would give two identical dialogs, so it is used for warnings only.
- **A non-existent file** in a PDB call is rejected by GIMP itself at argument validation (`CALLING_ERROR`).
- **The default font** comes from GIMP's context. If it is missing the plug-in falls back to "Sans-serif" at run time.
- **Nothing is left after a failed operation.** If the layer was already created and an error followed, the plug-in removes it; the undo group and the context are always closed (`try/finally`).

## Automatic tests and releases (for contributors)

- **Tests on every change in `gimp-wtyczki/`** (GitHub Actions, `.github/workflows/gimp-wtyczki-testy.yml` in the repository root): pyflakes and pytest for all plug-ins, in two LUT variants (with numpy and pure Python), with ffmpeg as an independent reference. Tests inside GIMP itself (`tests/gimp_*.py`) are run by hand because they need an installed GIMP.
- **Release packages**: pushing a tag `<plug-in>-v<version>` (e.g. `lut-cube-v1.2.0`) runs `.github/workflows/gimp-wtyczki-wydanie.yml`, which builds the zip (for `lut-cube` together with numpy) and attaches it to the GitHub release.
- **By hand** you can build the same zip with:
  ```
  python tools/build_dist.py lut-cube 1.2.0 --require-vendor
  ```
- **Translations**: user-visible texts in the code are Polish and wrapped in `tr("…")`; the English text lives in `en.json` of each plug-in. `tests/test_i18n.py` fails when a text has no translation, when an entry is unused, or when placeholders (`%s`, `%d`) differ.
