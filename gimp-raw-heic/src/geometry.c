/* gimp-raw-heic -- straighten and crop
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Applied to the developed, oriented image (after lens corrections):
 *
 *   1. rotate by s->straighten degrees (positive = counter-clockwise) about
 *      the centre, enlarged just enough that no empty corners appear
 *      (the "canvas" keeps the size of the image);
 *   2. cut out s->crop (x, y, w, h as fractions of that canvas).
 *
 * The neutral-point rectangle and the loupe position stay in the
 * coordinates of the image *before* this step; the mapping functions below
 * convert between the two.
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include "rawheic.h"

#define EPS 1e-6

gboolean
rawheic_geometry_active (const RawSettings *s)
{
  return fabs (s->straighten) > 0.005 ||
         s->crop[0] > EPS || s->crop[1] > EPS ||
         s->crop[2] < 1.0 - EPS || s->crop[3] < 1.0 - EPS;
}

/* Enlargement that keeps a w x h image rotated by @rad covering the
 * w x h canvas completely.
 */
static gdouble
cover_scale (gint    w,
             gint    h,
             gdouble rad)
{
  gdouble c = fabs (cos (rad)), s = fabs (sin (rad));
  gdouble r = MAX ((gdouble) w / h, (gdouble) h / w);

  return c + r * s;
}

void
rawheic_geometry_size (const RawSettings *s,
                       gint               w,
                       gint               h,
                       gint              *out_w,
                       gint              *out_h)
{
  *out_w = MAX (1, (gint) floor (s->crop[2] * w + 0.5));
  *out_h = MAX (1, (gint) floor (s->crop[3] * h + 0.5));
  *out_w = MIN (*out_w, w);
  *out_h = MIN (*out_h, h);
}

/* Output fraction (u, v) of the cropped result -> fraction of the image
 * before straightening.  With @uncropped the input is a fraction of the
 * rotated canvas instead (the crop tool shows the whole canvas).
 */
void
rawheic_geometry_to_source (const RawSettings *s,
                            gint               w,
                            gint               h,
                            gboolean           uncropped,
                            gdouble            u,
                            gdouble            v,
                            gdouble           *su,
                            gdouble           *sv)
{
  gdouble rad = s->straighten * G_PI / 180.0;
  gdouble k   = cover_scale (w, h, rad);
  gdouble cu  = uncropped ? u : s->crop[0] + u * s->crop[2];
  gdouble cv  = uncropped ? v : s->crop[1] + v * s->crop[3];
  gdouble dx  = (cu - 0.5) * w, dy = (cv - 0.5) * h;
  gdouble c   = cos (rad), sn = sin (rad);

  /* image y points down: a counter-clockwise turn on screen */
  *su = 0.5 + ( c * dx - sn * dy) / k / w;
  *sv = 0.5 + ( sn * dx + c * dy) / k / h;
}

/* The inverse: source fraction -> fraction of the result (or canvas). */
void
rawheic_geometry_from_source (const RawSettings *s,
                              gint               w,
                              gint               h,
                              gboolean           uncropped,
                              gdouble            su,
                              gdouble            sv,
                              gdouble           *u,
                              gdouble           *v)
{
  gdouble rad = s->straighten * G_PI / 180.0;
  gdouble k   = cover_scale (w, h, rad);
  gdouble dx  = (su - 0.5) * w * k, dy = (sv - 0.5) * h * k;
  gdouble c   = cos (rad), sn = sin (rad);
  gdouble cu  = 0.5 + ( c * dx + sn * dy) / w;
  gdouble cv  = 0.5 + (-sn * dx + c * dy) / h;

  if (uncropped)
    {
      *u = cu;
      *v = cv;
    }
  else
    {
      *u = s->crop[2] > EPS ? (cu - s->crop[0]) / s->crop[2] : 0.0;
      *v = s->crop[3] > EPS ? (cv - s->crop[1]) / s->crop[3] : 0.0;
    }
}

static inline gfloat
sample_f (const gfloat *src, gint w, gint h, gdouble x, gdouble y, gint c)
{
  gint    x0, y0, x1, y1;
  gdouble fx, fy;

  /* NaN passes CLAMP and (gint) NaN is undefined: never index with it */
  if (! isfinite (x) || ! isfinite (y))
    return 0.0f;
  x  = CLAMP (x, 0.0, (gdouble) (w - 1));
  y  = CLAMP (y, 0.0, (gdouble) (h - 1));
  x0 = (gint) x;  y0 = (gint) y;
  x1 = MIN (x0 + 1, w - 1);
  y1 = MIN (y0 + 1, h - 1);
  fx = x - x0;    fy = y - y0;

  return (gfloat) ((src[((gsize) y0 * w + x0) * 3 + c] * (1 - fx) +
                    src[((gsize) y0 * w + x1) * 3 + c] * fx) * (1 - fy) +
                   (src[((gsize) y1 * w + x0) * 3 + c] * (1 - fx) +
                    src[((gsize) y1 * w + x1) * 3 + c] * fx) * fy);
}

