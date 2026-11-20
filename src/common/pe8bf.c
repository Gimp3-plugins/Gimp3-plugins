/* PSHost - static analysis of Photoshop plug-in (.8bf) files. See pe8bf.h. */
#include "pe8bf.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#ifdef _WIN32
#include <windows.h>
#endif

/* ---------------------------------------------------------------- helpers */

typedef struct { const unsigned char *d; size_t n; } Buf;

static char *xstrdup (const char *s) {
  if (!s) return NULL;
  size_t l = strlen (s) + 1; char *r = malloc (l);
  if (r) memcpy (r, s, l);
  return r;
}
static int rd16 (Buf b, size_t o, unsigned *v) {
  if (o + 2 > b.n) return 0;
  *v = b.d[o] | (b.d[o + 1] << 8); return 1;
}
static int rd32 (Buf b, size_t o, unsigned *v) {
  if (o + 4 > b.n) return 0;
  *v = (unsigned) b.d[o] | ((unsigned) b.d[o + 1] << 8) | ((unsigned) b.d[o + 2] << 16) | ((unsigned) b.d[o + 3] << 24);
  return 1;
}

static unsigned char *read_file (const char *path_utf8, size_t *size) {
  FILE *f;
#ifdef _WIN32
  wchar_t wpath[4096];
  if (!MultiByteToWideChar (CP_UTF8, 0, path_utf8, -1, wpath, 4096)) return NULL;
  f = _wfopen (wpath, L"rb");
#else
  f = fopen (path_utf8, "rb");
#endif
  if (!f) return NULL;
  fseek (f, 0, SEEK_END); long n = ftell (f); fseek (f, 0, SEEK_SET);
  if (n <= 0 || n > 512L * 1024 * 1024) { fclose (f); return NULL; }
  unsigned char *d = malloc ((size_t) n);
  if (d && fread (d, 1, (size_t) n, f) != (size_t) n) { free (d); d = NULL; }
  fclose (f);
  *size = (size_t) n;
  return d;
}

/* Latin-1 -> UTF-8 (PiPL pascal strings are single-byte; Windows-1252 approximated by Latin-1) */
static char *latin1_to_utf8 (const unsigned char *s, size_t n) {
  char *r = malloc (n * 2 + 1); size_t j = 0;
  if (!r) return NULL;
  for (size_t i = 0; i < n; i++) {
    if (s[i] < 0x80) r[j++] = (char) s[i];
    else { r[j++] = (char) (0xC0 | (s[i] >> 6)); r[j++] = (char) (0x80 | (s[i] & 0x3F)); }
  }
  r[j] = 0; return r;
}

static void put_utf8 (char *r, size_t *j, unsigned cp) {
  if (cp < 0x80) r[(*j)++] = (char) cp;
  else if (cp < 0x800) { r[(*j)++] = (char) (0xC0 | (cp >> 6)); r[(*j)++] = (char) (0x80 | (cp & 0x3F)); }
  else { r[(*j)++] = (char) (0xE0 | (cp >> 12)); r[(*j)++] = (char) (0x80 | ((cp >> 6) & 0x3F)); r[(*j)++] = (char) (0x80 | (cp & 0x3F)); }
}

/* ------------------------------------------------------------ PE structure */

typedef struct { unsigned va, vsize, raw, rsize; } Section;
typedef struct { Section s[96]; unsigned n; } Sections;

static long rva_to_off (const Sections *S, Buf b, unsigned rva) {
  for (unsigned i = 0; i < S->n; i++) {
    unsigned sz = S->s[i].vsize > S->s[i].rsize ? S->s[i].vsize : S->s[i].rsize;
    if (rva >= S->s[i].va && rva < S->s[i].va + sz) {
      size_t off = (size_t) (rva - S->s[i].va) + S->s[i].raw;
      return off < b.n ? (long) off : -1;
    }
  }
  return -1;
}

static int read_cstr (Buf b, long off, char *out, size_t cap) {
  if (off < 0) return 0;
  size_t i = 0;
  for (; (size_t) off + i < b.n && i + 1 < cap; i++) { out[i] = (char) b.d[off + i]; if (!out[i]) return 1; }
  out[i] = 0; return i > 0;
}

static void add_str (char ***arr, size_t *n, const char *s) {
  char **t = realloc (*arr, (*n + 1) * sizeof (char *));
  if (!t) return;
  *arr = t; (*arr)[(*n)++] = xstrdup (s);
}

/* ------------------------------------------------------------- PiPL parse */

