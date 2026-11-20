# Ustalenia (PSHost) — stan: Etap 3

## Zweryfikowane na tej maszynie (fakty)
- GIMP **3.2.6**, instalacja per-user: `%LOCALAPPDATA%\Programs\GIMP 3`. Katalog użytkownika: `%APPDATA%\GIMP\3.2` (instrukcja zakładała 3.0 — używamy 3.2).
- Instalator GIMP zawiera pliki deweloperskie: `include\gimp-3.0`, `gtk-3.0`, `glib-2.0`, `lib\pkgconfig\gimp-3.0.pc`, biblioteki `.dll.a`. GTK 3.24.52, GLib 2.90.0, runtime UCRT. Wtyczki są więc budowane dokładnie przeciw wersji zainstalowanej.
- Toolchain: MSYS2 UCRT64 (gcc 16.2, cmake, ninja, pkgconf, gettext-tools). `pkg-config` psuje ścieżkę ze spacją („GIMP 3”) → junction bez spacji `C:\gimp3` (patrz `build.sh`).
- Kompilacja `#include <libgimp/gimp.h>` i uruchomienie z `C:\gimp3\bin` działa (`GIMP 3.2.6`).
- GIMP wykrywa wtyczkę `%APPDATA%\GIMP\3.2\plug-ins\pshost\pshost.exe`: wpis w `pluginrc` z flagą `has-init`, a przy uruchomieniu `gimp-console` ładuje procedurę `pshost-about` (komunikat o braku katalogu `locale` → trzeba `set_i18n` w Etapie 7).
- Mechanizm dynamicznej rejestracji: `GimpPlugInClass::init_procedures` jest wywoływane przy każdym starcie GIMP-a (w odróżnieniu od `query_procedures`), czyli nadaje się do rejestrowania filtrów z `config.json` (Etap 6). Źródło: `libgimp/gimpplugin.h` zainstalowanego GIMP-a.
- Wtyczki testowe: Zetmar (2 × x64) w `C:\Program Files\Adobe\Photoshop Elements 2026\Plug-Ins\Zetmar`; Nik Collection: 15 plików x64 w podkatalogach „(64-Bit)” i 15 x86 (muszą być odrzucone).

- Pozycja menu *Filtry → Photoshop → About / O wtyczce* potwierdzona przez użytkownika w GIMP 3.2.6.

## Etap 2 — format .8bf (zweryfikowane na prawdziwych plikach)
- Zasób binarny: typ **`PIPL`** (wielkie litery), id 16000+; układ: `u16 =1`, `u32 version=0`, `u32 count`, potem właściwości: sygnatura `8BIM`, klucz, `u32 id`, `u32 len`, dane dopełnione do 4. **Na Windows sygnatura i klucze są zapisane bajtami odwróconymi** (`MIB8`, `dnik`=kind, `eman`=name, `gtac`=catg, `4668`=`8664` punkt wejścia x64, `edom`=mode).
- `kind`: `8BFM` = filtr; inne (np. `8LIZ` w Nik HDR Efex — akcja) → nie filtr. `name`/`catg` to napisy Pascala (1 bajt długości). `mode` to maska big-endian: 0x1000 = RGB 8 bit, 0x0010 = RGB 16 bit.
- **Nowszy format: zasób `JSON` z obiektem `"PiPLs"`** (np. ZetmarWatermark — brak binarnego PIPL). Parser obsługuje oba; jeśli filtr jest opisany dwukrotnie (ZetmarKolor), zostaje opis binarny.
- Nik Dfine 2 ma pod-filtry z kategorią `**Hidden**` (nie mają trafiać do menu → powód „hidden”). Każdy plik Nik ma wersję x86 (odrzucana jako 32-bit) i x64 w katalogu „(64-Bit)”.
- Statyczny wynik na 30 plikach testowych: wszystkie x86 → NIE/32bit; x64: Zetmar ×2 OK, Nik: Analog, Color, Dfine 2, HDR, Sharpener ×2, Silver, Viveza OK; 7 ukrytych pod-filtrów Dfine → NIE/hidden; „Merge to HDR Efex” → NIE/not-filter. „OK” oznacza wyłącznie przejście testu statycznego (probe dynamiczny — Etap 4).
- Zależności importów sprawdzane przez `SearchPathW` (katalog wtyczki, potem standardowa ścieżka); wszystkie pliki testowe je spełniają. Test z brakującą zależnością — po zbudowaniu syntetycznego mini-filtra (Etap 3).
- Stary format bez PiPL (PIMI/PITL) — **nieobsługiwany**: wynik „no-pipl”.
- Opis PiPL w pliku może być w CP1252/MacRoman; konwertujemy jako Latin-1 → UTF-8 (przybliżenie).

