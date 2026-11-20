/* gimp-raw-heic -- unit tests for logic that does not need a running GIMP
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Run with:  meson test -C build
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include <glib/gstdio.h>

/* include the implementation to reach its static helpers */
#include "../../src/raw-develop.c"

static gchar *samples_dir = NULL;

/* --- settings ------------------------------------------------------------ */

static void
test_settings_roundtrip (void)
{
  RawSettings a, b;
  gchar      *text, *path = NULL;

  raw_settings_defaults (&a);
  a.wb_mode        = WB_MANUAL;
  a.wb_temperature = 3200;
  a.wb_tint        = -25;
  a.exposure       = 1.5;
  a.highlight      = HL_REBUILD;
  a.rebuild_level  = 7;
  a.demosaic       = 11;
  a.denoise        = 250;
  a.color_space    = CS_PROPHOTO;
  a.linear         = FALSE;
  a.depth          = DEPTH_FLOAT;
  a.half_size      = TRUE;
  a.spot[0] = 0.25; a.spot[1] = 0.5; a.spot[2] = 0.05; a.spot[3] = 0.04;

  text = raw_settings_serialize (&a, "C:\\Zdjęcia\\ąę IMG_1.CR3");
  g_assert_true (raw_settings_deserialize (&b, text, &path));
  g_assert_cmpstr (path, ==, "C:\\Zdjęcia\\ąę IMG_1.CR3");
  g_assert_cmpint (memcmp (&a, &b, sizeof a), ==, 0);

  g_free (text);
  g_free (path);
}

static void
test_settings_clamp_and_garbage (void)
{
  RawSettings s;
  gchar      *path = NULL;

  g_assert_true (raw_settings_deserialize (&s,
    "[raw]\nexposure=99\nwb-temperature=10\nbrightness=-4\nrebuild-level=42\n"
    "demosaic=bogus\ncolor-space=nope\nspot=9;9;9;9\nsource=x.nef\n", &path));
  g_assert_cmpfloat (s.exposure, ==, 3.0);
  g_assert_cmpfloat (s.wb_temperature, ==, 2000.0);
  g_assert_cmpfloat (s.brightness, ==, 0.25);
  g_assert_cmpint (s.rebuild_level, ==, 9);
  g_assert_cmpint (s.demosaic, ==, 3);            /* default kept */
  g_assert_cmpint (s.color_space, ==, CS_SRGB);
  g_assert_cmpfloat (s.spot[0], ==, 1.0);
  g_free (path);

  g_assert_false (raw_settings_deserialize (&s, "not a key file \x01\x02", NULL));
  g_assert_false (raw_settings_deserialize (&s, "[other]\na=1\n", NULL));
  g_assert_false (raw_settings_deserialize (&s, NULL, NULL));
}

/* --- white balance math --------------------------------------------------- */

static void
test_temperature_xy (void)
{
  struct { gdouble T, x, y; } ref[] =
  {
    { 6504, 0.3127, 0.3290 },   /* D65 */
    { 5003, 0.3457, 0.3585 },   /* D50 */
    { 2856, 0.4476, 0.4074 },   /* illuminant A */
  };
  gint i;

  for (i = 0; i < (gint) G_N_ELEMENTS (ref); i++)
    {
      gdouble x, y;

      temperature_to_xy (ref[i].T, &x, &y);
      g_assert_cmpfloat_with_epsilon (x, ref[i].x, 0.004);
      g_assert_cmpfloat_with_epsilon (y, ref[i].y, 0.004);
    }
}

/* --- neutral point mapping ------------------------------------------------- */

