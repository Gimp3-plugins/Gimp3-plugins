# Licencje

**Polski** · [English](LICENSES.en.md)

## gimp-raw-heic

Copyright © 2026 Marek Zettel.
Program na licencji **GNU General Public License w wersji 3 lub nowszej** (pełny tekst: [COPYING](COPYING)). Kod źródłowy jest w paczce `gimp-raw-heic-<wersja>-source.zip` i w repozytorium projektu.

## Co zawiera paczka binarna

| Składnik | Wersja | Licencja | Jak dołączony |
|---|---|---|---|
| **LibRaw** | 0.22.2 | LGPL-2.1 **lub** CDDL-1.0 (do wyboru); używana na warunkach **LGPL-2.1** | wkompilowana statycznie w `gimp-raw-heic.exe` |
| **lensfun** (biblioteka) | 0.3.4 | **LGPL-3.0** | `liblensfun.dll` w folderze wtyczki |
| **baza obiektywów lensfun** | 0.3.4 | **CC BY-SA 3.0** | `lensfun\*.xml` w folderze wtyczki |
| **TRE** | 0.9.0 | BSD-2-Clause | `libtre-5.dll` (zależność lensfun) |
| **libsystre** | 1.0.2 | BSD-2-Clause | `libsystre-0.dll` (zależność lensfun) |

Teksty licencji są w folderze `licenses\` paczki: `LibRaw-LGPL-2.1.txt`, `LibRaw-CDDL-1.0.txt`, `lensfun-LGPL-3.0.txt`, `lensfun-database-CC-BY-SA-3.0.txt`, `TRE-BSD-2-Clause.txt`, `libsystre.txt`.

Copyright LibRaw: © 2008–2025 LibRaw LLC (info@libraw.org); LibRaw wywodzi się z dcraw autorstwa Dave'a Coffina. Lensfun: © Andrew Zabolotny i współtwórcy projektu lensfun. TRE: © 2001–2009 Ville Laurikari. libsystre: © 2015 LRN.

**Zgodność z GPL:**
- **LibRaw (LGPL-2.1):** licencja pozwala połączyć bibliotekę z programem na GPL. Przy linkowaniu statycznym LGPL wymaga możliwości przebudowania programu z inną wersją biblioteki; spełnia to udostępniony pełny kod źródłowy wtyczki razem z `build.ps1` i `meson.build`. **CDDL nie jest zgodna z GPL**, dlatego jej nie wybieramy.
- **lensfun (LGPL-3.0):** licencja jest zgodna z GPL-3.0. Biblioteka jest dołączona jako osobny plik DLL i można ją podmienić.
- **Baza lensfun (CC BY-SA 3.0):** dotyczy danych, nie kodu. Jest rozpowszechniana bez zmian, z informacją o licencji.

## Biblioteki używane z instalacji GIMP (nie są rozpowszechniane z wtyczką)

| Biblioteka | Licencja | Do czego |
|---|---|---|
| libgimp, libgimpui (GIMP 3.2) | LGPL-3.0-or-later | API wtyczek |
| GEGL, babl | LGPL-3.0-or-later | bufory obrazu, konwersje, filtry |
| GLib, GTK 3 | LGPL-2.1-or-later | interfejs |
| libheif | LGPL-3.0 | HEIF/HEIC/AVIF |
| libde265 | LGPL-3.0 | dekoder HEVC |
| dav1d, libaom | BSD-2-Clause (+ licencja patentowa AOM) | dekoder AV1 |
| Little CMS 2 | MIT | profile ICC |
| GExiv2 / Exiv2 | GPL-2.0-or-later | metadane |
| libjpeg-turbo, zlib | IJG/BSD, zlib | używane przez LibRaw |
| LLVM OpenMP, libc++ | Apache-2.0 WITH LLVM-exception | wielowątkowość, C++ |

## Podziękowania

Odtwarzanie zdjęć HDR Apple wykorzystuje wzór opisany przez Apple w dokumencie „Applying Apple HDR effect to your photos”. Sposób jego zastosowania sprawdzono z projektem [apple-hdr-heic](https://github.com/johncf/apple-hdr-heic) (MIT); jego kod nie jest częścią wtyczki. Plik testowy z tego projektu służy tylko do testów i nie jest rozpowszechniany.

## Patenty HEVC (informacyjnie)

HEIC zawiera obraz zakodowany w **HEVC (H.265)**, którego dotyczą patenty kilku grup licencyjnych. Licencja oprogramowania open source nie obejmuje licencji patentowych, a w niektórych krajach komercyjna dystrybucja dekodera HEVC może jej wymagać. Wtyczka nie zawiera własnego dekodera HEVC (używa libde265 dostarczonego z GIMP-em) i nie koduje HEVC. AV1 (AVIF) jest udostępniany z bezpłatną licencją patentową AOM. To informacja, a nie porada prawna.
