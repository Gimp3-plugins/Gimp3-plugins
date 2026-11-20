# PSHost — Photoshop (.8bf) filters in GIMP 3

[Polski → README.pl.md](README.pl.md)

PSHost is a plug-in for **GIMP 3 on Windows (x64)** that lets you use **64-bit Photoshop filter plug-ins (`.8bf`)**
inside GIMP. You point it at folders with your Photoshop plug-ins; it tests every plug-in, tells you which ones will be
used (and why the others will not), and adds the usable ones to **Filters → Photoshop → \<Category\>**.

> **Status: 0.8.0 — works, with limits.** Tested with GIMP 3.2.6 on Windows 11. See [Known limitations](#known-limitations).
> A result of "will be used" means the plug-in passed a basic test, **not** that it works in every situation.

## What it does

- **Manage plug-ins…** (Filters → Photoshop): add / remove / rescan directories (optionally with subfolders), see a table
  of every `.8bf` found with the result (**OK / with reservations / NO**) and the reason, switch plug-ins on or off,
  remove rejected ones from the list (files on disk are never deleted), and run a filter from the **Filters** tab.
- **Two-stage check** of each plug-in: static (64-bit PE, PiPL description, entry point, RGB support, imported DLLs) and
  dynamic (the plug-in is loaded in a separate process and initialised on a tiny test image, with a time limit).
- **Filters in the menu** after you accept a GIMP restart (the window asks first and warns about unsaved images).
- Filters run **in a separate process**: a crashing or hanging plug-in does not close GIMP. The result is applied to the
  active layer, respects the selection (also irregular, anti-aliased), keeps the alpha channel and is **one Undo step**.
- **Polish and English** interface (Auto / Polski / English), Polish characters in paths work.
- **Installer** (per-user, no administrator rights).

## What it does not do (read this)

- Only **64-bit** plug-ins. 32-bit `.8bf` files are rejected ("it is a 32-bit plug-in").
- Only **filters** (`8BFM`). Import/export, format, selection and automation plug-ins are out of scope.
- **8 bits per channel, RGB(A) only.** GIMP images are converted to 8-bit sRGB for the filter and back; higher precision
  (16/32-bit float) is **reduced to 8 bits for the filtered area**. Layer alpha is not given to the filter — it is
  preserved unchanged (flat-image mode).
- Photoshop-specific host features are only partly emulated. Implemented: handles, buffers, properties, PICA
  *Handle / Property / UIHooks / ZString* suites, tiled image access, parameter storage, `displayPixels` previews.
  **Not implemented:** channel ports, Action Manager (descriptor suites), colour services, 16/32-bit modes, Smart Filters,
  GPU-bound custom windows. A plug-in that needs them may fail even if its basic test says OK.
- Plug-ins with licence protection (DRM) may refuse to work outside Photoshop.
- Each filter runs in a **new process**, so plug-ins that keep state only in memory between runs (e.g. "repeat last
  filter without a dialog") will show their window again.
- Built and tested against **GIMP 3.2.x**; other 3.x versions are untested (the installer warns for < 3.2).

## Security

A Photoshop plug-in is a DLL: **adding one runs third-party code** — during the compatibility test and whenever you use
the filter. Add only plug-ins from sources you trust. The separate process protects GIMP from crashes, not from malicious code.

## Install

1. Download `PSHost-Setup-<version>.exe` and run it (no administrator rights needed). It finds GIMP 3 automatically
   (or lets you pick its folder). If GIMP 2 is the only version found, the installer explains that PSHost needs GIMP 3.
2. Close GIMP when asked. The installer does not add any Photoshop plug-ins.
3. Start GIMP → **Filters → Photoshop → Manage plug-ins…** → **Add directory…**.

**SmartScreen:** the installer is **not code-signed**, so Windows may show "Windows protected your PC". Choose
*More info → Run anyway* only if you got the installer from a source you trust. (Code signing needs a paid certificate;
this is deliberately not worked around.)

**Uninstall:** Windows *Apps & features* → PSHost. You are asked whether to delete settings (`config.json`, logs, saved
filter parameters).

## Use

1. **Add a directory** with `.8bf` files (e.g. `C:\Program Files\Adobe\…\Plug-Ins`). Every plug-in is tested and listed:
   *"Plug-in ‘X’ will be used in GIMP."* or *"…will not be used: it is a 32-bit plug-in."*
2. Use **Remove rejected** to hide 32-bit / hidden helper entries (only from the list), or switch single plug-ins off.
3. Accept **Restart GIMP** (you are warned about unsaved images; GIMP itself asks to save them). New filters appear in
   **Filters → Photoshop → \<Category from the plug-in\>**.
4. Open an image and run a filter from the menu — or from **Manage plug-ins… → Filters → Run on current layer**.
   Settings are remembered for the next run.

Files: `%APPDATA%\GIMP\3.2\pshost\config.json` (settings and scan results), `…\pshost\params\` (saved filter parameters),
`…\pshost\registered.json` (what the running GIMP registered), `…\plug-ins\pshost\` (the program).
A scriptable procedure `pshost-run-filter` is available in GIMP's PDB.

## Build from source

Requirements: GIMP 3.2.x for Windows (its installer ships the development files), **MSYS2 UCRT64**
(`pacman -S mingw-w64-ucrt-x86_64-{gcc,pkgconf,cmake,ninja,gettext-tools}`), Inno Setup 6 (installer), Python 3 (tests).

```text
mklink /J C:\gimp3 "%LOCALAPPDATA%\Programs\GIMP 3"          # path without spaces for pkg-config
MSYSTEM=UCRT64 C:\msys64\usr\bin\bash.exe -l build.sh         # cmake + ninja -> build\
cmake --build build --target installer                        # installer\output\PSHost-Setup-<ver>.exe
ctest --test-dir build                                        # 6 suites; GIMP-based ones need GIMP + installed plug-in
```

The Photoshop SDK headers are **not** used or shipped; `src/common/ps_types.h` holds independently written definitions
(layouts cross-checked against the open-source PSFilterPdn host, MIT, and verified with real plug-ins — see
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)).

## License

PSHost is free software, licensed under the **GNU General Public License, version 3 or (at your option) any later
version** (**GPL-3.0-or-later**) — see [LICENSE](LICENSE). You may use, study, change and redistribute it under those
terms; if you receive PSHost binaries you are entitled to the corresponding source code (this repository). The licence
covers PSHost only: it does **not** cover the Photoshop plug-ins you add (each has its own licence) and it comes with no
warranty. Third-party notes: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Documents

[docs/ustalenia.md](docs/ustalenia.md) — what was verified vs assumed, per stage · [docs/kompatybilnosc.md](docs/kompatybilnosc.md) —
plug-in compatibility table · [docs/testy_reczne.md](docs/testy_reczne.md) — manual test checklist.

## Architecture

```
GIMP 3 ─ pshost.exe            GIMP plug-in (C, libgimp + GTK3): menu, manager window, scanning, registration, restart
           └ pshost_runner.exe separate 64-bit process: loads one .8bf, implements the host API, probes, restart helper
```