typedef struct { int id; int is_json; const unsigned char *d; size_t n; } Res;

static void add_item (Pe8File *f, Pe8Plugin *p) {
  Pe8Plugin *t = realloc (f->items, (f->count + 1) * sizeof *t);
  if (!t) return;
  f->items = t; f->items[f->count++] = *p;
}

static int key_is (const unsigned char *k, const char *name) { /* key stored byte-reversed */
  return k[0] == (unsigned char) name[3] && k[1] == (unsigned char) name[2] && k[2] == (unsigned char) name[1] && k[3] == (unsigned char) name[0];
}

static void parse_binary_pipl (Pe8File *f, const Res *r, const char *path) {
  Buf b = { r->d, r->n };
  size_t o; unsigned count = 0;
  if (r->n >= 14 && memcmp (r->d + 10, "MIB8", 4) == 0) { rd32 (b, 6, &count); o = 10; }
  else if (r->n >= 12 && memcmp (r->d + 8, "MIB8", 4) == 0) { rd32 (b, 4, &count); o = 8; }
  else return;
  if (count > 4096) return;

  Pe8Plugin p; memset (&p, 0, sizeof p);
  p.path = xstrdup (path); p.resource_id = r->id;
  for (unsigned i = 0; i < count; i++) {
    unsigned id, len;
    if (o + 16 > r->n || memcmp (r->d + o, "MIB8", 4) != 0) break;
    const unsigned char *key = r->d + o + 4;
    if (!rd32 (b, o + 8, &id) || !rd32 (b, o + 12, &len)) break;
    if (o + 16 + len > r->n) break;
    const unsigned char *data = r->d + o + 16;
    if (key_is (key, "kind") && len >= 4) { p.kind[0] = (char) data[3]; p.kind[1] = (char) data[2]; p.kind[2] = (char) data[1]; p.kind[3] = (char) data[0]; }
    else if (key_is (key, "name") && len >= 1) { size_t l = data[0]; if (l > len - 1) l = len - 1; free (p.name); p.name = latin1_to_utf8 (data + 1, l); }
    else if (key_is (key, "catg") && len >= 1) { size_t l = data[0]; if (l > len - 1) l = len - 1; free (p.category); p.category = latin1_to_utf8 (data + 1, l); }
    else if (memcmp (key, "4668", 4) == 0 /* '8664' reversed */ && len >= 1) { size_t l = strnlen ((const char *) data, len); free (p.entry); p.entry = malloc (l + 1); if (p.entry) { memcpy (p.entry, data, l); p.entry[l] = 0; } }
    else if (key_is (key, "mode") && len >= 2) { p.modes = (unsigned) (data[0] << 8 | data[1]); p.modes_known = 1; }
    o += 16 + len + ((4 - (len % 4)) % 4);
  }
  if (p.kind[0]) add_item (f, &p); else { free (p.path); free (p.name); free (p.category); free (p.entry); }
}

/* --- minimal tolerant JSON helpers (only for the "PiPLs" resource) --- */

static const char *json_skip_ws (const char *s, const char *e) { while (s < e && isspace ((unsigned char) *s)) s++; return s; }

static const char *json_find_key (const char *s, const char *e, const char *key) {
  size_t kl = strlen (key);
  for (const char *p = s; p + kl + 2 < e; p++)
    if (*p == '"' && memcmp (p + 1, key, kl) == 0 && p[kl + 1] == '"') {
      const char *q = json_skip_ws (p + kl + 2, e);
      if (q < e && *q == ':') return json_skip_ws (q + 1, e);
    }
  return NULL;
}

static char *json_get_string (const char *s, const char *e, const char *key) {
  const char *p = json_find_key (s, e, key);
  if (!p || p >= e || *p != '"') return NULL;
  p++;
  char *r = malloc ((size_t) (e - p) + 1); size_t j = 0;
  if (!r) return NULL;
  while (p < e && *p != '"') {
    if (*p == '\\' && p + 1 < e) {
      p++;
      if (*p == 'u' && p + 4 < e) { char hex[5] = { p[1], p[2], p[3], p[4], 0 }; put_utf8 (r, &j, (unsigned) strtoul (hex, NULL, 16)); p += 5; continue; }
      char c = *p == 'n' ? '\n' : *p == 't' ? '\t' : *p; r[j++] = c; p++;
    } else r[j++] = *p++;
  }
  r[j] = 0; return r;
}

