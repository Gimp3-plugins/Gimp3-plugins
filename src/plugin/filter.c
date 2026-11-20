/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
#include "filter.h"
#include "scan.h"
#include <gegl.h>
#include <string.h>
#include <glib/gstdio.h>
#ifdef GDK_WINDOWING_WIN32
#include <gdk/gdkwin32.h>
#endif

typedef struct { GMainLoop *loop; int status; } Wait;
static void child_cb (GPid pid, gint status, gpointer data) { Wait *w = data; w->status = status; g_spawn_close_pid (pid); g_main_loop_quit (w->loop); }

static gboolean write_file (const char *path, const void *d, gsize n) {
  GError *e = NULL; gboolean ok = g_file_set_contents (path, (const gchar *) d, (gssize) n, &e); g_clear_error (&e); return ok;
}

static char *log_value (const char *log, const char *key) {   /* last line starting with key, rest of the line */
  const char *p = NULL, *q = log;
  while ((q = strstr (q, key)) != NULL) { p = q; q += strlen (key); }
  if (!p) return NULL;
  p += strlen (key); gsize l = strcspn (p, "\r\n"); return g_strndup (p, l);
}

PsRunStatus ps_filter_run (const PsItem *item, GimpImage *image, GimpDrawable *drawable, GtkWindow *parent, gboolean interactive, char **error) {
  *error = NULL;
  if (!g_file_test (item->path, G_FILE_TEST_EXISTS)) { *error = g_strdup (_T ("The plug-in file no longer exists.")); return PS_RUN_ERROR; }
  int W = gimp_drawable_get_width (drawable), H = gimp_drawable_get_height (drawable);
  if (W <= 0 || H <= 0 || W > 32000 || H > 32000) { *error = g_strdup (_T ("Layers larger than 32000 pixels are not supported.")); return PS_RUN_ERROR; }

  const Babl *fmt = babl_format ("R'G'B'A u8"), *mfmt = babl_format ("Y u8");
  gsize npx = (gsize) W * H;
  guint8 *in = g_malloc (npx * 4), *mask = NULL;
  gegl_buffer_get (gimp_drawable_get_buffer (drawable), GEGL_RECTANGLE (0, 0, W, H), 1.0, fmt, in, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

  int rx = 0, ry = 0, rw = W, rh = H;
  gboolean has_sel = !gimp_selection_is_empty (image);
  if (has_sel) {
    if (!gimp_drawable_mask_intersect (drawable, &rx, &ry, &rw, &rh) || rw <= 0 || rh <= 0) { g_free (in); *error = g_strdup (_T ("The selection does not overlap the layer.")); return PS_RUN_ERROR; }
    int ox = 0, oy = 0; gimp_drawable_get_offsets (drawable, &ox, &oy);
    mask = g_malloc0 (npx);
    gegl_buffer_get (gimp_drawable_get_buffer (GIMP_DRAWABLE (gimp_image_get_selection (image))), GEGL_RECTANGLE (ox, oy, W, H), 1.0, mfmt, mask, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
  }

  char *tmp = g_dir_make_tmp ("pshostXXXXXX", NULL);
  if (!tmp) { g_free (in); g_free (mask); *error = g_strdup (_T ("Cannot create a temporary directory.")); return PS_RUN_ERROR; }
  char *f_in = g_build_filename (tmp, "in.raw", NULL), *f_out = g_build_filename (tmp, "out.raw", NULL), *f_mask = g_build_filename (tmp, "mask.raw", NULL);
  char *f_log = g_build_filename (tmp, "run.log", NULL), *f_pout = g_build_filename (tmp, "params.out", NULL);
  char *cdir = ps_config_dir (), *pdir = g_build_filename (cdir, "params", NULL), *pfile = g_strconcat (pdir, G_DIR_SEPARATOR_S, item->proc_name, ".bin", NULL);
  g_mkdir_with_parents (pdir, 0700);
  gboolean ok = write_file (f_in, in, npx * 4) && (!mask || write_file (f_mask, mask, npx));
  g_free (in); g_free (mask);

  PsRunStatus st = PS_RUN_ERROR;
  if (!ok) { *error = g_strdup (_T ("Cannot write the temporary image.")); goto cleanup; }

  {
    char *runner = ps_runner_path (), sw[16], sh[16], to[16], hw[32];
    g_snprintf (sw, sizeof sw, "%d", W); g_snprintf (sh, sizeof sh, "%d", H); g_snprintf (to, sizeof to, "%d", 1800000);
    g_snprintf (hw, sizeof hw, "%" G_GINT64_FORMAT, (gint64) 0);
#ifdef GDK_WINDOWING_WIN32
    if (parent && gtk_widget_get_window (GTK_WIDGET (parent))) g_snprintf (hw, sizeof hw, "%" G_GINT64_FORMAT, (gint64) (guintptr) gdk_win32_window_get_handle (gtk_widget_get_window (GTK_WIDGET (parent))));
#endif
    GPtrArray *a = g_ptr_array_new ();
    const char *fixed[] = { runner, "--mode", "run", "--plugin", item->path, "--entry", item->entry && *item->entry ? item->entry : "PluginMain", "--width", sw, "--height", sh,
                            "--in", f_in, "--out", f_out, "--log", f_log, "--params-out", f_pout, "--timeout-ms", to, "--hwnd", hw, "--ui", interactive ? "1" : "0" };
    for (gsize i = 0; i < G_N_ELEMENTS (fixed); i++) g_ptr_array_add (a, (gpointer) fixed[i]);
    if (mask) { g_ptr_array_add (a, "--mask"); g_ptr_array_add (a, f_mask); }
    if (g_file_test (pfile, G_FILE_TEST_EXISTS)) { g_ptr_array_add (a, "--params-in"); g_ptr_array_add (a, pfile); }
    g_ptr_array_add (a, NULL);

    GPid pid; GError *err = NULL;
    if (!g_spawn_async (NULL, (char **) a->pdata, NULL, G_SPAWN_DO_NOT_REAP_CHILD, NULL, NULL, &pid, &err)) {
      *error = g_strdup_printf ("%s: %s", _T ("Cannot start the filter process"), err->message); g_clear_error (&err); g_ptr_array_free (a, TRUE); g_free (runner); goto cleanup;
    }
    Wait w = { g_main_loop_new (NULL, FALSE), -1 };
    g_child_watch_add (pid, child_cb, &w);
    g_main_loop_run (w.loop); g_main_loop_unref (w.loop);
    g_ptr_array_free (a, TRUE); g_free (runner);

    char *log = NULL; g_file_get_contents (f_log, &log, NULL, NULL);
    const char *L = log ? log : "";
    guint code = (guint) w.status;
    if (code == 0) {
      gchar *out = NULL; gsize n = 0;
      if (g_file_get_contents (f_out, &out, &n, NULL) && n == npx * 4) {
        GeglBuffer *shadow = gimp_drawable_get_shadow_buffer (drawable);
        gegl_buffer_set (shadow, GEGL_RECTANGLE (rx, ry, rw, rh), 0, fmt, (guint8 *) out + ((gsize) ry * W + rx) * 4, (gint) ((gsize) W * 4));
        gegl_buffer_flush (shadow);
        gimp_image_undo_group_start (image);
        gimp_drawable_merge_shadow (drawable, TRUE);
        gimp_image_undo_group_end (image);
        gimp_drawable_update (drawable, rx, ry, rw, rh);
        gimp_displays_flush ();
        if (g_file_test (f_pout, G_FILE_TEST_EXISTS)) { gchar *pd = NULL; gsize pn = 0; if (g_file_get_contents (f_pout, &pd, &pn, NULL)) { write_file (pfile, pd, pn); g_free (pd); } }
        st = PS_RUN_OK;
      } else *error = g_strdup (_T ("The filter did not produce a valid result."));
      g_free (out);
    } else if (code == 7) st = PS_RUN_CANCELLED;
    else if (code == 124) *error = g_strdup (_T ("The filter did not finish in time and was stopped. The image was not changed."));
    else if (code == 0xC0DE0001u) *error = g_strdup (_T ("The filter crashed. The image was not changed."));
    else if (code == 3) { char *v = log_value (L, "LOAD_FAILED win32="); *error = g_strdup_printf (_T ("The plug-in could not be loaded (Windows error %s)."), v ? v : "?"); g_free (v); }
    else if (code == 2) {
      char *m = log_value (L, "PLUGIN_MESSAGE "), *v = log_value (L, "RESULT Start = ");
      if (!v) { g_free (v); v = log_value (L, "RESULT Prepare = "); }
      *error = m ? g_strdup_printf ("%s: %s", _T ("The filter reported an error"), m) : g_strdup_printf (_T ("The filter reported an error (code %s)."), v ? v : "?");
      g_free (m); g_free (v);
    } else *error = g_strdup_printf (_T ("The filter process ended unexpectedly (code %u)."), code);
    g_free (log);
  }

cleanup:
  g_remove (f_in); g_remove (f_out); g_remove (f_mask); g_remove (f_log); g_remove (f_pout); g_rmdir (tmp);
  g_free (f_in); g_free (f_out); g_free (f_mask); g_free (f_log); g_free (f_pout); g_free (tmp); g_free (cdir); g_free (pdir); g_free (pfile);
  return st;
}
