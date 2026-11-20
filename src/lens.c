/* gimp-raw-heic -- lens corrections with lensfun
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Vignetting, distortion and transverse chromatic aberration from the
 * lensfun database (shipped in the plug-in folder, see build.ps1).
 * Corrections are applied to the developed, oriented, linear float RGB;
 * all three models are radially symmetric, so the orientation does not
 * matter.  A part of the image (the preview loupe) is corrected with its
 * position inside the full image.
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include <lensfun/lensfun.h>

#include "rawheic.h"

static lfDatabase *lens_db = NULL;

/* Folder with the lensfun XML files: $RAWHEIC_LENSFUN_DB, then
 * <plug-in folder>/lensfun, then the build-time location (development).
 */
static gpointer
load_db (gpointer data)
{
  lfDatabase  *db  = lf_db_new ();
  const gchar *env = g_getenv ("RAWHEIC_LENSFUN_DB");
  gboolean     ok  = FALSE;

  if (env && *env)
    ok = lf_db_load_directory (db, env);

  if (! ok)
    {
      gchar *dir = NULL;

#ifdef G_OS_WIN32
      gchar *base = g_win32_get_package_installation_directory_of_module (NULL);

      dir = g_build_filename (base, "lensfun", NULL);
      g_free (base);
#endif
      if (dir && g_file_test (dir, G_FILE_TEST_IS_DIR))
        ok = lf_db_load_directory (db, dir);
      g_free (dir);
    }

#ifdef LENSFUN_DB_DIR
  if (! ok)
    ok = lf_db_load_directory (db, LENSFUN_DB_DIR);
#endif

  if (! ok)
    ok = lf_db_load (db) == LF_NO_ERROR;   /* system database (Linux) */

  if (! ok)
    {
      lf_db_destroy (db);
      db = NULL;
    }

  return db;
}

static lfDatabase *
get_db (void)
{
  static GOnce once = G_ONCE_INIT;

  lens_db = g_once (&once, load_db, NULL);

  return lens_db;
}

gboolean
rawheic_lens_db_available (void)
{
  return get_db () != NULL;
}

static const lfCamera *
find_camera (lfDatabase     *db,
             const LensInfo *info)
{
  const lfCamera **cams = lf_db_find_cameras_ext (db, info->camera_make,
                                                  info->camera_model, 0);
  const lfCamera  *cam  = cams ? cams[0] : NULL;

  lf_free (cams);

  return cam;
}

static const lfLens *
find_lens (lfDatabase      *db,
           const LensInfo  *info,
           const lfCamera **camera_out)
{
  const lfCamera *cam = find_camera (db, info);
  const lfLens  **lenses;
  const lfLens   *lens = NULL;

  if (camera_out)
    *camera_out = cam;

  if (! info->lens[0])
    return NULL;

  lenses = lf_db_find_lenses_hd (db, cam, info->lens_make[0] ? info->lens_make : NULL,
                                 info->lens, 0);
  if (! lenses)
    lenses = lf_db_find_lenses_hd (db, cam, NULL, info->lens, LF_SEARCH_LOOSE);

  if (lenses)
    lens = lenses[0];
  lf_free (lenses);

  return lens;
}

/* "Maker Model" of the matching database lens, or NULL. */
gchar *
rawheic_lens_describe (const LensInfo *info)
{
  lfDatabase   *db = get_db ();
  const lfLens *lens;

  if (! db)
    return NULL;

  lens = find_lens (db, info, NULL);
  if (! lens)
    return NULL;

  /* lensfun model names usually start with the maker already */
  if (g_str_has_prefix (lf_mlstr_get (lens->Model), lf_mlstr_get (lens->Maker)))
    return g_strdup (lf_mlstr_get (lens->Model));

  return g_strdup_printf ("%s %s", lf_mlstr_get (lens->Maker),
                          lf_mlstr_get (lens->Model));
}

static inline gfloat
sample (const gfloat *src,
        gint          w,
        gint          h,
        gfloat        x,
        gfloat        y,
        gint          c)
{
  gint   x0, y0, x1, y1;
  gfloat fx, fy, a, b;

  /* NaN/Inf would slip through CLAMP (comparisons are false) */
  if (! isfinite (x)) x = 0.0f;
  if (! isfinite (y)) y = 0.0f;
  x = CLAMP (x, 0.0f, (gfloat) (w - 1));
  y = CLAMP (y, 0.0f, (gfloat) (h - 1));
  x0 = CLAMP ((gint) x, 0, w - 1);
  y0 = CLAMP ((gint) y, 0, h - 1);
  x1 = MIN (x0 + 1, w - 1);
  y1 = MIN (y0 + 1, h - 1);
  fx = x - x0;  fy = y - y0;

  a = src[((gsize) y0 * w + x0) * 3 + c] * (1 - fx) + src[((gsize) y0 * w + x1) * 3 + c] * fx;
  b = src[((gsize) y1 * w + x0) * 3 + c] * (1 - fx) + src[((gsize) y1 * w + x1) * 3 + c] * fx;

  return a * (1 - fy) + b * fy;
}