static void parse_json_pipl (Pe8File *f, const Res *r, const char *path) {
  const char *s = (const char *) r->d, *e = s + r->n;
  if (r->n >= 3 && (unsigned char) s[0] == 0xEF) s += 3;
  const char *p = json_find_key (s, e, "PiPLs");
  if (!p || p >= e || *p != '[') return;
  p++;
  for (;;) {
    while (p < e && *p != '{' && *p != ']') p++;
    if (p >= e || *p == ']') break;
    const char *start = p; int depth = 0, instr = 0;
    for (; p < e; p++) {
      if (instr) { if (*p == '\\') { if (p + 1 < e) p++; } else if (*p == '"') instr = 0; continue; }
      if (*p == '"') instr = 1; else if (*p == '{') depth++; else if (*p == '}' && --depth == 0) { p++; break; }
    }
    const char *oe = p < e ? p : e;   /* never read past the resource end (truncated/malicious JSON) */
    Pe8Plugin it; memset (&it, 0, sizeof it);
    it.path = xstrdup (path); it.from_json = 1; it.resource_id = -1;
    char *kind = json_get_string (start, oe, "Kind");
    if (kind) {
      if (strcmp (kind, "Filter") == 0) strcpy (it.kind, "8BFM"); else { strncpy (it.kind, kind, 4); it.kind[4] = 0; }
      free (kind);
    }
    it.name = json_get_string (start, oe, "Name");
    it.category = json_get_string (start, oe, "Category");
    it.entry = json_get_string (start, oe, "CodeEntryPointWin64");
    const char *m = json_find_key (start, oe, "RGBColor");
    if (m) { it.modes_known = 1; if (strncmp (m, "true", 4) == 0) it.modes |= 0x1000; }
    if (it.kind[0]) add_item (f, &it); else { free (it.path); free (it.name); free (it.category); free (it.entry); }
  }
}

/* --------------------------------------------------------------- resources */

static int ci_eq_utf16 (Buf b, size_t off, const char *s) {
  unsigned len; if (!rd16 (b, off, &len)) return 0;
  if (len != strlen (s)) return 0;
  for (unsigned i = 0; i < len; i++) { unsigned c; if (!rd16 (b, off + 2 + 2 * i, &c)) return 0; if (toupper ((int) c) != toupper ((unsigned char) s[i])) return 0; }
  return 1;
}

static void walk_resources (Pe8File *f, Buf b, const Sections *S, unsigned rsrc_rva, const char *path) {
  long base = rva_to_off (S, b, rsrc_rva);
  if (base < 0) return;
  unsigned nn, ni;
  if (!rd16 (b, base + 12, &nn) || !rd16 (b, base + 14, &ni)) return;
  for (unsigned i = 0; i < nn + ni && i < 64; i++) {
    unsigned nm, off1;
    if (!rd32 (b, base + 16 + i * 8, &nm) || !rd32 (b, base + 20 + i * 8, &off1)) return;
    int named = (nm & 0x80000000u) != 0, is_pipl = 0, is_json = 0;
    if (named) { size_t no = (size_t) base + (nm & 0x7FFFFFFFu); is_pipl = ci_eq_utf16 (b, no, "PIPL"); is_json = ci_eq_utf16 (b, no, "JSON"); }
    if ((!is_pipl && !is_json) || !(off1 & 0x80000000u)) continue;
    size_t d1 = (size_t) base + (off1 & 0x7FFFFFFFu);
    unsigned n1a, n1b; if (!rd16 (b, d1 + 12, &n1a) || !rd16 (b, d1 + 14, &n1b)) continue;
    for (unsigned j = 0; j < n1a + n1b && j < 256; j++) {
      unsigned idv, off2;
      if (!rd32 (b, d1 + 16 + j * 8, &idv) || !rd32 (b, d1 + 20 + j * 8, &off2)) break;
      if (!(off2 & 0x80000000u)) continue;
      size_t d2 = (size_t) base + (off2 & 0x7FFFFFFFu);
      unsigned n2a, n2b; if (!rd16 (b, d2 + 12, &n2a) || !rd16 (b, d2 + 14, &n2b) || n2a + n2b == 0) continue;
      unsigned lang, off3; if (!rd32 (b, d2 + 16, &lang) || !rd32 (b, d2 + 20, &off3)) continue;
      unsigned drva, dsz;
      if ((off3 & 0x80000000u) || !rd32 (b, (size_t) base + off3, &drva) || !rd32 (b, (size_t) base + off3 + 4, &dsz)) continue;
      long doff = rva_to_off (S, b, drva);
      if (doff < 0 || (size_t) doff + dsz > b.n) continue;
      Res r = { (nm & 0x80000000u) ? (int) idv : 0, is_json, b.d + doff, dsz };
      r.id = (int) (idv & 0x7FFFFFFFu);
      if (is_json) parse_json_pipl (f, &r, path); else parse_binary_pipl (f, &r, path);
    }
  }
}

