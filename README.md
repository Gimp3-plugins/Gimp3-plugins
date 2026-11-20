# Gimp3-plugins

Plug-ins for **GIMP 3** (Windows). · Wtyczki do **GIMP-a 3** (Windows).

| Plug-in | What it does | Latest release | Docs |
|---|---|---|---|
| **[PSHost](pshost/)** | Use **64-bit Photoshop (`.8bf`) filter plug-ins** in GIMP 3: tests each plug-in, lists which ones will be used (and why not), adds them to *Filters → Photoshop*. PL/EN. | [Releases](../../releases) (`pshost-v*`) | [English](pshost/README.md) · [Polski](pshost/README.pl.md) |
| **[PSHost](pshost/)** (PL) | Używaj **64-bitowych filtrów Photoshop (`.8bf`)** w GIMP-ie 3: sprawdza każdą wtyczkę, mówi które zostaną użyte (a które nie i dlaczego), dodaje je do *Filtry → Photoshop*. | [Wydania](../../releases) (`pshost-v*`) | [Polski](pshost/README.pl.md) |
| **[LUT-y (.cube)](gimp-wtyczki/lut-cube/)** | Apply **color LUTs** (`.cube`, `.3dl`, Hald CLUT) with a library, before/after preview, strength, presets, batch mode and *save your own look as .cube*. | [Releases](../../releases) (`lut-cube-v*`) | [Polski](gimp-wtyczki/lut-cube/README.md) |
| **[LUT-y (.cube)](gimp-wtyczki/lut-cube/)** (PL) | Nakładanie **LUT-ów kolorystycznych** (`.cube`, `.3dl`, Hald) z biblioteką, podglądem przed/po, siłą efektu, presetami, trybem wsadowym i zapisem *własnego looku jako .cube*. | [Wydania](../../releases) (`lut-cube-v*`) | [Polski](gimp-wtyczki/lut-cube/README.md) |
| **[Kreator memów](gimp-wtyczki/meme-maker/)** | Meme maker: top/bottom text with outline, text bar, live preview, JPG/PNG export (Anton font included). | [Releases](../../releases) (`meme-maker-v*`) | [Polski](gimp-wtyczki/meme-maker/README.md) |
| **[Podpis na zdjęciu](gimp-wtyczki/)** | Signature/watermark on a photo: text or logo as a new layer, 9 positions, size in % of the image, saved templates. | [Releases](../../releases) (`podpis-zdjecia-v*`) | [Polski](gimp-wtyczki/README.md#podpis-na-zdjęciu) |
| **[Instagram filters / Filtry Instagram](gimp-instagram-filtry/)** | 22 Instagram-style filters (1977, Lofi, Toaster, X-Pro II…) and a *Text Border* plug-in, ported from GIMP 2 to GIMP 3 - pure Python, no external libraries. | [Releases](../../releases) (`instagram-filtry-v*`) | [English](gimp-instagram-filtry/README.md) · [Polski](gimp-instagram-filtry/README.pl.md) |
| **[Filtry Instagram](gimp-instagram-filtry/)** (PL) | 22 filtry w stylu Instagrama (1977, Lofi, Toaster, X-Pro II…) i wtyczka *Obramowanie tekstu*, przeniesione z GIMP 2 na GIMP 3 - Python, bez zewnętrznych bibliotek. | [Wydania](../../releases) (`instagram-filtry-v*`) | [Polski](gimp-instagram-filtry/README.pl.md) |

**PSHost demo video / Film demonstracyjny PSHost:** [pshost/docs/PSHost-demo.mp4](pshost/docs/PSHost-demo.mp4) (3:55)

Each plug-in lives in its own folder with its own README, tests and installer; releases are tagged `<plug-in>-vX.Y.Z`
(for example `pshost-v0.8.0`). The Python plug-ins (LUT, meme maker, signature) share one folder,
[`gimp-wtyczki/`](gimp-wtyczki/), with a common installer (`install.ps1`) and tests. Every plug-in here is free software
under the **GNU GPL v3 or later** (see [LICENSE](LICENSE)), except *Podpis na zdjęciu*, which is under the MIT license
([gimp-wtyczki/LICENSE](gimp-wtyczki/LICENSE)).

Każda wtyczka ma własny katalog z README, testami i instalatorem; wydania mają znaczniki `<wtyczka>-vX.Y.Z`. Wtyczki
w Pythonie (LUT-y, Kreator memów, Podpis) mają wspólny folder [`gimp-wtyczki/`](gimp-wtyczki/) z jednym instalatorem
(`install.ps1`) i testami. Całość jest wolnym oprogramowaniem na licencji **GNU GPL v3 lub nowszej** (zob.
[LICENSE](LICENSE)), z wyjątkiem *Podpisu na zdjęciu*, który ma licencję MIT ([gimp-wtyczki/LICENSE](gimp-wtyczki/LICENSE)).
