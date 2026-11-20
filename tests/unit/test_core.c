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
  g_test_add_func ("/batch/session",            test_batch_session);
  g_test_add_func ("/util/remote-paths",        test_remote_paths);
  g_test_add_func ("/develop/errors",           test_develop_errors);
  g_test_add_func ("/develop/sample",           test_develop_sample);

  return g_test_run ();
}
