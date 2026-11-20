/* pshost_runner - hosts ONE Photoshop filter (.8bf, 64-bit) in a separate process.
 *
 * Usage (all paths UTF-16 command line):
 *   pshost_runner --mode about|probe|run --plugin FILE --entry NAME [options]
 *   pshost_runner --mode restart --pid N --exe FILE [--args STRING] [--wait-ms N] [--log FILE]
 *       waits until process N (GIMP) has exited, then starts FILE (exit 124 if it did not exit in time)
 *   run options:  --width W --height H --in RGBA.raw --out RGBA.raw [--mask A8.raw]
 *                 [--params-in F] [--params-out F] [--ui 0|1] [--hwnd N]
 *                 [--fg r,g,b] [--bg r,g,b] [--timeout-ms N] [--log FILE]
 * Image exchange format: raw 8-bit RGBA, width*height*4 bytes, rows top to bottom, straight alpha.
 * Alpha is not given to the filter (flat-image filter cases); it is copied unchanged to the output.
 * Exit codes: 0 ok | 2 plug-in error | 3 cannot load DLL | 4 entry missing | 5 bad arguments
 *             6 I/O error | 7 plug-in cancelled | 124 timeout | 0xC0DE0001 crash in plug-in. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <stdarg.h>
#include "../common/ps_types.h"

/* ------------------------------------------------------------------ options */
typedef struct {
  const wchar_t *mode, *plugin, *in, *out, *mask, *params_in, *params_out, *log;
  char entry[256];
  int width, height, ui, timeout_ms;
  uintptr_t hwnd;
  uintptr_t pid; const wchar_t *exe, *args; int wait_ms;
  uint8_t fg[3], bg[3];
} Opts;
static Opts O;

static FILE *logf_ = NULL;
static void logmsg (const char *fmt, ...) {
  char b[1024]; va_list ap; va_start (ap, fmt); vsnprintf (b, sizeof b, fmt, ap); va_end (ap);
  fprintf (stdout, "%s\n", b); fflush (stdout);
  if (logf_) { fprintf (logf_, "%s\n", b); fflush (logf_); }
}

/* unsupported-callback bookkeeping (reported by probe) */
static char unsup[48][64]; static int n_unsup = 0;
static void unsupported (const char *what) {
  for (int i = 0; i < n_unsup; i++) if (!strcmp (unsup[i], what)) return;
  if (n_unsup < 48) { snprintf (unsup[n_unsup], sizeof unsup[0], "%.63s", what); n_unsup++; }
  logmsg ("UNSUPPORTED %s", what);
}

/* ------------------------------------------------------------------ handles */
struct PSHandleRec { size_t size; void *data; };
static PSHandle h_new (int32_t size) {
  struct PSHandleRec *h = calloc (1, sizeof *h); if (!h) return NULL;
  h->data = calloc (1, size > 0 ? (size_t) size : 1); if (!h->data) { free (h); return NULL; }
  h->size = (size_t) size; return h;
}
static void h_dispose (PSHandle h) { if (h) { free (h->data); free (h); } }
static int32_t h_size (PSHandle h) { return h ? (int32_t) h->size : 0; }
static int16_t h_setsize (PSHandle h, int32_t n) {
  if (!h) return PS_ERR_MEMORY_FULL;
  void *p = realloc (h->data, n > 0 ? (size_t) n : 1); if (!p) return PS_ERR_MEMORY_FULL;
  if ((size_t) n > h->size) memset ((char *) p + h->size, 0, (size_t) n - h->size);
  h->data = p; h->size = (size_t) n; return 0;
}
static void *h_lock (PSHandle h, PSBoolean mh) { (void) mh; return h ? h->data : NULL; }
static void h_unlock (PSHandle h) { (void) h; }
static void h_recover (int32_t s) { (void) s; }

static int16_t b_alloc (int32_t size, void **id) { void *p = calloc (1, size > 0 ? (size_t) size : 1); *id = p; return p ? 0 : PS_ERR_MEMORY_FULL; }
static void *b_lock (void *id, PSBoolean mh) { (void) mh; return id; }
static void b_unlock (void *id) { (void) id; }
static void b_free (void *id) { free (id); }
static int32_t b_space (void) { return 512 * 1024 * 1024; }

static int16_t r_count (uint32_t t) { (void) t; return 0; }
static PSHandle r_get (uint32_t t, int16_t i) { (void) t; (void) i; return NULL; }
static void r_delete (uint32_t t, int16_t i) { (void) t; (void) i; }
static int16_t r_add (uint32_t t, PSHandle d) { (void) t; (void) d; return 0; }

