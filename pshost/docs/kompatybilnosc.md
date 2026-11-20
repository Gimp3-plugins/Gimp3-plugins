# Kompatybilność wtyczek (PSHost 0.8.1)

Kolumny: **Test PSHost** = wynik `pshost_check` (statyczny + probe `Prepare`); **Start w runnerze** = filtr z własnym oknem
uruchomiony w `pshost_runner` na 8–15 s (`tests/try_plugin.py`): „bez awarii” = okno wtyczki się otworzyło i wczytało
obraz; **W GIMP-ie** = co potwierdził użytkownik w prawdziwym GIMP-ie. **„OK” w teście PSHost oznacza tylko test
podstawowy** — Nik pokazał, że wtyczka może przejść go i zawieść dopiero w `Start` (naprawione w 6b).

**Wersja Nik Collection użyta w testach:** darmowa wersja od Google **1.2.11** (64-bitowe filtry). Wtyczki nie są częścią PSHost i nie są przez niego rozpowszechniane.

| Wtyczka | Test PSHost | Start w runnerze | W GIMP-ie (potwierdzone przez użytkownika) | Uwagi |
|---|---|---|---|---|
| ZetmarKolor_64 (własna) | OK | okno + podgląd | **działa** (okno, filtr, Cofnij) | podgląd przez `inputRate` |
| ZetmarWatermark_64 (własna) | OK | okno | nie potwierdzono osobno | opis tylko w JSON PiPL |
| Nik: Color Efex Pro 4 | OK | bez awarii, obraz wczytany i wyświetlony | **okno otwiera się bez błędu** | przed 6b: awaria (brak `sSPBasic`) |
| Nik: Analog Efex Pro 2 | OK | bez awarii | nie sprawdzono | |
| Nik: Silver Efex Pro 2 | OK | bez awarii | nie sprawdzono | |
| Nik: HDR Efex Pro 2 | OK | bez awarii | nie sprawdzono | „Merge to HDR Efex Pro 2…” = NIE (nie jest filtrem) |
| Nik: Dfine 2 | OK | bez awarii | nie sprawdzono | 7 pod-filtrów `**Hidden**` pomijane |
| Nik: Sharpener Pro 3 (OS, RPS) | OK | bez awarii | nie sprawdzono | |
| Nik: Viveza 2 | OK | bez awarii | nie sprawdzono | |
| Topaz: Adjust 5, B&W Effects 2, Lens Effects, ReStyle (x64) | OK | bez awarii | nie sprawdzono | zgłaszają brak właściwości `plip` (nieistotne w testach) |
| Wszystkie wersje x86 (Nik 15, Topaz 4) | NIE: 32-bitowa | — | odrzucone (widoczne na liście) | |
| Syntetyczne: invert, tiled, pica | OK | pełny przebieg | testy automatyczne w GIMP-ie | |
| Syntetyczne: crash / hang / missingdep | NIE (probe-crash / probe-timeout / missing-dep) | — | testy automatyczne | |

Wynik zbiorczy na maszynie testowej: **14 użytych, 0 z zastrzeżeniami, 28 pominiętych** (20 plików 32-bitowych, 7 ukrytych,
1 nie-filtr).

## Znane niedziałające lub niepewne przypadki
- **Action Manager / zestawy descriptorów:** wtyczki (np. Nik) zgłaszają brak zestawu Action Descriptor; startują dalej,
  ale ustawień nie zapisują przez Action Manager. Efekt w praktyce — do sprawdzenia przy zatwierdzaniu filtra.
- **Channel ports, usługi kolorów, interpolacja (`imageServices`), 16/32 bit:** nieobsługiwane; wtyczki, które ich
  *wymagają*, zawiodą (komunikat o awarii lub błąd wtyczki).
- **Zapis wyniku z okien Nik/Topaz (OK → warstwa):** nie potwierdzony poza Color Efex Pro 4 (okno) — do testów ręcznych (D7).
- **Zawieszone okno filtra:** brak przycisku „przerwij” w GIMP-ie; zamknij okno wtyczki lub zakończ `pshost_runner.exe`
  (limit awaryjny 30 min). Test zgodności ma limit czasu i zawieszenie wykrywa.
- **„Powtórz ostatni filtr” bez okna:** wtyczki trzymające stan tylko w pamięci procesu pokażą okno ponownie.