static void
test_spot_mapping (void)
{
  /* a spot in the top-left corner of the displayed (oriented) image */
  const gdouble spot[4] = { 0.0, 0.0, 0.1, 0.2 };
  guint         box[4];

  spot_to_raw (spot, 0, 1000, 500, box);          /* no rotation */
  g_assert_cmpuint (box[0], ==, 0);
  g_assert_cmpuint (box[1], ==, 0);
  g_assert_cmpuint (box[2], ==, 100);
  g_assert_cmpuint (box[3], ==, 100);

  spot_to_raw (spot, 3, 1000, 500, box);          /* 180°: bottom-right of raw */
  g_assert_cmpuint (box[0], ==, 900);
  g_assert_cmpuint (box[1], ==, 400);

  spot_to_raw (spot, 6, 1000, 500, box);          /* 90° CW: bottom-left of raw */
  g_assert_cmpuint (box[0], ==, 0);
  g_assert_cmpuint (box[1], ==, 450);
  g_assert_cmpuint (box[2], ==, 200);             /* displayed height = raw width */

  spot_to_raw (spot, 5, 1000, 500, box);          /* 90° CCW: top-right of raw */
  g_assert_cmpuint (box[0], ==, 800);
  g_assert_cmpuint (box[1], ==, 0);
}

/* --- denoise ------------------------------------------------------------- */

static void
test_denoise (void)
{
  const gint w = 96, h = 64;
  guint16   *img = g_new (guint16, w * h * 3);
  gdouble    m0 = 0, m1 = 0, v0 = 0, v1 = 0;
  GRand     *r = g_rand_new_with_seed (7);
  gint       i;

  for (i = 0; i < w * h * 3; i++)
    img[i] = (guint16) CLAMP (10000 + g_rand_double_range (r, -800, 800), 0, 65535);

  for (i = 0; i < w * h * 3; i++) m0 += img[i];
  m0 /= w * h * 3;
  for (i = 0; i < w * h * 3; i++) v0 += (img[i] - m0) * (img[i] - m0);

  g_assert_true (rawheic_wavelet_denoise (img, w, h, 500.0));

  for (i = 0; i < w * h * 3; i++) m1 += img[i];
  m1 /= w * h * 3;
  for (i = 0; i < w * h * 3; i++) v1 += (img[i] - m1) * (img[i] - m1);

  g_assert_cmpfloat (fabs (m1 - m0) / m0, <, 0.01);   /* brightness kept */
  g_assert_cmpfloat (v1, <, v0 * 0.5);                /* noise reduced   */

  /* too small to filter: untouched, no crash */
  g_assert_true (rawheic_wavelet_denoise (img, 10, 10, 500.0));

  g_rand_free (r);
  g_free (img);
}


static void
test_denoise_banded_equals_full (void)
{
  const gint w = 120, h = 700;
  gsize      n = (gsize) w * h * 3;
  guint16   *a = g_new (guint16, n);
  guint16   *b = g_new (guint16, n);
  GRand     *r = g_rand_new_with_seed (11);
  gsize      i;

  for (i = 0; i < n; i++)
    a[i] = (guint16) CLAMP (8000 + (i / (w * 3)) * 20 + g_rand_double_range (r, -900, 900), 0, 65535);
  memcpy (b, a, n * sizeof (guint16));

  g_assert_true (rawheic_wavelet_denoise_banded (a, w, h, 400.0, 1 << 20)); /* one band */
  g_assert_true (rawheic_wavelet_denoise_banded (b, w, h, 400.0, 100));     /* many */
  g_assert_cmpmem (a, n * sizeof (guint16), b, n * sizeof (guint16));

  g_rand_free (r);
  g_free (a);
  g_free (b);
}