static int16_t p_get (uint32_t sig, uint32_t key, int32_t idx, intptr_t *simple, PSHandle *cplx) {
  (void) sig; (void) idx; (void) cplx;
  switch (key) {
    case 0x6E756368: *simple = 3; return 0;          /* 'nuch' number of channels */
    case 0x6D6F6465: *simple = ps_modeRGB; return 0; /* 'mode' image mode */
    case 0x77636873: *simple = 0; return 0;          /* 'wchs' watch suspension */
  }
  char k[40]; snprintf (k, sizeof k, "property:%c%c%c%c", key >> 24, key >> 16, key >> 8, key); unsupported (k);
  return PS_ERR_PROPERTY_UNDEFINED;
}
static int16_t p_set (uint32_t sig, uint32_t key, int32_t idx, intptr_t s, PSHandle c) { (void) sig; (void) key; (void) idx; (void) s; (void) c; return 0; }

static int16_t is_interp (PSImagePlane *a, PSImagePlane *b, Rect16 *r, Fixed16 *c, int16_t m) { (void) a; (void) b; (void) r; (void) c; (void) m; unsupported ("imageServices.interpolate"); return PS_ERR_HOST_INSUFFICIENT; }
static PSBoolean abort_proc (void) { return 0; }
static void progress_proc (int32_t done, int32_t total) { (void) done; (void) total; }
static void process_event (void *e) { (void) e; }
/* Draws a PSPixelMap (8-bit RGB or gray, planar/interleaved) into a device context: used for previews in plug-in windows. */
static int16_t display_pixels (const PSPixelMap *src, const PSVRect *sr, int32_t dstRow, int32_t dstCol, void *ctx) {
  if (!src || !sr || !ctx || !src->baseAddr) return PS_ERR_HOST_INSUFFICIENT;
  int w = sr->right - sr->left, h = sr->bottom - sr->top;
  if (w <= 0 || h <= 0 || w > 16384 || h > 16384) return 0;
  if (sr->left < src->bounds.left || sr->right > src->bounds.right || sr->top < src->bounds.top || sr->bottom > src->bounds.bottom) return PS_ERR_HOST_INSUFFICIENT;
  if (src->imageMode != ps_modeRGB && src->imageMode != 1) { unsupported ("displayPixels:mode"); return PS_ERR_HOST_INSUFFICIENT; }
  uint8_t *bgra = malloc ((size_t) w * h * 4); if (!bgra) return PS_ERR_MEMORY_FULL;
  for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
    const uint8_t *px = (const uint8_t *) src->baseAddr + (size_t) (sr->top - src->bounds.top + y) * src->rowBytes + (size_t) (sr->left - src->bounds.left + x) * src->colBytes;
    uint8_t *d = bgra + ((size_t) y * w + x) * 4;
    if (src->imageMode == 1) d[0] = d[1] = d[2] = px[0];
    else { d[2] = px[0]; d[1] = px[src->planeBytes]; d[0] = px[2 * (size_t) src->planeBytes]; }
    d[3] = 255;
  }
  BITMAPINFO bi; memset (&bi, 0, sizeof bi);
  bi.bmiHeader.biSize = sizeof bi.bmiHeader; bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h; bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
  SetDIBitsToDevice ((HDC) ctx, dstCol, dstRow, (DWORD) w, (DWORD) h, 0, 0, 0, (UINT) h, bgra, &bi, DIB_RGB_COLORS);
  free (bgra);
  return 0;
}
static void host_procs (int16_t s, void *d) { (void) s; (void) d; unsupported ("hostProcs"); }
static int16_t color_services (void *info) { (void) info; unsupported ("colorServices"); return PS_ERR_HOST_INSUFFICIENT; }


/* ------------------------------------------------------------------------------ PICA (SPBasic) suites
 * Many filters (e.g. the Nik Collection) acquire "suites" through filterRecord->sSPBasic and dereference it
 * unconditionally. Layouts follow the public PSFilterPdn host (MIT); only the suites below are provided,
 * everything else returns kSPSuiteNotFoundError and is reported as UNSUPPORTED. */
static PSPropertyProcs PP;   /* tentative definition: initialised further down */
#define SP_NO_ERROR 0
#define SP_BAD_PARAMETER 0x5061726d
#define SP_SUITE_NOT_FOUND 0x53214664
#define SP_UNIMPLEMENTED 0x21494d50

typedef struct { PSHandle (*New) (int32_t); void (*Dispose) (PSHandle); void (*SetLock) (PSHandle, PSBoolean, void **, PSBoolean *);
                 int32_t (*GetSize) (PSHandle); int16_t (*SetSize) (PSHandle, int32_t); void (*RecoverSpace) (int32_t); } PicaHandleSuite1;
typedef struct { PSHandle (*New) (int32_t); void (*Dispose) (PSHandle); void (*DisposeRegular) (PSHandle); void (*SetLock) (PSHandle, PSBoolean, void **, PSBoolean *);
                 int32_t (*GetSize) (PSHandle); int16_t (*SetSize) (PSHandle, int32_t); void (*RecoverSpace) (int32_t); } PicaHandleSuite2;
typedef struct { void (*processEvent) (void *); PSDisplayPixelsProc displayPixels; void (*progressBar) (int32_t, int32_t);
                 PSBoolean (*testAbort) (void); void *(*MainAppWindow) (void); int32_t (*SetCursor) (void *); uint32_t (*TickCount) (void);
                 int32_t (*GetPluginName) (void *plugInRef, void **name); } PicaUIHooksSuite1;

