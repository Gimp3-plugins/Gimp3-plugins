/* gimp-raw-heic -- camera input profiles: ICC and DCP
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Input is LibRaw's white-balanced, demosaiced camera RGB (linear,
 * output_color = 0).  Output is linear RGB in the chosen output space.
 *
 * ICC: a Little CMS transform from the camera profile to the linear
 *      output profile.
 * DCP: Adobe DNG camera profile (DNG specification 1.6, chapter 6):
 *      ForwardMatrix (or ColorMatrix + Bradford) interpolated between the
 *      two calibration illuminants by white balance temperature, then in
 *      linear ProPhoto: HueSatMap, optionally LookTable and the profile
 *      tone curve ("look"), then ProPhoto -> output space.
 *
 * Profile files are untrusted: every offset and count is checked.
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include <lcms2.h>

#include <glib/gstdio.h>

#include "rawheic.h"

typedef gdouble Mat3[3][3];

/* --- small colour maths -------------------------------------------------- */

static void
mat_mul (const Mat3 a, const Mat3 b, Mat3 r)
{
  Mat3 t;
  gint i, j, k;

  for (i = 0; i < 3; i++)
    for (j = 0; j < 3; j++)
      for (t[i][j] = 0, k = 0; k < 3; k++)
        t[i][j] += a[i][k] * b[k][j];
  memcpy (r, t, sizeof t);
}

static void
mat_vec (const Mat3 m, const gdouble v[3], gdouble r[3])
{
  gdouble t[3];
  gint    i;

  for (i = 0; i < 3; i++)
    t[i] = m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2];
  memcpy (r, t, sizeof t);
}

static gboolean
mat_inv (const Mat3 m, Mat3 r)
{
  gdouble det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
                m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
                m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  Mat3    t;

  if (! isfinite (det) || fabs (det) < 1e-12)
    return FALSE;

  t[0][0] =  (m[1][1] * m[2][2] - m[1][2] * m[2][1]) / det;
  t[0][1] = -(m[0][1] * m[2][2] - m[0][2] * m[2][1]) / det;
  t[0][2] =  (m[0][1] * m[1][2] - m[0][2] * m[1][1]) / det;
  t[1][0] = -(m[1][0] * m[2][2] - m[1][2] * m[2][0]) / det;
  t[1][1] =  (m[0][0] * m[2][2] - m[0][2] * m[2][0]) / det;
  t[1][2] = -(m[0][0] * m[1][2] - m[0][2] * m[1][0]) / det;
  t[2][0] =  (m[1][0] * m[2][1] - m[1][1] * m[2][0]) / det;
  t[2][1] = -(m[0][0] * m[2][1] - m[0][1] * m[2][0]) / det;
  t[2][2] =  (m[0][0] * m[1][1] - m[0][1] * m[1][0]) / det;
  memcpy (r, t, sizeof t);

  return TRUE;
}

static void
xy_to_XYZ (gdouble x, gdouble y, gdouble XYZ[3])
{
  XYZ[0] = x / y;
  XYZ[1] = 1.0;
  XYZ[2] = (1.0 - x - y) / y;
}

/* Bradford adaptation matrix from white @src to white @dst (XYZ). */
static void
bradford (const gdouble src[3], const gdouble dst[3], Mat3 r)
{
  static const Mat3 B  = { {  0.8951,  0.2664, -0.1614 },
                           { -0.7502,  1.7135,  0.0367 },
                           {  0.0389, -0.0685,  1.0296 } };
  Mat3    Bi, D = { { 0 } };
  gdouble s[3], d[3];
  gint    i;

  mat_inv (B, Bi);
  mat_vec (B, src, s);
  mat_vec (B, dst, d);
  for (i = 0; i < 3; i++)
    D[i][i] = d[i] / s[i];
  mat_mul (Bi, D, r);
  mat_mul (r, B, r);
}

/* RGB->XYZ for primaries/white given as xy. */
static void
rgb_to_xyz (const gdouble prim[3][2], const gdouble white[2], Mat3 r)
{
  Mat3    P, Pi;
  gdouble W[3], S[3];
  gint    i, j;

  for (j = 0; j < 3; j++)
    {
      gdouble XYZ[3];

      xy_to_XYZ (prim[j][0], prim[j][1], XYZ);
      for (i = 0; i < 3; i++)
        P[i][j] = XYZ[i];
    }
  xy_to_XYZ (white[0], white[1], W);
  mat_inv (P, Pi);
  mat_vec (Pi, W, S);
  for (i = 0; i < 3; i++)
    for (j = 0; j < 3; j++)
      r[i][j] = P[i][j] * S[j];
}

static const gdouble D50_xy[2] = { 0.3457, 0.3585 };
static const gdouble prophoto_prim[3][2] = { { 0.7347, 0.2653 }, { 0.1596, 0.8404 },
                                             { 0.0366, 0.0001 } };

/* XYZ (D50) -> linear RGB of output space @cs (adapted to its white). */
static void
xyz50_to_space (ColorSpace cs, Mat3 r)
{
  gdouble prim[3][2], white[2], W50[3], Wt[3];
  Mat3    M, Mi, A;

  rawheic_space_xy (cs, prim, white);
  rgb_to_xyz (prim, white, M);
  mat_inv (M, Mi);
  xy_to_XYZ (D50_xy[0], D50_xy[1], W50);
  xy_to_XYZ (white[0], white[1], Wt);
  bradford (W50, Wt, A);
  mat_mul (Mi, A, r);
}