## Etap 3 — runner (zweryfikowane)
- Układ `FilterRecord` (pack 4) i tablic callbacków przyjęty z publicznego, MIT-owego hosta PSFilterPdn (src/PSApi) jako referencji binarnej; własne definicje w `src/common/ps_types.h`, bez nagłówków Adobe. Sprawdzone empirycznie: prawdziwe filtry Zetmar (budowane na SDK Adobe) czytają z naszego rekordu poprawny obraz, kolory i callbacki.
- `pshost_runner.exe`: tryby `about`/`probe`/`run`, osobny proces, watchdog (kod 124), filtr wyjątków (kod 0xC0DE0001 zamiast awarii), ładowanie DLL z katalogiem wtyczki w ścieżce wyszukiwania. Wymiana obrazu: surowe RGBA8; alfa nie jest przekazywana filtrowi (przypadek „flat image”), wraca niezmieniona. Selekcja: maska 8-bit, host miesza wynik tylko gdy wtyczka zostawiła `autoMask=1`.
- Host realizuje: HandleProcs, BufferProcs, ResourceProcs (puste), PropertyProcs (nuch, mode, wchs), advanceState z kopiowaniem kafli, `samplingSupport` + `inputRate`/`maskRate` (podgląd w oknach wtyczek), parametry (uchwyt zapisywany/odczytywany z pliku).
- **Niezaimplementowane (logowane jako UNSUPPORTED):** channel ports / documentInfo (druga metoda odczytu podglądu w Zetmar), ImageServices (interpolacja), ColorServices, displayPixels, hostProcs, sSPBasic (PICA suites), descriptorParameters (Action Manager), 16/32 bit, alfa jako kanał.
- Wartości `PS_ERR_HOST_INSUFFICIENT=-30` i `PS_ERR_PROPERTY_UNDEFINED=-31` pochodzą z pamięci — **niezweryfikowane**.
- Testy: `tests/test_runner.py` (13 kontroli na syntetycznych mini-filtrach: invert, kafle, selekcja, parametry, crash, zawieszenie, brakująca zależność, brak entry) — wszystkie przechodzą.
- Probe (sam `Prepare`, 64×64) na 10 filtrach x64 testowych (Zetmar ×2, Nik: Analog, Color, Dfine 2, HDR, Sharpener ×2, Silver, Viveza): wszystkie `noErr`, bez nieobsługiwanych callbacków. **Uwaga:** `Prepare` to słaby test — filtry z własnym oknem (Zetmar, Nik) robią całą pracę w `Start`.
- Zetmar Color uruchomiony przez runner: okno otwiera się, podgląd działa (metoda `inputRate`). Pełnego przebiegu (OK → zapis) nie udało się potwierdzić automatycznie.

## Założenia / niezweryfikowane
- Brak Photoshop SDK na dysku; planowane własne minimalne definicje struktur (`src/common/ps_types.h`). Licencja Adobe SDK do sprawdzenia przed jakąkolwiek redystrybucją nagłówków.
- `ZetmarWatermark_64.8bf` jest filtrem — opisanym wyłącznie przez JSON PiPL (rozstrzygnięte w Etapie 2).
- Zachowanie GIMP przy zamykaniu i restarcie (API czystego zamknięcia) — do zbadania w Etapie 6.