static void hs_setlock (PSHandle h, PSBoolean lock, void **addr, PSBoolean *old) { if (old) *old = !lock; if (addr) *addr = lock && h ? h->data : NULL; }
static PicaHandleSuite1 HS1 = { h_new, h_dispose, hs_setlock, h_size, h_setsize, h_recover };
static PicaHandleSuite2 HS2 = { h_new, h_dispose, h_dispose, hs_setlock, h_size, h_setsize, h_recover };

/* ASZString: handles are 1-based indices into this table */
typedef struct { char *s; int ref; } ZStr;
static ZStr Z[512]; static int n_z = 0;
static void *z_new (const char *s, size_t n) { if (n_z >= 511) return NULL; ZStr *z = &Z[++n_z]; z->s = malloc (n + 1); memcpy (z->s, s, n); z->s[n] = 0; z->ref = 1; return (void *) (uintptr_t) n_z; }
static ZStr *z_get (void *h) { uintptr_t i = (uintptr_t) h; return i >= 1 && i <= (uintptr_t) n_z ? &Z[i] : NULL; }
static int32_t z_from_unicode (const void *src, size_t bytes, void **out) {
  char *u = malloc (bytes + 1); int n = WideCharToMultiByte (CP_UTF8, 0, (const wchar_t *) src, (int) (bytes / 2), u, (int) bytes * 2, NULL, NULL); if (n < 0) n = 0;
  *out = z_new (u, (size_t) n); free (u); return *out ? 0 : SP_BAD_PARAMETER; }
static int32_t z_from_c (const void *src, size_t n, void **out) { *out = z_new ((const char *) src, strnlen ((const char *) src, n)); return *out ? 0 : SP_BAD_PARAMETER; }
static int32_t z_from_pascal (const void *src, size_t n, void **out) { (void) n; const uint8_t *p = src; *out = z_new ((const char *) p + 1, p[0]); return *out ? 0 : SP_BAD_PARAMETER; }
static int32_t z_unimpl_i (int32_t a, void **o) { (void) a; (void) o; unsupported ("ASZString.MakeRomanization"); return SP_UNIMPLEMENTED; }
static int32_t z_unimpl_f (int32_t a, int32_t b, int32_t c, void **o) { (void) a; (void) b; (void) c; (void) o; unsupported ("ASZString.MakeRomanization"); return SP_UNIMPLEMENTED; }
static int32_t z_unimpl_d (double a, void **o) { (void) a; (void) o; unsupported ("ASZString.MakeRomanization"); return SP_UNIMPLEMENTED; }
static void *z_empty (void) { static void *e = NULL; if (!e) e = z_new ("", 0); return e; }
static int32_t z_copy (void *src, void **out) { ZStr *z = z_get (src); if (!z) return SP_BAD_PARAMETER; *out = z_new (z->s, strlen (z->s)); return 0; }
static int32_t z_replace (void *z, uint32_t i, void *r) { (void) z; (void) i; (void) r; unsupported ("ASZString.Replace"); return SP_UNIMPLEMENTED; }
static int32_t z_noop (void *z) { (void) z; return 0; }
static int32_t z_addref (void *h) { ZStr *z = z_get (h); if (z) z->ref++; return 0; }
static int32_t z_release (void *h) { ZStr *z = z_get (h); if (z && z->ref > 0) z->ref--; return 0; }
static uint8_t z_allws (void *h) { ZStr *z = z_get (h); if (!z) return 1; for (const char *c = z->s; *c; c++) if (*c != ' ' && *c != '\t' && *c != '\r' && *c != '\n') return 0; return 1; }
static uint8_t z_isempty (void *h) { ZStr *z = z_get (h); return !z || !z->s[0]; }
static uint8_t z_willreplace (void *h, uint32_t i) { (void) h; (void) i; return 0; }
static uint32_t z_len_unicode (void *h) { ZStr *z = z_get (h); return z ? (uint32_t) MultiByteToWideChar (CP_UTF8, 0, z->s, -1, NULL, 0) : 1; }
static int32_t z_as_unicode (void *h, void *dst, uint32_t size, uint8_t check) { ZStr *z = z_get (h); if (!z || !dst) return SP_BAD_PARAMETER;
  if (check && size < z_len_unicode (h)) return SP_BAD_PARAMETER;
  MultiByteToWideChar (CP_UTF8, 0, z->s, -1, (wchar_t *) dst, (int) size);
  return 0; }
static uint32_t z_len_c (void *h) { ZStr *z = z_get (h); return z ? (uint32_t) strlen (z->s) + 1 : 1; }
static int32_t z_as_c (void *h, void *dst, uint32_t size, uint8_t check) { ZStr *z = z_get (h); if (!z || !dst) return SP_BAD_PARAMETER;
  size_t n = strlen (z->s) + 1; if (check && size < n) return SP_BAD_PARAMETER; if (n > size) n = size; memcpy (dst, z->s, n); if (n) ((char *) dst)[n - 1] = 0; return 0; }
