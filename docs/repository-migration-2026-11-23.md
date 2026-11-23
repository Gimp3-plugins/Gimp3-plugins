# Migracja repozytoriów GIMP 3 — 23.11.2026

Docelowe repozytorium: https://github.com/Gimp3-plugins/Gimp3-plugins. Zachowano pełną historię wszystkich gałęzi źródłowych (każde repozytorium miało tylko `main`) oraz wszystkie tagi. Nowszy kod w kolekcji nie został zastąpiony starszym. Nie było issues ani pull requestów do przeniesienia.

## Repozytoria i historia

| Dawne repozytorium | Oryginalny HEAD | Docelowe pliki |
|---|---|---|
| `zetmar-collab/Gimp3-plugins` | [`54220c7cb263`](https://github.com/Gimp3-plugins/Gimp3-plugins/commit/54220c7cb26391ef03864fc11338f1c734f6f707) | `./` |
| `zetmar-collab/gimp-wtyczki` | [`68de0ffb97cb`](https://github.com/Gimp3-plugins/Gimp3-plugins/commit/68de0ffb97cb7f4e4915d24911bded5fde05b8d0) | `gimp-wtyczki/` |
| `zetmar-collab/gimp-instagram-filtry` | [`7288ac0265a1`](https://github.com/Gimp3-plugins/Gimp3-plugins/commit/7288ac0265a1f4a11bd62c12918e7f6b94338546) | `gimp-instagram-filtry/` |
| `zetmar-collab/gimp-kreator-memow` | [`bbc59c5c45c2`](https://github.com/Gimp3-plugins/Gimp3-plugins/commit/bbc59c5c45c2310a3031712184da992dab1cc34f) | `gimp-wtyczki/` |
| `zetmar-collab/gimp-raw-heic` | [`2c5db9dd2fc3`](https://github.com/Gimp3-plugins/Gimp3-plugins/commit/2c5db9dd2fc30a18a3d19009e56e3a2e5a018664) | `gimp-raw-heic/` |

## Wydania

Starsze wydania używają znaczników z prefiksem `migrated/`, aby nie kolidować z istniejącymi tagami i nie uruchamiać automatycznej budowy nowszej paczki. Pliki wydań są kopiowane bez zmian i sprawdzane sumami SHA-256. Istniejące wydania PSHost zawierały identyczne pliki.

| Dawne repozytorium | Dawny tag | Wydanie po migracji |
|---|---|---|
| `Gimp3-plugins` | `pshost-v0.8.1` | [pshost-v0.8.1](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/pshost-v0.8.1) |
| `Gimp3-plugins` | `pshost-v0.8.0` | [pshost-v0.8.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/pshost-v0.8.0) |
| `gimp-wtyczki` | `lut-cube-v1.0.0` | [migrated/gimp-wtyczki/lut-cube-v1.0.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-wtyczki/lut-cube-v1.0.0) |
| `gimp-wtyczki` | `meme-maker-v1.0.0` | [migrated/gimp-wtyczki/meme-maker-v1.0.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-wtyczki/meme-maker-v1.0.0) |
| `gimp-wtyczki` | `v1.0.0` | [migrated/gimp-wtyczki/v1.0.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-wtyczki/v1.0.0) |
| `gimp-instagram-filtry` | `v1.0.0` | [migrated/gimp-instagram-filtry/v1.0.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-instagram-filtry/v1.0.0) |
| `gimp-kreator-memow` | `v1.0.0` | [migrated/gimp-kreator-memow/v1.0.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-kreator-memow/v1.0.0) |
| `gimp-raw-heic` | `v0.9.0` | [migrated/gimp-raw-heic/v0.9.0](https://github.com/Gimp3-plugins/Gimp3-plugins/releases/tag/migrated/gimp-raw-heic/v0.9.0) |

## Dodatkowe pliki

Do `gimp-wtyczki/docs/meme-maker/` dołączono trzy oryginalne przykłady PNG z osobnego repozytorium Kreatora memów. Wtyczka w tym folderze pozostaje w nowszej wersji. Licencje i informacje o autorach zachowano w podkatalogach.

Oryginalne repozytoria, metadane oraz pliki wydań zabezpieczono także w lokalnej kopii migracji.
