# Ustalenia (PSHost) — stan: Etap 6

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
- Dodatkowe wtyczki testowe (wskazane przez użytkownika): `C:\Program Files (x86)\Topaz Labs` — 8 plików: 4 × x86 (Adjust 5, B&W 2, Lens Effects, ReStyle → NIE/32bit) i 4 × x64 (`PS_Plugins_x64`, `Plugins_x64`; wszystkie statycznie OK, entry `PluginMain`, kategoria „Topaz Labs”). Probe dynamiczny — w Etapie 4. Fusion Express 2 nie zawiera `.8bf`.
- Probe (sam `Prepare`, 64×64) na 10 filtrach x64 testowych (Zetmar ×2, Nik: Analog, Color, Dfine 2, HDR, Sharpener ×2, Silver, Viveza): wszystkie `noErr`, bez nieobsługiwanych callbacków. **Uwaga:** `Prepare` to słaby test — filtry z własnym oknem (Zetmar, Nik) robią całą pracę w `Start`.
- Zetmar Color uruchomiony przez runner: okno otwiera się, podgląd działa (metoda `inputRate`). Pełnego przebiegu (OK → zapis) nie udało się potwierdzić automatycznie.

## Etap 5 — okno zarządzania (zweryfikowane headless)
- GTK3 potwierdzone (gtk+-3.0 3.24.52 w pkgconfig GIMP-a; `gimp_ui_init`). Konfiguracja: `%APPDATA%\GIMP.2\pshost\config.json` (json-glib z instalacji GIMP-a): katalogi (+ podkatalogi), język, limit czasu testu, wyniki skanu z flagą `enabled`. Zapis atomowy (plik tmp + move). Nazwa procedury filtru: `pshost-filter-<12 znaków MD5(ścieżka|entry|nazwa)>` (do Etapu 6).
- Skan w wątku roboczym (UI nie blokuje się), ścieżki UTF-8 przez GLib; po skanie: okno podsumowania („Użyte: N, z zastrzeżeniami: K, pominięte: M” + rozwijane szczegóły; dla jednego pliku jedno zdanie).
- Testy bez ekranu: okno renderowane do GtkOffscreenWindow → PNG; skan na 3 katalogach testowych daje 42 wpisy: 14 OK / 28 NIE (tak jak `pshost_check`). Wizualnie sprawdzone zrzuty PL i EN.
- W prawdziwym GIMP-ie: procedury `pshost-manage` i `pshost-about` są rejestrowane (komunikaty `gimp-console`). **Otwarcie okna w żywym GIMP-ie — do potwierdzenia przez użytkownika.**
- Tłumaczenia UI na tym etapie: tabela EN→PL w `config.c` (`_T()`); zamiana na gettext/.po — Etap 7.

## Etap 5b — usuwanie z listy i uruchamianie filtrów z okna (zweryfikowane)
- „Usuń odrzucone” / „Usuń zaznaczone” usuwają wpisy **tylko z listy** (pliki na dysku nietknięte); wpisy trafiają do `ignored` w `config.json` i kolejne skany ich nie przywracają; „Przywróć usunięte” czyści tę listę i skanuje ponownie. Testy automatyczne: 3 kontrole.
- Karta „Filtry” w oknie: lista wtyczek użytych (OK/zastrzeżenia, włączonych) pogrupowana wg kategorii; przycisk „Uruchom na bieżącej warstwie” (także dwuklik) → `ps_filter_run`.
- `ps_filter_run` (src/plugin/filter.c) działa w prawdziwym GIMP-ie: warstwa → RGBA8 (`R'G'B'A u8`), selekcja → maska 8 bit, osobny proces runnera, wynik przez bufor cienia + `gimp_drawable_merge_shadow(undo=TRUE)` w grupie Cofnij, odświeżenie widoku. Parametry filtra zapisują się w `...\pshost\params\<proc>.bin` i są podawane przy następnym uruchomieniu.
- Procedura skryptowalna `pshost-run-filter(run-mode, image, drawables, filter, interactive)` (bez pozycji w menu). Dzięki niej test end-to-end w `gimp-console` (tests/test_gimp_e2e.py): cała warstwa odwrócona, selekcja prostokątna respektowana (prawa połowa bez zmian), nieznany filtr → czysty błąd PDB. **Cofnij:** w GIMP-ie 3 nie ma procedury PDB Cofnij, więc ten punkt wymaga ręcznego sprawdzenia (jeden krok Cofnij po filtrze).
- Ograniczenie: filtry, które pokazują okno w `Start`, wymagają interaktywnego uruchomienia; wtyczki zapamiętujące stan w pamięci procesu (np. „bez okna” przy Ctrl+F) pokażą okno ponownie, bo każdy filtr działa w nowym procesie.