/* Correct @rgb (@w x @h, float RGB) that sits at @off_x, @off_y inside an
 * image of @full_w x @full_h.  @flags: RAWHEIC_LENS_* bits.  Returns the
 * corrections actually applied (0 if the lens is unknown).
 */
gint
rawheic_lens_correct (gfloat         *rgb,
                      gint            w,
                      gint            h,
                      gint            full_w,
                      gint            full_h,
                      gint            off_x,
                      gint            off_y,
                      const LensInfo *info,
                      gint            flags)
{
  lfDatabase     *db = get_db ();
  const lfCamera *cam = NULL;
  const lfLens   *lens;
  lfModifier     *mod;
  gfloat          crop;
  gint            lf_flags = 0, done, y;

  /* metadata comes from the file: only accept finite, plausible values */
  if (! db || ! flags || w < 2 || h < 2 || full_w < 2 || full_h < 2 ||
      ! isfinite (info->focal) || info->focal < 1.0f || info->focal > 5000.0f)
    return 0;

  lens = find_lens (db, info, &cam);
  if (! lens)
    return 0;

  crop = 0.0f;
  if (isfinite (info->focal35) && info->focal35 >= 1.0f && info->focal35 <= 5000.0f)
    crop = info->focal35 / info->focal;
  if (! (crop >= 0.1f && crop <= 20.0f) && cam && cam->CropFactor >= 0.1f && cam->CropFactor <= 20.0f)
    crop = cam->CropFactor;
  if (! (crop >= 0.1f && crop <= 20.0f))
    crop = (lens->CropFactor >= 0.1f && lens->CropFactor <= 20.0f) ? lens->CropFactor : 1.0f;

  if (flags & RAWHEIC_LENS_VIGNETTING) lf_flags |= LF_MODIFY_VIGNETTING;
  if (flags & RAWHEIC_LENS_DISTORTION) lf_flags |= LF_MODIFY_DISTORTION;
  if (flags & RAWHEIC_LENS_TCA)        lf_flags |= LF_MODIFY_TCA;

  mod  = lf_modifier_new (lens, crop, full_w, full_h);
  /* scale 0 = lensfun picks the scale that leaves no empty corners */
  done = lf_modifier_initialize (mod, lens, LF_PF_F32, info->focal,
                                 (isfinite (info->aperture) && info->aperture >= 0.5f &&
                                  info->aperture <= 128.0f) ? info->aperture : 8.0f,
                                 1000.0f, (lf_flags & LF_MODIFY_DISTORTION) ? 0.0f : 1.0f,
                                 lens->Type, lf_flags, FALSE);

  if (done & LF_MODIFY_VIGNETTING)
    {
#pragma omp parallel for
      for (y = 0; y < h; y++)
        lf_modifier_apply_color_modification (mod, rgb + (gsize) y * w * 3,
                                              (gfloat) off_x, (gfloat) (off_y + y), w, 1,
                                              LF_CR_3 (RED, GREEN, BLUE),
                                              w * 3 * (gint) sizeof (gfloat));
    }

  if (done & (LF_MODIFY_DISTORTION | LF_MODIFY_TCA))
    {
      gfloat *out = g_try_malloc ((gsize) w * h * 3 * sizeof (gfloat));

      if (out)
        {
#pragma omp parallel for
          for (y = 0; y < h; y++)
            {
              gfloat *coords = g_malloc ((gsize) w * 6 * sizeof (gfloat));
              gint    x, c;

              lf_modifier_apply_subpixel_geometry_distortion (mod, (gfloat) off_x,
                                                              (gfloat) (off_y + y),
                                                              w, 1, coords);
              for (x = 0; x < w; x++)
                for (c = 0; c < 3; c++)
                  out[((gsize) y * w + x) * 3 + c] =
                    sample (rgb, w, h,
                            coords[x * 6 + c * 2]     - off_x,
                            coords[x * 6 + c * 2 + 1] - off_y, c);
              g_free (coords);
            }

          memcpy (rgb, out, (gsize) w * h * 3 * sizeof (gfloat));
          g_free (out);
        }
      else
        {
          done &= ~(LF_MODIFY_DISTORTION | LF_MODIFY_TCA);
        }
    }

  lf_modifier_destroy (mod);

  return ((done & LF_MODIFY_VIGNETTING) ? RAWHEIC_LENS_VIGNETTING : 0) |
         ((done & LF_MODIFY_DISTORTION) ? RAWHEIC_LENS_DISTORTION : 0) |
         ((done & LF_MODIFY_TCA)        ? RAWHEIC_LENS_TCA        : 0);
}
