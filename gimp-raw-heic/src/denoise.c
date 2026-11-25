/* gimp-raw-heic -- wavelet noise reduction
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * LibRaw's own wavelet denoise (params.threshold) crashes in the LibRaw
 * 0.22.2 build shipped by MSYS2 (also in its dcraw_emu), so it is never
 * used.  This is an independent à-trous wavelet soft-threshold denoiser
 * applied to the developed 16-bit linear RGB.  Values are square-root
 * transformed first (stabilises photon noise) so that the threshold has
 * roughly the same meaning as dcraw's "-n".
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include "rawheic.h"

/* relative noise of each level for a B3-like hat filter */
static const gfloat level_noise[5] = { 0.8002f, 0.2735f, 0.1202f, 0.0585f, 0.0291f };

/* 1-D hat transform with mirrored borders; requires size > 2 * sc */
static void
hat_transform (gfloat       *out,
               const gfloat *base,
               gsize         stride,
               gint          size,
               gint          sc)
{
  gint i;

  for (i = 0; i < sc; i++)
    out[i] = 2 * base[stride * i] + base[stride * (sc - i)] + base[stride * (i + sc)];
  for (; i + sc < size; i++)
    out[i] = 2 * base[stride * i] + base[stride * (i - sc)] + base[stride * (i + sc)];
  for (; i < size; i++)
    out[i] = 2 * base[stride * i] + base[stride * (i - sc)] +
             base[stride * (2 * size - 2 - (i + sc))];
}

/* Denoise one horizontal band: rows [a, b) of the image are loaded (from
 * @saved for rows that were already overwritten), filtered, and rows
 * [y0, y1) are written back.  @fimg holds 3 planes of width * (b - a).
 */
static void
denoise_band (guint16       *rgb,
              gint           width,
              gint           a,
              gint           b,
              gint           y0,
              gint           y1,
              const guint16 *saved,
              gint           saved_y,
              gint           saved_n,
              gfloat        *fimg,
              gdouble        threshold)
{
  gint  height = b - a;
  gsize size   = (gsize) width * height;
  gint  c;

  for (c = 0; c < 3; c++)
    {
      gsize  i, hpass = 0, lpass = 0;
      gint   lev, r;

#pragma omp parallel for
      for (r = 0; r < height; r++)
        {
          gint           y   = a + r;
          const guint16 *src = (saved && y >= saved_y && y < saved_y + saved_n) ?
                               saved + (gsize) (y - saved_y) * width * 3 :
                               rgb + (gsize) y * width * 3;
          gint           x;

          for (x = 0; x < width; x++)
            fimg[(gsize) r * width + x] = 256.0f * sqrtf ((gfloat) src[x * 3 + c]);
        }

      for (lev = 0; lev < 5; lev++)
        {
          gfloat thold = (gfloat) threshold * level_noise[lev];
          gint   sc    = 1 << lev;
          gint   row, col;

          lpass = size * ((lev & 1) + 1);

#pragma omp parallel
          {
            gfloat *temp = g_malloc (MAX (width, height) * sizeof (gfloat));

#pragma omp for
            for (row = 0; row < height; row++)
              {
                gint x;

                hat_transform (temp, fimg + hpass + (gsize) row * width, 1, width, sc);
                for (x = 0; x < width; x++)
                  fimg[lpass + (gsize) row * width + x] = temp[x] * 0.25f;
              }

#pragma omp for
            for (col = 0; col < width; col++)
              {
                gint y;

                hat_transform (temp, fimg + lpass + col, width, height, sc);
                for (y = 0; y < height; y++)
                  fimg[lpass + (gsize) y * width + col] = temp[y] * 0.25f;
              }

            g_free (temp);
          }

#pragma omp parallel for
          for (i = 0; i < size; i++)
            {
              gfloat d = fimg[hpass + i] - fimg[lpass + i];

              if      (d < -thold) d += thold;
              else if (d >  thold) d -= thold;
              else                 d  = 0.0f;

              fimg[hpass + i] = d;
              if (hpass)
                fimg[i] += d;
            }

          hpass = lpass;
        }

#pragma omp parallel for
      for (r = y0 - a; r < y1 - a; r++)
        {
          guint16 *dst = rgb + (gsize) (a + r) * width * 3;
          gint     x;

          for (x = 0; x < width; x++)
            {
              gsize  k = (gsize) r * width + x;
              gfloat v = fimg[k] + fimg[lpass + k];

              v = v * v / 65536.0f;
              dst[x * 3 + c] = (guint16) CLAMP (v + 0.5f, 0.0f, 65535.0f);
            }
        }
    }
}

/* The 5 levels reach 1+2+4+8+16 = 31 rows, so a 64-row margin makes the
 * banded result identical to filtering the whole image at once.
 */
#define BAND_MARGIN 64

gboolean
rawheic_wavelet_denoise_banded (guint16 *rgb,
                                gint     width,
                                gint     height,
                                gdouble  threshold,
                                gint     band)
{
  gint     max_rows, y0;
  gfloat  *fimg;
  guint16 *saved[2] = { NULL, NULL };
  gint     saved_y = 0, saved_n = 0, cur = 0;

  /* the coarsest level uses a step of 16 pixels */
  if (threshold <= 0 || width <= 2 * 16 + 1 || height <= 2 * 16 + 1)
    return TRUE;

  band     = MAX (band, BAND_MARGIN);
  max_rows = MIN (height, band + 3 * BAND_MARGIN);

  fimg = g_try_malloc ((gsize) width * max_rows * 3 * sizeof (gfloat));
  if (! fimg)
    return FALSE;

  saved[0] = g_try_malloc ((gsize) width * BAND_MARGIN * 3 * sizeof (guint16));
  saved[1] = g_try_malloc ((gsize) width * BAND_MARGIN * 3 * sizeof (guint16));
  if (! saved[0] || ! saved[1])
    {
      g_free (saved[0]);
      g_free (saved[1]);
      g_free (fimg);
      return FALSE;
    }

  for (y0 = 0; y0 < height; )
    {
      /* merge a short remainder into this band */
      gint y1 = (height - y0 <= band + BAND_MARGIN) ? height : y0 + band;
      gint a  = MAX (0, y0 - BAND_MARGIN);
      gint b  = MIN (height, y1 + BAND_MARGIN);
      gint nxt = 1 - cur;
      gint keep = MIN (BAND_MARGIN, y1 - y0);

      /* rows the next band reads above its start must stay original */
      if (y1 < height)
        memcpy (saved[nxt], rgb + (gsize) (y1 - keep) * width * 3,
                (gsize) keep * width * 3 * sizeof (guint16));

      denoise_band (rgb, width, a, b, y0, y1,
                    y0 > 0 ? saved[cur] : NULL, saved_y, saved_n,
                    fimg, threshold);

      saved_y = y1 - keep;
      saved_n = keep;
      cur     = nxt;
      y0      = y1;
    }

  g_free (saved[0]);
  g_free (saved[1]);
  g_free (fimg);

  return TRUE;
}

gboolean
rawheic_wavelet_denoise (guint16 *rgb,
                         gint     width,
                         gint     height,
                         gdouble  threshold)
{
  return rawheic_wavelet_denoise_banded (rgb, width, height, threshold, 1024);
}
