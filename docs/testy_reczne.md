# Lista kontrolna testów ręcznych (PSHost 0.8.0)

Legenda: **A** = pokryte też testem automatycznym · ✔ użytkownik = potwierdzone przez użytkownika w prawdziwym GIMP-ie podczas
prac · ☐ = do sprawdzenia ręcznie. Przed testami: zainstaluj `PSHost-Setup-0.8.0.exe` (albo skopiuj pliki z `build\` do
`%APPDATA%\GIMP\3.2\plug-ins\pshost\`) i uruchom GIMP-a. Wtyczki testowe: `C:\Program Files\Adobe\Photoshop Elements 2026\Plug-Ins\Zetmar`,
`C:\Program Files\Google\Nik Collection`, `C:\Program Files (x86)\Topaz Labs`.

## A. Instalacja i uruchomienie
| # | Scenariusz | Oczekiwany wynik | Status |
|---|---|---|---|
| A1 | Uruchom instalator (zwykły tryb, nie cichy) przy zamkniętym GIMP-ie | Wykrywa GIMP-a 3.2, pokazuje „Gotowe do instalacji” z folderem docelowym, instaluje bez UAC | ☐ (A: tryb cichy, wykrycie w rejestrze) |
| A2 | Uruchom instalator przy uruchomionym GIMP-ie | Prosi o zamknięcie GIMP-a (Ponów / Anuluj) | ☐ (A: tryb cichy odmawia) |
| A3 | Zainstaluj na maszynie bez GIMP-a 3 (lub z samym GIMP-em 2) | Komunikat PL/EN, możliwość wskazania folderu ręcznie | ☐ (A: zachowanie przy braku GIMP-a w trybie cichym) |
| A4 | Odinstaluj z „Aplikacje i funkcje” | Usuwa pliki; pyta o ustawienia (Nie → `config.json` zostaje) | ☐ (A: tryb cichy, `/PURGE`) |
| A5 | Po instalacji: Filtry → Photoshop | Widać „Zarządzaj wtyczkami…” i „O PSHost…” | ✔ użytkownik |

## B. Dodawanie wtyczek i komunikaty
| # | Scenariusz | Oczekiwany wynik | Status |
|---|---|---|---|
| B1 | Zarządzaj wtyczkami → Dodaj katalog (Nik Collection, z podkatalogami) | Pasek postępu, potem okno podsumowania „Użyte: N, z zastrzeżeniami: K, pominięte: M” + rozwijane szczegóły | ✔ użytkownik (okno ładuje wtyczki) · A |
| B2 | Dodaj katalog z jedną wtyczką | Jedno zdanie: „Wtyczka »X« zostanie użyta w GIMP-ie.” | ☐ · A (logika komunikatów) |
| B3 | Wtyczka 32-bitowa (np. wersje x86 Nik/Topaz) | „…nie zostanie użyta: jest 32-bitowa…”; pole „Użyj” nieaktywne | ✔ użytkownik (widział je na liście) · A |
| B4 | „Usuń odrzucone” / „Usuń zaznaczone” / „Przywróć usunięte” | Wpisy znikają tylko z listy; „Skanuj ponownie” ich nie przywraca; pliki na dysku nietknięte | ☐ · A |
| B5 | Wyłącz pojedynczą wtyczkę, zamknij okno | Zapytanie o restart; po restarcie filtra nie ma w menu | ☐ · A (sygnatura rejestru) |
| B6 | Zmień język w Ustawieniach (Auto / Polski / English) | Okno tłumaczy się po ponownym otwarciu; informacja o restarcie dla nazw w menu | ☐ · A |
| B7 | Katalog i plik z polskimi znakami („Wtyczki zażółć”, „filtr ŁÓDŹ.8bf”) | Znaleziony, przetestowany, uruchamialny z menu | ☐ (okno) · A (skan, config, uruchomienie z menu w GIMP) |
| B8 | Wtyczka z brakującą zależnością DLL | „NIE… brakuje biblioteki X.dll” | A (mini-filtr) · ☐ (prawdziwa wtyczka) |
| B9 | Uszkodzony plik `.8bf` (ucięty / nie-PE) | „NIE… plik jest uszkodzony lub nie jest wtyczką Windows” | A (fuzz ucięć) · ☐ |

## C. Restart GIMP-a
| # | Scenariusz | Oczekiwany wynik | Status |
|---|---|---|---|
| C1 | Zamknij okno zarządzania po zmianach | Pyta „Aby załadować nowe wtyczki, GIMP musi zostać uruchomiony ponownie. Uruchomić teraz?” | ✔ użytkownik (filtry w menu po restarcie) |
| C2 | Przy niezapisanym obrazie: „Uruchom ponownie teraz” | Ostrzeżenie wymienia obraz; GIMP sam pyta o zapis; po zamknięciu **uruchamia się ponownie sam** | ☐ (A: pomocnik z atrapą procesu, wymienia obrazy z atrapą) |
| C3 | Przy pytaniu GIMP-a o zapis wybierz „Anuluj” | GIMP zostaje otwarty i **nie** uruchamia się drugi raz po późniejszym zamknięciu (pomocnik rezygnuje po 3 min) | ☐ · A (limit pomocnika) |
| C4 | „Później” | Nic się nie zamyka; nowe filtry po ręcznym restarcie | ☐ |
| C5 | Po restarcie: Filtry → Photoshop → \<Kategoria\> | Filtry z kategoriami z PiPL („Nik Collection”, „Topaz Labs”, „Zetmar”) | ✔ użytkownik |

## D. Uruchamianie filtrów
| # | Scenariusz | Oczekiwany wynik | Status |
|---|---|---|---|
| D1 | Własny filtr (Zetmar Kolor) na warstwie z menu / z karty „Filtry” | Okno filtra z podglądem, po OK wynik w warstwie | ✔ użytkownik |
| D2 | Ctrl+Z po filtrze | Jeden krok cofa cały efekt | ✔ użytkownik (po zamknięciu okna zarządzania) |
| D3 | Zaznaczenie prostokątne / nieregularne (lasso, elipsa) | Zmiana tylko w zaznaczeniu; krawędź wygładzona (mieszana) | A (prostokąt, elipsa) · ☐ (lasso w GUI) |
| D4 | Warstwa z kanałem alfa (półprzezroczysta) | Kolor przefiltrowany, alfa bez zmian | A · ☐ |
| D5 | Duży obraz (np. 6000×4000) | Filtr działa, czas rozsądny; powyżej 32000 px komunikat o ograniczeniu | ☐ |
| D6 | Nik Color Efex Pro 4 z menu | Okno otwiera się **bez** komunikatu o awarii, podgląd obrazu | ✔ użytkownik |
| D7 | Pozostałe Nik / Topaz: OK w oknie i zapis wyniku do warstwy | Okno, podgląd, po zatwierdzeniu zmiana w warstwie | ☐ (A: okna startują bez awarii w runnerze) |
| D8 | Wtyczka, która ulegnie awarii | Komunikat „Filtr uległ awarii. Obraz nie został zmieniony.”; **GIMP działa dalej** | A (mini-filtr) · ☐ |
| D9 | Wtyczka, która się zawiesza | Dla testu zgodności: „NIE… nie odpowiedziała w czasie testu”. Dla okna filtra: zamknij je lub zakończ `pshost_runner.exe` w Menedżerze zadań (limit awaryjny 30 min); **GIMP działa dalej** | A (test zgodności) · ☐ |
| D10 | Anulowanie w oknie filtra (Cancel) | Obraz bez zmian, bez komunikatu o błędzie | ☐ |
| D11 | Obraz 16-bit / 32-bit float | Filtr działa na danych zredukowanych do 8 bitów (znane ograniczenie) | ☐ |

## E. Odporność
| # | Scenariusz | Oczekiwany wynik | Status |
|---|---|---|---|
| E1 | Zepsuj `config.json` (usuń nawias) i otwórz okno | Okno się otwiera z ustawieniami domyślnymi, bez awarii | A |
| E2 | Usuń plik `.8bf` z dysku po skanie i uruchom filtr | Komunikat „Plik wtyczki już nie istnieje.” | ☐ |
| E3 | Dwa różne `.8bf` o tej samej nazwie i kategorii | Etykiety w menu rozróżnione dopiskiem „(plik.8bf)” | A |

Raport z testów ręcznych wpisz w kolumnie „Status” (data, wersja GIMP-a, uwagi). Wyniki dla Nik/Topaz uzupełnij też w
[kompatybilnosc.md](kompatybilnosc.md).
