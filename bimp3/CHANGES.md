# Poprawki i funkcje po audycie

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

Testy obejmują interpolację i alfa LUT, piksele w GIMP, automatyczne odświeżanie edytora, odtwarzanie dziennika, anulowanie, metadane, fonty, ochronę zależności i błędy instalatora. Lokalny raport generuje `test.ps1`; nie jest publikowany, ponieważ może zawierać lokalne ścieżki. Testy instalatora: `tests/test_install.ps1`. GitHub Actions sprawdza model i lint; osobny test integracyjny wymaga zainstalowanego GIMP.

Nie zmieniono historycznego kodu GIMP 2 ani nie deklaruje się przetestowania Linux/macOS czy GIMP 3.0.x. Nieobsługiwane pozostają łączone LUT shaper 1D+3D; pojedyncze 1D/3D są obsługiwane.
