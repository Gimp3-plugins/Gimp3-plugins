# gimp-raw-heic

[Polski](README.md) · **English**

A plug-in for **GIMP 3.2** (Windows 11 x64) that opens **camera RAW files** and **HDR HEIC/HEIF/AVIF photos** directly in GIMP. It needs no darktable, RawTherapee, dcraw or any other program: RAW development is done by **LibRaw 0.22.2**, compiled into the plug-in.

Version: **1.1.0** · Licence: **GPL-3.0-or-later** · Library licences: [LICENSES.en.md](LICENSES.en.md) · Changes: [CHANGELOG.md](CHANGELOG.md)

The user interface is in **English and Polish**, following GIMP's language setting.

---

## Installation

**Download** `gimp-raw-heic-<version>-win64.zip` from [Releases](https://github.com/Gimp3-plugins/Gimp3-plugins/releases).

1. Close GIMP.
2. Unzip and copy the **`gimp-raw-heic`** folder to:
   ```
   %APPDATA%\GIMP\3.2\plug-ins\
   ```
   Result: `%APPDATA%\GIMP\3.2\plug-ins\gimp-raw-heic\gimp-raw-heic.exe`.
   (Paste `%APPDATA%` into Explorer's address bar; no administrator rights are needed.)
3. Start GIMP. The first start after installing takes a few seconds longer while GIMP registers the plug-in.

The folder also contains **lensfun** (lens corrections) with its lens database and two of its dependencies. Everything else (libheif, lcms2, OpenMP, GEGL) comes from GIMP itself.

Requirements: **GIMP 3.2 or a later 3.x** from gimp.org. Built and tested with GIMP 3.2.6; GIMP 3.0.x was not tested.

### Is GIMP using this plug-in for RAW files?

GIMP uses one RAW importer at a time. This plug-in takes that role automatically unless darktable or RawTherapee was chosen before. Check **Edit → Preferences → Image Import & Export → Raw image importer**: it should say `gimp-raw-heic`.

## Supported formats

**RAW (LibRaw, about 1250 camera models):** CR2, CR3, CRW (Canon), NEF, NRW (Nikon), ARW, SRF, SR2 (Sony), DNG (including phones, Apple ProRAW, linear DNG), RAF (Fujifilm, including X-Trans), ORF (Olympus / OM System), RW2 (Panasonic), RWL (Leica), PEF (Pentax), SRW (Samsung), 3FR, FFF (Hasselblad), IIQ, CAP (Phase One), ERF (Epson), MRW, MDC (Minolta), KDC, DCR (Kodak), MEF (Mamiya), MOS (Leaf), RAW, RWZ and others LibRaw can open.

Not supported: **X3F** (Sigma) and **GPR** (GoPro); this LibRaw build lacks the modules they need. Sigma cameras that write DNG work normally.

**HEIC / HEIF / AVIF:** **HDR** files (PQ and HLG transfer, and iPhone HDR photos with a gain map) are decoded by the plug-in. Ordinary photos (8/10/12-bit, with alpha) go to **GIMP's built-in HEIF loader**, which handles them well; the plug-in adds fast thumbnails to the Open dialog.

## How to use

### Opening RAW files
*File → Open*, drag and drop, or *Open as Layers*. The **Develop RAW** dialog appears with a live preview:

| Tab | Settings |
|---|---|
| **White balance** | as shot · automatic · manual (temperature K + tint) · **neutral point** (click a grey area in the preview) · multipliers from XMP |
| **Exposure** | exposure −2…+3 EV, highlight preservation, highlight recovery (clip / unclip / blend / rebuild 3–9) with **automatic brightness compensation**, brightness, automatic brightness, **base tone curve** (medium / strong S curve; hues kept, values above 1.0 untouched) |
| **Detail** | demosaicing (bilinear, VNG, PPG, **AHD**, DCB, DHT, AAHD; X-Trans automatically), wavelet and FBDD noise reduction, chromatic aberration (R/B), hot/dead pixels, colour artefact median |
| **Lens** | **vignetting**, **distortion** and **lateral chromatic aberration** correction from the **lensfun** database (lens detected from the file, shown under the preview) |
| **Colour** | **camera profile**: ICC (.icc/.icm) or Adobe **DCP**, optionally with the profile's look (look table and tone curve) · **find a profile automatically**: a DCP made for the camera (Adobe Standard first) from your folder, `<GIMP profile>/gimp-raw-heic/profiles` or Adobe's `CameraProfiles` |
| **Geometry** | **straighten** (−45…+45°, enlarged so that no empty corners appear) and **crop** |
| **Output** | sRGB, Adobe RGB, Display P3, ProPhoto, Rec. 2020 · linear or with a tone curve · 8/16/32-bit float · half size · rotation · camera default crop |

The preview grows with the dialog. Under it:
- **100% loupe:** click the preview to see that spot at full resolution (noise, sharpness, demosaicing). Click again to go back.
- **Before / after:** left half of the preview with the **default settings** or with a **snapshot** (the *Snapshot* button remembers the current settings), right half with yours.
- **Crop:** shows the whole straightened image; drag a rectangle (rule-of-thirds grid). A click without dragging removes the crop.
- **Clipping:** clipped highlights in red, crushed shadows in blue.
- **Histogram** (RGB) with the share of clipped highlights and shadows.

At the top of the dialog is the **preset** list: built-in ("Default", "Night / high ISO", "Fast preview") and your own, with *Save as…* and *Delete*. A preset never changes the neutral point, the crop or the straightening, which belong to one photo. **Save to XMP sidecar** writes the settings to `photo.xmp` next to the RAW (Lightroom / Camera Raw read white balance, exposure, noise, lens and crop; this plug-in reads everything back). A sidecar written by another program is never replaced.

Other behaviour when opening:
- **Remembered settings:** settings are kept between sessions.
- **"Always show this dialog":** when off, files open right away. Holding **Shift** while opening inverts this.
- **XMP sidecars:** if an XMP from **Lightroom** (`photo.xmp`) or **darktable** (`photo.nef.xmp`) lies next to the RAW, its white balance, exposure, lens corrections, noise reduction and (Lightroom) crop are taken over, also when the dialog is not shown. The dialog title names the source. Option *Use XMP sidecar settings*.
- **Result:** by default a **16-bit linear** sRGB image with a correct ICC profile. **EXIF, XMP and IPTC** are carried over and kept on export.

### Develop RAW again
**Filters → RAW → Develop RAW again…**

The image remembers the original RAW path and the settings, also in XCF files. The result **replaces the pixels of the developed layer**: its non-destructive effects, mask, mode, opacity, name and position stay, and the change can be undone. Alternatively the result goes to a **new layer**. If the stored path does not point to a local disk (for example `\\server\...` in someone else's XCF), the plug-in asks first. Colour space, precision and linear light stay as the image has them (greyed out in the dialog).

### Apply these settings to other RAW files
**Filters → RAW → Apply these settings to RAW files…** opens other RAW files with the settings stored in this image. The neutral point becomes the multipliers measured on this photo; crop and straightening are copied only when asked.

### Quick non-destructive adjustments
**Filters → RAW → Quick adjustments (non-destructive)…** adds **editable GEGL effects** to the layer: exposure, colour temperature, shadows/highlights, contrast, saturation and optionally neutral **Levels** and **Curves**.

### Many files
- **File → Open → Open several RAW files…**: choose the settings once, then all files open with a progress bar. Scripts get the opened images back (`images`).
- **File → Export → Develop RAW files to a folder…**: develops the files and writes them straight to **16-bit TIFF, JPEG, 16-bit PNG, 10-bit AVIF or XCF**, without leaving them open. Existing files get a number (`-2`) or are overwritten.

In both, a photo's own XMP sidecar wins over the shared settings.

### HDR HEIC
Opening an HDR photo shows a dialog with:
- **Linear 32-bit float** (default): BT.2100 / Rec. 2020, or linear Display P3 for iPhone photos. SDR white is 1.0 and brighter parts are kept above 1.0.
- **SDR:** tone mapping (PQ/HLG) or the base image (iPhone).
- **GIMP's built-in loader.**

It also has an **HDR exposure** slider. iPhone HDR photos (iOS 14–17, Apple gain map) are reconstructed with Apple's documented formula.

Also checked with ordinary HEIC photos from a **realme 14 Pro 5G** (Display P3, EXIF).

### HDR export
*File → Export As…*, then **Select File Type → HEIF/AVIF HDR**: the image (linear, 1.0 = SDR white, brighter values kept) is written in **BT.2100 PQ or HLG**, 10 or 12 bits, BT.2020, as `.heic` (HEVC) or `.avif` (AV1). GIMP's own HEIF exporter stays the default for these extensions. HLG reaches about 3.8× SDR white; PQ up to 10 000 cd/m².

### About
*Help → About RAW / HEIC loader* shows the plug-in, LibRaw and libheif versions.

## Limitations

- **ISO 21496-1 HDR** (iPhone with iOS 18 and later) and **Ultra HDR** JPEG files (Android) are not reconstructed: libheif 1.23 does not expose those maps and JPEG belongs to GIMP's loader. Such photos open as SDR.
- **Crop and straighten** apply to the developed image; the 100% loupe shows the uncropped image. A Lightroom crop with an angle is taken over approximately (Lightroom measures the rectangle before rotating).
- **HDR export** writes no EXIF/XMP yet.
- **DCP profiles:** matrices (Forward/Color with two-illuminant interpolation), HueSatMap, LookTable and the tone curve are supported. Rare parts of the specification are skipped: triple-illuminant profiles, ProfileGainTableMap and BaselineExposureOffset.
- **XMP import** only takes settings with a clear counterpart (see [CHANGELOG.md](CHANGELOG.md)); other Lightroom and darktable parameters are ignored. Lightroom's temperature scale is computed differently, so colours may differ slightly.
- **Wavelet noise reduction** is the plug-in's own implementation (LibRaw 0.22.2's version from MSYS2 crashes).
- **GPL2/GPL3 demosaicing packs** (AMaZE, LMMSE, …) no longer exist in LibRaw since 0.20.
- **Half size** does not shrink "linear DNG" files (e.g. Apple ProRAW).
- **Develop again** keeps the image's colour space and precision; "Output colour space", "Precision" and "Linear light" apply when opening.
- **8-bit** output always uses a tone curve.
- **Damaged files** do not crash GIMP; LibRaw opens some truncated files with the missing part blank.
- **Scripts** calling `gimp_file_load` get the default settings (plus XMP); pass all settings through `file-raw-heic-raw-load`.
- **Linux** is built and unit-tested in CI (Fedora, Debian testing: `./build.sh`, `./build.sh install`), not yet tested inside GIMP.

## Uninstall

Delete `%APPDATA%\GIMP\3.2\plug-ins\gimp-raw-heic`. Your presets are in `%APPDATA%\GIMP\3.2\gimp-raw-heic\presets\`.

## Privacy

The plug-in makes no network connections and sends no data.

---

## For developers

### Building (Windows, MSYS2 CLANG64, the toolchain GIMP itself uses)

Run the commands from the `gimp-raw-heic/` subdirectory of this repository.
```powershell
.\build.ps1 -Setup      # once: MSYS2 packages (clang, meson, gimp, libraw, libheif, lensfun, ...)
.\build.ps1 -Install    # build + install to %APPDATA%\GIMP\3.x\plug-ins
.\build.ps1 -Package    # dist\gimp-raw-heic-<version>-win64.zip + source package
.\build.ps1 -UpdatePo   # refresh po/gimp-raw-heic.pot and po/pl.po
```
GitHub Actions builds the plug-in, runs the unit tests and attaches the packages to `v*` releases.

### Tests
```powershell
meson test -C build                       # unit tests (no GIMP needed)
sh tests/fetch-samples.sh                 # RAW samples from raw.pixls.us (CC0)
python tests/make_heic_samples.py         # HEIC samples (SDR, 10-bit, alpha, PQ, HLG)
.\tests\run-tests.ps1                     # tests inside gimp-console (incl. regressions)
```

### Layout
`plugin.c` registration · `raw-load.c` RAW loader and thumbnails · `raw-develop.c` LibRaw · `raw-dialog.c` dialog, preview, loupe, presets · `settings.c` settings · `presets.c` presets · `denoise.c` noise reduction · `lens.c` lensfun · `camprofile.c` ICC/DCP · `xmp.c` XMP sidecars · `image.c`, `profiles.c` images and profiles · `redevelop.c` develop again · `adjust.c` non-destructive effects · `batch.c` many files · `export-batch.c` develop to a folder · `heif-load.c` HDR HEIC and Apple gain maps · `hdr-export.c` HDR export · `geometry.c` crop and straighten · `tone.c` base tone curve · `sync.c` apply settings to other files · `util.c` · `po/` translations.

### Translations
Source strings are English. To add a language: copy `po/pl.po` to `po/<code>.po`, translate it, and add the code to `languages` in `po/meson.build`.
