# Licences

[Polski](LICENSES.md) · **English**

## gimp-raw-heic

Copyright © 2026 Marek Zettel.
Licensed under the **GNU General Public License, version 3 or later** (full text: [COPYING](COPYING)). The source code is in `gimp-raw-heic-<version>-source.zip` and in the project repository.

## What the binary package contains

| Component | Version | Licence | How it is included |
|---|---|---|---|
| **LibRaw** | 0.22.2 | LGPL-2.1 **or** CDDL-1.0 (choice); used under **LGPL-2.1** | statically linked into `gimp-raw-heic.exe` |
| **lensfun** (library) | 0.3.4 | **LGPL-3.0** | `liblensfun.dll` in the plug-in folder |
| **lensfun lens database** | 0.3.4 | **CC BY-SA 3.0** | `lensfun\*.xml` in the plug-in folder |
| **TRE** | 0.9.0 | BSD-2-Clause | `libtre-5.dll` (lensfun dependency) |
| **libsystre** | 1.0.2 | BSD-2-Clause | `libsystre-0.dll` (lensfun dependency) |

The licence texts are in the package's `licenses\` folder: `LibRaw-LGPL-2.1.txt`, `LibRaw-CDDL-1.0.txt`, `lensfun-LGPL-3.0.txt`, `lensfun-database-CC-BY-SA-3.0.txt`, `TRE-BSD-2-Clause.txt`, `libsystre.txt`.

Copyright: LibRaw © 2008–2025 LibRaw LLC (info@libraw.org), derived from dcraw by Dave Coffin. Lensfun © Andrew Zabolotny and the lensfun contributors. TRE © 2001–2009 Ville Laurikari. libsystre © 2015 LRN.

**GPL compatibility:**
- **LibRaw (LGPL-2.1):** may be combined with a GPL program. For static linking, LGPL requires that users can relink against another LibRaw version; the complete plug-in source with `build.ps1` and `meson.build` provides that. **CDDL is not GPL-compatible**, so it is not the licence used.
- **lensfun (LGPL-3.0):** GPL-3.0-compatible. It ships as a separate, replaceable DLL.
- **lensfun database (CC BY-SA 3.0):** applies to data, not code. It is distributed unmodified with its licence notice.

## Libraries used from the GIMP installation (not distributed with the plug-in)

| Library | Licence | Purpose |
|---|---|---|
| libgimp, libgimpui (GIMP 3.2) | LGPL-3.0-or-later | plug-in API |
| GEGL, babl | LGPL-3.0-or-later | image buffers, conversions, filters |
| GLib, GTK 3 | LGPL-2.1-or-later | user interface |
| libheif | LGPL-3.0 | HEIF/HEIC/AVIF |
| libde265 | LGPL-3.0 | HEVC decoder |
| dav1d, libaom | BSD-2-Clause (+ AOM patent licence) | AV1 decoder |
| Little CMS 2 | MIT | ICC profiles |
| GExiv2 / Exiv2 | GPL-2.0-or-later | metadata |
| libjpeg-turbo, zlib | IJG/BSD, zlib | used by LibRaw |
| LLVM OpenMP, libc++ | Apache-2.0 WITH LLVM-exception | threading, C++ |

## Acknowledgements

Apple HDR reconstruction uses the formula Apple describes in "Applying Apple HDR effect to your photos". How to apply it was checked against [apple-hdr-heic](https://github.com/johncf/apple-hdr-heic) (MIT); none of its code is part of the plug-in. A sample file from that project is used for testing only and is not distributed.

## HEVC patents (for information)

HEIC images are encoded with **HEVC (H.265)**, which is covered by patents of several licensing pools. Open-source software licences do not include patent licences, and in some countries commercial distribution of an HEVC decoder may require one. The plug-in contains no HEVC decoder of its own (it uses the libde265 that ships with GIMP) and does not encode HEVC. AV1 (AVIF) comes with a royalty-free AOM patent licence. This is information, not legal advice.
