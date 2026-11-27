"""Interface language: Polish source strings with an English translation table.

SPDX-License-Identifier: GPL-2.0-or-later

Choice order: BIMP_LANG environment variable, the "language" preference saved by
the window ("auto", "pl", "en"), then the Windows UI language / locale.
Untranslated strings fall back to Polish.
"""

import json
import locale
import os
from pathlib import Path

LANGUAGES = {"auto": "Automatycznie", "pl": "Polski", "en": "English"}
_language = None


def system_language():
    if os.name == "nt":
        try:
            import ctypes

            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "pl" if primary == 0x15 else "en"
        except (AttributeError, OSError):
            pass
    for value in (os.environ.get("LANGUAGE"), os.environ.get("LC_ALL"), os.environ.get("LANG"), locale.getlocale()[0]):
        if value:
            return "pl" if value.lower().startswith(("pl", "polish")) else "en"
    return "en"


def preferred_language(preferences=None):
    forced = os.environ.get("BIMP_LANG", "").lower()
    if forced in ("pl", "en"):
        return forced
    if preferences:
        try:
            chosen = json.loads(Path(preferences).read_text(encoding="utf-8")).get("language", "auto")
        except (OSError, ValueError, AttributeError):
            chosen = "auto"
        if chosen in ("pl", "en"):
            return chosen
    return system_language()


def set_language(code):
    global _language
    _language = code if code in ("pl", "en") else system_language()


def language():
    if _language is None:
        set_language(preferred_language())
    return _language


def _(text):
    if language() == "en":
        return EN.get(text, text)
    return text


STATUS = {
    "success": ("zapisano", "saved"),
    "skipped": ("pominięto", "skipped"),
    "error": ("błąd", "error"),
    "running": ("w toku", "running"),
    "pending": ("czeka", "pending"),
    "done": ("zakończono", "finished"),
    "cancelled": ("przerwano", "cancelled"),
}


def status_label(code):
    labels = STATUS.get(code)
    if not labels:
        return str(code)
    return labels[1] if language() == "en" else labels[0]


def translate_message(text):
    """Translate an error message: exact text, else a known prefix; line by line."""
    if language() != "en" or not text:
        return text
    lines = []
    for line in str(text).split("\n"):
        if line in EN:
            lines.append(EN[line])
            continue
        for prefix in sorted(EN_PREFIXES, key=len, reverse=True):
            if line.startswith(prefix):
                line = EN_PREFIXES[prefix] + line[len(prefix) :]
                break
        lines.append(line)
    return "\n".join(lines)


