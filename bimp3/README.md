# BIMP dla GIMP 3 — LUT, podgląd i zadania w tle

Wtyczka do seryjnej obróbki zdjęć. Aktualna wersja używa Python 3, GTK 3, natywnego API GIMP 3 i dołączonego akceleratora LUT w C. Licencja: GPL-2.0-or-later.
Źródła oryginalnej wersji GIMP 2 i jej informacje o prawach autorskich znajdują się w `legacy-gimp2/`. Autor oryginalnego BIMP: Alessandro Francesconi. Kod jest dostępny na warunkach GPL-2.0-or-later; pełny tekst GPL 3, jednej z dozwolonych wersji licencji, znajduje się w `LICENSE-GPL-3.0`. Opis po angielsku: [README.en.md](README.en.md).

## Instalacja w Windows

W PowerShell, w tym katalogu:

```powershell
.\install.ps1 -CheckOnly
.\install.ps1
```

Instalator wykrywa GIMP, sprawdza biblioteki, przygotowuje kompletną wersję w osobnym katalogu i weryfikuje sumy plików oraz ładowanie modułów i akceleratora. Dopiero potem podmienia katalog wtyczki. Poprzednią wersję przenosi do `bimp3-backups` obok `plug-ins`; błąd podmiany uruchamia rollback. Obsługiwane parametry: `-GimpExe`, `-PluginDirectory`, `-CheckOnly`, `-WhatIf`.

Instalator rozpoznaje wersję GIMP niezależnie od języka (np. „Edytor obrazów GIMP w wersji 3.2.6”). Sprawdzona instalacja: GIMP 3.2.6, Windows x64, `%APPDATA%\GIMP\3.2\plug-ins\bimp3`. Po aktualizacji zamknij okna BIMP i uruchom ponownie GIMP. Menu: **Plik → BIMP 3 — przetwarzanie wsadowe…**. Nie trzeba mieć otwartego zdjęcia.

GIMP zawiera wymagane Python/PyGObject/GimpUi/GTK 3/GEGL. Nie trzeba instalować NumPy, pip ani kompilatora. Dołączona DLL akceleratora nie zależy od ABI Pythona i używa standardowego środowiska Windows. Wtyczka ładuje ją tylko wtedy, gdy jej SHA-256 zgadza się z plikiem `bimp_lut_native.dll.sha256`; `build-native.ps1` zapisuje ten plik po przebudowie. Na Linuksie/macOS `build-native.sh` buduje `bimp_lut_native.so`/`.dylib` z sumą kontrolną; bez niego LUT używa wolniejszej implementacji Python. Linux/macOS nie były tu uruchamiane.

## Kolejka i podgląd

1. Dodaj zdjęcia albo folder, opcjonalnie z podfolderami, albo przeciągnij pliki i foldery na listę. Foldery skanowane są porcjami; ponowne kliknięcie przycisku Folder przerywa skanowanie. Lista pokazuje miniatury (wczytywane w tle), a pole **Filtruj** zawęża ją po nazwie, folderze lub rozszerzeniu; Usuń i Podgląd działają na widocznych, zaznaczonych pozycjach.
2. Dodaj i ustaw operacje; strzałki zmieniają kolejność. Dostępne: rozmiar (także **Tylko pomniejszaj**), kadrowanie (z opcją odwrócenia proporcji dla zdjęć pionowych), obrót/odbicie, kolory, krzywe, wyostrzenie/rozmycie, tekstowy/obrazowy znak wodny, LUT, format (z limitem rozmiaru pliku), nazwy, **dodatkowe wersje wyniku** i dozwolone procedury obrazowe GIMP.
3. Zaznacz zdjęcie i otwórz zakładkę **Podgląd PRZED / PO**. Odśwież podgląd, aby zobaczyć aktualną sekwencję.
4. Wybierz folder wyników i sprawdź **Plan zapisu**. Pokazuje ścieżki oraz pomijanie lub zastępowanie bez zapisywania zdjęć.
5. Kliknij Uruchom. Praca odbywa się w osobnym konsolowym procesie GIMP; okno pozostaje responsywne. Przerwij zatrzymuje zadanie na najbliższej bezpiecznej granicy; podczas wywołania zewnętrznego eksportera trzeba poczekać na jego powrót.