## Etap 6 — filtry w menu i restart GIMP-a (zweryfikowane w gimp-console)
- **Rejestracja dynamiczna:** `query_procedures` zwraca tylko stałe procedury (manage, about, run-filter, restart), a `init_procedures` (wywoływane przy każdym starcie GIMP-a) — po jednej procedurze `pshost-filter-<hash>` na każdy włączony, użyteczny filtr, w `<Image>/Filters/Photoshop/<Kategoria z PiPL>` (brak kategorii → „Inne/Other”; `/` w kategorii → `-`; `_` w etykiecie jest podwajane, bo GIMP traktuje je jako mnemonik). Kolizje etykiet w jednym menu: dopisek `(plik.8bf)`, potem `#n`. Wstawiane do pluginrc są tylko procedury stałe, więc zmiana konfiguracji nie zostawia nieaktualnych wpisów.
- **Uruchomienie z menu:** `menu_filter_run` → `ps_filter_run` (jeden krok Cofnij, selekcja respektowana). Tryb interaktywny z menu otwiera okno filtra; „Powtórz ostatni filtr” (WITH_LAST_VALS) używa zapisanych parametrów bez Parameters (wtyczki trzymające stan tylko w pamięci procesu i tak mogą pokazać okno ponownie).
- **Stan zarejestrowany:** `registered.json` (sygnatura SHA-256 zbioru procedur + języka) zapisywany w `init_procedures`; okno porównuje ją z bieżącą konfiguracją i pokazuje „Zmień → wymagany restart”.
- **Restart (wybrany wariant):** tryb `pshost_runner --mode restart` (osobny proces pomocniczy, bez dodatkowego pliku exe) czeka na zakończenie GIMP-a (PID rodzica wtyczki, ścieżka exe z `QueryFullProcessImageName`, **bez zgadywania**), po 1,5 s uruchamia GIMP-a ponownie. Zamknięcie: wywołanie PDB `gimp-quit(force=FALSE)` — ta sama ścieżka co Plik → Zakończ, więc GIMP sam pyta o niezapisane obrazy; **procesu nie zabijamy**. Jeśli użytkownik anuluje zamykanie, pomocnik po 180 s kończy się bez uruchamiania GIMP-a (kod 124). Okno przed restartem prosi o zgodę i wymienia obrazy z niezapisanymi zmianami (`gimp_image_is_dirty`); „Później” niczego nie zamyka.
- **Zweryfikowane testami (13 kontroli):** procedura menu zarejestrowana i działa (warstwa odwrócona), `registered.json`, helper czeka/uruchamia/rezygnuje przy anulowaniu, `pshost-restart` w GIMP-ie znajduje proces rodzica, a helper przeżywa jego zakończenie; okno: wykrycie „potrzebny restart”, zgoda „Później”/„Teraz”, ostrzeżenie o niezapisanych obrazach.
- **Niezweryfikowane:** prawdziwy restart okienkowego GIMP-a (test użył gimp-console i zastępczego exe — celowo nie ruszam Twojego pulpitu); czy GIMP na Windows nie umieszcza wtyczek w obiekcie job z KILL_ON_JOB_CLOSE (helper próbuje `CREATE_BREAKAWAY_FROM_JOB`, a przy odmowie startuje bez niego); wygląd pozycji menu w żywym GIMP-ie.

## Założenia / niezweryfikowane
- Brak Photoshop SDK na dysku; planowane własne minimalne definicje struktur (`src/common/ps_types.h`). Licencja Adobe SDK do sprawdzenia przed jakąkolwiek redystrybucją nagłówków.
- `ZetmarWatermark_64.8bf` jest filtrem — opisanym wyłącznie przez JSON PiPL (rozstrzygnięte w Etapie 2).
- Zachowanie GIMP przy zamykaniu i restarcie (API czystego zamknięcia) — do zbadania w Etapie 6.
