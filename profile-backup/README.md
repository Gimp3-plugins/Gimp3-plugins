# GIMP 3 Profile Backup – kopia profilu GIMP-a

Wtyczka do **GIMP 3** (Python 3, API GObject Introspection), która robi kopię zapasową
katalogu profilu użytkownika do ZIP-a (dla dużych profili w częściach) i potrafi go odtworzyć.
Interfejs po polsku i angielsku. Działa na Windows i Linuksie (macOS – patrz „Ograniczenia”).

[English](README.en.md) · [Zmiany](CHANGES.md)

## Pobieranie

Gotowa paczka jest w wydaniu
[`profile-backup-v1.0.0`](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/profile-backup-v1.0.0):

- `profile-backup-v1.0.0.zip` – wtyczka z instalatorami (`install.ps1`, `install.sh`): rozpakuj
  i uruchom instalator,
- `profile-backup-v1.0.0-manual.zip` – sam folder `profile-backup` do skopiowania do `plug-ins`
  w profilu GIMP-a,
- `SHA256SUMS-v1.0.0.txt` – sumy kontrolne.

## Instalacja

**Windows** (PowerShell, z katalogu repozytorium):

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

**Linux / macOS:**

```bash
chmod +x install.sh && ./install.sh
```

Skrypt wykrywa profil tą samą funkcją co wtyczka (`pb_core.py detect`), kopiuje trzy pliki do
`<profil>/plug-ins/profile-backup/`, na Linuksie nadaje prawo wykonywania i **pyta przed
nadpisaniem** istniejącej instalacji (`-Force` / `-f` pomija pytanie). Profil można podać
ręcznie: `install.ps1 -ProfileDir <ścieżka>` / `./install.sh <ścieżka>`.

Ręcznie: skopiuj katalog `plug-ins/profile-backup` do `plug-ins` w profilu GIMP 3
(GIMP: *Edycja → Preferencje → Katalogi → Wtyczki*) i uruchom GIMP-a ponownie.

## Użycie

Menu: **Plik → Kopia profilu → Kopia zapasowa profilu… / Przywróć profil…**
Obie pozycje działają **bez otwartego obrazu**.