/* McCamy's approximation, fine for picking the illuminant blend. */
static gdouble
xy_to_cct (gdouble x, gdouble y)
{
  gdouble n = (x - 0.3320) / (0.1858 - y);

  return CLAMP (449.0 * n * n * n + 3525.0 * n * n + 6823.3 * n + 5520.33, 1500.0, 25000.0);
}

static gdouble
illuminant_temperature (guint code)
{
  switch (code)
    {
    case 17: return 2856;   /* standard A      */
    case 3:                 /* tungsten        */
    case 24: return 3200;   /* ISO tungsten    */
    case 15: return 3525;   /* white fluor.    */
    case 2:
    case 14: return 4150;   /* cool white fl.  */
    case 18: return 4874;   /* standard B      */
    case 13:
    case 23: return 5003;   /* D50             */
    case 1:
    case 4:
    case 9:
    case 20: return 5503;   /* daylight / D55  */
    case 10:
    case 21: return 6504;   /* D65             */
    case 12: return 6430;
    case 19: return 6774;   /* standard C      */
    case 11:
    case 22: return 7504;   /* shade / D75     */
    default: return 0;
    }
}

/* --- DCP ------------------------------------------------------------------ */

typedef struct
{
  gint     hue, sat, val;
  gfloat  *data;           /* hue*sat*val*3: hue shift (deg), sat scale, val scale */
  gboolean srgb_encoded;   /* value axis in sRGB gamma (LookTable encoding 1) */
} HsvMap;

typedef struct
{
  guint    illum[2];
  gboolean has_cm[2], has_fm[2];
  Mat3     cm[2];          /* XYZ -> camera */
  Mat3     fm[2];          /* white-balanced camera -> XYZ D50 */
  HsvMap   hsm[2];
  HsvMap   look;
  gfloat  *tone;           /* x,y pairs */
  gint     tone_n;
} Dcp;

typedef struct
{
  const guint8 *d;
  gsize         len;
  gboolean      be;
} Tiff;

static guint16
t16 (const Tiff *t, gsize o)
{
  return t->be ? (guint16) (t->d[o] << 8 | t->d[o + 1]) : (guint16) (t->d[o + 1] << 8 | t->d[o]);
}

static guint32
t32 (const Tiff *t, gsize o)
{
  return t->be ? ((guint32) t->d[o] << 24 | (guint32) t->d[o + 1] << 16 |
                  (guint32) t->d[o + 2] << 8 | t->d[o + 3])
               : ((guint32) t->d[o + 3] << 24 | (guint32) t->d[o + 2] << 16 |
                  (guint32) t->d[o + 1] << 8 | t->d[o]);
}

static const gsize type_size[] = { 0, 1, 1, 2, 4, 8, 1, 1, 2, 4, 8, 4, 8 };

/* Read @n numbers of an entry as doubles; FALSE if out of bounds. */
static gboolean
read_numbers (const Tiff *t,
              gsize       entry,
              gdouble    *out,
              guint32     n)
{
  guint16 type  = t16 (t, entry + 2);
  guint32 count = t32 (t, entry + 4);
  gsize   size, off, i;

  if (type == 0 || type > 12 || count < n)
    return FALSE;

  size = type_size[type];
  off  = size * count <= 4 ? entry + 8 : t32 (t, entry + 8);
  if (off > t->len || (gsize) n * size > t->len - off)
    return FALSE;

  for (i = 0; i < n; i++)
    {
      gsize o = off + i * size;

      switch (type)
        {
        case 1: case 7: out[i] = t->d[o]; break;
        case 3:  out[i] = t16 (t, o); break;
        case 8:  out[i] = (gint16) t16 (t, o); break;
        case 4:  out[i] = t32 (t, o); break;
        case 9:  out[i] = (gint32) t32 (t, o); break;
        case 5:  { guint32 d = t32 (t, o + 4);
                   out[i] = d ? (gdouble) t32 (t, o) / d : 0; } break;
        case 10: { gint32 d = (gint32) t32 (t, o + 4);
                   out[i] = d ? (gdouble) (gint32) t32 (t, o) / d : 0; } break;
        case 11: { guint32 u = t32 (t, o); gfloat f; memcpy (&f, &u, 4); out[i] = f; } break;
        default: return FALSE;
        }
      if (! isfinite (out[i]))
        return FALSE;
    }

  return TRUE;
}

static gboolean
read_hsv_map (const Tiff *t,
              gsize       data_entry,
              gint        dims[3],
              HsvMap     *map)
{
  gsize    n;
  gdouble *tmp;
  gsize    i;

  if (dims[0] < 1 || dims[1] < 2 || dims[2] < 1 ||
      dims[0] > 360 || dims[1] > 256 || dims[2] > 256)
    return FALSE;

  n = (gsize) dims[0] * dims[1] * dims[2] * 3;
  if (n > 4 * 1024 * 1024)
    return FALSE;

  tmp = g_new (gdouble, n);
  if (! read_numbers (t, data_entry, tmp, (guint32) n))
    {
      g_free (tmp);
      return FALSE;
    }

  map->hue  = dims[0];
  map->sat  = dims[1];
  map->val  = dims[2];
  map->data = g_new (gfloat, n);
  for (i = 0; i < n; i++)
    map->data[i] = (gfloat) CLAMP (tmp[i], -1e4, 1e4);
  g_free (tmp);

  return TRUE;
}