static void
test_recovery_compensation (void)
{
  libraw_data_t *lr = libraw_init (0);
  RawSettings    s;
  guint16        px[4] = { 0, 16384, 40000, 65535 };

  raw_settings_defaults (&s);
  lr->color.pre_mul[0] = 2.0f; lr->color.pre_mul[1] = 1.0f;
  lr->color.pre_mul[2] = 1.5f; lr->color.pre_mul[3] = 1.0f;

  s.highlight = HL_CLIP;
  g_assert_cmpfloat (recovery_compensation (lr, &s), ==, 1.0);
  s.highlight = HL_BLEND;
  g_assert_cmpfloat_with_epsilon (recovery_compensation (lr, &s), 2.0, 1e-6);
  s.highlight_compensate = FALSE;
  g_assert_cmpfloat (recovery_compensation (lr, &s), ==, 1.0);

  /* soft knee: monotonic, never wraps, mid-tones scaled exactly */
  compensate_u16 (px, 4, 2.0);
  g_assert_cmpuint (px[0], ==, 0);
  g_assert_cmpuint (px[1], ==, 32768);
  g_assert_cmpuint (px[2], <, px[3]);
  g_assert_cmpuint (px[3], <=, 65535);
  g_assert_cmpuint (px[2], >, 55000);

  libraw_close (lr);
}


/* --- presets --------------------------------------------------------------- */

static void
test_presets (void)
{
  RawSettings s, t;
  GList      *names, *l;
  gboolean    found = FALSE;
  GError     *error = NULL;
  gchar      *fn;

  /* file names never escape the preset directory */
  fn = raw_presets_file_name ("../../evil\\name:*?");
  g_assert_null (strchr (fn, '/'));
  g_assert_null (strchr (fn, '\\'));
  g_assert_null (strchr (fn, ':'));
  g_assert_false (g_str_has_prefix (fn, "."));
  g_free (fn);
  g_assert_null (raw_presets_file_name ("..."));
  g_assert_null (raw_presets_file_name (""));

  raw_settings_defaults (&s);
  s.exposure    = 1.25;
  s.denoise     = 333;
  s.color_space = CS_DISPLAY_P3;
  s.spot[0]     = 0.9;                      /* must not be stored */
  g_assert_true (raw_presets_save ("Ślub – plener", &s, &error));
  g_assert_no_error (error);

  names = raw_presets_list ();
  g_assert_cmpstr (names->data, ==, "Default");       /* built-ins first */
  for (l = names; l; l = l->next)
    found |= ! g_strcmp0 (l->data, "Ślub – plener");
  g_assert_true (found);
  g_list_free_full (names, g_free);

  raw_settings_defaults (&t);
  t.spot[0] = 0.1;
  g_assert_true (raw_presets_load ("Ślub – plener", &t));
  g_assert_cmpfloat (t.exposure, ==, 1.25);
  g_assert_cmpfloat (t.denoise, ==, 333);
  g_assert_cmpint (t.color_space, ==, CS_DISPLAY_P3);
  g_assert_cmpfloat (t.spot[0], ==, 0.1);             /* photo's spot kept */

  /* built-ins: loadable, protected */
  g_assert_true (raw_presets_load ("Night / high ISO", &t));
  g_assert_cmpfloat (t.denoise, >, 0);
  g_assert_false (raw_presets_save ("Default", &s, &error));
  g_assert_nonnull (error);
  g_clear_error (&error);
  g_assert_false (raw_presets_delete ("Default"));
  g_assert_false (raw_presets_save ("", &s, &error));
  g_clear_error (&error);

  g_assert_true (raw_presets_delete ("Ślub – plener"));
  g_assert_false (raw_presets_load ("Ślub – plener", &t));
  g_assert_false (raw_presets_load ("does not exist", &t));
}


/* --- 100% loupe: a region must match the same place of a full develop --- */