EN = {
    # Operations (SCHEMAS) and their fields
    "Zmiana rozmiaru": "Resize",
    "Szerokość: jednostka": "Width: unit",
    "Szerokość (%)": "Width (%)",
    "Szerokość (px)": "Width (px)",
    "Wysokość: jednostka": "Height: unit",
    "Wysokość (%)": "Height (%)",
    "Wysokość (px)": "Height (px)",
    "Procenty": "Percent",
    "Piksele": "Pixels",
    "Bez zmiany": "Unchanged",
    "Proporcje": "Aspect ratio",
    "Rozciągnij": "Stretch",
    "Zachowaj proporcje": "Keep aspect ratio",
    "Dopasuj i dodaj tło": "Fit and pad",
    "Kolor tła": "Background colour",
    "Krycie tła (0–65535)": "Background opacity (0–65535)",
    "Interpolacja": "Interpolation",
    "Brak": "None",
    "Liniowa": "Linear",
    "Sześcienna": "Cubic",
    "NoHalo": "NoHalo",
    "LoHalo": "LoHalo",
    "Tylko pomniejszaj (nie powiększaj mniejszych zdjęć)": "Only shrink (do not enlarge smaller photos)",
    "Zmień rozdzielczość druku": "Change print resolution",
    "Rozdzielczość X (ppi)": "Resolution X (ppi)",
    "Rozdzielczość Y (ppi)": "Resolution Y (ppi)",
    "Kadrowanie": "Crop",
    "Użyj wymiarów w pikselach": "Use pixel dimensions",
    "Własne": "Custom",
    "Własne proporcje: szerokość": "Custom ratio: width",
    "Własne proporcje: wysokość": "Custom ratio: height",
    "Położenie": "Position",
    "Środek": "Centre",
    "Lewy górny": "Top left",
    "Środek górny": "Top centre",
    "Prawy górny": "Top right",
    "Lewy środek": "Middle left",
    "Prawy środek": "Middle right",
    "Lewy dolny": "Bottom left",
    "Środek dolny": "Bottom centre",
    "Prawy dolny": "Bottom right",
    "Odwróć proporcje dla zdjęć pionowych / poziomych": "Swap the ratio for portrait / landscape photos",
    "Odbicie i obrót": "Flip and rotate",
    "Odbij poziomo": "Flip horizontally",
    "Odbij pionowo": "Flip vertically",
    "Obróć": "Rotate",
    "Kąt": "Angle",
    "Korekcja kolorów": "Colour correction",
    "Jasność": "Brightness",
    "Kontrast": "Contrast",
    "Automatyczne poziomy": "Automatic levels",
    "Skala szarości": "Greyscale",
    "Plik krzywych GIMP (opcjonalny)": "GIMP curves file (optional)",
    "Wyostrzenie / rozmycie": "Sharpen / blur",
    "Wartość: ujemna wyostrza, dodatnia rozmywa": "Amount: negative sharpens, positive blurs",
    "Znak wodny": "Watermark",
    "Tekst (wyłącz dla obrazu)": "Text (untick for an image)",
    "Tekst": "Text",
    "Czcionka i rozmiar": "Font and size",
    "Kolor": "Colour",
    "Plik obrazu": "Image file",
    "Skalowanie obrazu znaku": "Watermark image scaling",
    "Bez skalowania": "No scaling",
    "% szerokości zdjęcia": "% of photo width",
    "% wysokości zdjęcia": "% of photo height",
    "Rozmiar obrazu znaku (%)": "Watermark image size (%)",
    "Krycie (%)": "Opacity (%)",
    "Odstęp od krawędzi (px)": "Distance from edge (px)",
    "Format i kompresja": "Format and compression",
    "Format": "Format",
    "Maksymalny rozmiar pliku w KB (0 = bez limitu; JPEG, WebP, HEIF, AVIF)": (
        "Maximum file size in KB (0 = no limit; JPEG, WebP, HEIF, AVIF)"
    ),
    "Zmiana nazwy": "Rename",
    "Wzorzec: $$ lub {name}, ## lub {n:03}, @@ lub {date:%Y%m%d}, {exif:%Y-%m-%d}, {mtime}, {w}x{h}, {ext}, {folder}": (
        "Pattern: $$ or {name}, ## or {n:03}, @@ or {date:%Y%m%d}, {exif:%Y-%m-%d}, {mtime}, {w}x{h}, {ext}, {folder}"
    ),
    "Numer początkowy dla ## / {n}": "First number for ## / {n}",
    "Dodatkowa wersja wyniku (np. miniatura)": "Extra output version (e.g. thumbnail)",
    "Przyrostek nazwy pliku": "File name suffix",
    "Jak wynik główny": "Same as main output",
    "Najdłuższy bok w px (0 = bez zmiany)": "Longest side in px (0 = unchanged)",
    "Maksymalny rozmiar pliku w KB (0 = bez limitu)": "Maximum file size in KB (0 = no limit)",
    "Inna procedura GIMP 3": "Other GIMP 3 procedure",
    "Nazwa procedury": "Procedure name",
    "Kolory z LUT (.cube)": "Colours from LUT (.cube)",
    "Plik LUT (.cube)": "LUT file (.cube)",
    "Siła LUT (%)": "LUT strength (%)",
    # Export profiles
    "Własne ustawienia": "Custom settings",
    "WWW — JPEG 1600 px": "Web — JPEG 1600 px",
    "Druk — TIFF 300 ppi": "Print — TIFF 300 ppi",
    "Archiwum — XCF": "Archive — XCF",
    # Main window
    "BIMP 3 — zdjęcia, LUT i przetwarzanie wsadowe": "BIMP 3 — photos, LUT and batch processing",
    "Zamknij": "Close",
    "Operacje i zdjęcia": "Operations and photos",
    "Podgląd PRZED / PO": "BEFORE / AFTER preview",
    "Odśwież podgląd zaznaczonego zdjęcia": "Refresh preview of the selected photo",
    "Operacje w kolejności": "Operations in order",
    "Zdjęcia wejściowe — przeciągnij tu pliki lub foldery": "Input photos — drop files or folders here",
    "Filtruj listę (nazwa, folder, rozszerzenie)…": "Filter the list (name, folder, extension)…",
    "Dodaj": "Add",
    "Edytuj": "Edit",
    "Usuń": "Remove",
    "Pliki…": "Files…",
    "Folder…": "Folder…",
    "Podgląd": "Preview",
    "Dodaj profil": "Add profile",
    "Wczytaj zestaw…": "Load preset…",
    "Zapisz zestaw…": "Save preset…",
    "Przy dodawaniu folderu uwzględnij podfoldery": "Include subfolders when adding a folder",
    "Katalog wyników": "Output folder",
    "Katalog wyników:": "Output folder:",
    "Zachowaj podfoldery": "Keep subfolders",
    "Zachowaj daty plików": "Keep file dates",
    "Usuń udane wpisy z listy": "Remove successful entries from the list",
    "Pomiń istniejące": "Skip existing",
    "Zastąp wyniki": "Replace outputs",
    "Dodaj przyrostek _2, _3…": "Add suffix _2, _3…",
    "Zachowaj metadane, usuń GPS i nazwy miejsc": "Keep metadata, remove GPS and place names",
    "Zachowaj metadane": "Keep metadata",
    "Usuń EXIF / IPTC / XMP": "Remove EXIF / IPTC / XMP",
    "Zachowaj profil kolorów": "Keep colour profile",
    "Konwertuj do sRGB": "Convert to sRGB",
    "Kolizje nazw": "Name collisions",
    "Metadane": "Metadata",
    "Kolory": "Colours",
    "Język interfejsu": "Interface language",
    "Osadź profil ICC w wyniku": "Embed ICC profile in the output",
    "Obracaj zdjęcia zgodnie z orientacją EXIF": "Rotate photos according to EXIF orientation",
    "Eksport: metadane, kolory, kolizje i język": "Export: metadata, colours, collisions and language",
    "Plan zapisu…": "Write plan…",
    "Wznów zadanie…": "Resume job…",
    "Ponów błędne": "Retry failed",
    "Zapisz raport…": "Save report…",
    "Historia i dane…": "History and data…",
    "Uruchom": "Run",
    "Przerwij": "Stop",
    "Język zostanie zmieniony po ponownym otwarciu okna BIMP.": "The language changes when the BIMP window is reopened.",
    "Nie zapisano preferencji:": "Preferences were not saved:",
    "Nie odtworzono preferencji:": "Preferences were not restored:",
    "Ostatnie zadanie można wznowić:": "The last job can be resumed:",
    "jak wynik": "as output",
    "Dodaj zdjęcia": "Add photos",
    "Dodaj folder": "Add folder",
    "Skanowanie… Ponowne kliknięcie Folder… przerwie skanowanie.": "Scanning… Click Folder… again to stop.",
    "Skanowanie przerwane.": "Scanning stopped.",
    "Na liście: {count} zdjęć.": "Photos in the list: {count}.",
    "Skanowanie…": "Scanning…",
    "Zestaw BIMP 3 lub BIMP 2": "BIMP 3 or BIMP 2 preset",
    "Zapisz zestaw": "Save preset",
    "Zapisz raport": "Save report",
    "Plan zapisu — bez modyfikowania plików": "Write plan — no files are changed",
    "Zastąp": "Replace",
    "Pomiń": "Skip",
    "Nowy plik": "New file",
    "dodatkowa wersja": "extra version",
    "Źródło": "Source",
    "Wynik": "Output",
    "Działanie": "Action",
    "Dodaj i zaznacz zdjęcie.": "Add and select a photo.",
    "Historia zadań i dane BIMP": "Job history and BIMP data",
    "Utworzone": "Created",
    "Stan": "State",
    "Wyniki": "Results",
    "Rozmiar": "Size",
    "Folder": "Folder",
    "zapisano {ok}, pominięto {skipped}, błędów {errors}, czeka {pending}": (
        "saved {ok}, skipped {skipped}, errors {errors}, pending {pending}"
    ),
    "uszkodzone": "damaged",
    "Zadania: {jobs}   Podglądy: {previews}   Profile robocze GIMP: {profiles}": (
        "Jobs: {jobs}   Previews: {previews}   GIMP worker profiles: {profiles}"
    ),
    "Usunięto stare zadania: {count}": "Old jobs removed: {count}",
    "Usunięto pozostałości podglądów: {count}": "Preview leftovers removed: {count}",
    "Usuń zaznaczone": "Delete selected",
    "Wznów zaznaczone": "Resume selected",
    "Otwórz folder": "Open folder",
    "Wyczyść podglądy": "Clean previews",
    "Usuń starsze niż (dni):": "Delete older than (days):",
    "Uruchamianie procesu GIMP…": "Starting the GIMP process…",
    "Zadanie działa w osobnym procesie GIMP.": "The job runs in a separate GIMP process.",
    "Dziennik:": "Journal:",
    "Wybierz job.json zapisanego zadania": "Choose job.json of a saved job",
    "Brak zakończonego zadania.": "There is no finished job.",
    "Brak błędnych pozycji do ponowienia.": "There are no failed entries to retry.",
    "Przerywanie — oczekiwanie na bezpieczne zakończenie operacji…": "Stopping — waiting for a safe point…",
    "{status}: zapisano {good}, pominięto {skipped}, błędów {failed}": (
        "{status}: saved {good}, skipped {skipped}, errors {failed}"
    ),
    "Log:": "Log:",
    # Step editor and preview
    "Anuluj": "Cancel",
    "Wybierz": "Choose",
    "Zapisz": "Save",
    "Wybierz czcionkę GIMP": "Choose a GIMP font",
    "LUT w kodowaniu sRGB. Siła 0% zachowuje oryginalne kolory.": (
        "LUT in sRGB encoding. Strength 0% keeps the original colours."
    ),
    "Zdjęcie do podglądu LUT": "Photo for the LUT preview",
    "Zdjęcie wczytane. Wybierz plik LUT .cube, aby zobaczyć efekt.": (
        "Photo loaded. Choose a .cube LUT file to see the effect."
    ),
    "Wybierz zdjęcie do podglądu…": "Choose a preview photo…",
    "Wczytaj parametry procedury": "Load procedure parameters",
    "Procedury GIMP 3": "GIMP 3 procedures",
    "Nazwa (pisz, aby wyszukać)": "Name (type to search)",
    "Przeglądaj procedury GIMP…": "Browse GIMP procedures…",
    "PRZED": "BEFORE",
    "PO": "AFTER",
    "Wybierz zdjęcie i odśwież podgląd.": "Choose a photo and refresh the preview.",
    "Przygotowywanie podglądu…": "Preparing the preview…",
    "Uruchamianie procesu podglądu GIMP (tylko za pierwszym razem)…": (
        "Starting the GIMP preview process (first time only)…"
    ),
    "Proces podglądu GIMP zakończył się nieoczekiwanie.": "The GIMP preview process ended unexpectedly.",
    "Podgląd gotowy. Operacje wykonano na pełnej rozdzielczości; widok jest pomniejszony.": (
        "Preview ready. Operations ran at full resolution; the view is scaled down."
    ),
    "Podgląd przerwany lub proces nie zakończył renderowania.": "Preview stopped or the process did not finish rendering.",
    # Errors without variable parts
    "Wybierz katalog wyników.": "Choose an output folder.",
    "Wybierz istniejące pliki wejściowe.": "Choose existing input files.",
    "Lista wejściowa zawiera duplikaty.": "The input list contains duplicates.",
    "Wybierz plik obrazu znaku wodnego.": "Choose the watermark image file.",
    "Wybierz procedurę GIMP 3.": "Choose a GIMP 3 procedure.",
    "Wybierz plik LUT .cube.": "Choose a .cube LUT file.",
    "Wybierz czcionkę dostępną w GIMP.": "Choose a font available in GIMP.",
    "Można dodać tylko jedną zmianę nazwy i jedną zmianę formatu.": "Only one rename and one format change can be added.",
    "Każda dodatkowa wersja wymaga innego, niepustego przyrostka nazwy.": (
        "Every extra version needs a different, non-empty name suffix."
    ),
    "Parametry eksportu wersji wymagają wybrania formatu.": "Export parameters of a version require choosing a format.",
    "Wczytaj parametry wybranego formatu lub procedury przed zapisaniem.": (
        "Load the parameters of the chosen format or procedure before saving."
    ),
    "Nie można nadpisać zdjęcia, zależności ani wyniku zadania raportem lub zestawem.": (
        "A report or preset cannot overwrite a photo, a dependency or a job output."
    ),
    "Poczekaj na zakończenie bieżącego zadania.": "Wait until the current job finishes.",
    "To zadanie już działa w innym procesie.": "This job is already running in another process.",
    "Zadanie jest w trakcie przetwarzania.": "The job is being processed.",
    "Tego zadania nie można teraz usunąć: jest otwarte w oknie BIMP.": "This job is open in the BIMP window and cannot be deleted now.",
    "Wszystkie profile robocze GIMP są zajęte. Zamknij inne okna BIMP.": "All GIMP worker profiles are busy. Close other BIMP windows.",
    "Nie znaleziono konsolowego GIMP do pracy w tle.": "Console GIMP for background work was not found.",
    "Plik wynikowy nie może nadpisywać źródła.": "The output must not overwrite the source.",
    "Plik wynikowy nie może nadpisywać zależności zadania.": "The output must not overwrite a job dependency.",
    "Plik wynikowy musi znajdować się w katalogu wyjściowym.": "The output must be inside the output folder.",
    "Eksporter nie zapisał pliku.": "The exporter did not write the file.",
    "Eksporter nie zapisał dodatkowej wersji.": "The exporter did not write the extra version.",
    "Źródło zmieniło się po rozpoczęciu zadania.": "The source changed after the job started.",
    "Krzywe odręczne bez punktów kontrolnych nie są obsługiwane.": "Free-hand curves without control points are not supported.",
    "Nieobsługiwana wersja zestawu BIMP 3.": "Unsupported BIMP 3 preset version.",
    "Import obsługuje zestawy BIMP 2.x. Zestawy starsze wymagają odtworzenia ustawień.": (
        "Import supports BIMP 2.x presets. Older presets have to be recreated."
    ),
}

