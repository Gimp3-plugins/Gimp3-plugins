# Ustalenia (PSHost) — stan: Etap 9 (wersja 0.8.1)

## PODSUMOWANIE KOŃCOWE

### Kryteria akceptacji z instrukcji (stan)
| # | Kryterium | Stan |
|---|---|---|
| 1 | W menu Filtry → Photoshop jest „Zarządzaj wtyczkami / Manage plug-ins” | ✔ potwierdził użytkownik w prawdziwym GIMP-ie 3.2.6 |
| 2 | Dodanie katalogu daje wynik dla każdej wtyczki z komunikatem „zostanie użyta / nie” i powodem | ✔ użytkownik widział listę; komunikaty PL/EN testowane automatycznie |
| 3 | 32-bitowe i uszkodzone `.8bf` odrzucane z poprawnym komunikatem | ✔ 20 plików x86 odrzuconych (widoczne), uszkodzone — testy automatyczne (fuzz ucięć, nie-PE) |
| 4 | Po akceptacji GIMP restartuje się (zgoda, ostrzeżenie o niezapisanych), filtry w menu wg kategorii | ◐ filtry w menu po restarcie ✔ użytkownik; **automatyczne ponowne uruchomienie okienkowego GIMP-a nie było obserwowane** (testy z atrapą procesu i gimp-console) |
| 5 | Co najmniej jeden popularny filtr 64-bit **oraz** własny filtr testowy działają na zaznaczeniu i warstwie, Cofnij działa | ◐ własny filtr testowy: ✔ automat (zaznaczenie prostokątne, eliptyczne, alfa, 3 warianty); własna wtyczka Zetmar Kolor ✔ użytkownik (+ Cofnij ✔); popularny filtr — **Nik Color Efex Pro 4: okno otwiera się bez błędu ✔ użytkownik; zapis wyniku z jego okna do warstwy nie został potwierdzony** |
| 6 | Awaria lub zawieszenie `.8bf` nie zamyka GIMP-a | ✔ testy automatyczne (crash → kod 0xC0DE0001, zawieszenie → limit czasu, GIMP działa) i realna awaria Nik w 6b nie zamknęła GIMP-a |
| 7 | UI w pełni PL i EN, polskie znaki w ścieżkach | ◐ katalogi PL/EN kompletne (test), zrzuty okna sprawdzone; ścieżki z polskimi znakami ✔ automat (w tym uruchomienie z menu GIMP-a); **widok okna na żywo w obu językach nie był oglądany przez użytkownika w całości** |
| 8 | Instalator instaluje i odinstalowuje czysto, bez praw administratora | ◐ ✔ testy ciche (16 kontroli, HKCU, czyste odinstalowanie); **okna kreatora nie były oglądane**, instalacja na prawdziwym katalogu użytkownika z uruchomionym GIMP-em nie wykonana |
| 9 | W `ustalenia.md` lista tego, co zweryfikowane i założone, oraz znane niedziałające przypadki | ✔ ta sekcja + sekcje etapów; przypadki w `kompatybilnosc.md` |