static void
region_vs_full (const gchar *file,
                WbMode       wb,
                gdouble      rx,
                gdouble      ry)
{
  gchar      *path = g_build_filename (samples_dir, file, NULL);
  RawSettings s;
  RawSession *ses;
  RawImage   *full, *part;
  GError     *error = NULL;
  gint        fw, fh, x0, y0, x, y, c;
  gdouble     region[4], mf[3] = { 0 }, mp[3] = { 0 };

  if (! g_file_test (path, G_FILE_TEST_EXISTS))
    {
      g_test_skip ("sample missing");
      g_free (path);
      return;
    }

  raw_settings_defaults (&s);
  s.wb_mode = wb;
  s.depth   = DEPTH_FLOAT;

  ses = raw_session_open (path, &error);
  g_assert_no_error (error);
  raw_session_size (ses, &s, &fw, &fh);

  full = raw_session_develop (ses, &s, G_MAXINT, NULL, NULL, &error);  /* float, 1:1 */
  g_assert_no_error (error);
  g_assert_cmpint (full->width, ==, fw);
  g_assert_cmpint (full->height, ==, fh);

  region[2] = 640.0 / fw;
  region[3] = 480.0 / fh;
  region[0] = rx;
  region[1] = ry;
  part = raw_session_develop_region (ses, &s, region, &error);
  g_assert_no_error (error);
  g_assert_cmpint (ABS (part->width - 640), <=, 16);
  g_assert_cmpint (ABS (part->height - 480), <=, 16);

  x0 = (gint) (rx * fw);
  y0 = (gint) (ry * fh);
  for (y = 0; y < part->height; y++)
    for (x = 0; x < part->width; x++)
      for (c = 0; c < 3; c++)
        {
          mp[c] += part->pixels[((gsize) y * part->width + x) * 3 + c];
          mf[c] += full->pixels[((gsize) (y0 + y) * full->width + (x0 + x)) * 3 + c];
        }

  for (c = 0; c < 3; c++)
    g_assert_cmpfloat (fabs (mp[c] / mf[c] - 1.0), <, 0.04);

  raw_image_free (full);
  raw_image_free (part);
  raw_session_free (ses);
  g_free (path);
}

static void
test_region_nef (void)
{
  region_vs_full ("Nikon-D750.nef", WB_CAMERA, 0.40, 0.45);
}

static void
test_region_rotated_auto_wb (void)
{
  /* portrait iPhone DNG: exercises the orientation mapping */
  region_vs_full ("Apple-iPhone_12_Pro.dng", WB_AUTO, 0.05, 0.10);
}


/* --- lens corrections (lensfun) ----------------------------------------- */

