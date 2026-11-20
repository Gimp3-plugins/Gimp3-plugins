# Changelog / Zmiany

## 1.0.0 – 2026-11-20

### English

**Fixes**
- *Develop RAW again* (replace) no longer drops the layer's effects, mask, mode, opacity, name and position: it writes into the existing layer and stays undoable; an active selection no longer limits it.
- Paths read from an image (RAW file, camera profile) are opened only after confirmation unless they are plain local paths, so a crafted XCF cannot make Windows authenticate to a remote server.
- The neutral-point white balance matches the clicked spot when the camera crop is on.
- Highlight recovery modes no longer darken the image (automatic compensation; float keeps highlights above 1.0).
- X3F and GPR removed from the supported formats (this LibRaw build cannot decode them).
- Thumbnails report the cropped size; the preview keeps showing why a file failed; hot-pixel removal can be turned off again in the preview.
- Hardening of all new parsers against hostile files (lens metadata, DCP, XMP, Apple maker notes).

**New**
- **HDR dialog for HEIC** (linear float / SDR / built-in) with HDR exposure.
- **iPhone HDR photos** (Apple gain map, iOS 14–17) reconstructed to linear float.
- **Presets**: built-in and your own; `preset` argument for scripts.
- **100% loupe** and **before/after** split view in the preview.
- **Lens corrections** (vignetting, distortion, lateral CA) with lensfun and its database.
- **Camera profiles**: ICC and Adobe DCP (matrices, HueSatMap, LookTable, tone curve).
- **XMP sidecars** from Lightroom and darktable (see the table below).
- **File → Export → Develop RAW files to a folder** (TIFF 16, JPEG, PNG 16, AVIF 10, XCF).
- Wavelet noise reduction uses ~7× less memory on large images (banded, identical result).
- English documentation (README.en.md, LICENSES.en.md); all new texts translated to Polish.
- Unit tests (`meson test`), regression tests, GitHub Actions build.

**XMP settings that are taken over**

| Lightroom / Camera Raw (`crs:`) | darktable | Plug-in setting |
|---|---|---|
| WhiteBalance "As Shot" / "Auto", Temperature + Tint | `temperature` module multipliers | white balance (camera / auto / manual / multipliers) |
| Exposure2012 (or Exposure) | `exposure` module (version ≥ 5) | exposure; beyond +3 EV the rest becomes brightness |
| LensProfileEnable | `lens` module | distortion + vignetting (darktable: also lateral CA) |
| AutoLateralCA | – | lateral CA |
| LuminanceSmoothing (0–100) | – | wavelet noise reduction (×10) |

### Polski

**Poprawki**
- *Wywołaj RAW ponownie* (zamiana) nie kasuje już efektów, maski, trybu, krycia, nazwy i pozycji warstwy: piksele trafiają do istniejącej warstwy, a zmianę można cofnąć; aktywne zaznaczenie nie ogranicza już zamiany.
- Ścieżki odczytane z obrazu (plik RAW, profil aparatu) są otwierane bez pytania tylko wtedy, gdy są zwykłymi ścieżkami lokalnymi, więc spreparowany XCF nie zmusi Windows do logowania do obcego serwera.
- Punkt neutralny balansu bieli trafia w kliknięte miejsce także przy kadrowaniu aparatu.
- Tryby odzyskiwania prześwietleń nie przyciemniają już obrazu (automatyczna kompensacja; float zachowuje światła powyżej 1,0).
- X3F i GPR usunięte z obsługiwanych formatów (ta kompilacja LibRaw ich nie dekoduje).
- Miniatury podają rozmiar po kadrowaniu; podgląd stale pokazuje przyczynę błędu; usuwanie gorących pikseli da się w podglądzie znowu wyłączyć.
- Wszystkie nowe parsery są zabezpieczone przed wrogimi plikami (metadane obiektywu, DCP, XMP, makernote Apple).

**Nowości**
- **Okno HDR dla HEIC** (liniowy float / SDR / moduł wbudowany) z ekspozycją HDR.
- **Zdjęcia HDR z iPhone'a** (mapa wzmocnienia Apple, iOS 14–17) odtwarzane do liniowego float.
- **Presety**: wbudowane i własne; argument `preset` dla skryptów.
- **Lupa 100%** i podział **przed/po** w podglądzie.
- **Korekcja obiektywu** (winieta, dystorsja, poprzeczna aberracja) z lensfun i jego bazą.
- **Profile aparatu**: ICC i Adobe DCP (macierze, HueSatMap, LookTable, krzywa tonalna).
- **Pliki XMP** z Lightrooma i darktable (tabela powyżej, w części angielskiej).
- **Plik → Eksportuj → Wywołaj pliki RAW do folderu** (TIFF 16, JPEG, PNG 16, AVIF 10, XCF).
- Redukcja szumu falkowa zużywa ok. 7× mniej pamięci przy dużych zdjęciach (pasami, wynik identyczny).
- Dokumentacja po angielsku (README.en.md, LICENSES.en.md); wszystkie nowe teksty przetłumaczone na polski.
- Testy jednostkowe (`meson test`), testy regresji, budowanie w GitHub Actions.

## 0.9.0 – 2026-10-07

Pierwsza wersja / First release.

- RAW przez LibRaw 0.22.2 z oknem wywołania i podglądem, balansem bieli, ekspozycją, odzyskiwaniem prześwietleń, demozaikowaniem, redukcją szumu, przestrzeniami barw i wyjściem 8/16/32-bit z profilami ICC.
- Metadane EXIF/XMP/IPTC, szybkie miniatury.
- Filtry → RAW → Wywołaj RAW ponownie; Szybka korekta (nieniszcząca); Otwórz wiele plików RAW.
- HEIC HDR (PQ/HLG) do liniowego float; pliki SDR przez wbudowany moduł GIMP; miniatury HEIF.
- Interfejs po polsku i angielsku; `build.ps1`; testy w `gimp-console`.