static gboolean
sane_matrix (const gdouble v[9])
{
  gint k;

  for (k = 0; k < 9; k++)
    if (! isfinite (v[k]) || fabs (v[k]) > 100.0)
      return FALSE;
  return TRUE;
}

static void
dcp_free (Dcp *dcp)
{
  if (! dcp)
    return;
  g_free (dcp->hsm[0].data);
  g_free (dcp->hsm[1].data);
  g_free (dcp->look.data);
  g_free (dcp->tone);
  g_free (dcp);
}

static Dcp *
dcp_parse (const guint8 *data,
           gsize         len,
           GError      **error)
{
  Tiff     t = { data, len, FALSE };
  Dcp     *dcp;
  guint32  ifd;
  guint16  n, i;
  gint     hsm_dims[3] = { 0 }, look_dims[3] = { 0 };
  gsize    hsm_entry[2] = { 0, 0 }, look_entry = 0;
  gboolean look_srgb = FALSE;

  if (len < 8 || ! ((data[0] == 'I' && data[1] == 'I' && data[2] == 'R' && data[3] == 'C') ||
                    (data[0] == 'M' && data[1] == 'M' && data[2] == 'C' && data[3] == 'R')))
    {
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("This is not a DNG camera profile (DCP)."));
      return NULL;
    }

  t.be = data[0] == 'M';
  ifd  = t32 (&t, 4);
  if (ifd > len || len - ifd < 2)
    goto bad;

  n = t16 (&t, ifd);
  if ((gsize) ifd + 2 + (gsize) n * 12 > len)
    goto bad;

  dcp = g_new0 (Dcp, 1);

  for (i = 0; i < n; i++)
    {
      gsize   e   = ifd + 2 + (gsize) i * 12;
      guint16 tag = t16 (&t, e);
      gdouble v[9];
      gint    k;

      switch (tag)
        {
        case 50778: case 50779:          /* CalibrationIlluminant1/2 */
          if (read_numbers (&t, e, v, 1))
            dcp->illum[tag - 50778] = (guint) CLAMP (v[0], 0.0, 65535.0);
          break;

        case 50721: case 50722:          /* ColorMatrix1/2: XYZ -> camera */
          if (read_numbers (&t, e, v, 9) && sane_matrix (v))
            {
              for (k = 0; k < 9; k++)
                dcp->cm[tag - 50721][k / 3][k % 3] = v[k];
              dcp->has_cm[tag - 50721] = TRUE;
            }
          break;

        case 50964: case 50965:          /* ForwardMatrix1/2 */
          if (read_numbers (&t, e, v, 9) && sane_matrix (v))
            {
              for (k = 0; k < 9; k++)
                dcp->fm[tag - 50964][k / 3][k % 3] = v[k];
              dcp->has_fm[tag - 50964] = TRUE;
            }
          break;

        case 50937:                      /* ProfileHueSatMapDims */
          if (read_numbers (&t, e, v, 3))
            for (k = 0; k < 3; k++)
              hsm_dims[k] = (gint) CLAMP (v[k], 0.0, 65535.0);
          break;
        case 50938: hsm_entry[0] = e; break;
        case 50939: hsm_entry[1] = e; break;

        case 50981:                      /* ProfileLookTableDims */
          if (read_numbers (&t, e, v, 3))
            for (k = 0; k < 3; k++)
              look_dims[k] = (gint) CLAMP (v[k], 0.0, 65535.0);
          break;
        case 50982: look_entry = e; break;
        case 51108:                      /* ProfileLookTableEncoding */
          if (read_numbers (&t, e, v, 1))
            look_srgb = v[0] == 1;
          break;

        case 50940:                      /* ProfileToneCurve: x,y pairs */
          {
            guint32 count = t32 (&t, e + 4);

            if (count >= 4 && count <= 8192 && count % 2 == 0)
              {
                gdouble *tc = g_new (gdouble, count);

                if (read_numbers (&t, e, tc, count))
                  {
                    g_free (dcp->tone);   /* a repeated tag replaces the curve */
                    dcp->tone   = g_new (gfloat, count);
                    dcp->tone_n = (gint) count / 2;
                    for (k = 0; k < (gint) count; k++)
                      dcp->tone[k] = (gfloat) CLAMP (tc[k], 0.0, 1.0);
                  }
                g_free (tc);
              }
          }
          break;
        }
    }

  for (i = 0; i < 2; i++)
    if (hsm_entry[i] && hsm_dims[0])
      read_hsv_map (&t, hsm_entry[i], hsm_dims, &dcp->hsm[i]);
  if (look_entry && look_dims[0] && read_hsv_map (&t, look_entry, look_dims, &dcp->look))
    dcp->look.srgb_encoded = look_srgb;

  if (! dcp->has_cm[0] && ! dcp->has_fm[0])
    {
      dcp_free (dcp);
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("The DCP profile has no colour matrix."));
      return NULL;
    }

  return dcp;

bad:
  g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                       _("The DCP profile is damaged."));
  return NULL;
}