static void
test_lens (void)
{
  gchar      *path = g_build_filename (samples_dir, "Canon-EOS_6D.cr2", NULL);
  RawSession *ses;
  LensInfo    info;
  GError     *error = NULL;
  gchar      *desc;
  gfloat     *flat;
  gint        w = 600, h = 400, i, done;
  RawSettings s;
  RawImage   *img;

  if (! g_file_test (path, G_FILE_TEST_EXISTS))
    {
      g_test_skip ("sample missing");
      g_free (path);
      return;
    }

  g_assert_true (rawheic_lens_db_available ());

  ses = raw_session_open (path, &error);
  g_assert_no_error (error);
  lens_info_from_libraw (ses->lr, &info);
  g_test_message ("camera '%s %s' lens '%s' f=%.0f f35=%.0f N=%.1f",
                  info.camera_make, info.camera_model, info.lens,
                  info.focal, info.focal35, info.aperture);

  desc = rawheic_lens_describe (&info);
  g_assert_nonnull (desc);
  g_test_message ("lensfun match: %s", desc);
  g_free (desc);

  /* vignetting on a flat field: corners gain more than the centre */
  flat = g_new (gfloat, (gsize) w * h * 3);
  for (i = 0; i < w * h * 3; i++)
    flat[i] = 0.25f;
  info.aperture = 1.8f;                        /* wide open: strong vignetting */
  done = rawheic_lens_correct (flat, w, h, w, h, 0, 0, &info, RAWHEIC_LENS_VIGNETTING);
  g_assert_cmpint (done & RAWHEIC_LENS_VIGNETTING, !=, 0);
  g_assert_cmpfloat (flat[1], >, flat[((h / 2) * w + w / 2) * 3 + 1] * 1.05f);
  g_assert_cmpfloat (flat[((h / 2) * w + w / 2) * 3 + 1], <, 0.27f);
  g_free (flat);

  /* hostile metadata must not crash or read out of bounds */
  {
    LensInfo bad = info;
    gfloat  *buf = g_new0 (gfloat, (gsize) w * h * 3);

    bad.focal = NAN;
    g_assert_cmpint (rawheic_lens_correct (buf, w, h, w, h, 0, 0, &bad,
                                           RAWHEIC_LENS_DISTORTION | RAWHEIC_LENS_TCA), ==, 0);
    bad = info;
    bad.focal35  = INFINITY;
    bad.aperture = NAN;
    rawheic_lens_correct (buf, w, h, w, h, 0, 0, &bad,
                          RAWHEIC_LENS_DISTORTION | RAWHEIC_LENS_TCA | RAWHEIC_LENS_VIGNETTING);
    bad = info;
    bad.focal35 = 1e30f;
    rawheic_lens_correct (buf, w, h, w, h, -100000, 100000, &bad,
                          RAWHEIC_LENS_DISTORTION | RAWHEIC_LENS_TCA);
    for (i = 0; i < w * h * 3; i++)
      g_assert_true (isfinite (buf[i]));
    g_free (buf);
  }

  /* full develop with all corrections reports what was applied */
  raw_settings_defaults (&s);
  s.half_size       = TRUE;
  s.lens_vignetting = TRUE;
  s.lens_distortion = TRUE;
  s.lens_tca        = TRUE;
  img = raw_session_develop (ses, &s, 0, NULL, NULL, &error);
  g_assert_no_error (error);
  g_assert_true (img->lens_known);
  g_assert_cmpint (img->lens_done & RAWHEIC_LENS_VIGNETTING, !=, 0);
  g_test_message ("applied corrections: 0x%x", img->lens_done);
  raw_image_free (img);

  raw_session_free (ses);
  g_free (path);
}

/* --- batch session -------------------------------------------------------- */

static void
test_batch_session (void)
{
  RawSettings s, out;
  gchar      *files[] = { (gchar *) "C:\\Photos\\A.NEF", (gchar *) "C:\\Photos\\b.cr2", NULL };

  raw_settings_defaults (&s);
  s.exposure  = 2.0;
  s.half_size = TRUE;
  raw_batch_session_begin (&s, files);

  g_assert_true (raw_batch_session_lookup ("C:\\Photos\\A.NEF", &out));
  g_assert_cmpfloat (out.exposure, ==, 2.0);
  g_assert_true (out.half_size);
#ifdef G_OS_WIN32
  g_assert_true (raw_batch_session_lookup ("c:\\photos\\a.nef", &out));   /* case */
#endif
  g_assert_false (raw_batch_session_lookup ("C:\\Photos\\other.nef", &out));

  raw_batch_session_end ();
  g_assert_false (raw_batch_session_lookup ("C:\\Photos\\A.NEF", &out));
}

/* --- paths ------------------------------------------------------------- */

static void
test_remote_paths (void)
{
  /* everything that is not a plain local path counts as remote */
  g_assert_true  (rawheic_path_is_remote ("\\\\server\\share\\a.nef"));
  g_assert_true  (rawheic_path_is_remote ("//server/share/a.nef"));
  g_assert_true  (rawheic_path_is_remote (""));
  g_assert_true  (rawheic_path_is_remote (NULL));
#ifdef G_OS_WIN32
  g_assert_true  (rawheic_path_is_remote ("\\??\\UNC\\server\\share\\a.nef"));
  g_assert_true  (rawheic_path_is_remote ("\\\\?\\UNC\\server\\share\\a.nef"));
  g_assert_true  (rawheic_path_is_remote ("\\\\?\\C:\\a.nef"));
  g_assert_true  (rawheic_path_is_remote ("\\\\.\\C:\\a.nef"));
  g_assert_true  (rawheic_path_is_remote ("relative.nef"));
  g_assert_true  (rawheic_path_is_remote ("C:relative.nef"));
  g_assert_false (rawheic_path_is_remote ("C:\\Windows\\a.nef"));
  g_assert_false (rawheic_path_is_remote ("C:/Windows/../a.nef"));
#else
  g_assert_false (rawheic_path_is_remote ("/home/user/a.nef"));
  g_assert_true  (rawheic_path_is_remote ("relative.nef"));
#endif
}

