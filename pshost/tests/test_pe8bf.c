/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* Tests for src/common/pe8bf.c. Real-plug-in checks run only when the files exist on this machine. */
#include "../src/common/pe8bf.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int failures = 0, checks = 0;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf ("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); } } while (0)

static int exists (const char *p) { FILE *f = fopen (p, "rb"); if (f) fclose (f); return f != NULL; }

static void write_tmp (const char *path, const void *d, size_t n) { FILE *f = fopen (path, "wb"); fwrite (d, 1, n, f); fclose (f); }

static void test_garbage (void) {
  const char *tmp = "pe8bf_test_garbage.bin";
  Pe8File f;
  pe8_analyze_file ("does\\not\\exist.8bf", &f);
  CHECK (f.count == 0 && f.file_reason == PE8_R_UNREADABLE); pe8_free (&f);

  write_tmp (tmp, "hello world, not a PE file at all", 33);
  pe8_analyze_file (tmp, &f);
  CHECK (f.count == 0 && f.file_reason == PE8_R_NOT_PE); pe8_free (&f);

  unsigned char mz[128] = { 'M', 'Z' }; mz[0x3C] = 0x70;            /* e_lfanew beyond end */
  write_tmp (tmp, mz, sizeof mz);
  pe8_analyze_file (tmp, &f);
  CHECK (f.count == 0 && f.file_reason == PE8_R_NOT_PE); pe8_free (&f);

  /* truncated real file must not crash */
  const char *src = "C:\\Program Files\\Adobe\\Photoshop Elements 2026\\Plug-Ins\\Zetmar\\ZetmarKolor_64.8bf";
  if (exists (src)) {
    FILE *s = fopen (src, "rb"); unsigned char *buf = malloc (600000); size_t n = fread (buf, 1, 600000, s); fclose (s);
    for (size_t cut = 64; cut < n; cut += 40009) { write_tmp (tmp, buf, cut); pe8_analyze_file (tmp, &f); pe8_free (&f); }
    CHECK (1); free (buf);
  }
  remove (tmp);
}

static const Pe8Plugin *find (const Pe8File *f, const char *name) {
  for (size_t i = 0; i < f->count; i++) if (f->items[i].name && strcmp (f->items[i].name, name) == 0) return &f->items[i];
  return NULL;
}

static void test_real (void) {
  const char *kolor = "C:\\Program Files\\Adobe\\Photoshop Elements 2026\\Plug-Ins\\Zetmar\\ZetmarKolor_64.8bf";
  const char *wm = "C:\\Program Files\\Adobe\\Photoshop Elements 2026\\Plug-Ins\\Zetmar\\ZetmarWatermark_64.8bf";
  const char *nik64 = "C:\\Program Files\\Google\\Nik Collection\\Silver Efex Pro 2\\Silver Efex Pro 2 (64-Bit)\\Silver Efex Pro 2.8bf";
  const char *nik32 = "C:\\Program Files\\Google\\Nik Collection\\Silver Efex Pro 2\\Silver Efex Pro 2.8bf";
  const char *hdr = "C:\\Program Files\\Google\\Nik Collection\\HDR Efex Pro 2\\HDR Efex Pro 2 (64-Bit)\\HDR Efex Pro 2.8bf";
  const char *hidden = "C:\\Program Files\\Google\\Nik Collection\\Dfine 2\\Dfine 2 (64-Bit)\\Sky.8bf";
  Pe8File f;

  if (exists (kolor)) {
    pe8_analyze_file (kolor, &f); pe8_check_dependencies (&f, kolor);
    CHECK (f.machine == 0x8664 && f.count == 1);                  /* JSON + binary PiPL deduplicated */
    CHECK (f.count == 1 && !f.items[0].from_json && f.items[0].verdict == PE8_VERDICT_OK);
    CHECK (f.count == 1 && strcmp (f.items[0].category, "Zetmar") == 0 && strcmp (f.items[0].entry, "PluginMain") == 0);
    pe8_free (&f);
  }
  if (exists (wm)) {                                              /* JSON-only PiPL */
    pe8_analyze_file (wm, &f); pe8_check_dependencies (&f, wm);
    CHECK (f.count == 1 && f.items[0].from_json && f.items[0].verdict == PE8_VERDICT_OK);
    CHECK (f.count == 1 && find (&f, "Podpis (Watermark)...") != NULL);
    pe8_free (&f);
  }
  if (exists (nik64)) {
    pe8_analyze_file (nik64, &f);
    CHECK (f.count == 1 && f.items[0].verdict == PE8_VERDICT_OK && strcmp (f.items[0].entry, "filterMain") == 0);
    CHECK (f.n_imports > 0);
    pe8_free (&f);
  }
  if (exists (nik32)) {
    pe8_analyze_file (nik32, &f);
    CHECK (f.machine == 0x14C && f.count == 1 && f.items[0].verdict == PE8_VERDICT_NO && f.items[0].reason == PE8_R_32BIT);
    pe8_free (&f);
  }
  if (exists (hdr)) {
    pe8_analyze_file (hdr, &f);
    CHECK (f.count == 2);
    const Pe8Plugin *m = find (&f, "Merge to HDR Efex Pro 2...");
    CHECK (m && m->reason == PE8_R_NOT_FILTER);
    const Pe8Plugin *h = find (&f, "HDR Efex Pro 2");
    CHECK (h && h->verdict == PE8_VERDICT_OK);
    pe8_free (&f);
  }
  if (exists (hidden)) {
    pe8_analyze_file (hidden, &f);
    CHECK (f.count == 1 && f.items[0].reason == PE8_R_HIDDEN);
    pe8_free (&f);
  }
}

int main (void) {
  test_garbage ();
  test_real ();
  printf ("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