static inline gdouble
sample_u (const guint16 *src, gint w, gint h, gdouble x, gdouble y, gint c)
{
  gint    x0, y0, x1, y1;
  gdouble fx, fy;

  if (! isfinite (x) || ! isfinite (y))
    return 0.0;
  x  = CLAMP (x, 0.0, (gdouble) (w - 1));
  y  = CLAMP (y, 0.0, (gdouble) (h - 1));
  x0 = (gint) x;  y0 = (gint) y;
  x1 = MIN (x0 + 1, w - 1);
  y1 = MIN (y0 + 1, h - 1);
  fx = x - x0;    fy = y - y0;

  return (src[((gsize) y0 * w + x0) * 3 + c] * (1 - fx) +
          src[((gsize) y0 * w + x1) * 3 + c] * fx) * (1 - fy) +
         (src[((gsize) y1 * w + x0) * 3 + c] * (1 - fx) +
          src[((gsize) y1 * w + x1) * 3 + c] * fx) * fy;
}

/* Replace @img's pixels by the straightened and cropped result.  With
 * @uncropped only the rotation is applied (crop tool preview).
 */
gboolean
rawheic_geometry_apply (RawImage          *img,
                        const RawSettings *s,
                        gboolean           uncropped)
{
  gint     w = img->width, h = img->height, ow, oh, y;
  gdouble  rad = s->straighten * G_PI / 180.0;
  gdouble  k, c, sn, x0, y0;
  gpointer out;

  if (w < 2 || h < 2)
    return TRUE;
  /* settings normally arrive sanitized; refuse anything non-finite anyway */
  if (! isfinite (s->straighten) ||
      ! isfinite (s->crop[0]) || ! isfinite (s->crop[1]) ||
      ! isfinite (s->crop[2]) || ! isfinite (s->crop[3]))
    return TRUE;
  if (uncropped ? fabs (s->straighten) <= 0.005 : ! rawheic_geometry_active (s))
    return TRUE;

  if (uncropped)
    {
      ow = w;
      oh = h;
      x0 = y0 = 0.0;
    }
  else
    {
      rawheic_geometry_size (s, w, h, &ow, &oh);
      x0 = CLAMP (s->crop[0], 0.0, 1.0) * w;
      y0 = CLAMP (s->crop[1], 0.0, 1.0) * h;
      /* whole pixels: a plain crop must not resample */
      x0 = floor (MIN (x0, (gdouble) (w - ow)) + 0.5);
      y0 = floor (MIN (y0, (gdouble) (h - oh)) + 0.5);
      x0 = MIN (x0, (gdouble) (w - ow));
      y0 = MIN (y0, (gdouble) (h - oh));
    }

  k  = cover_scale (w, h, rad);
  c  = cos (rad);
  sn = sin (rad);

  out = img->pixels16 ? g_try_malloc ((gsize) ow * oh * 3 * sizeof (guint16))
                      : g_try_malloc ((gsize) ow * oh * 3 * sizeof (gfloat));
  if (! out)
    return FALSE;

#pragma omp parallel for
  for (y = 0; y < oh; y++)
    {
      gint x, ch;

      for (x = 0; x < ow; x++)
        {
          /* canvas pixel centre, relative to the image centre */
          gdouble dx = x0 + x + 0.5 - w * 0.5;
          gdouble dy = y0 + y + 0.5 - h * 0.5;
          gdouble sx = w * 0.5 + ( c * dx - sn * dy) / k - 0.5;
          gdouble sy = h * 0.5 + ( sn * dx + c * dy) / k - 0.5;
          gsize   o  = ((gsize) y * ow + x) * 3;

          if (img->pixels16)
            for (ch = 0; ch < 3; ch++)
              ((guint16 *) out)[o + ch] =
                (guint16) CLAMP (sample_u (img->pixels16, w, h, sx, sy, ch) + 0.5, 0.0, 65535.0);
          else
            for (ch = 0; ch < 3; ch++)
              ((gfloat *) out)[o + ch] = sample_f (img->pixels, w, h, sx, sy, ch);
        }
    }

  if (img->pixels16)
    {
      raw_image_release_pixels16 (img);
      img->pixels16 = out;
      img->own16    = TRUE;
    }
  else
    {
      g_free (img->pixels);
      img->pixels = out;
    }
  img->width  = ow;
  img->height = oh;

  return TRUE;
}