**Kopia zapasowa:** wybierz profil (lista wykrytych albo „Inny katalog…"), zobacz jego rozmiar,
wskaż katalog docelowy (domyślnie `Dokumenty\GIMP-Backups` / `~/GIMP-Backups`), ustaw próg
dzielenia i rozmiar części. Postęp pokazuje pasek, a operację można anulować (częściowe pliki
są wtedy usuwane). Na końcu wtyczka pokazuje raport: liczbę plików, rozmiary, miejsce zapisu,
pominięte pliki i ścieżkę dziennika.

**Przywracanie:** wskaż `.zip`, pierwszą część `.zip.001` albo `.manifest.json`. Wtyczka:

1. znajduje wszystkie części i sprawdza kompletność oraz SHA-256 każdej z nich,
2. czyta manifest i pokazuje podsumowanie (data, wersja GIMP, liczba plików), a potem prosi o potwierdzenie,
3. rozpakowuje kopię **obok** profilu (`3.2.restore-staging-…`) i weryfikuje SHA-256 każdego pliku,
4. po zamknięciu GIMP-a podmienia profil. Robi to automatycznie (opcja domyślna) albo po ręcznym
   uruchomieniu polecenia pokazanego w raporcie,
5. zachowuje poprzedni profil jako `3.2.before-restore-RRRRMMDD-GGMMSS`.

Tryby: **Zastąp cały profil** (poprzedni profil zostaje przeniesiony do kopii bezpieczeństwa)
albo **Scal** (kopia bezpieczeństwa jest kopiowana, pliki spoza archiwum zostają).
Przy następnym uruchomieniu dowolnej z procedur wtyczka pokaże wynik podmiany.

## CLI (bez GIMP-a)

```text
python pb_core.py detect [--json]
python pb_core.py backup  [--profile DIR] [--dest DIR] [--threshold-mb 500] [--part-mb 200] [--use-7z]
python pb_core.py verify  ARCHIWUM
python pb_core.py restore ARCHIWUM [--profile DIR] [--mode replace|merge] [--yes]
python pb_core.py apply-pending PLIK.restore-pending.json [--wait-pid PID]
python pb_core.py --lang pl|en ...
```

Polecenie `restore` w CLI podmienia profil od razu, więc **GIMP musi być zamknięty**.
Na Windows można użyć Pythona dołączonego do GIMP-a: `"%LOCALAPPDATA%\Programs\GIMP 3\bin\python.exe"`.

## Format kopii

- `GIMP3-profile-RRRRMMDD-GGMMSS.zip` – ZIP (`ZIP_DEFLATED`, ZIP64), ścieżki względne z `/`,
  włącznie z pustymi katalogami.
- W archiwum `backup_manifest.json`: wersja GIMP i wtyczki, system, data, oryginalna ścieżka,
  liczba plików, rozmiar, dla każdego pliku rozmiar, `mtime_ns`, uprawnienia i SHA-256,
  lista pominiętych i wykluczonych.
- Dla dużych profili: `….zip.001`, `.002`, … (zwykłe cięcie bajtów jednego ZIP-a) oraz obok
  `GIMP3-profile-….manifest.json` z listą części, ich rozmiarami, SHA-256 każdej części
  i SHA-256 całości. Manifest w archiwum nie może zawierać sum części (powstają po nim),
  więc są one w pliku obok.

**Ręczne rozpakowanie części** – wystarczy je skleić:

```text
Windows:  copy /b "X.zip.001"+"X.zip.002"+"X.zip.003" "X.zip"
Linux:    cat X.zip.[0-9][0-9][0-9] > X.zip
```

## Decyzje projektowe

**Przywracanie żywego profilu.** Wtyczka działa wewnątrz GIMP-a, który przy wyjściu zapisuje
m.in. `sessionrc`, `toolrc`, `devicerc`, `contextrc`, `tags.xml` i `tool-options`. Gdyby
wtyczka nadpisała profil od razu, GIMP przy zamykaniu nadpisałby część przywróconych plików
starym stanem. Na Windows nie da się też przenieść katalogu, w którym GIMP trzyma otwarte pliki.
Dlatego wewnątrz GIMP-a przywracanie jest **dwuetapowe**:

1. Wtyczka rozpakowuje i weryfikuje kopię w katalogu obok profilu (ten sam dysk, więc późniejsza
   zamiana to szybkie `rename`). Zapisuje też plik `<profil>.restore-pending.json`.
2. Odłączony proces pomocniczy (`pb_core.py apply-pending --wait-pid <PID GIMP-a>`) czeka na
   zakończenie GIMP-a i dopiero wtedy podmienia profil. W przypadku błędu przywraca poprzedni
   stan i zapisuje wynik w `<profil>.restore-result.json`. Wtyczka pokazuje ten wynik przy
   następnym uruchomieniu.

Rozważyłem też dwa inne warianty. Samo przywracanie do `3.0.restored` wymagałoby od
użytkownika ręcznego zamieniania katalogów. Zastosowanie zmian „przy następnym uruchomieniu"
jest nierealne, bo wtyczki startują już po wczytaniu profilu.

**Archiwum wieloczęściowe.** Moduł `zipfile` nie tworzy klasycznych archiwów dzielonych, więc
wtyczka zapisuje **jeden** ZIP przez własny strumień `SplitWriter`, który rozkłada bajty na pliki
`.001`, `.002`, … już w trakcie zapisu. Nie potrzeba przez to podwójnego miejsca na dysku.
Odtwarzanie **nie skleja części na dysku** (to zmiana względem pierwotnego planu), tylko czyta je
przez `MultiPartReader` jako jeden plik z dostępem swobodnym, więc nie potrzeba miejsca na plik
tymczasowy. Skutek jest ten sam. Jeśli wynik zmieści się w jednej części, powstaje zwykły `.zip`.

**7-Zip (opcjonalnie).** Jeśli wykryto `7zz`, `7z` lub `7za` (`PATH` lub `Program Files\7-Zip`),
w dialogu można go włączyć. Wtedy wtyczka liczy SHA-256 do manifestu, a ZIP tworzy 7-Zip
z `-mmt=on` i `-v…k`. Format części jest identyczny (cięcie bajtów ZIP-a), więc odtwarzanie
działa tak samo. W teście na profilu 300 MB: wbudowany ZIP 14,7 s, 7-Zip 7,4 s.

**Terminologia.** „Wielowątkowe" w zadaniu rozumiem jako **wieloczęściowe** (wolumeny).
Wielowątkowa kompresja jest tylko dodatkiem przy 7-Zip.

**Wykrywanie profilu.** Kolejność: `Gimp.directory()` (wewnątrz GIMP-a), `GIMP3_DIRECTORY`,
potem typowe ścieżki. GIMP 3 nazywa katalog **numerem serii**, a nie stałym `3.0`. Na badanej
maszynie GIMP 3.2.6 używa `%APPDATA%\GIMP\3.2`, więc wykrywanie szuka wszystkich `3.N`
i stawia najnowszy na początku. Profile 2.x są tylko zgłaszane, nigdy nie są kopiowane.

**Ustawienia** (ostatni katalog, próg, język) leżą **poza profilem**:
`%APPDATA%\gimp-profile-backup\settings.json` / `~/.config/gimp-profile-backup/settings.json`.
Wtyczka odmawia zapisu kopii wewnątrz profilu.

**Język:** wybór z Preferencji GIMP-a (`(language "…")` w `gimprc`), potem
`LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG`, potem język interfejsu Windows, a na końcu `locale`.
Polski wybierany jest dla `pl*`, a w pozostałych przypadkach angielski. Język można zmienić
w dialogu (jest zapamiętywany). Wszystkie teksty są w `pb_i18n.py`. Dziennik techniczny
(`gimp-profile-backup.log` w katalogu kopii) jest po angielsku.

## Co jest wykluczane z kopii

Lista jest w jednym miejscu: `EXCLUDE_*` na początku `pb_core.py`.

| Wzorzec | Dlaczego |
|---|---|
| `tmp/` (główny poziom) | pliki tymczasowe GIMP-a, odtwarzane przy starcie |
| `__pycache__/` (dowolny poziom) | bajtkod Pythona wtyczek |
| `*.pyc`, `*.pyo`, `*.lock`, `lock`, `.lock`, `*~`, `Thumbs.db`, `.DS_Store` | cache, blokady, śmieci systemowe |

Co znalazłem w prawdziwym profilu GIMP 3.2 (1484 pliki, 301 MB): `tmp/` (pusty), `backups/`
(pusty – zostawiony w kopii, bo nie mam pewności, do czego służy), `pluginrc` (424 KB, cache
zapytań o wtyczki, który GIMP sam odświeża – zostawiony, bo jest nieszkodliwy), `__pycache__`
we wtyczkach i plik `preview-1.lock` jednej z wtyczek. Większość rozmiaru to `plug-ins/`
(181 MB) i `lut-cube/` (123 MB).

Pliki zablokowane lub nieczytelne są **pomijane i wymieniane w raporcie**, w manifeście
(`skipped`) i w dzienniku. Dowiązania symboliczne i junctions **nie są śledzone**.

## Co zostało zweryfikowane

Na tej maszynie (Windows 11, **GIMP 3.2.6**, Python w GIMP-ie 3.14.7, 7-Zip):

- ✅ wtyczka **rejestruje się** w GIMP 3.2.6 (`gimp-console` w trybie wsadowym): obie procedury,
  polskie etykiety, `<Image>/File/Kopia profilu`, czułość „bez obrazu",
- ✅ **kopia prawdziwego profilu** przez procedurę GIMP-a (tryb NONINTERACTIVE): 1456 plików,
  301 MB → 135 MB w 32 s; przywrócenie, a potem porównanie SHA-256 – 0 różnic, 404 katalogi
  (także puste),
- ✅ archiwum wieloczęściowe na prawdziwym profilu (wbudowany ZIP i 7-Zip), przywracanie od `.001`,
- ✅ przywracanie przez procedurę GIMP-a w trybie „Scal" z automatyczną podmianą: proces
  pomocniczy czekał na PID GIMP-a i scalił profil po jego zamknięciu,
- ✅ ścieżki dłuższe niż 260 znaków (błąd znaleziony w tym teście i naprawiony),
- ✅ `pytest`: 48 testów w Pythonie 3.12 i w Pythonie 3.14 z GIMP-a,
- ✅ `install.ps1` w Windows PowerShell 5.1,
- ✅ **okna GTK przeklikane w GIMP 3.2.6** (Windows): menu bez obrazu, okno kopii, przełączanie
  PL/EN, lista profili, odmowa zapisu kopii w profilu, pasek postępu, anulowanie (częściowe
  archiwum usunięte), raport, okno przywracania, potwierdzenie, wybór pliku z filtrem, a potem
  wyjście z GIMP-a, automatyczna podmiana i komunikat o wyniku przy następnym uruchomieniu.
  Test ujawnił i pozwolił poprawić trzy błędy: przycisk „Zamknij” w języku systemu zamiast
  wtyczki, układ wiersza wyboru pliku oraz domyślny cel przywracania (był to ostatnio
  kopiowany profil, a teraz jest to profil używany przez GIMP-a).

## Czego NIE zweryfikowano

- ❌ **Okien GTK w Linuksie** (wygląd i motyw mogą się różnić).
- ❌ **Linux, Flatpak, Snap i macOS** na prawdziwym systemie. Wykrywanie ścieżek jest
  testowane na zasymulowanych środowiskach, a uprawnienia unixowe są zapisywane i odtwarzane
  (`chmod`), ale nie było to sprawdzone na Linuksie. `install.sh` nie był uruchamiany.
- ❌ **Flatpak:** nie wiadomo, czy odłączony proces pomocniczy przeżyje zamknięcie piaskownicy
  GIMP-a. Jeśli nie, raport pokazuje polecenie do ręcznego uruchomienia, a rozpakowana kopia
  czeka obok profilu.
- ❌ Zachowanie przy profilu na dysku sieciowym oraz przy plikach zablokowanych przez inny
  proces w Windows (zasymulowane w testach, nie odtworzone na żywo).

## Ograniczenia

- `os.getppid()` wtyczki = PID GIMP-a (sprawdzone na Windows). Gdyby GIMP uruchomiono przez
  pośredni proces, proces pomocniczy może podmienić profil wcześniej. Profil jest wtedy nadal
  bezpieczny (kopia bezpieczeństwa), ale GIMP mógłby nadpisać część plików przy wyjściu.
- Jeśli po zamknięciu GIMP-a od razu otworzysz go ponownie (w ciągu ~2 s), podmiana może się nie
  udać. Wtedy nic nie jest zmieniane, a błąd zostanie pokazany przy następnym użyciu wtyczki.
- Kopiowanie żywego profilu jest bezpieczne, ale pliki zapisywane przez GIMP-a w trakcie kopii
  mogą trafić do niej w stanie sprzed zapisu.
- Kopie nie są szyfrowane.

## Testy

```powershell
python -m pytest -q
```

## Licencja

MIT – zob. [LICENSE](LICENSE).