/* Blend weight of illuminant 1 for a scene at @temp (inverse temperature). */
static gdouble
dcp_weight (const Dcp *dcp,
            gdouble    temp)
{
  gdouble t1 = illuminant_temperature (dcp->illum[0]);
  gdouble t2 = illuminant_temperature (dcp->illum[1]);

  if (! dcp->has_cm[1] && ! dcp->has_fm[1])
    return 1.0;
  if (t1 <= 0 || t2 <= 0 || t1 == t2)
    return 0.5;
  if (t1 > t2)
    {
      gdouble s = t1; t1 = t2; t2 = s;
      return 1.0 - CLAMP ((1.0 / temp - 1.0 / t2) / (1.0 / t1 - 1.0 / t2), 0.0, 1.0);
    }

  return CLAMP ((1.0 / temp - 1.0 / t2) / (1.0 / t1 - 1.0 / t2), 0.0, 1.0);
}

static void
blend (const Mat3 a, const Mat3 b, gdouble w, gboolean has_b, Mat3 r)
{
  gint i, j;

  for (i = 0; i < 3; i++)
    for (j = 0; j < 3; j++)
      r[i][j] = has_b ? w * a[i][j] + (1 - w) * b[i][j] : a[i][j];
}

/* White point (xy) of the scene from the camera neutral, iterating the
 * interpolated ColorMatrix like the DNG SDK does.
 */
static gdouble
dcp_scene_temperature (const Dcp     *dcp,
                       const gdouble  neutral[3],
                       gdouble        xy[2])
{
  gdouble temp = 5000.0;
  gint    it;

  xy[0] = D50_xy[0];
  xy[1] = D50_xy[1];

  if (! dcp->has_cm[0])
    return temp;

  for (it = 0; it < 10; it++)
    {
      Mat3    cm, inv;
      gdouble XYZ[3], s;
      gdouble w = dcp_weight (dcp, temp);

      blend (dcp->cm[0], dcp->cm[1], w, dcp->has_cm[1], cm);
      if (! mat_inv (cm, inv))
        break;
      mat_vec (inv, neutral, XYZ);
      s = XYZ[0] + XYZ[1] + XYZ[2];
      if (! (s > 1e-9) || XYZ[1] <= 0)
        break;
      xy[0] = XYZ[0] / s;
      xy[1] = XYZ[1] / s;
      temp  = xy_to_cct (xy[0], xy[1]);
    }

  return temp;
}

static inline void
rgb_to_hsv (const gfloat c[3], gfloat *h, gfloat *s, gfloat *v)
{
  gfloat mx = MAX (c[0], MAX (c[1], c[2]));
  gfloat mn = MIN (c[0], MIN (c[1], c[2]));
  gfloat d  = mx - mn;

  *v = mx;
  *s = mx > 0 ? d / mx : 0;
  if (d <= 0)
    *h = 0;
  else if (mx == c[0])
    *h = (c[1] - c[2]) / d;
  else if (mx == c[1])
    *h = (c[2] - c[0]) / d + 2.0f;
  else
    *h = (c[0] - c[1]) / d + 4.0f;
  if (*h < 0)
    *h += 6.0f;
}

static inline void
hsv_to_rgb (gfloat h, gfloat s, gfloat v, gfloat c[3])
{
  gint   i;
  gfloat f, p, q, t;

  h = fmodf (h, 6.0f);
  if (h < 0)
    h += 6.0f;
  i = (gint) h;
  f = h - i;
  p = v * (1 - s);
  q = v * (1 - s * f);
  t = v * (1 - s * (1 - f));
  switch (i)
    {
    case 0:  c[0] = v; c[1] = t; c[2] = p; break;
    case 1:  c[0] = q; c[1] = v; c[2] = p; break;
    case 2:  c[0] = p; c[1] = v; c[2] = t; break;
    case 3:  c[0] = p; c[1] = q; c[2] = v; break;
    case 4:  c[0] = t; c[1] = p; c[2] = v; break;
    default: c[0] = v; c[1] = p; c[2] = q; break;
    }
}

static inline gfloat
srgb_oetf (gfloat v)
{
  return v <= 0.0031308f ? v * 12.92f : 1.055f * powf (v, 1 / 2.4f) - 0.055f;
}

static inline gfloat
srgb_eotf (gfloat v)
{
  return v <= 0.04045f ? v / 12.92f : powf ((v + 0.055f) / 1.055f, 2.4f);
}

