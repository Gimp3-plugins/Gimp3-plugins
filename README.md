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
| **Ekspozycja** | ekspozycja −2…+3 EV, ochrona świateł, odzyskiwanie prześwietleń (obetnij / nie obcinaj / mieszaj / odbuduj 3–9) z **automatyczną kompensacją jasności**, jasność, automatyczna jasność |
| **Szczegóły** | demozaikowanie (dwuliniowe, VNG, PPG, **AHD**, DCB, DHT, AAHD; X-Trans automatycznie), redukcja szumu falkowa i FBDD, aberracja chromatyczna (R/B), gorące i martwe piksele, mediana artefaktów barwnych |
| **Obiektyw** | korekcja **winiety**, **dystorsji** i **poprzecznej aberracji chromatycznej** z bazy **lensfun** (obiektyw rozpoznawany z pliku, widoczny pod podglądem) |
| **Kolor** | **profil aparatu**: ICC (.icc/.icm) albo Adobe **DCP**, opcjonalnie z „wyglądem” profilu (tabela wyglądu i krzywa tonalna) |
| **Wyjście** | sRGB, Adobe RGB, Display P3, ProPhoto, Rec. 2020 · liniowe lub z krzywą · 8/16/32-bit float · połowa rozmiaru · obrót · kadrowanie aparatu |

Pod podglądem są dwa przełączniki:
- **Lupa 100%**: kliknij podgląd, aby zobaczyć to miejsce w pełnej rozdzielczości (szum, ostrość, demozaikowanie). Ponowne kliknięcie wraca do całości.
- **Przed / po**: lewa połowa podglądu z ustawieniami domyślnymi, prawa z Twoimi.

U góry okna jest lista **presetów**: wbudowane („Domyślne”, „Noc / wysokie ISO”, „Szybki podgląd”) i własne, z przyciskami *Zapisz jako…* i *Usuń*. Preset nie zmienia punktu neutralnego, bo ten zależy od zdjęcia.

Inne zachowania przy otwieraniu:
- **Pamięć ustawień:** ustawienia są zapamiętywane między sesjami.
- **„Zawsze pokazuj to okno”:** gdy wyłączone, pliki otwierają się od razu. **Shift** przy otwieraniu odwraca to zachowanie.
- **Pliki XMP:** jeśli obok pliku RAW leży XMP z **Lightrooma** (`zdjecie.xmp`) albo **darktable** (`zdjecie.nef.xmp`), wtyczka przejmuje z niego balans bieli, ekspozycję, korekcje obiektywu i redukcję szumu. Tytuł okna pokazuje źródło ustawień. Opcja *Użyj ustawień z pliku XMP*.
- **Obraz wynikowy:** domyślnie **16-bit liniowy** w sRGB z poprawnym profilem ICC. **EXIF, XMP i IPTC** są przenoszone i zapisywane przy eksporcie.

### Ponowne wywołanie RAW
**Filtry → RAW → Wywołaj RAW ponownie…**

Obraz pamięta ścieżkę oryginalnego pliku RAW i użyte ustawienia, także w pliku XCF. Wynik **zastępuje piksele wywołanej warstwy**: jej efekty nieniszczące, maska, tryb, krycie, nazwa i pozycja zostają, a całość da się cofnąć. Alternatywnie wynik trafia na **nową warstwę**. Jeśli zapisana ścieżka nie prowadzi na dysk lokalny (np. `\\serwer\...` w cudzym pliku XCF), wtyczka najpierw pyta o zgodę.

### Szybka korekta nieniszcząca
**Filtry → RAW → Szybka korekta (nieniszcząca)…** dodaje do warstwy **edytowalne efekty GEGL**: ekspozycję, temperaturę barwową, cienie/światła, kontrast, nasycenie oraz opcjonalnie neutralne **Poziomy** i **Krzywe**.