/* --- LibRaw error handling without GIMP ------------------------------------ */

static void
test_develop_errors (void)
{
  RawSettings s;
  GError     *error = NULL;
  gchar      *tmp;
  RawImage   *img;

  raw_settings_defaults (&s);

  img = raw_develop ("Z:\\does\\not\\exist.nef", &s, 0, NULL, NULL, &error);
  g_assert_null (img);
  g_assert_nonnull (error);
  g_clear_error (&error);

  tmp = g_build_filename (g_get_tmp_dir (), "rawheic-garbage.nef", NULL);
  g_file_set_contents (tmp, "II*\0garbage garbage garbage", 26, NULL);
  img = raw_develop (tmp, &s, 0, NULL, NULL, &error);
  g_assert_null (img);
  g_assert_nonnull (error);
  g_clear_error (&error);
  g_remove (tmp);
  g_free (tmp);
}

static void
test_develop_sample (void)
{
  RawSettings s;
  GError     *error = NULL;
  RawImage   *img;
  gchar      *path = g_build_filename (samples_dir, "Nikon-D750.nef", NULL);

  if (! g_file_test (path, G_FILE_TEST_EXISTS))
    {
      g_test_skip ("sample Nikon-D750.nef not present (tests/fetch-samples.sh)");
      g_free (path);
      return;
    }

  raw_settings_defaults (&s);
  s.half_size = TRUE;
  img = raw_develop (path, &s, 512, NULL, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (img);
  g_assert_cmpint (MAX (img->width, img->height), <=, 512);
  g_assert_nonnull (img->pixels);
  raw_image_free (img);
  g_free (path);
}

int
main (int argc, char **argv)
{
  gchar *gimpdir;

  g_test_init (&argc, &argv, NULL);

  /* keep the batch session file away from the real GIMP profile */
  gimpdir = g_dir_make_tmp ("rawheic-test-XXXXXX", NULL);
  g_setenv ("GIMP3_DIRECTORY", gimpdir, TRUE);

  samples_dir = g_strdup (g_getenv ("RAWHEIC_SAMPLES") ? g_getenv ("RAWHEIC_SAMPLES")
                                                        : SAMPLES_DIR);

  g_test_add_func ("/settings/roundtrip",       test_settings_roundtrip);
  g_test_add_func ("/settings/clamp-garbage",   test_settings_clamp_and_garbage);
  g_test_add_func ("/wb/temperature-xy",        test_temperature_xy);
  g_test_add_func ("/wb/spot-mapping",          test_spot_mapping);
  g_test_add_func ("/denoise/wavelet",          test_denoise);
  g_test_add_func ("/denoise/banded",           test_denoise_banded_equals_full);
  g_test_add_func ("/develop/recovery-comp",    test_recovery_compensation);
  g_test_add_func ("/batch/session",            test_batch_session);
  g_test_add_func ("/presets/save-load-delete", test_presets);
  g_test_add_func ("/util/remote-paths",        test_remote_paths);
  g_test_add_func ("/develop/errors",           test_develop_errors);
  g_test_add_func ("/develop/sample",           test_develop_sample);
  g_test_add_func ("/loupe/region-nef",         test_region_nef);
  g_test_add_func ("/loupe/region-rotated-auto", test_region_rotated_auto_wb);
  g_test_add_func ("/lens/lensfun",             test_lens);

  return g_test_run ();
}
