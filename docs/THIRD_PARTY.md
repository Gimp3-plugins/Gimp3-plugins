# Third-party material / Materiały zewnętrzne

**PSHost ships no Adobe code, no Adobe SDK headers and no Photoshop plug-ins** (the installer does not add any; the
folder `third_party/photoshop_sdk/` only explains where the SDK could be obtained and is git-ignored).

## Photoshop plug-in ABI (src/common/ps_types.h)
The structure layouts (`FilterRecord`, callback tables, PICA suites, `PSPixelMap`) are **independently written** C
definitions. Field order and sizes were cross-checked against the public, MIT-licensed host implementation
**PSFilterPdn** by Nicholas Hayes (https://github.com/0xC0000054/PSFilterPdn, `src/PSApi`), which documents binary
compatibility with the Adobe SDK, and were verified empirically with real third-party 64-bit plug-ins (for example the
offset of `sSPBasic` in `FilterRecord` was confirmed by disassembling a shipping plug-in). No source code of PSFilterPdn
was copied; its licence text is reproduced below as a courtesy and because it is the reference the layouts were
compared with.

> The MIT License (MIT) — Copyright (c) 2010-2026 Nicholas Hayes. Permission is hereby granted, free of charge, to any
> person obtaining a copy of this software and associated documentation files, to deal in the Software without
> restriction, … THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. (Full text: the repository's `License.txt`.)

Not used: **pspi** (GIMP 2, GPL, 32-bit) — only studied as an architectural precedent, no code taken.

## Libraries linked by the GIMP plug-in
GIMP 3 (libgimp, GTK 3, GLib, json-glib, GEGL, babl — LGPL), taken from the user's GIMP installation at build time and
loaded from it at run time (they are not redistributed by the PSHost installer).

## Tools used to build
MSYS2 UCRT64 (GCC, CMake, Ninja, GNU gettext), Inno Setup 6 (installer).

## PSHost's own licence
**Not decided yet** — the project owner has to choose one before public distribution (no licence file is included on purpose).

---

**PSHost nie zawiera kodu Adobe, nagłówków Adobe SDK ani wtyczek Photoshop.** Definicje struktur w `ps_types.h` napisano
niezależnie, porównując układy z otwartoźródłowym hostem PSFilterPdn (MIT) i weryfikując je na prawdziwych wtyczkach;
kodu PSFilterPdn nie kopiowano. Biblioteki GIMP-a są brane z instalacji użytkownika. **Licencja samego PSHost nie została
jeszcze wybrana** — wymaga decyzji właściciela projektu przed publiczną dystrybucją.