/* Apply an HSV map (trilinear, hue wraps) to one linear ProPhoto pixel. */
static void
apply_hsv (const HsvMap *m,
           const gfloat *data,
           gfloat        c[3])
{
  gfloat h, s, v, vl, hf, sf, vf;
  gint   h0, h1, s0, s1, v0, v1, k;
  gfloat out[3] = { 0, 0, 0 };

  rgb_to_hsv (c, &h, &s, &v);
  if (! isfinite (h) || ! isfinite (s) || ! isfinite (v))
    return;
  vl = m->srgb_encoded ? srgb_oetf (CLAMP (v, 0.0f, 1.0f)) : CLAMP (v, 0.0f, 1.0f);

  hf = h * m->hue / 6.0f;
  sf = s * (m->sat - 1);
  vf = m->val > 1 ? vl * (m->val - 1) : 0;

  hf = CLAMP (hf, 0.0f, (gfloat) m->hue);
  h0 = (gint) floorf (hf);
  hf -= h0;
  h0 = ((h0 % m->hue) + m->hue) % m->hue;
  h1 = (h0 + 1) % m->hue;
  s0 = CLAMP ((gint) sf, 0, m->sat - 1); s1 = MIN (s0 + 1, m->sat - 1); sf -= s0;
  v0 = CLAMP ((gint) vf, 0, m->val - 1); v1 = MIN (v0 + 1, m->val - 1); vf -= v0;
  sf = CLAMP (sf, 0.0f, 1.0f);
  vf = CLAMP (vf, 0.0f, 1.0f);

  /* data layout: [val][hue][sat][3] (DNG spec) */
#define E(vi, hi, si, ch) data[(((gsize) (vi) * m->hue + (hi)) * m->sat + (si)) * 3 + (ch)]
  for (k = 0; k < 3; k++)
    {
      gfloat a = E (v0, h0, s0, k) * (1 - sf) + E (v0, h0, s1, k) * sf;
      gfloat b = E (v0, h1, s0, k) * (1 - sf) + E (v0, h1, s1, k) * sf;
      gfloat c0 = a * (1 - hf) + b * hf;
      gfloat d = E (v1, h0, s0, k) * (1 - sf) + E (v1, h0, s1, k) * sf;
      gfloat e = E (v1, h1, s0, k) * (1 - sf) + E (v1, h1, s1, k) * sf;
      gfloat c1 = d * (1 - hf) + e * hf;

      out[k] = c0 * (1 - vf) + c1 * vf;
    }
#undef E

  h += out[0] / 60.0f;
  s  = CLAMP (s * out[1], 0.0f, 1.0f);
  if (m->srgb_encoded)
    v = srgb_eotf (CLAMP (vl * out[2], 0.0f, 1.0f)) * (v > 1.0f ? v : 1.0f);
  else
    v *= out[2];

  hsv_to_rgb (h, s, v, c);
}

static gfloat
tone_eval (const Dcp *dcp,
           gfloat     x)
{
  gint i;

  if (x <= dcp->tone[0])
    return dcp->tone[1];
  for (i = 1; i < dcp->tone_n; i++)
    if (x <= dcp->tone[i * 2])
      {
        gfloat x0 = dcp->tone[i * 2 - 2], y0 = dcp->tone[i * 2 - 1];
        gfloat x1 = dcp->tone[i * 2],     y1 = dcp->tone[i * 2 + 1];

        return x1 > x0 ? y0 + (y1 - y0) * (x - x0) / (x1 - x0) : y1;
      }

  return dcp->tone[dcp->tone_n * 2 - 1];
}

/* Hue-preserving RGB tone (as the DNG SDK's RefBaselineRGBTone): the
 * largest and smallest channels go through the curve, the middle one
 * keeps its relative position.
 */
static void
apply_tone (const Dcp *dcp,
            gfloat     c[3])
{
  gint   mx = 0, mn = 0, md, i;
  gfloat a, b;

  for (i = 1; i < 3; i++)
    {
      if (c[i] > c[mx]) mx = i;
      if (c[i] < c[mn]) mn = i;
    }
  if (mx == mn)
    {
      c[0] = c[1] = c[2] = tone_eval (dcp, CLAMP (c[0], 0.0f, 1.0f));
      return;
    }
  md = 3 - mx - mn;

  a = tone_eval (dcp, CLAMP (c[mx], 0.0f, 1.0f));
  b = tone_eval (dcp, CLAMP (c[mn], 0.0f, 1.0f));
  c[md] = b + (a - b) * (c[md] - c[mn]) / (c[mx] - c[mn]);
  c[mx] = a;
  c[mn] = b;
}