static uint32_t z_len_p (void *h) { ZStr *z = z_get (h); size_t n = z ? strlen (z->s) : 0; return (uint32_t) (n > 255 ? 255 : n) + 1; }
static int32_t z_as_p (void *h, void *dst, uint32_t size, uint8_t check) { ZStr *z = z_get (h); if (!z || !dst || size < 1) return SP_BAD_PARAMETER;
  size_t n = strlen (z->s); if (n > 255) n = 255; if (check && size < n + 1) return SP_BAD_PARAMETER; if (n > size - 1) n = size - 1; ((uint8_t *) dst)[0] = (uint8_t) n; memcpy ((char *) dst + 1, z->s, n); return 0; }

typedef struct { int32_t (*MakeFromUnicode) (const void *, size_t, void **); int32_t (*MakeFromCString) (const void *, size_t, void **);
  int32_t (*MakeFromPascalString) (const void *, size_t, void **); int32_t (*MakeRomanizationOfInteger) (int32_t, void **);
  int32_t (*MakeRomanizationOfFixed) (int32_t, int32_t, int32_t, void **); int32_t (*MakeRomanizationOfDouble) (double, void **);
  void *(*GetEmpty) (void); int32_t (*Copy) (void *, void **); int32_t (*Replace) (void *, uint32_t, void *); int32_t (*TrimEllipsis) (void *);
  int32_t (*TrimSpaces) (void *); int32_t (*RemoveAccelerators) (void *); int32_t (*AddRef) (void *); int32_t (*Release) (void *);
  uint8_t (*IsAllWhiteSpace) (void *); uint8_t (*IsEmpty) (void *); uint8_t (*WillReplace) (void *, uint32_t);
  uint32_t (*LengthAsUnicodeCString) (void *); int32_t (*AsUnicodeCString) (void *, void *, uint32_t, uint8_t);
  uint32_t (*LengthAsCString) (void *); int32_t (*AsCString) (void *, void *, uint32_t, uint8_t);
  uint32_t (*LengthAsPascalString) (void *); int32_t (*AsPascalString) (void *, void *, uint32_t, uint8_t); } PicaZStringSuite1;
static PicaZStringSuite1 ZS1 = { z_from_unicode, z_from_c, z_from_pascal, z_unimpl_i, z_unimpl_f, z_unimpl_d, z_empty, z_copy, z_replace, z_noop, z_noop, z_noop,
                                 z_addref, z_release, z_allws, z_isempty, z_willreplace, z_len_unicode, z_as_unicode, z_len_c, z_as_c, z_len_p, z_as_p };

static void *ui_main_window (void) { return (void *) O.hwnd; }
static int32_t ui_set_cursor (void *c) { (void) c; return SP_UNIMPLEMENTED; }
static uint32_t ui_tick (void) { return (uint32_t) (GetTickCount () * 60ULL / 1000ULL); }
static int32_t ui_plugin_name (void *ref, void **name) { (void) ref; if (!name) return SP_BAD_PARAMETER; *name = z_new ("PSHost", 6); return 0; }
static PicaUIHooksSuite1 UIH1 = { process_event, display_pixels, progress_proc, abort_proc, ui_main_window, ui_set_cursor, ui_tick, ui_plugin_name };

static int32_t sp_acquire (const char *name, int32_t version, const void **suite) {
  char what[160]; if (!name || !suite) return SP_BAD_PARAMETER;
  *suite = NULL;
  if (!strcmp (name, "Photoshop Handle Suite for Plug-ins") && version == 1) *suite = &HS1;
  else if (!strcmp (name, "Photoshop Handle Suite for Plug-ins") && version == 2) *suite = &HS2;
  else if (!strcmp (name, "Photoshop Property Suite for Plug-ins") && version == 1) *suite = &PP;
  else if (!strcmp (name, "Photoshop UIHooks Suite for Plug-ins") && version == 1) *suite = &UIH1;
  else if (!strcmp (name, "AS ZString Suite") && version == 1) *suite = &ZS1;
  if (*suite) { logmsg ("PICA acquire '%s' v%d", name, version); return SP_NO_ERROR; }
  snprintf (what, sizeof what, "pica:%s v%d", name, version); unsupported (what);
  return SP_SUITE_NOT_FOUND;
}
static int32_t sp_release (const char *name, int32_t version) { (void) name; (void) version; return SP_NO_ERROR; }
static uint8_t sp_isequal (const char *a, const char *b) { return a && b && !strcmp (a, b); }
static int32_t sp_alloc (int32_t size, void **block) { if (!block) return SP_BAD_PARAMETER; *block = calloc (1, size > 0 ? (size_t) size : 1); return *block ? 0 : PS_ERR_MEMORY_FULL; }
static int32_t sp_free (void *block) { free (block); return 0; }
static int32_t sp_realloc (void *block, int32_t size, void **nb) { if (!nb) return SP_BAD_PARAMETER; *nb = realloc (block, size > 0 ? (size_t) size : 1); return *nb ? 0 : PS_ERR_MEMORY_FULL; }
static int32_t sp_undefined (void) { return SP_UNIMPLEMENTED; }
typedef struct { int32_t (*AcquireSuite) (const char *, int32_t, const void **); int32_t (*ReleaseSuite) (const char *, int32_t); uint8_t (*IsEqual) (const char *, const char *);
                 int32_t (*AllocateBlock) (int32_t, void **); int32_t (*FreeBlock) (void *); int32_t (*ReallocateBlock) (void *, int32_t, void **); int32_t (*Undefined) (void); } SPBasicSuite;
