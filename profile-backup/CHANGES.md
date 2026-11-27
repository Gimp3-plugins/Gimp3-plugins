# Zmiany / Changes

## 1.0.0 – 2026-11-27

Pierwsze wydanie. / First release.

- Kopia zapasowa profilu GIMP 3 do ZIP (ZIP64, ścieżki względne, puste katalogi, manifest
  z SHA-256 każdego pliku); duże profile w częściach `.zip.001…` z osobnym manifestem części.
  Opcjonalnie 7-Zip (wielowątkowo).
- Przywracanie z `.zip`, `.zip.001` lub `.manifest.json`: kontrola kompletności i SHA-256,
  potwierdzenie, rozpakowanie obok profilu, podmiana po zamknięciu GIMP-a z kopią
  bezpieczeństwa i wycofaniem zmian przy błędzie; tryby „zastąp” i „scal”.
- Wykrywanie profilu: `Gimp.directory()`, `GIMP3_DIRECTORY`, Windows, Linux (XDG, Flatpak, Snap),
  macOS; obsługa serii `3.0`, `3.2`, …
- Interfejs PL/EN z przełącznikiem w oknie; CLI `pb_core.py` do użycia bez GIMP-a.
- Ochrona przed zip-slip, ścieżki dłuższe niż 260 znaków w Windows, pomijanie dowiązań
  symbolicznych, raport pominiętych plików.
- Backup of the GIMP 3 profile to ZIP (optionally split, optional 7-Zip), verified restore
  applied after GIMP exits with a safety copy and rollback, PL/EN UI, CLI, zip-slip protection.