/* --------------------------------------------------------------- main entry */

void pe8_analyze_file (const char *path, Pe8File *f) {
  memset (f, 0, sizeof *f);
  f->file_verdict = PE8_VERDICT_NO;
  size_t n; unsigned char *d = read_file (path, &n);
  if (!d) { f->file_reason = PE8_R_UNREADABLE; return; }
  Buf b = { d, n };
  unsigned v, pe, magic, nsec, osz, machine, rsrc_rva = 0, rsrc_sz = 0, exp_rva = 0, exp_sz = 0, imp_rva = 0, imp_sz = 0;
  Sections S; memset (&S, 0, sizeof S);

  if (!rd16 (b, 0, &v) || v != 0x5A4D || !rd32 (b, 0x3C, &pe) || !rd32 (b, pe, &v) || v != 0x00004550) goto bad;
  if (!rd16 (b, pe + 4, &machine) || !rd16 (b, pe + 6, &nsec) || !rd16 (b, pe + 20, &osz) || !rd16 (b, pe + 24, &magic)) goto bad;
  f->machine = machine;
  size_t ddo = pe + 24 + (magic == 0x20B ? 112 : magic == 0x10B ? 96 : 0);
  if (ddo == pe + 24 || nsec > 96) goto bad;
  rd32 (b, ddo + 0, &exp_rva); rd32 (b, ddo + 4, &exp_sz);
  rd32 (b, ddo + 8, &imp_rva); rd32 (b, ddo + 12, &imp_sz);
  rd32 (b, ddo + 16, &rsrc_rva); rd32 (b, ddo + 20, &rsrc_sz);
  for (unsigned i = 0; i < nsec; i++) {
    size_t so = pe + 24 + osz + i * 40; unsigned vs, va, rs, ro;
    if (!rd32 (b, so + 8, &vs) || !rd32 (b, so + 12, &va) || !rd32 (b, so + 16, &rs) || !rd32 (b, so + 20, &ro)) goto bad;
    S.s[S.n++] = (Section) { va, vs, ro, rs };
  }
  (void) exp_sz; (void) imp_sz; (void) rsrc_sz;

  /* imports */
  if (imp_rva) {
    long io = rva_to_off (&S, b, imp_rva);
    for (int i = 0; io >= 0 && i < 512; i++) {
      unsigned nrva; if (!rd32 (b, io + i * 20 + 12, &nrva) || nrva == 0) break;
      char nm[260]; if (read_cstr (b, rva_to_off (&S, b, nrva), nm, sizeof nm)) add_str (&f->imports, &f->n_imports, nm);
    }
  }
  /* exports */
  char **exports = NULL; size_t n_exports = 0;
  if (exp_rva) {
    long eo = rva_to_off (&S, b, exp_rva); unsigned nnames, nptr;
    if (eo >= 0 && rd32 (b, eo + 24, &nnames) && rd32 (b, eo + 32, &nptr) && nnames < 100000) {
      long no = rva_to_off (&S, b, nptr);
      for (unsigned i = 0; no >= 0 && i < nnames; i++) {
        unsigned r; char nm[260];
        if (!rd32 (b, no + 4 * i, &r)) break;
        if (read_cstr (b, rva_to_off (&S, b, r), nm, sizeof nm)) add_str (&exports, &n_exports, nm);
      }
    }
  }
  if (rsrc_rva) walk_resources (f, b, &S, rsrc_rva, path);

  /* a filter may be described by both a binary and a JSON PiPL: keep the binary one only */
  for (size_t i = 0; i < f->count; i++) {
    Pe8Plugin *a = &f->items[i];
    if (!a->from_json) continue;
    for (size_t j = 0; j < f->count; j++) {
      Pe8Plugin *c = &f->items[j];
      if (c->from_json || !a->name || !c->name || strcmp (a->name, c->name) != 0) continue;
      if (strcmp (a->category ? a->category : "", c->category ? c->category : "") != 0) continue;
      free (a->path); free (a->name); free (a->category); free (a->entry);
      memmove (a, a + 1, (f->count - i - 1) * sizeof *a);
      f->count--; i--; break;
    }
  }

  /* verdicts */
  for (size_t i = 0; i < f->count; i++) {
    Pe8Plugin *p = &f->items[i];
    p->verdict = PE8_VERDICT_OK; p->reason = PE8_R_NONE;
    if (machine == 0x14C) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_32BIT; continue; }
    if (machine != 0x8664) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_WRONG_ARCH; continue; }
    if (strcmp (p->kind, "8BFM") != 0) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_NOT_FILTER; continue; }
    if (p->category && strcmp (p->category, "**Hidden**") == 0) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_HIDDEN; continue; }
    if (!p->entry) { p->entry = xstrdup ("PluginMain"); }
    int found = 0;
    for (size_t k = 0; k < n_exports; k++) if (strcmp (exports[k], p->entry) == 0) { found = 1; break; }
    if (!found) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_NO_ENTRY; continue; }
    if (p->modes_known && !(p->modes & 0x1000)) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_NO_RGB; continue; }
  }
  if (f->count == 0) {
    f->file_reason = machine == 0x14C ? PE8_R_32BIT : machine != 0x8664 ? PE8_R_WRONG_ARCH : PE8_R_NO_PIPL;
  }
  for (size_t k = 0; k < n_exports; k++) free (exports[k]);
  free (exports); free (d);
  return;
