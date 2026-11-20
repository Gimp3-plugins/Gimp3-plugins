# PSHost — filtry Photoshop (.8bf) w GIMP-ie 3

[English → README.md](README.md)

PSHost to wtyczka do **GIMP-a 3 na Windows (x64)**, dzięki której można używać w GIMP-ie **64-bitowych filtrów Photoshop
(`.8bf`)**. Wskazujesz katalogi z wtyczkami Photoshop, a PSHost sprawdza każdą z nich, mówi, które zostaną użyte (a dla
pozostałych — dlaczego nie), i dodaje użyteczne do menu **Filtry → Photoshop → \<Kategoria\>**.

> **Stan: 0.8.0 — działa, z ograniczeniami.** Testowane z GIMP-em 3.2.6 na Windows 11. Zobacz
> [Znane ograniczenia](#znane-ograniczenia). Wynik „zostanie użyta” oznacza, że wtyczka przeszła test podstawowy, a
> **nie** że zadziała w każdej sytuacji.

**Film demonstracyjny (3:55):** [docs/PSHost-demo.mp4](docs/PSHost-demo.mp4) — dodawanie wtyczek, menu Filtry, Nik / Topaz / Podpis (Watermark) działające w GIMP-ie 3.

## Co robi

- **Zarządzaj wtyczkami…** (Filtry → Photoshop): dodawanie, usuwanie i ponowne skanowanie katalogów (opcjonalnie z
  podkatalogami), tabela wszystkich znalezionych `.8bf` z wynikiem (**OK / z zastrzeżeniami / NIE**) i powodem,
  włączanie i wyłączanie wtyczek, usuwanie odrzuconych z listy (pliki na dysku nigdy nie są kasowane) oraz uruchamianie
  filtra z karty **Filtry**.
- **Dwustopniowy test** każdej wtyczki: statyczny (64-bitowy PE, opis PiPL, funkcja wejściowa, obsługa RGB, importowane
  DLL-e) i dynamiczny (wtyczka jest ładowana w osobnym procesie i inicjowana na małym obrazku testowym, z limitem czasu).
- **Filtry w menu** po zaakceptowaniu restartu GIMP-a (okno najpierw pyta i ostrzega o niezapisanych obrazach).
- Filtry działają **w osobnym procesie**: wtyczka, która ulegnie awarii lub się zawiesi, nie zamyka GIMP-a. Wynik trafia
  do aktywnej warstwy, respektuje zaznaczenie (także nieregularne, z wygładzaniem), zachowuje kanał alfa i jest
  **jednym krokiem Cofnij**.
- Interfejs **polski i angielski** (Auto / Polski / English); polskie znaki w ścieżkach działają.
- **Instalator** (dla bieżącego użytkownika, bez uprawnień administratora).

## Czego nie robi (przeczytaj)

- Tylko wtyczki **64-bitowe**. Pliki `.8bf` 32-bitowe są odrzucane („jest 32-bitowa”).
- Tylko **filtry** (`8BFM`). Wtyczki importu/eksportu, formatów, selekcji i automatyzacji są poza zakresem.
- **8 bitów na kanał, wyłącznie RGB(A).** Obraz GIMP-a jest konwertowany do 8-bitowego sRGB na czas filtra i z powrotem;
  wyższa precyzja (16/32-bit zmiennoprzecinkowa) jest **redukowana do 8 bitów w filtrowanym obszarze**. Alfa warstwy nie
  jest przekazywana filtrowi — wraca niezmieniona (tryb „flat image”).
- Funkcje hosta specyficzne dla Photoshopa są emulowane tylko częściowo. Zrealizowane: uchwyty, bufory, właściwości,
  zestawy PICA *Handle / Property / UIHooks / ZString*, kafelkowy dostęp do obrazu, zapis parametrów, podgląd
  `displayPixels`. **Niezrealizowane:** channel ports, Action Manager (zestawy descriptorów), usługi kolorów, tryby
  16/32 bit, Smart Filters, własne okna z GPU. Wtyczka, która ich wymaga, może zawieść, mimo że jej test podstawowy
  daje „OK”.
- Wtyczki z zabezpieczeniem licencyjnym (DRM) mogą odmówić pracy poza Photoshopem.
- Każdy filtr działa w **nowym procesie**, więc wtyczki trzymające stan wyłącznie w pamięci między uruchomieniami (np.
  „powtórz ostatni filtr bez okna”) pokażą okno ponownie.
- Zbudowane i przetestowane z **GIMP-em 3.2.x**; inne wersje 3.x nie były testowane (instalator ostrzega dla < 3.2).

## Bezpieczeństwo

Wtyczka Photoshop to biblioteka DLL: **dodanie jej uruchamia obcy kod** — podczas testu zgodności i przy każdym użyciu
filtra. Dodawaj tylko wtyczki z zaufanych źródeł. Osobny proces chroni GIMP-a przed awariami, ale nie przed
złośliwym kodem.

## Instalacja

1. Pobierz `PSHost-Setup-<wersja>.exe` z [najnowszego wydania](https://github.com/zetmar-collab/Gimp3-plugins/releases/latest) (sprawdź sumę SHA-256 w opisie wydania) i uruchom go (uprawnienia administratora nie są potrzebne). Instalator sam
   znajduje GIMP-a 3 (lub pozwala wskazać jego folder). Jeśli znaleziono tylko GIMP-a 2, wyjaśnia, że PSHost wymaga GIMP-a 3.
2. Gdy instalator o to poprosi, zamknij GIMP-a. Instalator nie dodaje żadnych wtyczek Photoshop.
3. Uruchom GIMP-a → **Filtry → Photoshop → Zarządzaj wtyczkami…** → **Dodaj katalog…**.

**SmartScreen:** instalator **nie jest podpisany certyfikatem**, więc Windows może pokazać „System Windows ochronił ten
komputer”. Wybierz *Więcej informacji → Uruchom mimo to* tylko wtedy, gdy instalator pochodzi ze źródła, któremu ufasz.
(Podpis kodu wymaga płatnego certyfikatu; celowo tego nie omijamy.)

**Odinstalowanie:** Windows *Aplikacje i funkcje* → PSHost. Instalator zapyta, czy usunąć ustawienia (`config.json`,
logi, zapisane parametry filtrów).

## Użycie

1. **Dodaj katalog** z plikami `.8bf` (np. `C:\Program Files\Adobe\…\Plug-Ins`). Każda wtyczka zostanie przetestowana i
   wypisana: *„Wtyczka »X« zostanie użyta w GIMP-ie.”* albo *„…nie zostanie użyta: jest 32-bitowa.”*
2. **Usuń odrzucone** ukrywa wpisy 32-bitowe i ukryte filtry pomocnicze (tylko z listy); pojedyncze wtyczki można wyłączyć.
3. Zaakceptuj **Uruchom ponownie GIMP-a** (zostaniesz ostrzeżony o niezapisanych obrazach; o ich zapis pyta sam GIMP).
   Nowe filtry pojawią się w **Filtry → Photoshop → \<Kategoria z wtyczki\>**.
4. Otwórz obraz i uruchom filtr z menu — albo z **Zarządzaj wtyczkami… → Filtry → Uruchom na bieżącej warstwie**.
   Ustawienia są zapamiętywane do następnego uruchomienia.

Pliki: `%APPDATA%\GIMP\3.2\pshost\config.json` (ustawienia i wyniki skanu), `…\pshost\params\` (zapisane parametry
filtrów), `…\pshost\registered.json` (co zarejestrował działający GIMP), `…\plug-ins\pshost\` (program).
W PDB GIMP-a dostępna jest skryptowalna procedura `pshost-run-filter`.

## Budowanie ze źródeł

Wymagania: GIMP 3.2.x dla Windows (jego instalator zawiera pliki deweloperskie), **MSYS2 UCRT64**
(`pacman -S mingw-w64-ucrt-x86_64-{gcc,pkgconf,cmake,ninja,gettext-tools}`), Inno Setup 6 (instalator), Python 3 (testy).

```text
mklink /J C:\gimp3 "%LOCALAPPDATA%\Programs\GIMP 3"          # ścieżka bez spacji dla pkg-config
MSYSTEM=UCRT64 C:\msys64\usr\bin\bash.exe -l build.sh         # cmake + ninja -> build\
cmake --build build --target installer                        # installer\output\PSHost-Setup-<wersja>.exe
ctest --test-dir build                                        # 6 zestawów; te oparte na GIMP-ie wymagają GIMP-a i zainstalowanej wtyczki
```

Nagłówki Photoshop SDK **nie są** używane ani dołączane; `src/common/ps_types.h` zawiera niezależnie napisane definicje
(układy sprawdzone z otwartoźródłowym hostem PSFilterPdn, MIT, i zweryfikowane na prawdziwych wtyczkach — zob.
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)).

## Licencja

PSHost jest wolnym oprogramowaniem na licencji **GNU General Public License w wersji 3 lub (według Twojego wyboru)
dowolnej późniejszej** (**GPL-3.0-or-later**) — zob. [LICENSE](LICENSE). Na tych warunkach możesz go używać, badać,
zmieniać i rozpowszechniać; jeśli otrzymujesz binaria PSHost, masz prawo do odpowiadającego im kodu źródłowego (to
repozytorium). Licencja dotyczy wyłącznie PSHost: **nie obejmuje** dodawanych przez Ciebie wtyczek Photoshop (każda ma
własną licencję), a program jest udostępniany bez gwarancji. Uwagi o materiałach zewnętrznych: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Dokumenty

[docs/ustalenia.md](docs/ustalenia.md) — co zweryfikowano, a co założono, etap po etapie · [docs/kompatybilnosc.md](docs/kompatybilnosc.md) —
tabela zgodności wtyczek · [docs/testy_reczne.md](docs/testy_reczne.md) — lista kontrolna testów ręcznych.

## Architektura

```
GIMP 3 ─ pshost.exe            wtyczka GIMP-a (C, libgimp + GTK3): menu, okno zarządzania, skanowanie, rejestracja, restart
           └ pshost_runner.exe osobny 64-bitowy proces: ładuje jeden .8bf, implementuje API hosta, probe, pomocnik restartu
```
