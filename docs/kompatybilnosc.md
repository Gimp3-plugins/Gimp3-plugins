# Kompatybilność wtyczek (PSHost)

Stan: Etap 4. Kolumna „Test PSHost” to wynik `pshost_check` (statyczny + probe `Prepare` na obrazie 64×64).
**„OK” = przeszła test podstawowy**, nie dowód, że filtr działa w GIMP-ie. Kolumna „Realnie w GIMP-ie” zostanie uzupełniona po Etapie 6 (filtry w menu).

| Wtyczka | Test PSHost | Realnie w GIMP-ie | Uwagi |
|---|---|---|---|
| ZetmarKolor_64 (własna) | OK | okno + podgląd działają w runnerze; zapis wyniku do potwierdzenia | PiPL binarny + JSON; podgląd przez `inputRate` |
| ZetmarWatermark_64 (własna) | OK | do potwierdzenia | tylko JSON PiPL |
| Nik: Analog Efex Pro 2 | OK | nie sprawdzone | entry `filterMain`; 32-bit odrzucony |
| Nik: Color Efex Pro 4 | OK | nie sprawdzone | j.w. |
| Nik: Dfine 2 | OK | nie sprawdzone | 7 pod-filtrów `**Hidden**` pominięte (NIE/hidden) |
| Nik: HDR Efex Pro 2 | OK | nie sprawdzone | „Merge to HDR Efex Pro 2…” = NIE (nie jest filtrem) |
| Nik: Sharpener Pro 3 (OS, RPS) | OK | nie sprawdzone | |
| Nik: Silver Efex Pro 2 | OK | nie sprawdzone | |
| Nik: Viveza 2 | OK | nie sprawdzone | |
| Topaz: Adjust 5, B&W Effects 2, Lens Effects, ReStyle (x64) | OK | nie sprawdzone | wersje x86 → NIE (32-bit) |
| Wszystkie wersje x86 (Nik 15, Topaz 4) | NIE | — | „jest 32-bitowa” |
| Syntetyczne: invert, tiled | OK | — | testy automatyczne |
| Syntetyczne: crash / hang / missingdep | NIE | — | probe-crash / probe-timeout / missing-dep |

Wynik zbiorczy na maszynie testowej: 14 użytych, 0 z zastrzeżeniami, 28 pominiętych (20 plików 32-bitowych, 7 ukrytych, 1 nie-filtr).

## Ograniczenia testu
- Probe wywołuje tylko `Prepare`. Filtry z własnym oknem (Zetmar, Nik, Topaz) robią właściwą pracę dopiero w `Start`, gdzie mogą zażądać funkcji hosta, których nie ma (channel ports, PICA suites, 16/32 bit). Takie przypadki wyjdą dopiero w uruchomieniu filtra i zostaną dopisane tutaj.
- Wtyczki z DRM/licencją mogą przejść probe, a odmówić pracy później.
