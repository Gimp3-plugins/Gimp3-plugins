/* Synthetic test filter (.8bf). Variants selected at build time:
 *   (default) invert RGB in one go        -DTILED  invert in 16-row tiles driven by Continue
 *   -DCRASH   crash in Prepare            -DHANG   hang in Prepare
 *   -DMISSINGDEP  imports a DLL that does not exist at run time
 * Parameters handle holds an int counter that is incremented on every Start (tests parameter round trip). */
#include "../../src/common/ps_types.h"
#include <windows.h>
#ifdef MISSINGDEP
__declspec (dllimport) int absent_fn (void);
#endif

static void bump_params (FilterRecord *fr) {
  if (!fr->parameters) { fr->parameters = fr->handleProcs->newProc (4); *(int *) fr->handleProcs->lockProc (fr->parameters, 0) = 0; fr->handleProcs->unlockProc (fr->parameters); }
  int *p = (int *) fr->handleProcs->lockProc (fr->parameters, 0); (*p)++; fr->handleProcs->unlockProc (fr->parameters);
}

static void invert (FilterRecord *fr) {
  int w = fr->inRect.right - fr->inRect.left, h = fr->inRect.bottom - fr->inRect.top;
  int np = fr->inHiPlane - fr->inLoPlane + 1;
  for (int y = 0; y < h; y++) {
    const unsigned char *s = (const unsigned char *) fr->inData + (size_t) y * fr->inRowBytes;
    unsigned char *d = (unsigned char *) fr->outData + (size_t) y * fr->outRowBytes;
    for (int x = 0; x < w * np; x++) d[x] = (unsigned char) (255 - s[x]);
  }
}

__declspec (dllexport) void PluginMain (int16_t sel, FilterRecord *fr, intptr_t *data, int16_t *res) {
  (void) data; *res = 0;
#ifdef MISSINGDEP
  if (sel == 99) *res = (int16_t) absent_fn ();
#endif
  switch (sel) {
    case ps_selAbout: MessageBoxA ((HWND) fr->platformData->hwnd, "PSHost mini test filter", "About", MB_OK); break;
    case ps_selPrepare:
#ifdef CRASH
      *(volatile int *) 0 = 1;
#endif
#ifdef HANG
      for (;;) Sleep (100);
#endif
      break;
    case ps_selStart:
      bump_params (fr);
#ifdef TILED
      fr->inRect = fr->outRect = fr->filterRect;
      fr->inRect.bottom = fr->outRect.bottom = (int16_t) (fr->filterRect.top + (fr->filterRect.bottom - fr->filterRect.top < 16 ? fr->filterRect.bottom - fr->filterRect.top : 16));
      fr->inLoPlane = fr->outLoPlane = 0; fr->inHiPlane = fr->outHiPlane = 2;
      break;
    case ps_selContinue:
      invert (fr);
      if (fr->inRect.bottom >= fr->filterRect.bottom) { fr->inRect.top = fr->inRect.bottom = fr->outRect.top = fr->outRect.bottom = 0; fr->inRect.left = fr->inRect.right = fr->outRect.left = fr->outRect.right = 0; }
      else {
        fr->inRect.top = fr->outRect.top = fr->inRect.bottom;
        int nb = fr->inRect.top + 16; if (nb > fr->filterRect.bottom) nb = fr->filterRect.bottom;
        fr->inRect.bottom = fr->outRect.bottom = (int16_t) nb;
      }
      break;
#else
      fr->inRect = fr->outRect = fr->filterRect;
      fr->inLoPlane = fr->outLoPlane = 0; fr->inHiPlane = fr->outHiPlane = 2;
      *res = fr->advanceState ();
      if (!*res) invert (fr);
      fr->inRect.top = fr->inRect.bottom = fr->outRect.top = fr->outRect.bottom = 0;
      fr->inRect.left = fr->inRect.right = fr->outRect.left = fr->outRect.right = 0;
      *res = *res ? *res : fr->advanceState ();   /* commit output */
      break;
#endif
    default: break;
  }
}