static SPBasicSuite SPB = { sp_acquire, sp_release, sp_isequal, sp_alloc, sp_free, sp_realloc, sp_undefined };

/* ------------------------------------------------------------------- image */
static int W, H;
static uint8_t *rgb_in, *rgb_out, *alpha, *selmask;   /* planar-interleaved RGB 8-bit */
static FilterRecord FR;
static PSBufferProcs BP = { 1, 5, b_alloc, b_lock, b_unlock, b_free, b_space };
static PSHandleProcs HP = { 1, 8, h_new, h_dispose, h_size, h_setsize, h_lock, h_unlock, h_recover, h_dispose };
static PSResourceProcs RP = { 1, 4, r_count, r_get, r_delete, r_add };
static PSPropertyProcs PP = { 1, 2, p_get, p_set };
static PSImageServicesProcs IP = { 1, 2, is_interp, is_interp };
static PlatformData PD;
static PStr255 ERRSTR;

static uint8_t *inbuf, *outbuf, *maskbuf;
static Rect16 pend_out; static int16_t pend_lo, pend_hi, pend_nplanes;

static int nonempty (Rect16 r) { return r.bottom > r.top && r.right > r.left; }
static int clampi (int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
/* source pixel for a (possibly sub-sampled) coordinate: rate is 16.16 fixed, <= 1.0 means no sub-sampling */
static int src_coord (int c, Fixed16 rate, int max) {
  if (rate < (1 << 16)) rate = 1 << 16;
  return clampi ((int) (((int64_t) c * rate) >> 16), 0, max);
}

static void flush_out (void) {
  if (!outbuf) return;
  int w = pend_out.right - pend_out.left;
  for (int y = pend_out.top; y < pend_out.bottom; y++) {
    if (y < 0 || y >= H) continue;
    for (int x = pend_out.left; x < pend_out.right; x++) {
      if (x < 0 || x >= W) continue;
      const uint8_t *s = outbuf + ((size_t) (y - pend_out.top) * w + (x - pend_out.left)) * pend_nplanes;
      for (int p = pend_lo; p <= pend_hi && p < 3; p++) rgb_out[((size_t) y * W + x) * 3 + p] = s[p - pend_lo];
    }
  }
  free (outbuf); outbuf = NULL;
}

static int16_t advance_state (void) {
  flush_out ();
  free (inbuf); inbuf = NULL; free (maskbuf); maskbuf = NULL;
  FilterRecord *f = &FR;
  if (nonempty (f->inRect)) {
    int np = f->inHiPlane - f->inLoPlane + 1, w = f->inRect.right - f->inRect.left, h = f->inRect.bottom - f->inRect.top;
    if (np < 1 || np > 4) np = 3;
    inbuf = malloc ((size_t) w * h * np);
    if (!inbuf) return PS_ERR_MEMORY_FULL;
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int sy = src_coord (f->inRect.top + y, f->inputRate, H - 1), sx = src_coord (f->inRect.left + x, f->inputRate, W - 1);
      for (int p = 0; p < np; p++) { int pl = f->inLoPlane + p; inbuf[((size_t) y * w + x) * np + p] = pl < 3 ? rgb_in[((size_t) sy * W + sx) * 3 + pl] : 255; }
    }
    f->inData = inbuf; f->inRowBytes = w * np; f->inColumnBytes = np; f->inPlaneBytes = 1;
  } else { f->inData = NULL; f->inRowBytes = 0; }
  if (nonempty (f->outRect)) {
    int np = f->outHiPlane - f->outLoPlane + 1, w = f->outRect.right - f->outRect.left, h = f->outRect.bottom - f->outRect.top;
    if (np < 1 || np > 4) np = 3;
    outbuf = malloc ((size_t) w * h * np);
    if (!outbuf) return PS_ERR_MEMORY_FULL;
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int sy = clampi (f->outRect.top + y, 0, H - 1), sx = clampi (f->outRect.left + x, 0, W - 1);
      for (int p = 0; p < np; p++) { int pl = f->outLoPlane + p; outbuf[((size_t) y * w + x) * np + p] = pl < 3 ? rgb_out[((size_t) sy * W + sx) * 3 + pl] : 255; }
    }
    pend_out = f->outRect; pend_lo = f->outLoPlane; pend_hi = f->outHiPlane; pend_nplanes = (int16_t) np;
    f->outData = outbuf; f->outRowBytes = w * np; f->outColumnBytes = np; f->outPlaneBytes = 1;
  } else { f->outData = NULL; f->outRowBytes = 0; }
  if (f->haveMask && nonempty (f->maskRect) && selmask) {
    int w = f->maskRect.right - f->maskRect.left, h = f->maskRect.bottom - f->maskRect.top;
    maskbuf = malloc ((size_t) w * h);
    if (!maskbuf) return PS_ERR_MEMORY_FULL;
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int sy = src_coord (f->maskRect.top + y, f->maskRate, H - 1), sx = src_coord (f->maskRect.left + x, f->maskRate, W - 1);
      maskbuf[(size_t) y * w + x] = selmask[(size_t) sy * W + sx];
    }
    f->maskData = maskbuf; f->maskRowBytes = w;
  }
  return 0;
}