### Zweryfikowane (automatycznie) — 6 zestawów, `ctest` 100%
`test_pe8bf` 16 · `test_runner` 28 (w tym 29 kontroli jednostkowych konfiguracji/rejestru/scalania) · `test_i18n` 11 ·
`test_gimp_e2e` 8 (prawdziwy `gimp-console`) · `test_gimp_stage6` 14 (menu, rejestr, restart, polskie ścieżki) ·
`test_installer` 16. Łącznie ≈ 93 kontrole zewnętrzne + 29 wewnętrznych. Testy odkryły i pozwoliły naprawić m.in.: błąd
rozróżniania duplikatów etykiet w menu, komunikaty krytyczne json-glib przy złośliwym `config.json`, różnicę `/` vs `\` w
porównaniu ścieżek, zawieszanie się runnera przy `ExitProcess`.

### Zweryfikowane przez użytkownika (prawdziwy GIMP 3.2.6)
Menu „Zarządzaj wtyczkami”; okno wczytuje wtyczki i pokazuje 32-bitowe; filtr uruchomiony z okna działa; Ctrl+Z po zamknięciu
okna cofa efekt; po restarcie filtry są w menu wg kategorii; Nik Color Efex Pro 4 otwiera się bez błędu po poprawce 6b.

### Założenia (niezweryfikowane)
- Układ struktur Photoshop API przyjęty z PSFilterPdn i potwierdzony empirycznie dla `FilterRecord`/`sSPBasic`; zestawy PICA
  Progress/Feature/Action Descriptor niezaimplementowane; kody błędów `-30`/`-31` (host/property) z pamięci.
- Że helper restartu przeżywa zamknięcie okienkowego GIMP-a (próba wyjścia z obiektu job); że `gimp-quit(force=FALSE)` pyta o zapis.
- Zgodność z GIMP-em 3.0/3.1 (zbudowano i przetestowano tylko 3.2.x).
- Zachowanie na obrazach 16/32-bit, bardzo dużych (> ~10 Mpx) i wtyczek z DRM.

### Licencja
**GPL-3.0-or-later** (wybór właściciela): plik `LICENSE` (oficjalny tekst GPLv3), nagłówki SPDX w 43 plikach źródłowych, `LICENSE.txt` w instalatorze, sekcje w README i `THIRD_PARTY.md`. Zależności: biblioteki GIMP-a (LGPL) linkowane dynamicznie, PSFilterPdn (MIT) tylko jako referencja układów, bez kopiowania kodu.

### Znane niedziałające / ograniczone przypadki
Tylko 64-bit, tylko filtry, tylko 8-bit RGB(A); brak channel ports, Action Manager, usług kolorów, Smart Filters, własnych
okien GPU; brak przycisku przerwania zawieszonego okna filtra (limit 30 min); „powtórz bez okna” pokazuje okno; instalator niepodpisany (SmartScreen).


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

## Etap 6b — awaria Nik Collection w GIMP-ie (zdiagnozowana i naprawiona)
- **Objaw:** Color Efex Pro 4 uruchomiony z menu pokazał własne okno „The application did crash”. **Test probe (tylko `Prepare`) tego nie wykrył** — wtyczka żąda funkcji hosta dopiero w `Start`.
- **Diagnoza (z raportu awarii wtyczki):** minidump: `EXCEPTION_ACCESS_VIOLATION` (odczyt spod adresu 0) w kodzie samego `Color Efex Pro 4.8bf` (+0x15261). Dezasemblacja: `mov rax,[rax+0x1d0]; call [rax]` — wtyczka bierze z `FilterRecord` wskaźnik `sSPBasic` (offset 0x1D0 **zgadza się** z `offsetof(FilterRecord,sSPBasic)` w `ps_types.h` — niezależne potwierdzenie układu struktury) i bez sprawdzania wywołuje `AcquireSuite`. Mój host zostawiał to pole puste.
- **Naprawa (runner):** `SPBasicSuite` + zestawy PICA: *Photoshop Handle Suite* v1/v2, *Photoshop Property Suite* v1, *Photoshop UIHooks Suite* v1, *AS ZString Suite* v1 (układy z PSFilterPdn, MIT). Nieobsługiwane zestawy (np. Action Descriptor `df135115-…` v2, Progress, Feature) zwracają `kSPSuiteNotFoundError` i są logowane jako UNSUPPORTED. Dodatkowo `displayPixels` (rysowanie podglądu przez `SetDIBitsToDevice`) według `PSPixelMap` oraz poprawiony podpis `displayPixels` w `ps_types.h`.
- **Błąd w obsłudze zawieszeń wykryty przy okazji:** `ExitProcess` w watchdogu/filtrze wyjątków czekał na wątki wtyczki Nik i runner nie kończył się w limicie czasu; zamienione na `TerminateProcess`.
- **Wynik:** wszystkie 12 filtrów x64 Nik i Topaz uruchamia się teraz w runnerze bez awarii, a Color Efex Pro 4 wczytuje obraz 640×480, liczy podglądy i go wyświetla (log wtyczki: „Displayed Image update finished”). Zgłaszane jako nieobsługiwane: zestaw Action Descriptor (wtyczki działają dalej), właściwości `unnm`, `xmpd`, `EXIF`, `plip`.
- **Test regresji:** mini-filtr `pica` dereferuje `sSPBasic` jak Nik; po wyłączeniu poprawki test się oblewa, po włączeniu przechodzi.
- **Niezweryfikowane:** pełny zapis wyniku (OK → warstwa) dla Nik/Topaz w żywym GIMP-ie; poprawność narysowanych podglądów (`displayPixels`) w oknach Dfine/Sharpener/Viveza — do obejrzenia przez użytkownika.

## Etap 7 — lokalizacja PL/EN (zweryfikowane)
- **Standardowy gettext:** msgid-y to angielskie teksty w kodzie (`_T()`, `N_()`, `ps_tr_lang()`); `po/pshost.pot` generuje `xgettext` (`po/update_pot.sh` robi też `msgmerge`), `po/pl.po` (93 komunikaty, bez fuzzy/pustych) i `po/en.po`; `msgfmt -c --check-format` buduje `locale/<lang>/LC_MESSAGES/pshost.mo` (ten sam układ, którego używa GIMP). Zamiast dwujęzycznych tabel w kodzie — jedno źródło prawdy w `.po`.
- **Wybór języka w trakcie działania:** wbudowany czytnik `.mo` (src/common/i18n.c) zamiast `libintl`, bo język musi się przełączać (Auto / Polski / English) niezależnie od locale procesu wtyczki. Katalog ładowany z `<katalog wtyczki>\locale` (lub `PSHOST_LOCALE_DIR`); jeśli go brak — z katalogu **wbudowanego** w binarkę (`cmake/embed_mo.cmake`), więc UI nie „gubi” tłumaczeń.
- **Auto:** język z `g_get_language_names()` — uwzględnia `LANGUAGE` ustawiany przez GIMP-a (jego ustawienie języka) i język systemu (ten komputer: pl-PL, `gimprc`: language „” = systemowy). Test: `LANGUAGE=pl/en` → właściwy język.
- **`set_i18n` wyłączone:** GIMP nie tłumaczy sam naszych msgid-ów, bo ręczny wybór „English” byłby nadpisany językiem GIMP-a; znika też ostrzeżenie „catalog directory does not exist”. Nazwy menu filtrów zależą od kategorii z PiPL (nietłumaczone) i etykiet z wtyczek; nazwa kategorii zastępczej: „Inne/Other”; po zmianie języka etykiety menu zmieniają się po restarcie GIMP-a (okno to komunikuje).
- **Polskie znaki w ścieżkach (UTF-8 ↔ UTF-16):** ścieżki w GLib/GTK i `config.json` są UTF-8; Windows API wywoływane przez wersje `W` (`_wfopen`, `CreateProcessW`, `LoadLibraryExW`, `SearchPathW`). Testy: katalog „Wtyczki zażółć gęślą jaźń” i plik „filtr ŁÓDŹ.8bf” — skan, probe, zapis w `config.json` jako UTF-8 oraz uruchomienie filtra z menu w prawdziwym GIMP-ie (warstwa odwrócona).
- **Testy:** `tests/test_i18n.py` (poprawność i kompletność katalogów, aktualność `.pot` względem kodu, wybór języka, polskie ścieżki).

## Etap 8 — instalator (Inno Setup 6.7.3; zweryfikowane testami cichymi)
- **Wybór narzędzia:** Inno Setup (już zainstalowany na tej maszynie, natywne wsparcie PL, instalacja per-user bez UAC, prosty skrypt Pascala do wykrywania GIMP-a); WiX odrzucony jako cięższy bez zysku dla jednego pakietu.
- **Jeden plik:** `installer/output/PSHost-Setup-0.8.1.exe` (≈2,1 MB), metadane wersji w nagłówku (VersionInfo), `PrivilegesRequired=lowest` (HKCU, bez administratora), x64. Budowa: `cmake --build build --target installer` albo `ISCC /DAppVersion=0.8.1 /DBuildDir=..\build installer\PSHost.iss`.
- **Zawartość:** `pshost.exe`, `pshost_runner.exe` (także tryb restartu — osobnego `pshost_restart.exe` nie ma, bo to ten sam runner), `locale\{pl,en}\LC_MESSAGES\pshost.mo`. **Żadnych wtyczek Photoshop ani nagłówków Adobe.** Katalog docelowy: `%APPDATA%\GIMP\<wersja>\plug-ins\pshost\` — wersja (`3.2`) wyliczona z `bin\gimp-3.x.exe` wykrytego GIMP-a. Deinstalator leży poza folderem wtyczek GIMP-a (`%LOCALAPPDATA%\PSHost`).
- **Wykrywanie GIMP-a:** wpisy Uninstall (HKCU, HKLM 64/32: nazwa „GIMP 3…”, `InstallLocation`, weryfikacja `bin\gimp-3.*.exe`) + typowe ścieżki; przetestowane na prawdziwym rejestrze (3.2, `...\Programs\GIMP 3`). **GIMP 2** jest wykrywany osobno: gdy nie ma GIMP-a 3, strona instalatora wyjaśnia, że wtyczka działa tylko z GIMP-em 3. Brak GIMP-a 3 → strona z wyborem folderu ręcznie (z walidacją) i komunikat PL/EN; w trybie cichym — przerwanie z komunikatem. GIMP < 3.2 → ostrzeżenie (zbudowano i przetestowano z 3.2).
- **GIMP uruchomiony:** instalator i deinstalator proszą o jego zamknięcie (Ponów/Anuluj) — działa też w trybie cichym (odmowa zamiast cichego nadpisywania).
- **Odinstalowanie:** usuwa pliki; pyta, czy usunąć ustawienia (`config.json`, logi, parametry); w trybie cichym zostawia je, chyba że `/PURGE`.
- **Przełączniki testowe:** `/GIMPDATA=` (inny katalog danych, pomija wykrywanie), `/NOGIMPDETECT`, zmienna `PSHOST_GIMP_PROCESS` (nazwa procesu GIMP-a do sprawdzenia „czy działa”) — dzięki nim testy nie dotykają prawdziwego GIMP-a ani jego katalogu użytkownika.
- **Testy (`tests/test_installer.py`, 16 kontroli):** kompilacja; instalacja/aktualizacja/odinstalowanie; wpisy tylko w HKCU; deinstalator poza folderem wtyczek; odmowa przy działającym GIMP-ie (instalacja i deinstalacja); zachowanie/usunięcie ustawień; polska wersja językowa; wykrycie GIMP-a w rejestrze; zachowanie przy braku GIMP-a 3.
- **SmartScreen:** instalator nie jest podpisany certyfikatem, więc Windows może ostrzegać; informacja jest w tekście po instalacji (PL/EN) i trafi do README (Etap 9). Nie omijamy tego.
- **Niezweryfikowane:** wygląd i działanie okien kreatora (strona wyboru folderu GIMP-a, strona „Gotowe do instalacji”, teksty PL/EN w GUI) — testy były ciche; instalacja na prawdziwym katalogu użytkownika z działającym GIMP-em (celowo nie zamykałem Twojego GIMP-a).

## Założenia / niezweryfikowane
- Brak Photoshop SDK na dysku; planowane własne minimalne definicje struktur (`src/common/ps_types.h`). Licencja Adobe SDK do sprawdzenia przed jakąkolwiek redystrybucją nagłówków.
- `ZetmarWatermark_64.8bf` jest filtrem — opisanym wyłącznie przez JSON PiPL (rozstrzygnięte w Etapie 2).
- Zachowanie GIMP przy zamykaniu i restarcie (API czystego zamknięcia) — do zbadania w Etapie 6.