bad:
  free (d); f->file_reason = PE8_R_NOT_PE;
}

void pe8_check_dependencies (Pe8File *f, const char *path_utf8) {
#ifdef _WIN32
  wchar_t wpath[4096], dir[4096];
  if (!MultiByteToWideChar (CP_UTF8, 0, path_utf8, -1, wpath, 4096)) return;
  wcscpy (dir, wpath);
  wchar_t *sl = wcsrchr (dir, L'\\'); if (!sl) sl = wcsrchr (dir, L'/');
  if (sl) *sl = 0;
  for (size_t i = 0; i < f->n_imports; i++) {
    const char *nm = f->imports[i];
    if (_strnicmp (nm, "api-ms-win-", 11) == 0 || _strnicmp (nm, "ext-ms-", 7) == 0) continue;
    wchar_t wn[260]; MultiByteToWideChar (CP_UTF8, 0, nm, -1, wn, 260);
    wchar_t out[MAX_PATH];
    if (SearchPathW (dir, wn, NULL, MAX_PATH, out, NULL) || SearchPathW (NULL, wn, NULL, MAX_PATH, out, NULL)) continue;
    for (size_t k = 0; k < f->count; k++) {
      Pe8Plugin *p = &f->items[k];
      if (p->verdict != PE8_VERDICT_NO) { p->verdict = PE8_VERDICT_NO; p->reason = PE8_R_MISSING_DEP; free (p->reason_detail); p->reason_detail = xstrdup (nm); }
    }
    return;
  }
#else
  (void) f; (void) path_utf8;
#endif
}

void pe8_free (Pe8File *f) {
  for (size_t i = 0; i < f->count; i++) {
    free (f->items[i].path); free (f->items[i].name); free (f->items[i].category);
    free (f->items[i].entry); free (f->items[i].reason_detail);
  }
  free (f->items);
  for (size_t i = 0; i < f->n_imports; i++) free (f->imports[i]);
  free (f->imports);
  memset (f, 0, sizeof *f);
}

const char *pe8_reason_key (Pe8Reason r) {
  switch (r) {
    case PE8_R_NONE: return "none"; case PE8_R_UNREADABLE: return "unreadable"; case PE8_R_NOT_PE: return "not-pe";
    case PE8_R_32BIT: return "32bit"; case PE8_R_WRONG_ARCH: return "wrong-arch"; case PE8_R_NO_PIPL: return "no-pipl";
    case PE8_R_NOT_FILTER: return "not-filter"; case PE8_R_HIDDEN: return "hidden"; case PE8_R_NO_ENTRY: return "no-entry";
    case PE8_R_NO_RGB: return "no-rgb"; case PE8_R_MISSING_DEP: return "missing-dep";
    case PE8_R_LOAD_FAILED: return "load-failed"; case PE8_R_PROBE_CRASH: return "probe-crash"; case PE8_R_PROBE_TIMEOUT: return "probe-timeout";
    case PE8_R_PROBE_ERROR: return "probe-error"; case PE8_R_UNSUPPORTED_CB: return "unsupported-callbacks";
  }
  return "?";
}
const char *pe8_verdict_key (Pe8Verdict v) { return v == PE8_VERDICT_OK ? "OK" : v == PE8_VERDICT_WARN ? "WARN" : "NO"; }
