/* gimp-raw-heic -- base tone curve
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A scene-linear development looks flat next to a camera JPEG, which
 * always has an S-shaped tone curve.  This adds one, in a perceptual
 * (gamma 2.2) domain around middle grey:
 *
 *   S(t) = t + a * t (1 - t) (2t - 1)       0 <= t <= 1, monotonic for a < 1
 *
 * Values above 1.0 (recovered highlights in float) are left as they are.
 * The curve acts on the largest channel and all three channels are scaled
 * by the same factor, so hues and saturation do not shift.
 */

#include "config.h"

#include <math.h>

#include "rawheic.h"

static gdouble
strength (gint curve)
{
  switch (curve)
    {
    case TONE_MEDIUM: return 0.35;
    case TONE_STRONG: return 0.6;
    default:          return 0.0;
    }
}

/* linear in, linear out */
gdouble
rawheic_tone_eval (gint    curve,
                   gdouble x)
{
  gdouble a = strength (curve), t;

  if (a <= 0.0 || ! (x > 0.0) || x >= 1.0)
    return x;

  t = pow (x, 1.0 / 2.2);
  t = t + a * t * (1.0 - t) * (2.0 * t - 1.0);

  return pow (CLAMP (t, 0.0, 1.0), 2.2);
}

void
rawheic_tone_apply (RawImage *img,
                    gint      curve)
{
  gsize   n = (gsize) img->width * img->height, i;
  gfloat *ratio;
  gint    k;

  if (strength (curve) <= 0.0 || n == 0)
    return;

  /* factor per 16-bit level of the largest channel */
  ratio = g_new (gfloat, 65536);
  ratio[0] = 1.0f;
  for (k = 1; k < 65536; k++)
    {
      gdouble x = k / 65535.0;

      ratio[k] = (gfloat) (rawheic_tone_eval (curve, x) / x);
    }

  if (img->pixels16)
    {
      guint16 *p = img->pixels16;

#pragma omp parallel for
      for (i = 0; i < n; i++)
        {
          guint16 *q = p + i * 3;
          guint16  m = MAX (q[0], MAX (q[1], q[2]));
          gfloat   r = ratio[m];
          gint     c;

          for (c = 0; c < 3; c++)
            q[c] = (guint16) MIN (q[c] * r + 0.5f, 65535.0f);
        }
    }
  else if (img->pixels)
    {
      gfloat *p = img->pixels;

#pragma omp parallel for
      for (i = 0; i < n; i++)
        {
          gfloat *q = p + i * 3;
          gfloat  m = MAX (q[0], MAX (q[1], q[2]));
          gfloat  r;
          gint    c;

          if (! (m > 0.0f) || m >= 1.0f)
            continue;   /* black, or highlights above white: unchanged */
          r = ratio[(gint) (m * 65535.0f + 0.5f)];
          for (c = 0; c < 3; c++)
            q[c] *= r;
        }
    }

  g_free (ratio);
}
