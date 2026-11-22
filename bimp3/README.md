# BIMP dla GIMP 3 — LUT, podgląd i zadania w tle

Wtyczka do seryjnej obróbki zdjęć. Aktualna wersja używa Python 3, GTK 3, natywnego API GIMP 3 i dołączonego akceleratora LUT w C. Licencja: GPL-2.0-or-later.
Źródła oryginalnej wersji GIMP 2 i jej informacje o prawach autorskich znajdują się w `legacy-gimp2/`. Autor oryginalnego BIMP: Alessandro Francesconi. Kod jest dostępny na warunkach GPL-2.0-or-later; pełny tekst GPL 3, jednej z dozwolonych wersji licencji, znajduje się w `LICENSE-GPL-3.0`.

## Instalacja w Windows

W PowerShell, w tym katalogu:

```powershell
.\install.ps1 -CheckOnly
.\install.ps1
```

Instalator wykrywa GIMP, sprawdza biblioteki, przygotowuje kompletną wersję w osobnym katalogu i weryfikuje sumy plików oraz ładowanie modułów i akceleratora. Dopiero potem podmienia katalog wtyczki. Poprzednią wersję przenosi do `bimp3-backups` obok `plug-ins`; błąd podmiany uruchamia rollback. Obsługiwane parametry: `-GimpExe`, `-PluginDirectory`, `-CheckOnly`, `-WhatIf`.

Sprawdzona instalacja: GIMP 3.2.6, Windows x64, `%APPDATA%\GIMP\3.2\plug-ins\bimp3`. Po aktualizacji zamknij okna BIMP i uruchom ponownie GIMP. Menu: **Plik → BIMP 3 — przetwarzanie wsadowe…**. Nie trzeba mieć otwartego zdjęcia.

GIMP zawiera wymagane Python/PyGObject/GimpUi/GTK 3/GEGL. Nie trzeba instalować NumPy, pip ani kompilatora. Dołączona DLL akceleratora nie zależy od ABI Pythona i używa standardowego środowiska Windows. Jej źródło oraz `build-native.ps1` są dostarczone do przebudowy przez programistę. Na innych platformach LUT ma wolniejszą implementację Python; Linux/macOS nie były tu uruchamiane.

## Kolejka i podgląd

1. Dodaj zdjęcia albo folder, opcjonalnie z podfolderami. Foldery skanowane są porcjami; ponowne kliknięcie przycisku Folder przerywa skanowanie.
2. Dodaj i ustaw operacje; strzałki zmieniają kolejność. Dostępne: rozmiar, kadrowanie, obrót/odbicie, kolory, krzywe, wyostrzenie/rozmycie, tekstowy/obrazowy znak wodny, LUT, format, nazwy i dozwolone procedury obrazowe GIMP.
3. Zaznacz zdjęcie i otwórz zakładkę **Podgląd PRZED / PO**. Odśwież podgląd, aby zobaczyć aktualną sekwencję.
4. Wybierz folder wyników i sprawdź **Plan zapisu**. Pokazuje ścieżki oraz pomijanie lub zastępowanie bez zapisywania zdjęć.
5. Kliknij Uruchom. Praca odbywa się w osobnym konsolowym procesie GIMP; okno pozostaje responsywne. Przerwij zatrzymuje zadanie na najbliższej bezpiecznej granicy; podczas wywołania zewnętrznego eksportera trzeba poczekać na jego powrót.

Podgląd wykonuje operacje na pełnej rozdzielczości, a wyświetlany obraz jest pomniejszony. Nie symuluje strat kompresji eksportera. Pierwszy start procesu roboczego może potrwać dłużej. Podglądy i zadania mają osobne profile; główny profil GIMP nie jest nadpisywany.

Przy wyborze zdjęcia popularne formaty pojawiają się od razu po stronie PRZED, a wynik PO powstaje w tle. W edytorze LUT można najpierw wybrać zdjęcie, a dopiero potem plik `.cube`. Dla formatów obsługiwanych wyłącznie przez GIMP oba obrazy pojawią się po wczytaniu przez proces roboczy.