Podgląd wykonuje operacje na pełnej rozdzielczości, a wyświetlany obraz jest pomniejszony. Nie symuluje strat kompresji eksportera. Podglądy renderuje jeden stały proces GIMP, wspólny dla okna głównego i edytorów LUT: uruchamia się przy pierwszym podglądzie, a kolejne zmiany (np. suwak LUT) nie czekają na start GIMP. Proces kończy się po zamknięciu okna BIMP, po 5 minutach bezczynności albo gdy proces okna zniknie. Folder żądania jest usuwany od razu po wyświetleniu obrazów.

Podglądy i zadania używają stałych, ponumerowanych profili roboczych w `bimp3-data/profiles` (`preview-1`, `batch-1`…). Profil jest blokowany na czas pracy procesu, więc dwa okna BIMP dostają osobne profile, a liczba profili jest ograniczona. Główny profil GIMP nie jest nadpisywany.

Przy wyborze zdjęcia popularne formaty pojawiają się od razu po stronie PRZED, a wynik PO powstaje w tle. W edytorze LUT można najpierw wybrać zdjęcie, a dopiero potem plik `.cube`. Dla formatów obsługiwanych wyłącznie przez GIMP oba obrazy pojawią się po wczytaniu przez proces roboczy.

## LUT `.cube`

Wybierz **Dodaj → Kolory z LUT (.cube)**, wskaż plik i ustaw suwak **Siła LUT (%)**. Edytor zawiera własny podgląd PRZED/PO oraz wybór zdjęcia testowego. Zmiana pliku lub siły automatycznie zleca aktualizację podglądu; starsze żądanie jest anulowane. Suwak 0% zachowuje oryginał, 100% daje pełne przekształcenie, wartości pośrednie mieszają kolory.

Obsługiwane są pojedyncze tablice Iridas/Resolve 1D i 3D, TITLE, DOMAIN_MIN/MAX i pojedynczy INPUT_RANGE. Interpolacja 3D jest trójliniowa, z czerwonym indeksem zmieniającym się najszybciej. Alfa pozostaje zachowana. Limit pliku: 128 MB; rozmiar 1D: 2–65536, 3D: 2–129. Nieprawidłowa liczba próbek, wartości niefinitywne i niejednoznaczne nagłówki są odrzucane. Połączone tablice shaper 1D + 3D nie są obsługiwane — wyeksportuj pojedynczą tablicę 3D.

Znak wodny korzysta z listy czcionek GIMP; rozmiar i jednostkę ustawia się obok wyboru czcionki. Dawne zestawy z nazwami GTK są odczytywane również wtedy, gdy GTK dodało kursywę do rodziny bez takiej odmiany. W tym przypadku używana jest dostępna w GIMP odmiana tej samej rodziny. Wybranie fontu ponownie pokazuje faktyczną nazwę zasobu GIMP.

Operacja konwertuje obraz do sRGB i stosuje LUT do kanałów RGB z kodowaniem gamma sRGB, z zachowaniem precyzji warstwy. LUT przeznaczony do materiału Log wymaga odpowiednio przygotowanego materiału; nie jest wykonywana automatyczna interpretacja przestrzeni kamery.

## Orientacja EXIF

GIMP nie obraca zdjęć według znacznika EXIF Orientation przy wczytywaniu wsadowym. BIMP robi to sam, zanim wykona operacje (kadr, znak wodny i nazwy `{w}x{h}` dotyczą zdjęcia w pozycji wyświetlanej), a w wyniku ustawia Orientation = 1. Opcję **Obracaj zdjęcia zgodnie z orientacją EXIF** można wyłączyć w sekcji Eksport; podgląd stosuje to samo ustawienie.