static gboolean
apply_dcp (const Dcp     *dcp,
           gfloat        *rgb,
           gsize          n,
           const gfloat   pre_mul[4],
           ColorSpace     cs,
           gboolean       look)
{
  gdouble neutral[3], xy[2], temp, w;
  Mat3    cam_to_xyz, to_pp, pp_to_out, xyz_to_pp, pp_to_xyz;
  HsvMap  hsm = { 0 };
  gfloat *hsm_data = NULL;
  gsize   i;
  gint    c;

  /* camera neutral: LibRaw's (normalised) multipliers are 1/neutral */
  for (c = 0; c < 3; c++)
    neutral[c] = pre_mul[c] > 0 ? 1.0 / pre_mul[c] : 1.0;
  {
    gdouble m = MAX (neutral[0], MAX (neutral[1], neutral[2]));
    for (c = 0; c < 3; c++)
      neutral[c] /= m;
  }

  temp = dcp_scene_temperature (dcp, neutral, xy);
  w    = dcp_weight (dcp, temp);

  /* white-balanced camera RGB -> XYZ D50 */
  if (dcp->has_fm[0])
    {
      blend (dcp->fm[0], dcp->fm[1], w, dcp->has_fm[1], cam_to_xyz);
    }
  else
    {
      Mat3    cm, inv, A, Nd = { { 0 } };
      gdouble Wsc[3], W50[3];

      blend (dcp->cm[0], dcp->cm[1], w, dcp->has_cm[1], cm);
      if (! mat_inv (cm, inv))
        return FALSE;
      /* data is white balanced: undo it (multiply by neutral), then
       * camera -> XYZ at the scene white, then adapt to D50
       */
      for (c = 0; c < 3; c++)
        Nd[c][c] = neutral[c];
      xy_to_XYZ (xy[0], xy[1], Wsc);
      xy_to_XYZ (D50_xy[0], D50_xy[1], W50);
      bradford (Wsc, W50, A);
      mat_mul (inv, Nd, cam_to_xyz);
      mat_mul (A, cam_to_xyz, cam_to_xyz);
    }

  /* the neutral (1,1,1) must land on D50 white with Y = 1 */
  {
    gdouble one[3] = { 1, 1, 1 }, Y[3], s;

    mat_vec (cam_to_xyz, one, Y);
    s = Y[1] > 1e-9 ? 1.0 / Y[1] : 1.0;
    for (c = 0; c < 9; c++)
      cam_to_xyz[c / 3][c % 3] *= s;
  }

  rgb_to_xyz (prophoto_prim, D50_xy, pp_to_xyz);
  mat_inv (pp_to_xyz, xyz_to_pp);
  mat_mul (xyz_to_pp, cam_to_xyz, to_pp);
  xyz50_to_space (cs, pp_to_out);
  mat_mul (pp_to_out, pp_to_xyz, pp_to_out);

  /* HueSatMap blended between the two illuminants */
  if (dcp->hsm[0].data)
    {
      gsize m = (gsize) dcp->hsm[0].hue * dcp->hsm[0].sat * dcp->hsm[0].val * 3;

      hsm = dcp->hsm[0];
      if (dcp->hsm[1].data && dcp->hsm[1].hue == hsm.hue &&
          dcp->hsm[1].sat == hsm.sat && dcp->hsm[1].val == hsm.val)
        {
          hsm_data = g_new (gfloat, m);
          for (i = 0; i < m; i++)
            hsm_data[i] = (gfloat) (w * dcp->hsm[0].data[i] + (1 - w) * dcp->hsm[1].data[i]);
          hsm.data = hsm_data;
        }
    }

#pragma omp parallel for
  for (i = 0; i < n; i++)
    {
      gfloat *p = rgb + i * 3;
      gfloat  q[3];
      gint    k;

      for (k = 0; k < 3; k++)
        q[k] = (gfloat) (to_pp[k][0] * p[0] + to_pp[k][1] * p[1] + to_pp[k][2] * p[2]);
      for (k = 0; k < 3; k++)
        q[k] = isfinite (q[k]) ? CLAMP (q[k], 0.0f, 1e6f) : 0.0f;

      if (hsm.data)
        apply_hsv (&hsm, hsm.data, q);
      if (look && dcp->look.data)
        apply_hsv (&dcp->look, dcp->look.data, q);
      if (look && dcp->tone)
        apply_tone (dcp, q);

      for (k = 0; k < 3; k++)
        p[k] = (gfloat) (pp_to_out[k][0] * q[0] + pp_to_out[k][1] * q[1] + pp_to_out[k][2] * q[2]);
    }

  g_free (hsm_data);

  return TRUE;
}

/* --- ICC ------------------------------------------------------------------ */

static gboolean
apply_icc (const guint8 *data,
           gsize         len,
           gfloat       *rgb,
           gsize         n,
           ColorSpace    cs,
           GError      **error)
{
  cmsHPROFILE       in = cmsOpenProfileFromMem (data, (cmsUInt32Number) len);
  GimpColorProfile *out;
  cmsHTRANSFORM     xf;
  gsize             i, chunk = 65536;

  if (! in || cmsGetColorSpace (in) != cmsSigRgbData)
    {
      if (in)
        cmsCloseProfile (in);
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("The camera profile is not a valid RGB ICC profile."));
      return FALSE;
    }

  out = rawheic_profile_new (cs, TRUE);
  xf  = cmsCreateTransform (in, TYPE_RGB_FLT, gimp_color_profile_get_lcms_profile (out),
                            TYPE_RGB_FLT, INTENT_RELATIVE_COLORIMETRIC,
                            cmsFLAGS_NOCACHE | cmsFLAGS_NOOPTIMIZE);
  cmsCloseProfile (in);
  g_object_unref (out);

  if (! xf)
    {
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("The camera profile cannot be used for conversion."));
      return FALSE;
    }

#pragma omp parallel for
  for (i = 0; i < n; i += chunk)
    cmsDoTransform (xf, rgb + i * 3, rgb + i * 3, (cmsUInt32Number) MIN (chunk, n - i));

  cmsDeleteTransform (xf);

  return TRUE;
}

/* --- file cache ------------------------------------------------------------
 * The preview develops again on every slider change: keep the last profile
 * file in memory as long as its size and modification time stay the same.
 */

#define MAX_PROFILE_SIZE (64 * 1024 * 1024)

static GMutex  cache_lock;
static gchar  *cache_path;
static gint64  cache_mtime;
static goffset cache_size;
static GBytes *cache_bytes;

