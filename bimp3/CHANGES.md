# 1.1.0 (2026-11-27): poprawki i funkcje po audycie

## Błędy

- Instalator rozpoznaje wersję GIMP w każdym języku. Wcześniej polski GIMP („w wersji 3.2.6”) przerywał instalację.
- Wznawianie po awarii: blokada zadania sprawdza proces przez Windows API (numer i czas startu). `os.kill(pid, 0)` nie działało w Windows, więc pozostała blokada uniemożliwiała wznowienie.
- Blokady i profile zapisywane są atomowo; uszkodzona blokada nie blokuje zadania na stałe.
- Test jednostkowy działa na Pythonie 3.14 dołączonym do GIMP 3.2; CI sprawdza Python 3.12 i 3.14.
- `build-release.py` nie spakuje wyniku testów z filtrem, z błędami ani starszego niż kod; `release-result.json` jest generowany.
- „Usuń GPS” usuwa również miasto, region, kraj i lokalizację IPTC/XMP.
- „Inna procedura GIMP” działa na wszystkich warstwach zdjęcia, a nie tylko na ostatnio wstawionym znaku wodnym lub tle.
- Plik, przy którym proces GIMP padł dwukrotnie, kończy się błędem zamiast zapętlać wznawianie.
- Orientacja EXIF jest stosowana przed operacjami (GIMP nie robi tego przy wczytywaniu wsadowym); można ją wyłączyć.
- Fonty znaku wodnego są dopasowywane niezależnie od języka nazw stylów (np. „Arial Pogrubiony” = „Arial Bold”).
- Czytelne komunikaty o brakujących plikach wejściowych, LUT, krzywych i logo zamiast surowego `WinError 2`.
- Względne teksty argumentów procedur nie są już traktowane jako pliki zależności.
- Biblioteka LUT w C ładuje się tylko przy zgodnej sumie SHA-256; dodano `build-native.sh` dla Linux/macOS.
- Czytanie `.cube` jest ok. 9× szybsze (65³: 1,9 s → 0,2 s), a ścieżka Python LUT ok. 1,7× szybsza.
- Dziennik okna ma limit linii; okno nie zostaje zablokowane, gdy odczyt stanu procesu zgłosi wyjątek.
- Ruff sprawdza też Pyflakes i flake8-bugbear; usunięto nieużywane importy i zmienne.

## Funkcje

- Historia i dane: lista zadań z rozmiarem, wznawianie, usuwanie, czyszczenie starszych niż N dni i pozostałości podglądów.
- Stały proces podglądu wspólny dla okna i edytorów LUT; stałe, blokowane profile robocze zamiast nowego profilu przy każdym podglądzie i zadaniu.
- Zmiana rozmiaru „Tylko pomniejszaj”; kadrowanie z odwróceniem proporcji dla zdjęć pionowych.
- Wzorce nazw: `{name}`, `{n:03}` z numerem początkowym, `{date:…}`, `{exif:…}`, `{mtime:…}`, `{w}`, `{h}`, `{ext}`, `{folder}`.
- Dodatkowe wersje wyniku (np. miniatura, WebP) z własnym formatem, rozmiarem i parametrami.
- Maksymalny rozmiar pliku dla JPEG, WebP, HEIF i AVIF (automatyczny dobór jakości).
- `bimp3-cli.ps1`: przetwarzanie bez okna i obserwowany folder; nowe argumenty PDB `output-color`, `embed-color-profile`, `auto-orient`, `report-file`.
- Przeciąganie plików i folderów, miniatury i filtr listy zdjęć.
- Interfejs polski i angielski z wyborem języka.

# 1.0.0–1.0.1: poprawki i funkcje po audycie

## Ochrona danych i poprawność

- Naprawiono wybór fontów znaku wodnego: lista pokazuje zasoby GIMP, a zapisane wcześniej nazwy GTK są dopasowywane do rzeczywistych fontów tej samej rodziny.

- Wynik nie może nadpisać wejścia ani zależności, w tym obrazu znaku wodnego, krzywych i LUT.
- Wzorce nazw są podstawiane jeden raz; `##` i `@@` w nazwie źródłowej pozostają dosłowne.
- Zachowane są odmiany fontów tekstowego znaku wodnego.
- Błędy sprzątania nie pomijają przywrócenia kontekstu i nie przesłaniają wyniku eksportu.
- Walidowane są pary punktów krzywych i rosnące wartości X.
- Podfoldery są obliczane osobno dla każdego dysku; różne dyski otrzymują oddzielne prefiksy.
- USERDEF ma listę dozwolonych natywnych operacji obrazowych; import nie uruchomi globalnych procedur.
- Zestawy, preferencje, raporty i manifesty zapisywane są przez plik tymczasowy i podmianę.
- Instalacja przygotowuje pełny katalog, weryfikuje pliki, zachowuje poprzednią wersję i wycofuje nieudaną podmianę.

## Funkcje

- Podgląd PRZED/PO całej sekwencji, wykonywany w tle na pełnym obrazie.
- LUT Cube 1D/3D, kontrola siły 0–100%, podgląd w edytorze aktualizowany po zmianie siły lub pliku.
- Polityki EXIF/IPTC/XMP/GPS, konwersja sRGB i osadzanie ICC.
- Profile eksportu WWW, druk, archiwum.
- Przyrostki rozstrzygające kolizje nazw.
- Plan zapisu przed rozpoczęciem przetwarzania.
- Zapis i przywracanie ostatnich ustawień oraz listy zdjęć.
- Dziennik zadania, wznawianie po przerwaniu, wykrywanie zmienionych źródeł i zależności.
- Ponawianie błędnych wpisów z ustawieniami danego zadania.
- Osobny proces roboczy GIMP, anulowanie, skanowanie folderów porcjami i przyrostowa aktualizacja postępu.

## Kontrole

Testy obejmują interpolację i alfa LUT, piksele w GIMP, automatyczne odświeżanie edytora, odtwarzanie dziennika, anulowanie, metadane, fonty, ochronę zależności i błędy instalatora. Aktualne wyniki są w `tests/integration-result.json`. Testy instalatora: `tests/test_install.ps1`. Dodano Ruff i szablon GitHub Actions w katalogu repozytorium; zdalny workflow nie został uruchomiony ani opublikowany.

Nie zmieniono historycznego kodu GIMP 2 ani nie deklaruje się przetestowania Linux/macOS czy GIMP 3.0.x. Nieobsługiwane pozostają łączone LUT shaper 1D+3D; pojedyncze 1D/3D są obsługiwane.
