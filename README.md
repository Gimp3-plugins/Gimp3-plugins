# gimp-raw-heic

**Polski** · [English](README.en.md)

Wtyczka do **GIMP 3.2** (Windows 11 x64), która otwiera **pliki RAW z aparatów** oraz **zdjęcia HEIC/HEIF/AVIF z HDR** bezpośrednio w GIMP. Nie potrzebuje darktable, RawTherapee, dcraw ani żadnego innego programu: wywoływanie RAW robi biblioteka **LibRaw 0.22.2**, wkompilowana w plik wtyczki.

Wersja: **1.0.0** · Licencja: **GPL-3.0-or-later** · Licencje bibliotek: [LICENSES.md](LICENSES.md) · Zmiany: [CHANGELOG.md](CHANGELOG.md)

Interfejs jest **po polsku i po angielsku**, zgodnie z językiem ustawionym w GIMP.

---

## Instalacja

**Pobierz** plik `gimp-raw-heic-<wersja>-win64.zip` z zakładki [Releases](https://github.com/zetmar-collab/gimp-raw-heic/releases).

1. Zamknij GIMP.
2. Rozpakuj ZIP. Folder **`gimp-raw-heic`** skopiuj do:
   ```
   %APPDATA%\GIMP\3.2\plug-ins\
   ```
   Wynik: `%APPDATA%\GIMP\3.2\plug-ins\gimp-raw-heic\gimp-raw-heic.exe`.
   (Ścieżkę `%APPDATA%` wklej w pasek adresu Eksploratora; nie potrzeba uprawnień administratora.)
3. Uruchom GIMP. Pierwsze uruchomienie po instalacji trwa kilka sekund dłużej, bo GIMP rejestruje nową wtyczkę.

W folderze są też biblioteka **lensfun** (korekcja obiektywów) z bazą obiektywów i dwie jej zależności. Pozostałe biblioteki (libheif, lcms2, OpenMP, GEGL) wtyczka bierze z GIMP-a.

Wymagania: **GIMP 3.2 lub nowszy 3.x** w wersji z gimp.org. Zbudowano i przetestowano na GIMP 3.2.6. Na GIMP 3.0.x wtyczki nie testowano.

### Czy GIMP używa tej wtyczki do RAW?

GIMP używa naraz tylko jednego importera RAW. Wtyczka przejmuje tę rolę automatycznie, o ile wcześniej nie wybrano darktable lub RawTherapee. Sprawdzisz to w **Edycja → Preferencje → Import i eksport obrazów → Importer RAW**: powinno tam być `gimp-raw-heic`.

## Obsługiwane formaty

**RAW (przez LibRaw, ok. 1250 modeli aparatów):** CR2, CR3, CRW (Canon), NEF, NRW (Nikon), ARW, SRF, SR2 (Sony), DNG (także z telefonów, Apple ProRAW, linear DNG), RAF (Fujifilm, także X-Trans), ORF (Olympus / OM System), RW2 (Panasonic), RWL (Leica), PEF (Pentax), SRW (Samsung), 3FR, FFF (Hasselblad), IIQ, CAP (Phase One), ERF (Epson), MRW, MDC (Minolta), KDC, DCR (Kodak), MEF (Mamiya), MOS (Leaf), RAW, RWZ i inne, które otwiera LibRaw.

Nieobsługiwane: **X3F** (Sigma) i **GPR** (GoPro), bo ta kompilacja LibRaw nie zawiera potrzebnych modułów. Aparaty Sigma zapisujące DNG działają normalnie.

**HEIC / HEIF / AVIF:** pliki **HDR** (krzywe PQ i HLG oraz zdjęcia HDR z iPhone'a z mapą wzmocnienia) wtyczka dekoduje sama. Zwykłe zdjęcia (8/10/12-bit, z kanałem alfa) przekazuje do **wbudowanego w GIMP modułu HEIF**, który robi to dobrze, i dokłada szybkie miniatury w oknie Otwórz.

## Jak używać

### Otwieranie RAW
*Plik → Otwórz*, przeciągnięcie pliku na okno albo *Otwórz jako warstwy*. Pokaże się okno **Wywołaj RAW** z podglądem na żywo:

| Zakładka | Ustawienia |
|---|---|
| **Balans bieli** | z aparatu · automatyczny · ręczny (temperatura K + tint) · **punkt neutralny** (kliknij szary obszar w podglądzie) · mnożniki z XMP |
| **Ekspozycja** | ekspozycja −2…+3 EV, ochrona świateł, odzyskiwanie prześwietleń (obetnij / nie obcinaj / mieszaj / odbuduj 3–9) z **automatyczną kompensacją jasności**, jasność, automatyczna jasność, **bazowa krzywa tonalna** (średni / mocny kontrast w kształcie S; odcienie zachowane, wartości powyżej 1,0 bez zmian) |
| **Szczegóły** | demozaikowanie (dwuliniowe, VNG, PPG, **AHD**, DCB, DHT, AAHD; X-Trans automatycznie), redukcja szumu falkowa i FBDD, aberracja chromatyczna (R/B), gorące i martwe piksele, mediana artefaktów barwnych |
| **Obiektyw** | korekcja **winiety**, **dystorsji** i **poprzecznej aberracji chromatycznej** z bazy **lensfun** (obiektyw rozpoznawany z pliku, widoczny pod podglądem) |
| **Kolor** | **profil aparatu**: ICC (.icc/.icm) albo Adobe **DCP**, opcjonalnie z „wyglądem” profilu (tabela wyglądu i krzywa tonalna) · **automatyczny wybór profilu**: DCP dla danego aparatu (najpierw Adobe Standard) z Twojego folderu, `<profil GIMP>/gimp-raw-heic/profiles` albo folderu Adobe `CameraProfiles` |
| **Geometria** | **prostowanie** (−45…+45°, z powiększeniem bez pustych narożników) i **kadrowanie** |
| **Wyjście** | sRGB, Adobe RGB, Display P3, ProPhoto, Rec. 2020 · liniowe lub z krzywą · 8/16/32-bit float · połowa rozmiaru · obrót · kadrowanie aparatu |

Podgląd rośnie razem z oknem. Pod nim są:
- **Lupa 100%**: kliknij podgląd, aby zobaczyć to miejsce w pełnej rozdzielczości (szum, ostrość, demozaikowanie). Ponowne kliknięcie wraca do całości.
- **Przed / po**: lewa połowa podglądu z **ustawieniami domyślnymi** albo z **migawką** (przycisk *Migawka* zapamiętuje bieżące ustawienia), prawa z Twoimi.
- **Kadruj**: pokazuje cały wyprostowany obraz; przeciągnij prostokąt (z siatką trójpodziału). Kliknięcie bez przeciągania usuwa kadr.
- **Przepalenia**: przepalone światła na czerwono, zgniecione cienie na niebiesko.
- **Histogram** RGB z udziałem przepalonych świateł i cieni.

U góry okna jest lista **presetów**: wbudowane („Domyślne”, „Noc / wysokie ISO”, „Szybki podgląd”) i własne, z przyciskami *Zapisz jako…* i *Usuń*. Preset nie zmienia punktu neutralnego, kadru ani prostowania, bo te zależą od zdjęcia. **Zapisz do pliku XMP** zapisuje ustawienia do `zdjecie.xmp` obok pliku RAW (Lightroom / Camera Raw odczyta balans bieli, ekspozycję, szum, obiektyw i kadr; ta wtyczka odczyta wszystko). Pliku XMP innego programu wtyczka nigdy nie zastępuje.

Inne zachowania przy otwieraniu:
- **Pamięć ustawień:** ustawienia są zapamiętywane między sesjami.
- **„Zawsze pokazuj to okno”:** gdy wyłączone, pliki otwierają się od razu. **Shift** przy otwieraniu odwraca to zachowanie.
- **Pliki XMP:** jeśli obok pliku RAW leży XMP z **Lightrooma** (`zdjecie.xmp`) albo **darktable** (`zdjecie.nef.xmp`), wtyczka przejmuje z niego balans bieli, ekspozycję, korekcje obiektywu, redukcję szumu i (z Lightrooma) kadr, także gdy okno się nie pokazuje. Tytuł okna pokazuje źródło ustawień. Opcja *Użyj ustawień z pliku XMP*.
- **Obraz wynikowy:** domyślnie **16-bit liniowy** w sRGB z poprawnym profilem ICC. **EXIF, XMP i IPTC** są przenoszone i zapisywane przy eksporcie.

### Ponowne wywołanie RAW
**Filtry → RAW → Wywołaj RAW ponownie…**

Obraz pamięta ścieżkę oryginalnego pliku RAW i użyte ustawienia, także w pliku XCF. Wynik **zastępuje piksele wywołanej warstwy**: jej efekty nieniszczące, maska, tryb, krycie, nazwa i pozycja zostają, a całość da się cofnąć. Alternatywnie wynik trafia na **nową warstwę**. Jeśli zapisana ścieżka nie prowadzi na dysk lokalny (np. `\\serwer\...` w cudzym pliku XCF), wtyczka najpierw pyta o zgodę. Przestrzeń barw, precyzja i światło liniowe zostają takie, jakie ma obraz (w oknie są wyszarzone).

### Zastosuj ustawienia do innych plików RAW
**Filtry → RAW → Zastosuj te ustawienia do plików RAW…** otwiera inne pliki RAW z ustawieniami zapisanymi w tym obrazie. Punkt neutralny zamienia się w mnożniki zmierzone na tym zdjęciu; kadr i prostowanie są kopiowane tylko na życzenie.

### Szybka korekta nieniszcząca
**Filtry → RAW → Szybka korekta (nieniszcząca)…** dodaje do warstwy **edytowalne efekty GEGL**: ekspozycję, temperaturę barwową, cienie/światła, kontrast, nasycenie oraz opcjonalnie neutralne **Poziomy** i **Krzywe**.

### Wiele plików
- **Plik → Otwórz → Otwórz wiele plików RAW…**: ustawienia wybierasz raz, wtyczka otwiera wszystkie pliki z paskiem postępu. Skrypty dostają otwarte obrazy (`images`).
- **Plik → Eksportuj → Wywołaj pliki RAW do folderu…**: wywołuje pliki i od razu zapisuje je jako **TIFF 16-bit, JPEG, PNG 16-bit, AVIF 10-bit albo XCF**, bez zostawiania ich otwartych. Istniejące pliki dostają numer (`-2`) albo są nadpisywane.

W obu przypadkach XMP danego zdjęcia ma pierwszeństwo przed wspólnymi ustawieniami.

### HEIC z HDR
Przy otwieraniu zdjęcia HDR pokazuje się okno z wyborem:
- **Liniowy 32-bit float** (domyślnie): BT.2100 / Rec. 2020; dla zdjęć z iPhone'a liniowy Display P3. Biel SDR ma wartość 1,0, jaśniejsze partie są zachowane powyżej 1,0.
- **SDR**: mapowanie tonów (PQ/HLG) albo obraz bazowy (iPhone).
- **Wbudowany moduł GIMP.**

Jest też suwak **ekspozycji HDR**. Zdjęcia HDR z iPhone'a (iOS 14–17, mapa wzmocnienia Apple) są odtwarzane według wzoru opisanego przez Apple.

Sprawdzono też na zwykłych zdjęciach HEIC z **realme 14 Pro 5G** (Display P3, EXIF).

### Eksport HDR
*Plik → Eksportuj jako…*, potem **Wybierz typ pliku → HEIF/AVIF HDR**: obraz (liniowy, 1,0 = biel SDR, jaśniejsze wartości zachowane) trafia do pliku w **BT.2100 PQ albo HLG**, 10 lub 12 bitów, BT.2020, jako `.heic` (HEVC) albo `.avif` (AV1). Domyślnym eksporterem tych rozszerzeń pozostaje moduł GIMP-a. HLG sięga ok. 3,8× bieli SDR, PQ do 10 000 cd/m².

### Informacje
*Pomoc → O wtyczce RAW / HEIC* pokazuje wersje wtyczki, LibRaw i libheif.

## Ograniczenia

- **HDR ISO 21496-1** (iPhone z iOS 18 i nowsze) oraz **Ultra HDR** w plikach JPEG (Android) nie są odtwarzane: libheif 1.23 nie udostępnia tych map, a JPEG obsługuje GIMP. Takie zdjęcia otwierają się jako SDR.
- **Kadrowanie i prostowanie** działają na wywołanym obrazie; lupa 100% pokazuje obraz bez kadru. Kadr z Lightrooma z kątem obrotu jest przenoszony w przybliżeniu (Lightroom mierzy prostokąt przed obrotem).
- **Eksport HDR** nie zapisuje jeszcze EXIF/XMP.
- **Profile DCP**: obsługiwane są macierze (Forward/Color z interpolacją dwóch oświetlaczy), HueSatMap, LookTable i krzywa tonalna. Pomijane są rzadkie elementy specyfikacji: profile z trzema oświetlaczami, ProfileGainTableMap i BaselineExposureOffset.
- **Import z XMP** przenosi tylko ustawienia z jednoznacznym odpowiednikiem (tabela w [CHANGELOG.md](CHANGELOG.md)); pozostałe parametry Lightrooma i darktable są pomijane. Temperatura z Lightrooma jest liczona inną metodą, więc kolor może się nieco różnić.
- **Redukcja szumu falkowa** to własna implementacja wtyczki (odpowiednik w LibRaw 0.22.2 z MSYS2 wywraca program).
- **Algorytmy demozaikowania z pakietów GPL2/GPL3** (AMaZE, LMMSE…) nie istnieją w LibRaw od wersji 0.20.
- **Połowa rozmiaru** nie zmniejsza „linear DNG” (np. Apple ProRAW).
- **Przy ponownym wywołaniu** przestrzeń barw i precyzja obrazu się nie zmieniają; „Przestrzeń barw wyjścia”, „Precyzja” i „Światło liniowe” działają przy otwieraniu.
- **8-bit** zawsze używa krzywej tonalnej.
- **Uszkodzone pliki** nie wywracają GIMP-a; część uciętych plików LibRaw otwiera z brakującym fragmentem.
- **Skrypty** wywołujące `gimp_file_load` dostają ustawienia domyślne (i XMP); wszystkie ustawienia przekażesz przez `file-raw-heic-raw-load`.
- **Linux** jest budowany i testowany jednostkowo w CI (Fedora, Debian testing: `./build.sh`, `./build.sh install`), ale nie był jeszcze sprawdzony w samym GIMP-ie.

## Odinstalowanie

Usuń folder `%APPDATA%\GIMP\3.2\plug-ins\gimp-raw-heic`. Własne presety leżą w `%APPDATA%\GIMP\3.2\gimp-raw-heic\presets\`.

## Prywatność

Wtyczka nie łączy się z siecią i nie wysyła żadnych danych.

---

## Dla programistów

### Budowanie (Windows, MSYS2 CLANG64, czyli tym samym toolchainem co GIMP)
```powershell
.\build.ps1 -Setup      # jednorazowo: pakiety MSYS2 (clang, meson, gimp, libraw, libheif, lensfun, …)
.\build.ps1 -Install    # kompilacja + instalacja do %APPDATA%\GIMP\3.x\plug-ins
.\build.ps1 -Package    # dist\gimp-raw-heic-<wersja>-win64.zip + paczka źródeł
.\build.ps1 -UpdatePo   # odśwież po/gimp-raw-heic.pot i po/pl.po
```
GitHub Actions buduje wtyczkę, uruchamia testy jednostkowe i dołącza paczki do wydań oznaczonych `v*`.

### Testy
```powershell
meson test -C build                       # testy jednostkowe (bez GIMP-a)
sh tests/fetch-samples.sh                 # próbki RAW z raw.pixls.us (CC0)
python tests/make_heic_samples.py         # próbki HEIC (SDR, 10-bit, alfa, PQ, HLG)
.\tests\run-tests.ps1                     # testy w gimp-console (w tym regresje)
```

### Struktura
`plugin.c` rejestracja · `raw-load.c` loader i miniatury RAW · `raw-develop.c` LibRaw · `raw-dialog.c` okno, podgląd, lupa, presety · `settings.c` ustawienia · `presets.c` presety · `denoise.c` redukcja szumu · `lens.c` lensfun · `camprofile.c` ICC/DCP · `xmp.c` XMP · `image.c`, `profiles.c` obraz i profile · `redevelop.c` ponowne wywołanie · `adjust.c` filtry nieniszczące · `batch.c` wiele plików · `export-batch.c` wywołanie do folderu · `heif-load.c` HEIC HDR i mapy Apple · `hdr-export.c` eksport HDR · `geometry.c` kadrowanie i prostowanie · `tone.c` krzywa bazowa · `sync.c` ustawienia dla innych plików · `util.c` · `po/` tłumaczenie.