### Wiele plików
- **Plik → Otwórz → Otwórz wiele plików RAW…**: ustawienia wybierasz raz, wtyczka otwiera wszystkie pliki z paskiem postępu.
- **Plik → Eksportuj → Wywołaj pliki RAW do folderu…**: wywołuje pliki i od razu zapisuje je jako **TIFF 16-bit, JPEG, PNG 16-bit, AVIF 10-bit albo XCF**, bez zostawiania ich otwartych. Istniejące pliki dostają numer (`-2`) albo są nadpisywane.

W obu przypadkach XMP danego zdjęcia ma pierwszeństwo przed wspólnymi ustawieniami.

### HEIC z HDR
Przy otwieraniu zdjęcia HDR pokazuje się okno z wyborem:
- **Liniowy 32-bit float** (domyślnie): BT.2100 / Rec. 2020; dla zdjęć z iPhone'a liniowy Display P3. Biel SDR ma wartość 1,0, jaśniejsze partie są zachowane powyżej 1,0.
- **SDR**: mapowanie tonów (PQ/HLG) albo obraz bazowy (iPhone).
- **Wbudowany moduł GIMP.**

Jest też suwak **ekspozycji HDR**. Zdjęcia HDR z iPhone'a (iOS 14–17, mapa wzmocnienia Apple) są odtwarzane według wzoru opisanego przez Apple.

Sprawdzono też na zwykłych zdjęciach HEIC z **realme 14 Pro 5G** (Display P3, EXIF).

### Informacje
*Pomoc → O wtyczce RAW / HEIC* pokazuje wersje wtyczki, LibRaw i libheif.

## Ograniczenia

- **HDR ISO 21496-1** (iPhone z iOS 18 i nowsze) oraz **Ultra HDR** w plikach JPEG (Android) nie są odtwarzane: libheif 1.23 nie udostępnia tych map, a JPEG obsługuje GIMP. Takie zdjęcia otwierają się jako SDR.
- **Profile DCP**: obsługiwane są macierze (Forward/Color z interpolacją dwóch oświetlaczy), HueSatMap, LookTable i krzywa tonalna. Pomijane są rzadkie elementy specyfikacji: profile z trzema oświetlaczami, ProfileGainTableMap i BaselineExposureOffset.
- **Import z XMP** przenosi tylko ustawienia z jednoznacznym odpowiednikiem (tabela w [CHANGELOG.md](CHANGELOG.md)); pozostałe parametry Lightrooma i darktable są pomijane. Temperatura z Lightrooma jest liczona inną metodą, więc kolor może się nieco różnić.
- **Redukcja szumu falkowa** to własna implementacja wtyczki (odpowiednik w LibRaw 0.22.2 z MSYS2 wywraca program).
- **Algorytmy demozaikowania z pakietów GPL2/GPL3** (AMaZE, LMMSE…) nie istnieją w LibRaw od wersji 0.20.
- **Połowa rozmiaru** nie zmniejsza „linear DNG” (np. Apple ProRAW).
- **Przy ponownym wywołaniu** precyzja obrazu się nie zmienia; „Precyzja” i „Światło liniowe” działają przy otwieraniu.
- **8-bit** zawsze używa krzywej tonalnej.
- **Uszkodzone pliki** nie wywracają GIMP-a; część uciętych plików LibRaw otwiera z brakującym fragmentem.
- **Skrypty** wywołujące `gimp_file_load` dostają ustawienia domyślne (i XMP); wszystkie ustawienia przekażesz przez `file-raw-heic-raw-load`.
- **Linux** nie był testowany.

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
`plugin.c` rejestracja · `raw-load.c` loader i miniatury RAW · `raw-develop.c` LibRaw · `raw-dialog.c` okno, podgląd, lupa, presety · `settings.c` ustawienia · `presets.c` presety · `denoise.c` redukcja szumu · `lens.c` lensfun · `camprofile.c` ICC/DCP · `xmp.c` XMP · `image.c`, `profiles.c` obraz i profile · `redevelop.c` ponowne wywołanie · `adjust.c` filtry nieniszczące · `batch.c` wiele plików · `export-batch.c` wywołanie do folderu · `heif-load.c` HEIC HDR i mapy Apple · `util.c` · `po/` tłumaczenie.
