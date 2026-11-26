# Zadanie dla Claude Code: Puppet/Mesh Warp dla GIMP 3

## Cel

Stwórz plugin **WarpForge** dla GIMP 3: nieniszczący **Puppet Warp** oraz **Mesh Warp** dla warstw i zaznaczeń. Plugin ma pozwalać użytkownikowi deformować obraz przez punkty kontrolne lub siatkę, z podglądem i możliwością późniejszej edycji efektu.

Priorytetem jest działający, stabilny MVP dla systemu Linux. Drugi priorytet: Windows. Nie buduj w pierwszej wersji integracji AI, chmury ani zaawansowanego trybu animacji.

## Kontekst techniczny

- Target: **GIMP 3.x**, aktualna stabilna linia API.
- Język UI/pluginu: **Python 3 + PyGObject**.
- Ciężkie obliczenia deformacji: najlepiej **Rust** przez `PyO3`, albo **C/C++** przez `cffi`/rozszerzenie natywne. Jeśli natywny moduł jest zbyt ryzykowny w pierwszym wydaniu, użyj NumPy/SciPy, ale zaprojektuj kod tak, aby backend dało się podmienić.
- Interfejs: **GTK 4** przez PyGObject.
- Obraz: przetwarzanie przez **GEGL buffers** lub bufor pikseli udostępniany przez API GIMP 3; nie zakładaj istnienia API z GIMP 2.10.
- Format projektu: plugin musi być instalowalny lokalnie i pakowalny jako ZIP; przygotuj też manifest/flatpak-friendly strukturę.
- Licencja: GPL-3.0-or-later, zgodnie z ekosystemem GIMP.

Ważne: GIMP 3 zmienił API względem 2.10. Nie kopiuj kodu pluginów dla GIMP 2.10. Przed implementacją sprawdź aktualną dokumentację GIMP 3, przykłady Python-Fu oraz schemat rejestracji procedur, argumentów, menu i efektów nieniszczących.

## Zakres MVP

### Funkcje obowiązkowe

1. **Puppet Warp**
   - Użytkownik dodaje punkty kontrolne („piny”) na warstwie.
   - Przeciąga pin myszą lub tabletem.
   - Obraz wokół pinów deformuje się płynnie.
   - Użytkownik może ustawiać wpływ/zasięg pinu oraz globalną sztywność deformacji.
   - Może usuwać piny i przywracać ich pozycję.

2. **Mesh Warp**
   - Użytkownik nakłada regularną siatkę, np. 4x4, 6x6, 8x8.
   - Może przesuwać wierzchołki siatki.
   - Obraz jest transformowany przez siatkę.
   - Może przełączać widoczność siatki i podglądu oryginału.

3. **Nieniszczący efekt**
   - Deformacja jest zapisywana jako parametryczny efekt/filtr powiązany z warstwą.
   - Użytkownik może ponownie otworzyć efekt i edytować punkty.
   - Może wyłączyć, usunąć lub przywrócić efekt.
   - Nie nadpisuje trwale pikseli warstwy źródłowej.

4. **Podgląd**
   - Podgląd w czasie rzeczywistym podczas przesuwania pinu.
   - Podgląd liczony na zmniejszonym buforze, np. maks. 1024 px po dłuższym boku.
   - Finalna deformacja wykonywana w pełnej rozdzielczości po zatwierdzeniu.

5. **Maska działania**
   - Domyślnie działa na całej warstwie.
   - Opcjonalnie ogranicza działanie do zaznaczenia.
   - Respektuje istniejącą maskę warstwy, jeśli jest dostępna w API.

6. **Zapis i odczyt presetu**
   - Eksport parametrów do JSON.
   - Import JSON.
   - JSON zawiera: typ warp, wymiary warstwy, punkty, siatkę, parametry sztywności, nazwę presetu, wersję schematu.

7. **Undo**
   - Każda zmiana zatwierdzona w GIMP musi być cofalna przez natywny mechanizm undo.
   - Zmiany w trakcie przeciągania nie powinny zalewać stosu undo; commituj po zakończeniu gestu.

### Funkcje poza MVP

Nie implementuj w pierwszym wydaniu:

- Animacji klatka po klatce.
- Automatycznego wykrywania szkieletu postaci.
- AI inpaintingu.
- Content-aware fill.
- Eksportu wideo.
- Współdzielonej biblioteki presetów online.
- Obsługi wielu otwartych obrazów jednocześnie.
- Pełnej obsługi warstw tekstowych jako obiektów wektorowych; w MVP rasteryzuj roboczą kopię tekstury.

## UX

### Punkt wejścia

Dodaj pozycję menu:

- `Filters > Distort > WarpForge…`