/* ----------------------------------------------------------------- plumbing */
static LONG WINAPI crash_filter (EXCEPTION_POINTERS *ep) {
  logmsg ("CRASH exception=0x%08lX address=%p", ep->ExceptionRecord->ExceptionCode, ep->ExceptionRecord->ExceptionAddress);
  TerminateProcess (GetCurrentProcess (), 0xC0DE0001);   /* ExitProcess could block on the plug-in's threads */
  return EXCEPTION_EXECUTE_HANDLER;
}
static DWORD WINAPI watchdog (LPVOID p) {
  Sleep ((DWORD) (uintptr_t) p); logmsg ("TIMEOUT: plug-in did not finish in %d ms", O.timeout_ms); TerminateProcess (GetCurrentProcess (), 124); return 0;
}

static uint8_t *read_all (const wchar_t *path, size_t *n) {
  FILE *f = _wfopen (path, L"rb"); if (!f) return NULL;
  fseek (f, 0, SEEK_END); long l = ftell (f); fseek (f, 0, SEEK_SET);
  uint8_t *d = malloc (l > 0 ? (size_t) l : 1); if (d && l > 0 && fread (d, 1, (size_t) l, f) != (size_t) l) { free (d); d = NULL; }
  fclose (f); *n = (size_t) (l > 0 ? l : 0); return d;
}
static int write_all (const wchar_t *path, const void *d, size_t n) {
  FILE *f = _wfopen (path, L"wb"); if (!f) return 0;
  size_t w = n ? fwrite (d, 1, n, f) : 0; fclose (f); return w == n;
}

static int parse_rgb (const wchar_t *s, uint8_t out[3]) { int r, g, b; if (swscanf (s, L"%d,%d,%d", &r, &g, &b) == 3) { out[0] = (uint8_t) r; out[1] = (uint8_t) g; out[2] = (uint8_t) b; return 1; } return 0; }

static void setup_record (void) {
  FilterRecord *f = &FR; memset (f, 0, sizeof *f);
  PD.hwnd = (void *) O.hwnd;
  f->abortProc = abort_proc; f->progressProc = progress_proc;
  f->imageSize.v = (int16_t) H; f->imageSize.h = (int16_t) W; f->wholeSize = f->imageSize;
  f->planes = 3; f->filterRect.right = (int16_t) W; f->filterRect.bottom = (int16_t) H;
  f->foreground.red = (uint16_t) (O.fg[0] * 257); f->foreground.green = (uint16_t) (O.fg[1] * 257); f->foreground.blue = (uint16_t) (O.fg[2] * 257);
  f->background.red = (uint16_t) (O.bg[0] * 257); f->background.green = (uint16_t) (O.bg[1] * 257); f->background.blue = (uint16_t) (O.bg[2] * 257);
  memcpy (f->foreColor, O.fg, 3); memcpy (f->backColor, O.bg, 3);
  f->maxSpace = 512 * 1024 * 1024; f->bufferSpace = b_space ();
  f->hostSig = PS_SIG_8BIM; f->hostProcs = host_procs; f->imageMode = ps_modeRGB;
  f->imageHRes = f->imageVRes = 72 << 16;
  f->platformData = &PD; f->bufferProcs = &BP; f->resourceProcs = &RP; f->handleProcs = &HP;
  f->processEvent = process_event; f->displayPixels = display_pixels;
  f->advanceState = advance_state; f->colorServices = color_services;
  f->filterCase = (O.mask && selmask) ? ps_FlatImageWithSelection : ps_FlatImageNoSelection;
  f->sSPBasic = &SPB; f->imageServicesProcs = &IP; f->propertyProcs = &PP; f->errorString = &ERRSTR;
  f->depth = 8; f->inputRate = f->maskRate = 1 << 16; f->samplingSupport = 1;
  f->inNonLayerPlanes = 3; f->outNonLayerPlanes = 3;
  if (selmask) { f->haveMask = 1; f->autoMask = 1; f->maskRect = f->filterRect; }
}