## LUT `.cube`

Wybierz **Dodaj → Kolory z LUT (.cube)**, wskaż plik i ustaw suwak **Siła LUT (%)**. Edytor zawiera własny podgląd PRZED/PO oraz wybór zdjęcia testowego. Zmiana pliku lub siły automatycznie zleca aktualizację podglądu; starsze żądanie jest anulowane. Suwak 0% zachowuje oryginał, 100% daje pełne przekształcenie, wartości pośrednie mieszają kolory.

Obsługiwane są pojedyncze tablice Iridas/Resolve 1D i 3D, TITLE, DOMAIN_MIN/MAX i pojedynczy INPUT_RANGE. Interpolacja 3D jest trójliniowa, z czerwonym indeksem zmieniającym się najszybciej. Alfa pozostaje zachowana. Limit pliku: 128 MB; rozmiar 1D: 2–65536, 3D: 2–129. Nieprawidłowa liczba próbek, wartości niefinitywne i niejednoznaczne nagłówki są odrzucane. Połączone tablice shaper 1D + 3D nie są obsługiwane — wyeksportuj pojedynczą tablicę 3D.

Znak wodny korzysta z listy czcionek GIMP; rozmiar i jednostkę ustawia się obok wyboru czcionki. Dawne zestawy z nazwami GTK są odczytywane również wtedy, gdy GTK dodało kursywę do rodziny bez takiej odmiany. W tym przypadku używana jest dostępna w GIMP odmiana tej samej rodziny. Wybranie fontu ponownie pokazuje faktyczną nazwę zasobu GIMP.

Operacja konwertuje obraz do sRGB i stosuje LUT do kanałów RGB z kodowaniem gamma sRGB, z zachowaniem precyzji warstwy. LUT przeznaczony do materiału Log wymaga odpowiednio przygotowanego materiału; nie jest wykonywana automatyczna interpretacja przestrzeni kamery.

## Eksport i bezpieczeństwo danych

Formaty: BMP, GIF, ICO, JPEG, PNG, TGA, TIFF, HEIF, WebP, AVIF, EXR i XCF. Dostępność zależy od kodeków GIMP. Parametry są pobierane z rzeczywistego PDB z kontrolą typów i zakresów. Dla pozostałych rozszerzeń przy zachowaniu formatu używany jest standardowy zapis GIMP.

Profile **WWW**, **druk** i **archiwum** ustawiają odpowiednio JPEG 1600 px/sRGB, TIFF 300 ppi/LZW oraz XCF. Zachowują twórcze operacje i zastępują ustawienia rozmiaru oraz formatu. Wszystkie parametry pozostają edytowalne.

W sekcji Eksport wybierzesz:

- pomijanie, zastępowanie albo przyrostki `_2`, `_3` przy kolizjach;
- zachowanie metadanych, zachowanie z usunięciem GPS lub usunięcie EXIF/IPTC/XMP;
- zachowanie przestrzeni barw albo konwersję do sRGB oraz osadzanie ICC;
- zachowanie dat plików i struktury podfolderów, również dla źródeł z różnych dysków.

Wzorce nazw: `$$` = nazwa źródłowa, `##` = numer od 1, `@@` = data/godzina. Znaczniki znajdujące się w samej nazwie zdjęcia pozostają dosłowne. Na różnych dyskach struktury otrzymują osobny folder dysku. Zdjęcia źródłowe i zależności (logo, krzywe, LUT) są chronione przed nadpisaniem. Wyniki najpierw powstają w pliku tymczasowym. Windows używa bezpiecznego zapisu również na exFAT/FAT, bez wymagania twardych dowiązań.