Dodaj też akcję w menu kontekstowym warstwy, jeśli API na to pozwala:

- `WarpForge: Puppet/Mesh Warp`

### Okno dialogowe

Zaprojektuj okno z układem:

```text
+--------------------------------------------------------------+
| WarpForge                                        [X]         |
+--------------------------------------------------------------+
| Tryb: [Puppet Warp] [Mesh Warp]                              |
|                                                              |
| +----------------------------------------------------------+ |
| |                  Canvas / preview                        | |
| |                                                          | |
| +----------------------------------------------------------+ |
|                                                              |
| Sztywność: [========|----]  55%                              |
| Zasięg pinu: [======|------]  180 px                         |
| Gęstość siatki: [4x4] [6x6] [8x8] [Custom]                  |
|                                                              |
| [Dodaj pin] [Usuń pin] [Reset] [Pokaż oryginał]              |
|                                                              |
| [Zastosuj] [Anuluj] [Zapisz preset] [Wczytaj preset]         |
+--------------------------------------------------------------+
```

### Interakcje

- LPM na canvas: dodaje pin w trybie Puppet Warp.
- LPM na istniejącym pinie: wybiera pin.
- Przeciąganie pinu: deformuje podgląd.
- `Delete`: usuwa wybrany pin.
- `Ctrl+Z`: cofa ostatni zatwierdzony krok.
- `Space` przytrzymane: pokazuje oryginał.
- `Enter`: zatwierdza efekt.
- `Esc`: anuluje zmiany niesaved.
- Podwójne kliknięcie na pin: otwiera panel parametrów pinu.
- Scroll: zoom podglądu.
- Środkowy przycisk lub `Space` + przeciąganie: przesuwanie widoku.

## Model danych

Użyj poniższego JSON Schema jako kanonicznego formatu presetu.

```json
{
  "schema_version": 1,
  "plugin": "warpforge",
  "warp_type": "puppet",
  "image_width": 1920,
  "image_height": 1080,
  "layer_id": 12,
  "selection_bounds": [0, 0, 1920, 1080],
  "stiffness": 0.55,
  "mesh": {
    "columns": 0,
    "rows": 0,
    "vertices": []
  },
  "pins": [
    {
      "id": "pin-1",
      "source": [512.0, 384.0],
      "target": [542.0, 371.0],
      "radius": 180.0,
      "weight": 1.0,
      "pinned_rotation": false,
      "pinned_scale": false
    }
  ],
  "mask": {
    "enabled": false,
    "source": "selection"
  }
}
```

Dla `warp_type: "mesh"`:

```json
{
  "schema_version": 1,
  "plugin": "warpforge",
  "warp_type": "mesh",
  "image_width": 1920,
  "image_height": 1080,
  "mesh": {
    "columns": 6,
    "rows": 6,
    "vertices": [
      [0.0, 0.0],
      [320.0, 0.0]
    ]
  },
  "stiffness": 0.5
}
```

Zasady:

- Współrzędne są w przestrzeni pikseli warstwy.
- `source` to pozycja pierwotna.
- `target` to aktualna pozycja po deformacji.
- `vertices` dla mesh są zapisywane jako lista par `[x, y]`.
- Nie zapisuj pikseli w JSON.
- Przy zmianie wymiarów warstwy skaluj parametry proporcjonalnie lub wyświetl ostrzeżenie o niezgodności.

## Algorytm deformacji

### Puppet Warp

Zaimplementuj deformację opartą na **Moving Least Squares** albo ważonej interpolacji RBF. Preferuj wariant, który daje stabilny wynik przy 3–30 pinach.

Wymagania:

- Deformacja musi być ciągła i płynna.
- Pin powinien przesuwać się dokładnie do pozycji docelowej.
- Obszary oddalone od pinów powinny wracać do pierwotnego położenia.
- Nie dopuszczaj do samoprzecinającej się geometrii w typowych przypadkach.
- Uwzględniaj wagę i promień wpływu pinu.
- Zapewnij opcję „rigid segments”: połączone piny zachowują względną odległość i orientację, jeśli użytkownik tego wybierze.

Przykładowy pipeline:

1. Zbierz piny: `(source_i, target_i, weight_i, radius_i)`.
2. Zbuduj ważoną funkcję przekształcenia `f(x)`.
3. Dla każdego piksela oblicz źródłowy współrzędny przez odwrotne mapowanie.
4. Próbkuj obraz źródłowy z interpolacją dwuliniową lub kubiczną.
5. Zapisz wynik do bufora wyjściowego.

### Mesh Warp

Zaimplementuj deformację siatki:

1. Wygeneruj regularną siatkę `columns x rows`.
2. Pozwól przesuwać wierzchołki.
3. Dla każdego piksela znajdź komórkę siatki.
4. Użyj interpolacji barycentrycznej w trójkątach lub mapowania dwuliniowego w czworokątach.
5. Odczytaj piksel z pozycji źródłowej i zapisz do wyjścia.

Wymagania:

- Krawędzie siatki muszą pozostać na brzegach warstwy.
- Wierzchołki nie mogą tworzyć odwróconych trójkątów w typowych przypadkach.
- Zapewnij opcję „clamp to bounds”.
- Podgląd musi reagować poniżej 50 ms dla typowego obrazu 2000x2000 na downscaled bufferze.

## Wydajność

- Podgląd: maksymalnie 1024 px po dłuższym boku, chyba że warstwa jest mniejsza.
- Finalizacja: w pełnej rozdzielczości, w tle lub z progresywnym paskiem postępu.
- Nie blokuj wątku UI długim obliczeniem.
- Cache'uj siatkę, triangulację i macierze wag, dopóki parametry się nie zmienią.
- Dla obrazów powyżej 4000 px po dłuższym boku używaj tile'owania lub streamingu buforów.
- Testuj na obrazach 1000x1000, 4000x4000 i 8000x8000.

## Struktura repozytorium

```text
warpforge/
├── README.md
├── LICENSE
├── pyproject.toml
├── meson.build
├── src/
│   └── warpforge/
│       ├── __init__.py
│       ├── plugin.py
│       ├── dialog.py
│       ├── canvas.py
│       ├── state.py
│       ├── presets.py
│       ├── gimp_bridge.py
│       ├── render.py
│       └── native/
│           ├── Cargo.toml
│           └── src/
│               ├── lib.rs
│               ├── puppet.rs
│               ├── mesh.rs
│               └── geometry.rs
├── data/
│   └── schemas/
│       └── warpforge-preset-v1.schema.json
├── tests/
│   ├── test_geometry.py
│   ├── test_puppet.py
│   ├── test_mesh.py
│   ├── test_presets.py
│   └── fixtures/
└── packaging/
    ├── flatpak/
    └── windows/
```

## API pluginu

Stwórz moduł `gimp_bridge.py` jako jedyną warstwę komunikacji z GIMP. Nie rozlewaj wywołań GIMP po całym kodzie.

Potrzebne operacje:

- Rejestracja procedury pluginu.
- Pobranie aktywnej warstwy i jej wymiarów.
- Odczyt bufora pikseli.
- Zapis bufora pikseli.
- Rejestracja/odczyt parametrów nieniszczącego filtra.
- Obsługa undo.
- Obsługa postępu i anulowania.
- Obsługa zaznaczenia.
- Obsługa maski warstwy.

Jeżeli aktualne API GIMP 3 nie pozwala w pełni zapisać parametrycznego efektu jako filtru NDE, zaimplementuj fallback:

- Zapisz preset JSON obok pliku XCF lub w metadanych obrazu, jeśli API to umożliwia.
- Zapewnij akcję `Edit WarpForge effect`, która odtwarza punkty i pozwala ponownie zastosować deformację.
- Wyraźnie oznacz w README ograniczenie i nie udawaj pełnej trwałości NDE, jeśli nie jest osiągalna.

## Testy

Napisz testy jednostkowe dla logiki niezależnej od GIMP:

- Deformacja pojedynczego pinu przesuwa piksel w promieniu wpływu.
- Piksel daleko od pinu pozostaje niezmieniony.
- Mesh 2x2 przesuwa obraz zgodnie z oczekiwaną transformacją afiniczną.
- Mesh nie tworzy odwróconych trójkątów dla poprawnych danych.
- Preset JSON round-trip nie traci danych.
- Skalowanie presetu po zmianie wymiaru warstwy.
- Wydajność: 1024x1024 podgląd w akceptowalnym czasie.
- Brak wycieków pamięci przy powtarzalnym przesuwaniu pinu.

Dodaj testy integracyjne uruchamiane ręcznie w GIMP:

- Otwarcie pluginu z warstwą RGB 8-bit.
- Otwarcie pluginu z warstwą RGB 16-bit float.
- Działanie na warstwie z maską.
- Działanie na zaznaczeniu.
- Cofnięcie operacji.
- Zapisanie i ponowne otwarcie XCF z efektem.

## Jakość kodu

Wymagania dla implementacji:

- Typowanie Pythona: `from __future__ import annotations`, `typing`, `dataclasses`.
- Brak globalnego stanu poza jawnym obiektem `WarpSession`.
- Wszystkie wywołania GIMP izolowane w `gimp_bridge.py`.
- Logowanie przez `logging`, bez `print`.
- Obsługa błędów: brak aktywnej warstwy, brak pikseli, anulowanie, nieobsługiwany format, nieprawidłowy preset.
- Komunikaty błędów po angielsku, gotowe do późniejszej lokalizacji.
- README po angielsku, z sekcjami: Features, Requirements, Install, Usage, Limitations, Development, License.
- CI: linting (`ruff`), typowanie (`mypy`, tam gdzie wykonalne), testy pytest.
- Nie używaj niepotwierdzonych API ani nie zgaduj nazw funkcji GIMP; sprawdź dokumentację i przykłady przed implementacją.

## Plan implementacji

### Etap 1: Fundament

1. Utwórz repozytorium i strukturę katalogów.
2. Dodaj `README.md`, licencję, `pyproject.toml`, konfigurację lintów i testów.
3. Zbadaj aktualne API GIMP 3 dla pluginów Python, procedur, buforów, undo i NDE.
4. Zaimplementuj rejestrację procedury i otwarcie pustego dialogu.
5. Zaimplementuj odczyt i zapis warstwy przez `gimp_bridge.py`.

### Etap 2: Mesh Warp

1. Zaimplementuj generowanie siatki.
2. Zaimplementuj canvas GTK z rysowaniem warstwy i siatki.
3. Zaimplementuj przesuwanie wierzchołków.
4. Zaimplementuj algorytm deformacji mesh.
5. Zaimplementuj podgląd na downscaled bufferze.
6. Zaimplementuj finalny render w pełnej rozdzielczości.
7. Dodaj undo i obsługę anulowania.

### Etap 3: Puppet Warp

1. Zaimplementuj dodawanie, wybieranie i przesuwanie pinów.
2. Zaimplementuj algorytm deformacji.
3. Dodaj parametry: radius, weight, stiffness.
4. Dodaj wizualizację pinów i obszaru wpływu.
5. Zoptymalizuj podgląd.
6. Dodaj testy geometryczne i wizualne.

### Etap 4: NDE i presety

1. Zbadaj realne możliwości zapisu parametrycznego efektu w GIMP 3.
2. Zaimplementuj trwały efekt NDE, jeśli API na to pozwala.
3. W przeciwnym razie wdroż opisany fallback.
4. Dodaj eksport/import JSON.
5. Dodaj walidację schematu.
6. Dodaj obsługę wersjonowania presetów.

### Etap 5: Wydanie

1. Dodaj ikonę, metadane i dokumentację.
2. Przygotuj instalację dla Linux i Windows.
3. Dodaj przykładowe obrazy testowe.
4. Wykonaj testy ręczne na GIMP 3 w Flatpak i natywnej instalacji.
5. Opublikuj repozytorium, release i instrukcję zgłaszania błędów.

## Kryteria akceptacji MVP

Plugin jest gotowy, gdy:

- Użytkownik może otworzyć `Filters > Distort > WarpForge…` na warstwie.
- Może użyć Puppet Warp z co najmniej 3 pinami.
- Może użyć Mesh Warp 4x4, 6x6 i 8x8.
- Podgląd reaguje płynnie na typowym obrazie.
- Zatwierdzenie tworzy deformację bez trwałego zniszczenia źródłowej warstwy.
- Efekt można ponownie edytować albo co najmniej odtworzyć z presetu.
- Operacja jest cofalna.
- Plugin nie crashuje przy braku aktywnej warstwy.
- Testy jednostkowe przechodzą.
- README wyjaśnia instalację, użycie i ograniczenia.

## Pierwsze polecenie dla Claude Code

```text
Zaimplementuj plugin WarpForge dla GIMP 3 zgodnie z tym plikiem.

Najpierw sprawdź aktualną dokumentację i przykłady API GIMP 3 dla:
- rejestracji pluginu Python/PyGObject,
- odczytu i zapisu buforów pikseli,
- procedur i argumentów,
- undo,
- nieniszczących filtrów/efektów,
- obsługi zaznaczeń i masek warstw.

Nie zgaduj nazw API. Jeśli jakaś funkcja nie istnieje albo ma inną sygnaturę, znajdź właściwy odpowiednik w dokumentacji GIMP 3 i zapisz znalezione rozwiązanie w NOTES.md.

Zacznij od Etapu 1. Zrób minimalny, działający plugin, który otwiera dialog i potrafi odczytać aktywną warstwę. Nie implementuj jeszcze algorytmów deformacji. Po każdym etapie podsumuj:
- co zostało zrobione,
- jakie API zostały użyte,
- jakie ograniczenia odkryłeś,
- jakie ryzyka pozostały,
- co zrobić w kolejnym kroku.
```