static GBytes *
profile_bytes (const gchar  *path,
               GError      **error)
{
  GStatBuf st;
  GBytes  *bytes = NULL;
  gchar   *data  = NULL;
  gsize    len   = 0;

  if (g_stat (path, &st) != 0)
    {
      gchar *name = g_filename_display_name (path);

      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_NOENT,
                   _("The camera profile '%s' cannot be read."), name);
      g_free (name);
      return NULL;
    }

  if (st.st_size > MAX_PROFILE_SIZE)
    {
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("The camera profile file is too large."));
      return NULL;
    }

  g_mutex_lock (&cache_lock);
  if (cache_bytes && ! g_strcmp0 (cache_path, path) &&
      cache_mtime == (gint64) st.st_mtime && cache_size == (goffset) st.st_size)
    bytes = g_bytes_ref (cache_bytes);
  g_mutex_unlock (&cache_lock);

  if (bytes)
    return bytes;

  if (! g_file_get_contents (path, &data, &len, error))
    return NULL;
  if (len > MAX_PROFILE_SIZE)
    {
      g_free (data);
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                           _("The camera profile file is too large."));
      return NULL;
    }

  bytes = g_bytes_new_take (data, len);

  g_mutex_lock (&cache_lock);
  g_clear_pointer (&cache_bytes, g_bytes_unref);
  g_free (cache_path);
  cache_path  = g_strdup (path);
  cache_mtime = (gint64) st.st_mtime;
  cache_size  = (goffset) st.st_size;
  cache_bytes = g_bytes_ref (bytes);
  g_mutex_unlock (&cache_lock);

  return bytes;
}

/* --- finding a profile for a camera -----------------------------------------
 * Adobe's DNG Converter / Camera Raw install their profiles as
 *   <ProgramData>/Adobe/CameraRaw/CameraProfiles/Adobe Standard/<Camera> Adobe Standard.dcp
 *   <ProgramData>/Adobe/CameraRaw/CameraProfiles/Camera/<Camera>/<Camera> Camera *.dcp
 * File names are matched first (cheap), then the profile's
 * UniqueCameraModel tag confirms the camera.
 */

/* "Canon EOS 6D" -> "canoneos6d" */
static gchar *
camera_key (const gchar *text)
{
  GString     *out = g_string_new (NULL);
  const gchar *p;

  for (p = text; p && *p; p++)
    if (g_ascii_isalnum (*p))
      g_string_append_c (out, g_ascii_tolower (*p));

  return g_string_free (out, FALSE);
}

/* UniqueCameraModel (tag 50708) of a DCP, or NULL. */
static gchar *
dcp_camera_model (const guint8 *data,
                  gsize         len)
{
  Tiff     t = { data, len, FALSE };
  guint32  ifd;
  guint16  n, i;

  if (len < 8 || ! ((data[0] == 'I' && data[1] == 'I' && data[2] == 'R' && data[3] == 'C') ||
                    (data[0] == 'M' && data[1] == 'M' && data[2] == 'C' && data[3] == 'R')))
    return NULL;

  t.be = data[0] == 'M';
  ifd  = t32 (&t, 4);
  if (ifd > len || len - ifd < 2)
    return NULL;
  n = t16 (&t, ifd);
  if ((gsize) ifd + 2 + (gsize) n * 12 > len)
    return NULL;

  for (i = 0; i < n; i++)
    {
      gsize   e     = ifd + 2 + (gsize) i * 12;
      guint32 count = t32 (&t, e + 4);
      gsize   off;

      if (t16 (&t, e) != 50708 || t16 (&t, e + 2) != 2 || count == 0 || count > 256)
        continue;
      off = count <= 4 ? e + 8 : t32 (&t, e + 8);
      if (off > len || count > len - off)
        return NULL;
      return g_strndup ((const gchar *) data + off, count);
    }

  return NULL;
}

/* Folders searched for profiles: @folder first, then the usual places. */
gchar **
rawheic_camprofile_dirs (const gchar *folder)
{
  GPtrArray *dirs = g_ptr_array_new ();

  if (folder && *folder)
    g_ptr_array_add (dirs, g_strdup (folder));

  g_ptr_array_add (dirs, g_build_filename (gimp_directory (), "gimp-raw-heic", "profiles", NULL));
#ifdef G_OS_WIN32
  {
    const gchar *pd = g_getenv ("PROGRAMDATA");
    const gchar *ad = g_getenv ("APPDATA");

    if (pd)
      g_ptr_array_add (dirs, g_build_filename (pd, "Adobe", "CameraRaw", "CameraProfiles", NULL));
    if (ad)
      g_ptr_array_add (dirs, g_build_filename (ad, "Adobe", "CameraRaw", "CameraProfiles", NULL));
  }
#else
  g_ptr_array_add (dirs, g_build_filename (g_get_user_data_dir (), "gimp-raw-heic", "profiles", NULL));
#endif
  g_ptr_array_add (dirs, NULL);

  return (gchar **) g_ptr_array_free (dirs, FALSE);
}

/* Collect .dcp files whose name contains @key, at most 3 levels deep. */
static void
scan_dir (const gchar *dir,
          const gchar *key,
          gint         depth,
          GPtrArray   *found)
{
  GDir        *d = g_dir_open (dir, 0, NULL);
  const gchar *name;
  gint         entries = 0;

  if (! d)
    return;

  while ((name = g_dir_read_name (d)) && entries++ < 20000)
    {
      gchar *path = g_build_filename (dir, name, NULL);

      if (g_file_test (path, G_FILE_TEST_IS_DIR))
        {
          if (depth < 3)
            scan_dir (path, key, depth + 1, found);
        }
      else
        {
          gchar *lower = g_ascii_strdown (name, -1);

          if (g_str_has_suffix (lower, ".dcp"))
            {
              gchar *k = camera_key (name);

              if (strstr (k, key))
                {
                  g_ptr_array_add (found, path);
                  path = NULL;
                }
              g_free (k);
            }
          g_free (lower);
        }
      g_free (path);
    }

  g_dir_close (d);
}

