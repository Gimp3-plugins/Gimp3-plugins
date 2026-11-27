# GIMP 3 Profile Backup

A **GIMP 3** plug-in (Python 3, GObject Introspection API) that backs up the user profile
folder to a ZIP (split into parts for large profiles) and restores it. Polish and English
interface. Windows and Linux (macOS untested).

[Polski](README.md) · [Changes](CHANGES.md)

## Download

Get the packages from release
[`profile-backup-v1.0.0`](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/profile-backup-v1.0.0):
`profile-backup-v1.0.0.zip` (plug-in + `install.ps1` / `install.sh`),
`profile-backup-v1.0.0-manual.zip` (just the `profile-backup` folder to copy into the profile's
`plug-ins`) and `SHA256SUMS-v1.0.0.txt`.

## Install

Windows: `powershell -ExecutionPolicy Bypass -File .\install.ps1` · Linux/macOS: `./install.sh`.
Both detect the profile with the plug-in's own detection, copy three files into
`<profile>/plug-ins/profile-backup/`, set the executable bit on Linux and **ask before
overwriting**. Restart GIMP afterwards.

## Use

**File → Profile Backup → Back Up Profile… / Restore Profile…** (works with no image open).

*Backup* writes `GIMP3-profile-YYYYMMDD-HHMMSS.zip` (relative paths with `/`, ZIP64,
`backup_manifest.json` with per-file SHA-256, mtime and mode). Profiles above the threshold
(default 500 MB) are written as byte-split parts `.zip.001…` (default 200 MB) plus
`….manifest.json` with each part's SHA-256. To unpack by hand, concatenate the parts
(`copy /b` / `cat`). Optional 7-Zip makes it about 2× faster with the same part format.

*Restore* accepts `.zip`, `.zip.001` or `.manifest.json`. It checks that all parts are there
and that their checksums match, shows a summary, asks for confirmation, then extracts and
verifies everything **next to** the profile. A detached helper waits for GIMP to exit and only
then swaps the profile in (*replace* or *merge*), keeping the previous profile as
`<series>.before-restore-<timestamp>` and rolling back on any error. The live profile is never
modified while GIMP runs, because GIMP rewrites `sessionrc`, `toolrc` and others on exit.
The CLI (`pb_core.py restore`) restores immediately and is meant for use with GIMP closed.

Zip-slip protection: absolute paths, drive letters, `..`, NUL bytes and NTFS stream names are
rejected, and every target is checked to stay inside the profile after normalisation.

## Design notes

- The GIMP 3 profile folder is named after the **series** (`3.0`, `3.2`, …), not always `3.0`.
  Detection order: `Gimp.directory()` → `GIMP3_DIRECTORY` → known locations
  (`%APPDATA%\GIMP\3.N`, `$XDG_CONFIG_HOME/GIMP/3.N`, Flatpak, Snap, macOS), newest series first.
  GIMP 2.x profiles are only reported.
- Split archives are produced by streaming one ZIP through a seekable `SplitWriter`, so no
  double disk space is needed. They are read back through `MultiPartReader`, without a joined
  temp copy. This deviates from the original plan; the outcome is the same and it needs less
  disk space.
- Exclusions (`tmp/`, `__pycache__/`, `*.pyc`, `*.lock`, …) live in one place at the top of
  `pb_core.py`.
- Settings are stored outside the profile. Backups are refused inside the profile.
- Language: GIMP preference (`gimprc`) → `LANGUAGE`/`LC_*`/`LANG` → Windows UI language →
  `locale`. Polish for `pl*`, otherwise English, switchable in the dialog. The log is in English.

## Verified / not verified

Verified on Windows 11 with **GIMP 3.2.6** (embedded Python 3.14): plug-in registration,
non-interactive backup of a real 301 MB profile with a hash-identical restore, split archives
(zipfile and 7-Zip), merge restore with the apply-after-exit helper waiting for GIMP's PID,
paths longer than 260 characters, 48 pytest tests on Python 3.12 and 3.14, and a manual
click-through of all GTK dialogs in GIMP 3.2.6 (language switch, progress, cancel, restore,
auto-apply after exit, and the result notice on the next run).

**Not verified:** real Linux/Flatpak/Snap/macOS systems (only simulated), `install.sh`, and
whether the detached helper survives Flatpak sandbox shutdown (a manual command is shown as
the fallback).

## Tests

`python -m pytest -q`

## License

MIT – see [LICENSE](LICENSE).
