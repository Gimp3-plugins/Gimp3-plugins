# -*- coding: utf-8 -*-
"""Translations (Polish / English) for GIMP 3 Profile Backup.

All user-visible text lives here. Every key must have both "pl" and "en"
(checked by tests/test_core.py). Placeholders use str.format syntax.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LANGUAGES = ("pl", "en")
LANGUAGE_NAMES = {"pl": "Polski", "en": "English"}

STRINGS: dict[str, dict[str, str]] = {
    # ---- menu / procedures ------------------------------------------------
    "menu_submenu": {"pl": "Kopia profilu", "en": "Profile Backup"},
    "menu_backup": {"pl": "_Kopia zapasowa profilu…", "en": "_Back Up Profile…"},
    "menu_restore": {"pl": "_Przywróć profil…", "en": "_Restore Profile…"},
    "doc_backup": {"pl": "Tworzy kopię zapasową profilu użytkownika GIMP 3 (ZIP, opcjonalnie w częściach)",
                   "en": "Back up the GIMP 3 user profile (ZIP, optionally split into parts)"},
    "doc_restore": {"pl": "Przywraca profil użytkownika GIMP 3 z kopii zapasowej",
                    "en": "Restore the GIMP 3 user profile from a backup"},

    # ---- common dialog bits -------------------------------------------------
    "title_backup": {"pl": "Kopia zapasowa profilu GIMP", "en": "GIMP Profile Backup"},
    "title_restore": {"pl": "Przywracanie profilu GIMP", "en": "GIMP Profile Restore"},
    "title_report": {"pl": "Raport", "en": "Report"},
    "title_error": {"pl": "Błąd", "en": "Error"},
    "title_confirm": {"pl": "Potwierdzenie", "en": "Confirmation"},
    "btn_cancel": {"pl": "_Anuluj", "en": "_Cancel"},
    "btn_close": {"pl": "_Zamknij", "en": "_Close"},
    "btn_backup": {"pl": "_Utwórz kopię", "en": "_Back Up"},
    "btn_restore": {"pl": "_Przywróć", "en": "_Restore"},
    "btn_browse": {"pl": "Wybierz…", "en": "Browse…"},
    "btn_yes": {"pl": "_Tak", "en": "_Yes"},
    "btn_no": {"pl": "_Nie", "en": "_No"},
    "btn_continue": {"pl": "_Kontynuuj mimo to", "en": "_Continue anyway"},
    "btn_cancel_pending": {"pl": "Anuluj przygotowane przywracanie",
                           "en": "Cancel prepared restore"},
    "lbl_language": {"pl": "Język:", "en": "Language:"},
    "lbl_profile": {"pl": "Katalog profilu:", "en": "Profile folder:"},
    "lbl_profile_other": {"pl": "Inny katalog…", "en": "Other folder…"},
    "lbl_profile_size": {"pl": "Zawartość: {files} plików, {size}",
                         "en": "Contents: {files} files, {size}"},
    "lbl_profile_size_calc": {"pl": "Liczenie rozmiaru…", "en": "Calculating size…"},
    "lbl_no_profile": {"pl": "Nie znaleziono profilu GIMP 3 – wskaż katalog ręcznie.",
                       "en": "No GIMP 3 profile found – choose the folder manually."},
    "lbl_dest": {"pl": "Katalog docelowy:", "en": "Destination folder:"},
    "lbl_free_space": {"pl": "Wolne miejsce: {free}", "en": "Free space: {free}"},
    "lbl_threshold": {"pl": "Dziel na części, gdy profil przekracza (MB):",
                      "en": "Split into parts when the profile exceeds (MB):"},
    "lbl_part_size": {"pl": "Rozmiar części (MB):", "en": "Part size (MB):"},
    "lbl_use_7z": {"pl": "Użyj 7-Zip (szybciej, wielowątkowo): {path}",
                   "en": "Use 7-Zip (faster, multi-threaded): {path}"},
    "lbl_no_7z": {"pl": "7-Zip nie znaleziony – użyty zostanie wbudowany ZIP.",
                  "en": "7-Zip not found – the built-in ZIP will be used."},
    "lbl_archive": {"pl": "Plik kopii (.zip, .zip.001 lub .manifest.json):",
                    "en": "Backup file (.zip, .zip.001 or .manifest.json):"},
    "lbl_target_profile": {"pl": "Przywróć do profilu:", "en": "Restore into profile:"},
    "lbl_mode": {"pl": "Tryb:", "en": "Mode:"},
    "mode_replace": {"pl": "Zastąp cały profil", "en": "Replace the whole profile"},
    "mode_merge": {"pl": "Scal (zachowaj pliki, których nie ma w kopii)",
                   "en": "Merge (keep files that are not in the backup)"},
    "lbl_auto_apply": {"pl": "Zastosuj automatycznie po zamknięciu GIMP-a",
                       "en": "Apply automatically after GIMP is closed"},
    "lbl_restore_how": {
        "pl": "GIMP używa teraz tego profilu i nadpisze część plików przy wyjściu. "
              "Dlatego kopia zostanie rozpakowana i sprawdzona obok profilu, a podmiana "
              "nastąpi dopiero po zamknięciu GIMP-a. Bieżący profil zostanie zachowany "
              "jako kopia bezpieczeństwa.",
        "en": "GIMP is using this profile right now and rewrites some of its files on exit. "
              "The backup is therefore extracted and verified next to the profile, and the "
              "swap happens only after GIMP has closed. The current profile is kept as a "
              "safety copy."},
    "info_legacy_profile": {"pl": "Uwaga: istnieje też profil GIMP 2.x: {path} (nie jest objęty kopią).",
                            "en": "Note: a GIMP 2.x profile also exists: {path} (not included)."},
    "dlg_choose_profile": {"pl": "Wybierz katalog profilu GIMP 3", "en": "Choose the GIMP 3 profile folder"},
    "dlg_choose_dest": {"pl": "Wybierz katalog na kopie", "en": "Choose the backup folder"},
    "dlg_choose_archive": {"pl": "Wybierz plik kopii zapasowej", "en": "Choose a backup file"},
    "filter_backups": {"pl": "Kopie profilu GIMP", "en": "GIMP profile backups"},

    # ---- progress stages ----------------------------------------------------
    "stage_scanning": {"pl": "Przeglądanie profilu…", "en": "Scanning the profile…"},
    "stage_archiving": {"pl": "Archiwizacja…", "en": "Archiving…"},
    "stage_hashing": {"pl": "Liczenie sum kontrolnych…", "en": "Computing checksums…"},
    "stage_archiving_7z": {"pl": "Kompresja (7-Zip)…", "en": "Compressing (7-Zip)…"},
    "stage_hashing_parts": {"pl": "Sumy kontrolne części…", "en": "Checksumming parts…"},
    "stage_verifying_parts": {"pl": "Sprawdzanie części archiwum…", "en": "Verifying archive parts…"},
    "stage_extracting": {"pl": "Rozpakowywanie i weryfikacja…", "en": "Extracting and verifying…"},
    "stage_extracted": {"pl": "Rozpakowano.", "en": "Extracted."},
    "stage_done": {"pl": "Gotowe.", "en": "Done."},
    "stage_cancelling": {"pl": "Anulowanie…", "en": "Cancelling…"},

    # ---- questions ----------------------------------------------------------
    "ask_low_space": {
        "pl": "W katalogu docelowym może brakować miejsca.\nWolne: {free}\nPotrzebne (szacunkowo): {needed}\n\nKontynuować?",
        "en": "The destination may not have enough space.\nFree: {free}\nNeeded (estimate): {needed}\n\nContinue?"},
    "ask_confirm_restore": {
        "pl": "Przywrócić profil z tej kopii?\n\n{summary}\n\nProfil docelowy: {profile}\nTryb: {mode}\n\n{how}",
        "en": "Restore the profile from this backup?\n\n{summary}\n\nTarget profile: {profile}\nMode: {mode}\n\n{how}"},
    "ask_pending_exists": {
        "pl": "Przywracanie z kopii {source} jest już przygotowane i zostanie zastosowane po zamknięciu GIMP-a.",
        "en": "A restore from {source} is already prepared and will be applied when GIMP closes."},
    "warn_close_gimp": {
        "pl": "UWAGA: GIMP musi być zamknięty podczas przywracania. Po przywróceniu uruchom GIMP-a ponownie.",
        "en": "WARNING: GIMP must be closed while restoring. Start GIMP again afterwards."},
    "confirm_restore_cli": {
        "pl": "Przywrócić do {profile} (tryb: {mode})? [t/N]",
        "en": "Restore into {profile} (mode: {mode})? [y/N]"},

    # ---- summaries / reports ------------------------------------------------
    "summary_backup": {
        "pl": "Data kopii: {created}\nWersja GIMP: {gimp} (profil {series})\nPliki: {files} ({size})\nCzęści: {parts}\nŹródło: {source}",
        "en": "Backup date: {created}\nGIMP version: {gimp} (profile {series})\nFiles: {files} ({size})\nParts: {parts}\nSource: {source}"},
    "verify_ok": {"pl": "Kopia jest kompletna, sumy kontrolne się zgadzają.",
                  "en": "The backup is complete and its checksums match."},
    "report_backup": {
        "pl": "Kopia zapasowa gotowa.\nPliki: {files}\nRozmiar profilu: {size}\nRozmiar archiwum: {archive_size}\nZapisano:\n  {where}",
        "en": "Backup finished.\nFiles: {files}\nProfile size: {size}\nArchive size: {archive_size}\nSaved to:\n  {where}"},
    "report_skipped_header": {"pl": "Pominięte pliki ({count}):", "en": "Skipped files ({count}):"},
    "report_excluded": {"pl": "Wykluczone (tymczasowe/cache): {count}",
                        "en": "Excluded (temporary/cache): {count}"},
    "report_log": {"pl": "Dziennik: {path}", "en": "Log: {path}"},
    "report_restore": {
        "pl": "Przywracanie zakończone.\nPrzywrócono plików: {files}\nProfil: {profile}\nKopia bezpieczeństwa poprzedniego profilu: {safety}",
        "en": "Restore finished.\nFiles restored: {files}\nProfile: {profile}\nSafety copy of the previous profile: {safety}"},
    "report_pending": {
        "pl": "Kopia została rozpakowana i sprawdzona ({files} plików).\n\n"
              "Teraz zamknij GIMP-a (Plik → Zakończ). {auto}\n\n"
              "Bieżący profil zostanie zachowany jako:\n  {safety}\n\n"
              "Rozpakowana kopia czeka w:\n  {staging}",
        "en": "The backup has been extracted and verified ({files} files).\n\n"
              "Now close GIMP (File → Quit). {auto}\n\n"
              "The current profile will be kept as:\n  {safety}\n\n"
              "The extracted backup is waiting in:\n  {staging}"},
    "report_pending_auto": {
        "pl": "Profil zostanie podmieniony automatycznie kilka sekund po zamknięciu; potem uruchom GIMP-a ponownie.",
        "en": "The profile will be swapped automatically a few seconds after GIMP exits; then start GIMP again."},
    "report_pending_manual": {
        "pl": "Po zamknięciu GIMP-a uruchom w terminalu:\n  {command}",
        "en": "After GIMP has closed, run in a terminal:\n  {command}"},
    "report_previous_ok": {
        "pl": "Poprzednie przywracanie zostało zastosowane ({finished}).\nProfil: {profile}\nKopia bezpieczeństwa: {safety}",
        "en": "The previous restore was applied ({finished}).\nProfile: {profile}\nSafety copy: {safety}"},
    "report_previous_failed": {
        "pl": "Poprzednie przywracanie NIE powiodło się ({finished}):\n{error}\nProfil nie został zmieniony.",
        "en": "The previous restore FAILED ({finished}):\n{error}\nThe profile was not changed."},
    "report_cancelled": {"pl": "Operacja anulowana. Nic nie zostało zmienione.",
                         "en": "Operation cancelled. Nothing was changed."},

    # ---- skip reasons -------------------------------------------------------
    "reason_symlink": {"pl": "dowiązanie symboliczne (nie jest kopiowane)",
                       "en": "symbolic link (not followed)"},
    "reason_reserved_name": {"pl": "nazwa zarezerwowana dla manifestu", "en": "name reserved for the manifest"},
    "reason_open_error": {"pl": "nie można otworzyć (zablokowany?)", "en": "cannot open (locked?)"},
    "reason_read_error": {"pl": "błąd odczytu", "en": "read error"},
    "reason_stat_error": {"pl": "brak dostępu do atrybutów", "en": "cannot read attributes"},
    "reason_not_a_regular_file": {"pl": "nie jest zwykłym plikiem", "en": "not a regular file"},
    "reason_not_in_manifest": {"pl": "wpis spoza manifestu (pominięty)", "en": "entry not in manifest (ignored)"},
    "reason_unsafe_path": {"pl": "niebezpieczna ścieżka (odrzucona)", "en": "unsafe path (rejected)"},
    "reason_missing_in_archive": {"pl": "brak w archiwum", "en": "missing from the archive"},

    # ---- errors -------------------------------------------------------------
    "err_cancelled": {"pl": "Anulowano.", "en": "Cancelled."},
    "err_no_profile_found": {"pl": "Nie znaleziono profilu GIMP 3.", "en": "No GIMP 3 profile was found."},
    "err_profile_missing": {"pl": "Katalog profilu nie istnieje: {path}",
                            "en": "The profile folder does not exist: {path}"},
    "err_dest_inside_profile": {
        "pl": "Nie można zapisać kopii wewnątrz profilu.\nCel: {dest}\nProfil: {profile}",
        "en": "Backups cannot be stored inside the profile.\nDestination: {dest}\nProfile: {profile}"},
    "err_dest_not_writable": {"pl": "Nie można zapisywać w katalogu {path}:\n{error}",
                              "en": "Cannot write to {path}:\n{error}"},
    "err_no_space": {"pl": "Za mało miejsca w {path}. Wolne: {free}, potrzebne: {needed}.",
                     "en": "Not enough space in {path}. Free: {free}, needed: {needed}."},
    "err_output_exists": {"pl": "Plik już istnieje: {path}", "en": "File already exists: {path}"},
    "err_7z_failed": {"pl": "7-Zip zakończył się błędem (kod {code}): {output}",
                      "en": "7-Zip failed (code {code}): {output}"},
    "err_manifest_unreadable": {"pl": "Nie można odczytać manifestu {path}: {error}",
                                "en": "Cannot read manifest {path}: {error}"},
    "err_not_a_backup": {"pl": "To nie jest kopia profilu utworzona tą wtyczką: {path}",
                         "en": "This is not a profile backup made by this plug-in: {path}"},
    "err_parts_missing": {"pl": "Brakuje części archiwum: {parts}", "en": "Missing archive parts: {parts}"},
    "err_file_missing": {"pl": "Plik nie istnieje: {path}", "en": "File not found: {path}"},
    "err_part_corrupt": {"pl": "Część archiwum jest uszkodzona (niezgodna suma SHA-256 lub rozmiar): {part}",
                         "en": "Archive part is damaged (SHA-256 or size mismatch): {part}"},
    "err_zip_corrupt": {"pl": "Archiwum jest uszkodzone: {path}\n{error}",
                        "en": "The archive is damaged: {path}\n{error}"},
    "err_extract_failed": {"pl": "Nie można rozpakować {path}: {error}",
                           "en": "Cannot extract {path}: {error}"},
    "err_checksum_mismatch": {"pl": "Niezgodna suma kontrolna pliku: {path}",
                              "en": "Checksum mismatch for file: {path}"},
    "err_staging_missing": {"pl": "Brak rozpakowanej kopii: {path}", "en": "Extracted backup is missing: {path}"},
    "err_profile_in_use": {
        "pl": "Nie można przenieść profilu {path} – prawdopodobnie GIMP jest uruchomiony.\n{error}",
        "en": "Cannot move the profile {path} – GIMP is probably running.\n{error}"},
    "err_rollback_failed": {
        "pl": "Przywracanie się nie powiodło i nie udało się cofnąć zmian. Oryginalny profil jest w: {safety}",
        "en": "Restore failed and could not be rolled back. The original profile is at: {safety}"},
    "err_apply_failed": {"pl": "Nie udało się zastosować kopii (profil przywrócono do stanu sprzed): {error}",
                         "en": "Could not apply the backup (the profile was put back as it was): {error}"},
    "err_safety_copy_failed": {"pl": "Nie udało się utworzyć kopii bezpieczeństwa {path}: {error}",
                               "en": "Could not create the safety copy {path}: {error}"},
    "err_no_archive": {"pl": "Wskaż plik kopii zapasowej.", "en": "Choose a backup file."},
    "err_no_dest": {"pl": "Wskaż katalog docelowy.", "en": "Choose a destination folder."},
    "err_unexpected": {"pl": "Nieoczekiwany błąd: {error}", "en": "Unexpected error: {error}"},
    "err_helper_failed": {"pl": "Nie udało się uruchomić procesu pomocniczego: {error}",
                          "en": "Could not start the helper process: {error}"},
}


def tr(key: str, lang: str = "en", **params) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        text = key
    else:
        text = entry.get(lang) or entry.get("en") or key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text + " " + repr(params)
    return text


def reason_text(reason: str, lang: str = "en") -> str:
    """'open-error: Permission denied' -> translated reason + detail."""
    head, _, detail = reason.partition(":")
    key = "reason_" + head.strip().replace("-", "_")
    base = tr(key, lang) if key in STRINGS else head
    return f"{base} ({detail.strip()})" if detail.strip() else base


def _from_code(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip().lower()
    if not code or code in ("c", "posix"):
        return None
    # "pl", "pl_PL.UTF-8", and Windows-style "Polish_Poland"
    return "pl" if code.startswith(("pl", "polish")) else "en"


def gimprc_language(gimprc: Path | None) -> str | None:
    """Language chosen in GIMP's Preferences (gimprc: (language "pl"))."""
    if not gimprc:
        return None
    try:
        text = Path(gimprc).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'^\(language\s+"([^"]*)"\)', text, re.MULTILINE)
    return _from_code(m.group(1)) if m else None


def _windows_ui_language() -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "pl" if (langid & 0x3FF) == 0x15 else "en"
    except Exception:
        return None


def detect_language(gimprc: Path | None = None, env: dict | None = None,
                    windows_ui: bool = True) -> str:
    """Polish if GIMP or the system is Polish, otherwise English.

    Order: gimprc (language ...) -> LANGUAGE/LC_ALL/LC_MESSAGES/LANG ->
    Windows UI language -> locale module -> English.
    """
    lang = gimprc_language(gimprc)
    if lang:
        return lang
    env = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _from_code((env.get(var) or "").split(":")[0])
        if lang:
            return lang
    if windows_ui:
        lang = _windows_ui_language()
        if lang:
            return lang
    try:
        import locale
        lang = _from_code((locale.getlocale()[0] or ""))
        if lang:
            return lang
    except Exception:
        pass
    return "en"