TIFF ma domyślnie wyłączoną osadzoną miniaturę: lokalny loader GIMP 3.2.6 traktował ją jako dodatkową stronę. ICC jest oddzielony od prywatnych metadanych. Usunięcie metadanych nie wyłącza ICC, jeśli pozostawisz zaznaczone osadzanie profilu. Nie wszystkie formaty przenoszą wszystkie rodzaje metadanych.

## Wznawianie, błędy i preferencje

Ustawienia i lista zdjęć są automatycznie zapisywane w `GIMP/3.2/bimp3-data/preferences.json`. Zestawy można również eksportować/importować niezależnie.

Każde zadanie ma `jobs/<id>/job.json`, dopisywany dziennik `events.jsonl` i `worker.log`. Wznów zadanie odtwarza stan po przerwaniu lub awarii. Ukończone wyniki z niezmienionym rozmiarem i czasem modyfikacji nie są eksportowane ponownie. Zmiana zdjęcia lub zależności blokuje wznawianie, aby nie mieszać różnych danych w jednej paczce. Przyciskiem **Ponów błędne** utworzysz nową kolejkę wyłącznie z nieudanych pozycji. Raport JSON zawiera ścieżki, statusy i szczegóły błędów. Dzienniki pozostają lokalnie; nie są wysyłane do usług zewnętrznych.

## Zgodność zestawów i ograniczenia

Nowe zestawy są plikami JSON z `bimp3: 1`; dotychczasowe zestawy nowej implementacji nadal działają. Import `.bimp` obsługuje wersję 2.x i jawnie mapuje zgodne ustawienia. Dawne USERDEF i nieodwzorowane opcje eksportu wymagają odtworzenia. Nowe USERDEF dopuszcza wyłącznie zdefiniowaną w kodzie listę natywnych operacji obrazowych — nie uruchamia globalnych poleceń ani dowolnych wtyczek z importowanego zestawu.

Filtry GEGL nie gwarantują identycznych pikseli względem GIMP 2. Krzywe wymagają uporządkowanych punktów kontrolnych; krzywe odręczne nie są obsługiwane. Ustawienia niektórych eksporterów mają nazwy angielskie. API docelowe to GIMP 3.0, ale testowane środowisko to GIMP 3.2.6 / Windows x64. Podgląd nie zastępuje oceny finalnego eksportu.

## Testy i rozwój

```powershell
.\test.ps1
.\tests\test_install.ps1
.\build-native.ps1
```

`test.ps1` uruchamia unittest i testy wewnątrz oddzielnego GIMP. Raport: `tests/integration-result.json`; obrazy i zrzuty okien: `tests/output`. `BIMP_TEST_REMOVABLE_ROOT=D:\` włącza test exFAT/FAT na nośniku; tworzony i sprzątany jest wyłącznie własny folder testowy. `BIMP_TEST_FILTER` służy do wyboru nazw testów w trakcie rozwoju; przed pełną regresją usuń tę zmienną. `test_install.ps1` sprawdza pierwszą instalację, aktualizację, backup i rollback w izolowanym katalogu testowym.

Konfiguracja Ruff jest w `pyproject.toml`; sprawdzenie: `ruff check bimp3 tests`. Ruff nie jest zależnością wtyczki. Skrypty PowerShell i moduły Python można sprawdzić bez dostępu do kont zewnętrznych. W tym dostarczonym drzewie nie ma `.git`; nie utworzono zdalnego repozytorium ani nie opublikowano wydania.

## Dokumentacja wykorzystana przy implementacji

- Oficjalny GIMP: https://developer.gimp.org/resource/writing-a-plug-in/tutorial-python/
- API GIMP: https://developer.gimp.org/api/3.0/libgimp/
- Bufory GEGL: https://developer.gimp.org/api/gegl/class.Buffer.html
- Metadane: https://developer.gimp.org/api/3.0/libgimp/class.Metadata.html
- Specyfikacja i kolejność Cube: https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/main/src/OpenColorIO/fileformats/FileFormatIridasCube.cpp
- Konfiguracja Ruff: https://docs.astral.sh/ruff/configuration/