EN_PREFIXES = {
    "Nie znaleziono pliku LUT:": "LUT file not found:",
    "Nie znaleziono pliku krzywych:": "Curves file not found:",
    "Nie znaleziono pliku wejściowego:": "Input file not found:",
    "Nie znaleziono pliku obrazu znaku wodnego:": "Watermark image file not found:",
    "Plik nie istnieje lub został przeniesiony:": "The file does not exist or was moved:",
    "Plik wynikowy nadpisałby plik wejściowy lub zależność:": "The output would overwrite an input file or dependency:",
    "Dwie pozycje mają tę samą nazwę wynikową:": "Two entries have the same output name:",
    "Plik źródłowy zmienił się od utworzenia zadania:": "The source file changed after the job was created:",
    "Zależność zadania uległa zmianie:": "A job dependency changed:",
    "Wynik ukończonego zadania został zmieniony:": "An output of the finished job was changed:",
    "Niebezpieczna lub powtórzona ścieżka wyniku:": "Unsafe or repeated output path:",
    "Ta instalacja GIMP nie zawiera procedury:": "This GIMP installation lacks the procedure:",
    "Procedura nie znajduje się na liście dozwolonych operacji obrazowych:": "The procedure is not an allowed image operation:",
    "Nieprawidłowa nazwa pliku:": "Invalid file name:",
    "Zastrzeżona nazwa pliku:": "Reserved file name:",
    "Niezamknięty lub nieznany znacznik we wzorcu nazwy:": "Unclosed or unknown tag in the name pattern:",
    "Limit rozmiaru pliku nie działa dla formatu": "The file size limit does not work for the format",
    "Nie da się zmieścić wyniku w": "The output cannot fit in",
    "Nie udało się odczytać rozmiaru zdjęcia": "Could not read the photo size of",
    "GIMP: nie powiodło się:": "GIMP failed:",
    "GIMP odrzucił wartość parametru": "GIMP rejected the value of parameter",
    "Brak obrazu znaku wodnego:": "Watermark image missing:",
    "Proces GIMP przerwał pracę na tym pliku": "The GIMP process stopped working on this file",
    "Proces GIMP zakończył się kodem": "The GIMP process ended with code",
    "Wartość poza zakresem:": "Value out of range:",
    "Nieprawidłowa wartość:": "Invalid value:",
    "Nieznane ustawienia:": "Unknown settings:",
    "LUT: wiersz": "LUT: line",
}
