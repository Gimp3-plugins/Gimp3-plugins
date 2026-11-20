/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
#include "i18n.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#endif

/* generated at build time from po/pl.po (see CMakeLists.txt): */
extern const unsigned char ps_embedded_pl_mo[];
extern const size_t ps_embedded_pl_mo_len;

typedef struct { unsigned char *data; size_t len; unsigned n, orig_off, trans_off; int swap; int loaded; int ok; } Catalog;
static Catalog cat_pl;
static Pe8Lang cur = PE8_LANG_EN;

static unsigned rd (const Catalog *c, size_t off) {
  const unsigned char *p = c->data + off;
  return c->swap ? ((unsigned) p[0] << 24) | ((unsigned) p[1] << 16) | ((unsigned) p[2] << 8) | p[3]
                 : ((unsigned) p[3] << 24) | ((unsigned) p[2] << 16) | ((unsigned) p[1] << 8) | p[0];
}

static int parse (Catalog *c) {
  if (c->len < 28) return 0;
  unsigned magic = (unsigned) c->data[0] | ((unsigned) c->data[1] << 8) | ((unsigned) c->data[2] << 16) | ((unsigned) c->data[3] << 24);
  if (magic == 0x950412deu) c->swap = 0; else if (magic == 0xde120495u) c->swap = 1; else return 0;
  c->n = rd (c, 8); c->orig_off = rd (c, 12); c->trans_off = rd (c, 16);
  if ((size_t) c->orig_off + (size_t) c->n * 8 > c->len || (size_t) c->trans_off + (size_t) c->n * 8 > c->len) return 0;
  return 1;
}

static unsigned char *read_file (const char *path, size_t *n) {
  FILE *f;
#ifdef _WIN32
  wchar_t w[2048];
  if (!MultiByteToWideChar (CP_UTF8, 0, path, -1, w, 2048)) return NULL;
  f = _wfopen (w, L"rb");
#else
  f = fopen (path, "rb");
#endif
  if (!f) return NULL;
  fseek (f, 0, SEEK_END); long l = ftell (f); fseek (f, 0, SEEK_SET);
  if (l <= 0 || l > 8 * 1024 * 1024) { fclose (f); return NULL; }
  unsigned char *d = malloc ((size_t) l);
  if (d && fread (d, 1, (size_t) l, f) != (size_t) l) { free (d); d = NULL; }
  fclose (f); *n = (size_t) l; return d;
}

static int locale_dir (char *out, size_t cap) {
  const char *o = getenv ("PSHOST_LOCALE_DIR");
  if (o && *o) { snprintf (out, cap, "%s", o); return 1; }
#ifdef _WIN32
  wchar_t w[2048]; DWORD n = GetModuleFileNameW (NULL, w, 2048);
  if (n == 0 || n >= 2048) return 0;
  wchar_t *s = wcsrchr (w, L'\\'); if (!s) return 0; *s = 0;
  char u[4096]; if (!WideCharToMultiByte (CP_UTF8, 0, w, -1, u, sizeof u, NULL, NULL)) return 0;
  snprintf (out, cap, "%s\\locale", u); return 1;
#else
  return 0;
#endif
}

static void load_pl (void) {
  if (cat_pl.loaded) return;
  cat_pl.loaded = 1;
  char dir[4200], path[4400];
  if (locale_dir (dir, sizeof dir)) {
    snprintf (path, sizeof path, "%s/pl/LC_MESSAGES/pshost.mo", dir);
    size_t n; unsigned char *d = read_file (path, &n);
    if (d) { cat_pl.data = d; cat_pl.len = n; if (parse (&cat_pl)) { cat_pl.ok = 1; return; } free (d); cat_pl.data = NULL; }
  }
  /* fallback: embedded catalog */
  cat_pl.data = (unsigned char *) ps_embedded_pl_mo; cat_pl.len = ps_embedded_pl_mo_len;
  cat_pl.ok = parse (&cat_pl);
}

static const char *lookup (const Catalog *c, const char *msgid) {
  size_t idlen = strlen (msgid); unsigned lo = 0, hi = c->n;
  while (lo < hi) {
    unsigned mid = (lo + hi) / 2;
    unsigned len = rd (c, c->orig_off + (size_t) mid * 8), off = rd (c, c->orig_off + (size_t) mid * 8 + 4);
    if ((size_t) off + len > c->len) return NULL;
    int cmp = strncmp (msgid, (const char *) c->data + off, len);
    if (cmp == 0 && idlen != len) cmp = idlen < len ? -1 : 1;
    if (cmp == 0) {
      unsigned tl = rd (c, c->trans_off + (size_t) mid * 8), to = rd (c, c->trans_off + (size_t) mid * 8 + 4);
      if ((size_t) to + tl > c->len || tl == 0) return NULL;
      return (const char *) c->data + to;
    }
    if (cmp < 0) hi = mid; else lo = mid + 1;
  }
  return NULL;
}

void ps_i18n_set_language (Pe8Lang l) { cur = l; }
Pe8Lang ps_i18n_get_language (void) { return cur; }

const char *ps_tr_lang (Pe8Lang lang, const char *msgid) {
  if (lang != PE8_LANG_PL || !msgid || !*msgid) return msgid;
  load_pl ();
  if (!cat_pl.ok) return msgid;
  const char *t = lookup (&cat_pl, msgid);
  return t && *t ? t : msgid;
}
const char *ps_tr (const char *msgid) { return ps_tr_lang (cur, msgid); }

size_t ps_i18n_catalog_size (Pe8Lang lang) {
  if (lang != PE8_LANG_PL) return 0;
  load_pl (); return cat_pl.ok ? cat_pl.n : 0;
}