/* Restart helper: wait for GIMP to exit (it was asked to close cleanly by the plug-in), then start it again. */
static int do_restart (void) {
  if (!O.exe || !O.pid) { logmsg ("ERROR usage: --pid N --exe FILE"); return 5; }
  HANDLE h = OpenProcess (SYNCHRONIZE, FALSE, (DWORD) O.pid);
  if (h) {
    logmsg ("RESTART waiting for pid %lu", (unsigned long) O.pid);
    DWORD w = WaitForSingleObject (h, O.wait_ms > 0 ? (DWORD) O.wait_ms : 120000);
    CloseHandle (h);
    if (w != WAIT_OBJECT_0) { logmsg ("RESTART_TIMEOUT the process did not exit (closing was cancelled?) - not restarting"); return 124; }
  } else logmsg ("RESTART process %lu is already gone", (unsigned long) O.pid);
  Sleep (1500);   /* let the old instance release its files and locks */
  wchar_t cmd[4096];
  swprintf (cmd, 4096, L"\"%ls\"%ls%ls", O.exe, O.args && *O.args ? L" " : L"", O.args ? O.args : L"");
  STARTUPINFOW si; memset (&si, 0, sizeof si); si.cb = sizeof si;
  PROCESS_INFORMATION pi; memset (&pi, 0, sizeof pi);
  if (!CreateProcessW (NULL, cmd, NULL, NULL, FALSE, DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, NULL, NULL, &si, &pi)) { logmsg ("RESTART_FAILED win32=%lu", GetLastError ()); return 3; }
  CloseHandle (pi.hThread); CloseHandle (pi.hProcess);
  logmsg ("RESTART_LAUNCHED");
  return 0;
}

static const char *selname[] = { "About", "Parameters", "Prepare", "Start", "Continue", "Finish" };
static PSPluginMain entry_fn; static intptr_t plugin_data;

static int call (int16_t sel) {
  int16_t res = 0;
  logmsg ("CALL %s", selname[sel]);
  entry_fn (sel, &FR, &plugin_data, &res);
  logmsg ("RESULT %s = %d", selname[sel], res);
  if (res == PS_ERR_USER_CANCELED) return 7;
  if (res != 0) {
    if (ERRSTR.data[0]) logmsg ("PLUGIN_MESSAGE %.*s", ERRSTR.data[0], (char *) ERRSTR.data + 1);
    return 2;
  }
  return 0;
}

/* host_cycle: Start/Continue loop that hands tiles to the plug-in */
static int run_cycle (void) {
  int rc = call (ps_selStart); if (rc) return rc;
  for (int guard = 0; guard < 1000000; guard++) {
    if (!nonempty (FR.inRect) && !nonempty (FR.outRect)) break;
    int16_t a = advance_state (); if (a) return 2;
    rc = call (ps_selContinue); if (rc) return rc;
  }
  flush_out ();
  return 0;
}

static void blend_selection (void) {
  if (!selmask) return;
  for (size_t i = 0; i < (size_t) W * H; i++) {
    unsigned m = selmask[i];
    for (int p = 0; p < 3; p++) rgb_out[i * 3 + p] = (uint8_t) ((rgb_out[i * 3 + p] * m + rgb_in[i * 3 + p] * (255 - m) + 127) / 255);
  }
}

static int save_params (void) {
  if (!O.params_out || !FR.parameters) return 0;
  return write_all (O.params_out, FR.parameters->data, FR.parameters->size) ? 0 : 6;
}

static int run (void) {
  int rc;
  if (!wcscmp (O.mode, L"about")) { setup_record (); return call (ps_selAbout); }
  int probe = !wcscmp (O.mode, L"probe");
  size_t n;
  if (probe) {
    W = H = 64; rgb_in = malloc (W * H * 3); rgb_out = malloc (W * H * 3); alpha = malloc (W * H);
    for (int i = 0; i < W * H; i++) { rgb_in[i * 3] = (uint8_t) (i % W * 4); rgb_in[i * 3 + 1] = (uint8_t) (i / W * 4); rgb_in[i * 3 + 2] = 128; alpha[i] = 255; }
    memcpy (rgb_out, rgb_in, W * H * 3);
  } else {
    W = O.width; H = O.height;
    if (W <= 0 || H <= 0 || W > 32000 || H > 32000 || !O.in || !O.out) { logmsg ("ERROR bad image arguments (size must be 1..32000)"); return 5; }
    uint8_t *raw = read_all (O.in, &n);
    if (!raw || n != (size_t) W * H * 4) { logmsg ("ERROR cannot read input image (%zu bytes)", n); return 6; }
    rgb_in = malloc ((size_t) W * H * 3); rgb_out = malloc ((size_t) W * H * 3); alpha = malloc ((size_t) W * H);
    for (size_t i = 0; i < (size_t) W * H; i++) { memcpy (rgb_in + i * 3, raw + i * 4, 3); alpha[i] = raw[i * 4 + 3]; }
    memcpy (rgb_out, rgb_in, (size_t) W * H * 3); free (raw);
    if (O.mask) { selmask = read_all (O.mask, &n); if (!selmask || n != (size_t) W * H) { logmsg ("ERROR cannot read selection mask"); return 6; } }
  }
  setup_record ();
  if (O.params_in) {
    uint8_t *pd = read_all (O.params_in, &n);
    if (pd && n > 0) { FR.parameters = h_new ((int32_t) n); memcpy (FR.parameters->data, pd, n); }
    free (pd);
  }
  if (!probe && O.ui) { if ((rc = call (ps_selParameters))) return rc; rc = save_params (); if (rc) return rc; }
  if ((rc = call (ps_selPrepare))) return rc;
  if (probe) {
    logmsg ("PROBE_PREPARE_OK unsupported=%d", n_unsup);
    return 0;
  }
  if ((rc = run_cycle ())) return rc;
  if (FR.autoMask) blend_selection ();   /* plug-in may take over masking by clearing autoMask */
  rc = call (ps_selFinish); if (rc) return rc;
  rc = save_params (); if (rc) return rc;
  uint8_t *outraw = malloc ((size_t) W * H * 4);
  for (size_t i = 0; i < (size_t) W * H; i++) { memcpy (outraw + i * 4, rgb_out + i * 3, 3); outraw[i * 4 + 3] = alpha[i]; }
  int ok = write_all (O.out, outraw, (size_t) W * H * 4);
  free (outraw);
  if (!ok) { logmsg ("ERROR cannot write output image"); return 6; }
  logmsg ("RUN_OK unsupported=%d", n_unsup);
  return 0;
}