## Eksport i bezpieczeństwo danych

Formaty: BMP, GIF, ICO, JPEG, PNG, TGA, TIFF, HEIF, WebP, AVIF, EXR i XCF. Dostępność zależy od kodeków GIMP. Parametry są pobierane z rzeczywistego PDB z kontrolą typów i zakresów. Dla pozostałych rozszerzeń przy zachowaniu formatu używany jest standardowy zapis GIMP.

Profile **WWW**, **druk** i **archiwum** ustawiają odpowiednio JPEG 1600 px/sRGB, TIFF 300 ppi/LZW oraz XCF. Zachowują twórcze operacje i zastępują ustawienia rozmiaru oraz formatu. Wszystkie parametry pozostają edytowalne.

W sekcji Eksport wybierzesz:

- pomijanie, zastępowanie albo przyrostki `_2`, `_3` przy kolizjach;
- zachowanie metadanych, zachowanie z usunięciem GPS i nazw miejsc (miasto, region, kraj, lokalizacja IPTC/XMP) lub usunięcie EXIF/IPTC/XMP;
- zachowanie przestrzeni barw albo konwersję do sRGB oraz osadzanie ICC;
- zachowanie dat plików i struktury podfolderów, również dla źródeł z różnych dysków.

Wzorce nazw (operacja **Zmiana nazwy**):

| Znacznik | Znaczenie |
|---|---|
| `$$`, `{name}`, `{name:lower}`, `{name:upper}` | nazwa źródłowa bez rozszerzenia |
| `##`, `{n}`, `{n:03}` | numer (od wartości **Numer początkowy**), opcjonalnie z zerami |
| `@@`, `{date}`, `{date:%Y%m%d}` | data i godzina uruchomienia |
| `{exif:%Y-%m-%d}` | data wykonania zdjęcia z EXIF (JPEG, TIFF, PNG eXIf); bez niej data modyfikacji |
| `{mtime:%Y-%m-%d}` | data modyfikacji pliku |
| `{w}`, `{h}` | wymiary oryginału po obrocie EXIF (PNG, JPEG, GIF, BMP, WebP, TIFF) |
| `{ext}`, `{folder}` | rozszerzenie źródła i nazwa jego folderu |

Znaczniki znajdujące się w samej nazwie zdjęcia pozostają dosłowne. Nieznane lub niedomknięte znaczniki są odrzucane przy zapisie operacji.

**Dodatkowa wersja wyniku** zapisuje obok wyniku głównego plik `<nazwa><przyrostek>.<format>`, np. `foto_min.jpg`. Wersja powstaje z obrazu w miejscu sekwencji, w którym stoi operacja (np. przed znakiem wodnym), może być pomniejszona do najdłuższego boku i mieć własny format, parametry i limit rozmiaru. Wersje są publikowane dopiero po udanym zapisie wyniku głównego; uwzględniają je plan zapisu, kolizje (`_2` dotyczy całej grupy) i wznawianie zadań.

**Maksymalny rozmiar pliku** (format i wersje) wyszukuje binarnie najwyższą jakość eksportera mieszczącą się w limicie (JPEG, WebP, HEIF, AVIF; najwyżej ok. 10 zapisów). Jeśli nawet najniższa jakość jest za duża, pozycja kończy się błędem z osiągniętym rozmiarem. Na różnych dyskach struktury otrzymują osobny folder dysku. Zdjęcia źródłowe i zależności (logo, krzywe, LUT) są chronione przed nadpisaniem. Wyniki najpierw powstają w pliku tymczasowym. Windows używa bezpiecznego zapisu również na exFAT/FAT, bez wymagania twardych dowiązań.