/* Lower is better: Adobe Standard, then a "Camera Standard", then others. */
static gint
profile_rank (const gchar *path)
{
  gchar *k    = camera_key (path);
  gint   rank = strstr (k, "adobestandard")  ? 0 :
                strstr (k, "camerastandard") ? 1 :
                strstr (k, "standard")       ? 2 : 3;

  g_free (k);
  return rank;
}

static gint
compare_profiles (gconstpointer a,
                  gconstpointer b)
{
  const gchar *pa = *(const gchar * const *) a;
  const gchar *pb = *(const gchar * const *) b;
  gint         d  = profile_rank (pa) - profile_rank (pb);

  return d ? d : g_utf8_collate (pa, pb);
}

static gchar *
find_uncached (const gchar *folder,
               const gchar *key)
{
  gchar    **dirs = rawheic_camprofile_dirs (folder);
  GPtrArray *found = g_ptr_array_new_with_free_func (g_free);
  gchar     *result = NULL;
  guint      i;

  for (i = 0; dirs[i] && found->len == 0; i++)
    scan_dir (dirs[i], key, 0, found);
  g_strfreev (dirs);

  g_ptr_array_sort (found, compare_profiles);

  /* the file name may name a related camera ("EOS 6D" in "EOS 6D Mark II"):
   * the tag inside decides
   */
  for (i = 0; i < found->len && ! result; i++)
    {
      gchar *data = NULL;
      gsize  len  = 0;

      if (g_file_get_contents (found->pdata[i], &data, &len, NULL) && len <= MAX_PROFILE_SIZE)
        {
          gchar *model = dcp_camera_model ((const guint8 *) data, len);
          gchar *k     = model ? camera_key (model) : NULL;

          if (k && ! strcmp (k, key))
            result = g_strdup (found->pdata[i]);
          g_free (k);
          g_free (model);
        }
      g_free (data);
    }

  g_ptr_array_free (found, TRUE);

  return result;
}

static GMutex      find_lock;
static GHashTable *find_cache;   /* "folder\nkey" -> path or "" */

/* A camera profile for "@make @model", or NULL.  Results are cached for
 * the plug-in's lifetime (one preview dialog asks many times).
 */
gchar *
rawheic_camprofile_find (const gchar *folder,
                         const gchar *make,
                         const gchar *model)
{
  gchar *name, *key, *ckey, *result;
  const gchar *cached;

  if (! model || ! *model)
    return NULL;

  /* LibRaw gives "Canon" + "EOS 6D"; Adobe writes "Canon EOS 6D" */
  name = g_strdup_printf ("%s %s", make ? make : "", model);
  key  = camera_key (name);
  g_free (name);
  if (! *key)
    {
      g_free (key);
      return NULL;
    }

  ckey = g_strdup_printf ("%s\n%s", folder ? folder : "", key);

  g_mutex_lock (&find_lock);
  if (! find_cache)
    find_cache = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);
  cached = g_hash_table_lookup (find_cache, ckey);
  result = cached ? g_strdup (cached) : NULL;
  g_mutex_unlock (&find_lock);

  if (! cached)
    {
      result = find_uncached (folder, key);

      g_mutex_lock (&find_lock);
      g_hash_table_replace (find_cache, g_strdup (ckey), g_strdup (result ? result : ""));
      g_mutex_unlock (&find_lock);
    }

  g_free (ckey);
  g_free (key);

  if (result && ! *result)
    g_clear_pointer (&result, g_free);

  return result;
}

/* --- public ------------------------------------------------------------- */

/* Convert camera RGB (white balanced, linear) in place to linear RGB of
 * @cs using the profile file at @path (.icc/.icm or .dcp).
 */
gboolean
rawheic_camprofile_apply (const gchar  *path,
                          gfloat       *rgb,
                          gsize         n,
                          const gfloat  pre_mul[4],
                          ColorSpace    cs,
                          gboolean      look,
                          GError      **error)
{
  GBytes      *bytes = profile_bytes (path, error);
  const gchar *data;
  gsize        len  = 0;
  gboolean     ok;

  if (! bytes)
    return FALSE;
  data = g_bytes_get_data (bytes, &len);

  if (len >= 4 && ((data[0] == 'I' && data[1] == 'I' && data[2] == 'R' && data[3] == 'C') ||
                   (data[0] == 'M' && data[1] == 'M' && data[2] == 'C' && data[3] == 'R')))
    {
      Dcp *dcp = dcp_parse ((const guint8 *) data, len, error);

      ok = dcp && apply_dcp (dcp, rgb, n, pre_mul, cs, look);
      if (dcp && ! ok)
        g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                             _("The DCP colour matrix cannot be inverted."));
      dcp_free (dcp);
    }
  else
    {
      ok = apply_icc ((const guint8 *) data, len, rgb, n, cs, error);
    }

  g_bytes_unref (bytes);

  return ok;
}