int wmain (int argc, wchar_t **argv) {
  O.timeout_ms = 60000; O.mode = L"run"; O.fg[0] = O.fg[1] = O.fg[2] = 0; O.bg[0] = O.bg[1] = O.bg[2] = 255;
  for (int i = 1; i + 1 < argc || i < argc; i++) {
    const wchar_t *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : L"";
    if (!wcscmp (a, L"--mode")) O.mode = v; else if (!wcscmp (a, L"--plugin")) O.plugin = v;
    else if (!wcscmp (a, L"--entry")) WideCharToMultiByte (CP_ACP, 0, v, -1, O.entry, sizeof O.entry, NULL, NULL);
    else if (!wcscmp (a, L"--width")) O.width = _wtoi (v); else if (!wcscmp (a, L"--height")) O.height = _wtoi (v);
    else if (!wcscmp (a, L"--in")) O.in = v; else if (!wcscmp (a, L"--out")) O.out = v; else if (!wcscmp (a, L"--mask")) O.mask = v;
    else if (!wcscmp (a, L"--params-in")) O.params_in = v; else if (!wcscmp (a, L"--params-out")) O.params_out = v;
    else if (!wcscmp (a, L"--ui")) O.ui = _wtoi (v); else if (!wcscmp (a, L"--hwnd")) O.hwnd = (uintptr_t) _wtoi64 (v);
    else if (!wcscmp (a, L"--timeout-ms")) O.timeout_ms = _wtoi (v); else if (!wcscmp (a, L"--log")) O.log = v;
    else if (!wcscmp (a, L"--pid")) O.pid = (uintptr_t) _wtoi64 (v); else if (!wcscmp (a, L"--exe")) O.exe = v; else if (!wcscmp (a, L"--args")) O.args = v;
    else if (!wcscmp (a, L"--wait-ms")) O.wait_ms = _wtoi (v);
    else if (!wcscmp (a, L"--fg")) parse_rgb (v, O.fg); else if (!wcscmp (a, L"--bg")) parse_rgb (v, O.bg);
    else continue;
    i++;
  }
  if (O.log) logf_ = _wfopen (O.log, L"ab");
  if (!wcscmp (O.mode, L"restart")) return do_restart ();
  if (!O.plugin || !O.entry[0]) { logmsg ("ERROR usage: --plugin FILE --entry NAME"); return 5; }
  SetUnhandledExceptionFilter (crash_filter);
  SetErrorMode (SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
  if (O.timeout_ms > 0 && wcscmp (O.mode, L"about") != 0) CreateThread (NULL, 0, watchdog, (LPVOID) (uintptr_t) O.timeout_ms, 0, NULL);

  /* let the plug-in find its own dependencies next to it */
  wchar_t dir[MAX_PATH * 2]; wcsncpy (dir, O.plugin, MAX_PATH * 2 - 1); dir[MAX_PATH * 2 - 1] = 0;
  wchar_t *sl = wcsrchr (dir, L'\\'); if (!sl) sl = wcsrchr (dir, L'/'); if (sl) *sl = 0;
  SetDefaultDllDirectories (LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_USER_DIRS);
  AddDllDirectory (dir);
  HMODULE m = LoadLibraryExW (O.plugin, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_USER_DIRS);
  if (!m) { logmsg ("LOAD_FAILED win32=%lu", GetLastError ()); return 3; }
  entry_fn = (PSPluginMain) (void *) GetProcAddress (m, O.entry);
  if (!entry_fn) { logmsg ("ENTRY_MISSING %s", O.entry); return 4; }
  logmsg ("LOADED %s", O.entry);
  int rc = run ();
  for (int i = 0; i < n_unsup; i++) logmsg ("SUMMARY_UNSUPPORTED %s", unsup[i]);
  return rc;
}