TIFF ma domyślnie wyłączoną osadzoną miniaturę: lokalny loader GIMP 3.2.6 traktował ją jako dodatkową stronę. ICC jest oddzielony od prywatnych metadanych. Usunięcie metadanych nie wyłącza ICC, jeśli pozostawisz zaznaczone osadzanie profilu. Nie wszystkie formaty przenoszą wszystkie rodzaje metadanych.

## Wznawianie, błędy i preferencje

Ustawienia i lista zdjęć są automatycznie zapisywane w `GIMP/3.2/bimp3-data/preferences.json`. Zestawy można również eksportować/importować niezależnie.

Każde zadanie ma `jobs/<id>/job.json`, dopisywany dziennik `events.jsonl` i `worker.log`. Wznów zadanie odtwarza stan po przerwaniu lub awarii, również po restarcie komputera: blokada `.worker.lock` zawiera numer i czas startu procesu, więc blokada martwego procesu (także przy ponownym użyciu numeru PID) jest usuwana automatycznie. Plik, przy którym proces GIMP padł dwukrotnie, jest oznaczany jako błąd zamiast zapętlać wznawianie; **Ponów błędne** pozwala spróbować ponownie. Ukończone wyniki z niezmienionym rozmiarem i czasem modyfikacji nie są eksportowane ponownie. Zmiana zdjęcia lub zależności blokuje wznawianie, aby nie mieszać różnych danych w jednej paczce. Przyciskiem **Ponów błędne** utworzysz nową kolejkę wyłącznie z nieudanych pozycji. Raport JSON zawiera ścieżki, statusy i szczegóły błędów. Dzienniki pozostają lokalnie; nie są wysyłane do usług zewnętrznych.

**Historia i dane…** pokazuje zadania (data, stan, wyniki, rozmiar). Pozwala wznowić lub usunąć zaznaczone, usunąć zadania starsze niż N dni, otworzyć folder zadania i wyczyścić pozostałości podglądów (także z poprzednich wersji). Uruchomionego i otwartego w oknie zadania nie można usunąć.

## Język interfejsu

Interfejs jest dostępny po polsku i angielsku. Domyślnie wybierany jest język Windows (polski dla polskiego interfejsu systemu, w przeciwnym razie angielski). Ustawienie **Język interfejsu** w sekcji Eksport zapisuje wybór w preferencjach i działa po ponownym otwarciu okna. Zmienna `BIMP_LANG=pl|en` ma pierwszeństwo. Komunikaty błędów są tłumaczone przy wyświetlaniu; nieprzetłumaczone teksty pozostają po polsku.

## Wiersz poleceń i obserwowany folder

`bimp3-cli.ps1` przetwarza zdjęcia zapisanym zestawem bez otwierania okna, przez procedurę PDB `plug-in-bimp3`. Używa osobnego, stałego profilu w `%LOCALAPPDATA%\bimp3-cli\profile`, więc główny profil GIMP nie jest zmieniany, a kolejne uruchomienia są szybsze.

```powershell
.\bimp3-cli.ps1 -Settings .\examples\web-1600.bimp3.json -InputFolder D:\Zdjecia -Output D:\Wyniki
```

```powershell
.\bimp3-cli.ps1 -Settings web.json -InputFolder D:\Import -Output D:\Web -Watch -Collision suffix
```

Parametry: `-Files`, `-InputFolder`, `-Recurse`, `-Collision skip|replace|suffix`, `-Metadata strip-gps|preserve|strip`, `-OutputColor preserve|srgb`, `-KeepHierarchy`, `-KeepDates`, `-NoAutoOrient`, `-NoColorProfile`, `-GimpExe`, `-PluginDirectory`. Każdy plik jest wypisywany ze statusem; kod wyjścia 1 oznacza błąd. W trybie `-Watch` (co `-PollSeconds` s) plik jest przetwarzany dopiero, gdy jego rozmiar i data nie zmieniły się między dwoma przeglądami. Przetworzone pliki są zapamiętywane w `.bimp3-watch.json` w folderze wyników; plik z błędem zostanie ponowiony po zmianie. Zatrzymanie: Ctrl+C.

