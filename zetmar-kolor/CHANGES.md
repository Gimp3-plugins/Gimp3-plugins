# Zmiany / Changes

## 1.0.0 (2026-11-28)

Pierwsze wydanie. Port wtyczki *Zetmar Kolor* (.8bf) dla Photoshopa na GIMP 3, bez LUT-ów.

- Krzywe (PCHIP, RGB/R/G/B, tylko jasność, 8 presetów, histogram), czerń-biel z mikserem 6 kolorów,
  sepia, monochromia, duotone, toning, siła ogólna.
- Podgląd po / przed / podział, wynik na nowej warstwie albo na aktywnej, zaznaczenie respektowane.
- Zapis i wczytywanie looku `.zklook` zgodnego z wersją dla Photoshopa.
- Wywołanie bez okna (`look`, `look-file`, `output`), powtarzanie filtra (Ctrl+F). Interfejs PL/EN.

First release. A GIMP 3 port of the *Zetmar Color* Photoshop (.8bf) plug-in, without LUTs:
curves, black & white with a 6-color mixer, sepia, monochrome, duotone, toning, overall strength,
before/after preview, `.zklook` looks compatible with the Photoshop version, PL/EN interface.
