# Weryfikacja Zetmar Maski 1.0.0

Data: 28.11.2026. System: Windows, GIMP 3.2.8, Python dołączony do GIMP-a.

## Testy automatyczne

- 12/12 testów jednostkowych: zakresy i łagodne przejścia, inwersja i zaznaczenie,
  maska koloru, przezroczystość, HDR, wartości niefinitywne, walidacja i zapis/odczyt presetów.
- 18/18 testów integracyjnych w prawdziwym GIMP-ie: rejestracja PDB, cztery rodzaje wyniku
  w precyzji 8-bit, 16-bit i 32-bit float, niezmienność źródłowych pikseli i precyzji,
  przesunięcie warstwy i zaznaczenia, ochrona istniejącej maski i iloczyn masek na kopii,
  wykonanie przez PDB bez okna, zgodność małego podglądu z wynikiem oraz zapis/odczyt XCF z maską i metadanymi.
- Osobne profile w `work`, bez nadpisywania profilu użytkownika.

## Test interfejsu GTK

Na sztucznym obrazie 600 × 400 px, przez rzeczywiste okno GTK w GIMP-ie:

- otwarto panel i sprawdzono podgląd czarno-białej maski;
- włączono pobieranie koloru i kliknięto zdjęcie;
- sprawdzono ustawienie koloru, włączenie maski koloru i czerwoną nakładkę;
- sprawdzono dostęp do dolnej części panelu;
- zatwierdzono maskę: powstały dwie warstwy, nowa warstwa miała maskę, brak błędów;
- po korekcie układu ponownie otwarto okno i wzrokowo potwierdzono widoczność wyboru wyniku,
  nazwy i przycisków presetów przy zwiniętej sekcji koloru.

Plik `work/ui-result.json` zawiera wynik zatwierdzonego przebiegu interfejsu.
Nie sprawdzano przez klikanie każdego wariantu wyjścia ani systemowych okien zapisu i odczytu presetów.
Warianty wyjścia i serializacja presetów są objęte testami automatycznymi.

## Granice weryfikacji

- Nie testowano GIMP 3.0, Linux ani macOS.
- Nie mierzono wydajności na zdjęciach z aparatów i bardzo dużych obrazach.
- Grupa cofania jest stosowana w API; nie wykonano osobnego testu skrótu Ctrl+Z w głównym oknie GIMP-a.
- Test interfejsu w odizolowanym profilu bez interfejsu głównego GIMP-a wypisuje ostrzeżenie
  o braku `theme.css`; nie uniemożliwia ono działania panelu.