Procedura PDB ma nowe, opcjonalne argumenty: `output-color`, `embed-color-profile`, `auto-orient` i `report-file` (raport JSON dla każdego zdjęcia). `overwrite` pozostaje dla zgodności i oznacza to samo co `collision-policy=replace`.

## Zgodność zestawów i ograniczenia

Nowe zestawy są plikami JSON z `bimp3: 1`; dotychczasowe zestawy nowej implementacji nadal działają. Import `.bimp` obsługuje wersję 2.x i jawnie mapuje zgodne ustawienia. Dawne USERDEF i nieodwzorowane opcje eksportu wymagają odtworzenia. Nowe USERDEF dopuszcza wyłącznie zdefiniowaną w kodzie listę natywnych operacji obrazowych — nie uruchamia globalnych poleceń ani dowolnych wtyczek z importowanego zestawu.

Filtry GEGL nie gwarantują identycznych pikseli względem GIMP 2. Krzywe wymagają uporządkowanych punktów kontrolnych; krzywe odręczne nie są obsługiwane. Ustawienia niektórych eksporterów mają nazwy angielskie. API docelowe to GIMP 3.0, ale testowane środowisko to GIMP 3.2.6 / Windows x64. Podgląd nie zastępuje oceny finalnego eksportu.

## Testy i rozwój

```powershell
.\test.ps1
.\tests\test_install.ps1
.\tests\test_cli.ps1
.\build-native.ps1
python build-release.py
```

`test.ps1` uruchamia unittest i testy wewnątrz oddzielnego GIMP. Raport: `tests/integration-result.json`; obrazy i zrzuty okien: `tests/output`. `BIMP_TEST_REMOVABLE_ROOT=D:\` włącza test exFAT/FAT na nośniku; tworzony i sprzątany jest wyłącznie własny folder testowy. `BIMP_TEST_FILTER` służy do wyboru nazw testów w trakcie rozwoju; przed pełną regresją usuń tę zmienną. `test_install.ps1` sprawdza pierwszą instalację, aktualizację, backup i rollback w izolowanym katalogu testowym. `test_cli.ps1` sprawdza pojedynczy przebieg i obserwowany folder (wymaga obrazu testowego z `test.ps1`).

`build-release.py` odmawia spakowania wydania, jeśli `tests/integration-result.json` pochodzi z przebiegu z filtrem, ma błędy, mniej niż 28 testów albo jest starszy niż kod. Zapisuje też `tests/release-result.json` z sumami SHA-256 plików wtyczki. Testy ustawiają `BIMP_LANG=pl`, bo sprawdzają polskie komunikaty; CI uruchamia testy jednostkowe na Pythonie 3.12 i 3.14 (wersja dołączona do GIMP 3.2).

Konfiguracja Ruff jest w `pyproject.toml` (błędy składni, Pyflakes i flake8-bugbear); sprawdzenie: `ruff check bimp3 tests`. Ruff nie jest zależnością wtyczki. Skrypty PowerShell i moduły Python można sprawdzić bez dostępu do kont zewnętrznych.

## Dokumentacja wykorzystana przy implementacji

- Oficjalny GIMP: https://developer.gimp.org/resource/writing-a-plug-in/tutorial-python/
- API GIMP: https://developer.gimp.org/api/3.0/libgimp/
- Bufory GEGL: https://developer.gimp.org/api/gegl/class.Buffer.html
- Metadane: https://developer.gimp.org/api/3.0/libgimp/class.Metadata.html
- Specyfikacja i kolejność Cube: https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/main/src/OpenColorIO/fileformats/FileFormatIridasCube.cpp
- Konfiguracja Ruff: https://docs.astral.sh/ruff/configuration/
