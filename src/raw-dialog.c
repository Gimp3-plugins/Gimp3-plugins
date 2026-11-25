/* gimp-raw-heic -- RAW import / re-develop dialog with live preview
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include <libgimp/gimpui.h>

#include "rawheic.h"

#define PREVIEW_W     640   /* initial and minimum preview size */
#define PREVIEW_H     480
#define PREVIEW_MAX   2048
#define HIST_W        256
#define HIST_H        80
#define SPOT_SIZE     0.04

typedef struct
{
  guchar *rgb;          /* sRGB u8 */
  gint    w, h;
} Shot;

typedef struct
{
  GimpProcedureConfig *config;
  gchar               *path;
  GtkWidget           *area;
  GtkWidget           *status;
  GtkWidget           *loupe_toggle;
  GtkWidget           *compare_toggle;
  GtkWidget           *clip_toggle;
  GtkWidget           *crop_toggle;
  GtkWidget           *compare_with;   /* default settings / snapshot */
  GtkWidget           *snapshot_button;

  RawSettings          snapshot;       /* remembered for comparison   */
  gboolean             have_snapshot;
  gint                 snapshot_serial;
  GtkWidget           *histogram;
  GtkWidget           *hist_label;

  gint                 view_w;       /* current size of the preview area */
  gint                 view_h;
  guint                hist[3][256]; /* of the "after" preview, sRGB u8  */
  gboolean             hist_valid;

  RawSettings          shown;            /* geometry of the shown preview */
  gboolean             shown_geometry;   /* straighten/crop were applied  */
  gboolean             shown_uncropped;  /* crop tool: whole canvas shown */
  gboolean             dragging;         /* drawing a crop rectangle      */
  gdouble              drag_x0, drag_y0, drag_x1, drag_y1;

  RawSession          *session;
  gboolean             session_failed;
  gchar               *open_error;   /* why the session could not open */
  gboolean             busy;
  gboolean             pending;
  gboolean             closing;
  guint                timeout_id;

  Shot                 after;        /* current settings           */
  Shot                 before;       /* default settings           */
  gchar               *before_key;   /* what "before" was made for */

  gboolean             loupe_active; /* showing a 100% crop        */
  gdouble              loupe_cx;     /* its centre, fractions of   */
  gdouble              loupe_cy;     /* the oriented image         */
  gint                 full_w;       /* full-resolution size of    */
  gint                 full_h;       /* the oriented image         */
} PreviewUI;

typedef struct
{
  RawSettings  settings;
  gboolean     loupe;
  gdouble      region[4];
  gboolean     want_before;
  gchar       *before_key;
  RawImage    *image;
  RawImage    *before;
  gint         full_w, full_h;
  gint         box_w, box_h;   /* the preview must fit into this */
  gboolean     crop_tool;      /* show the whole straightened canvas */
  gboolean     use_snapshot;   /* "before" = the snapshot, not defaults */
  RawSettings  snapshot;
  gchar       *error;
  gint64       usecs;
} RenderJob;


static void render_start    (PreviewUI *ui);
static void schedule_render (PreviewUI *ui,
                             guint      delay);
static void draw_preview    (PreviewUI *ui);


static void
render_job_free (RenderJob *job)
{
  raw_image_free (job->image);
  raw_image_free (job->before);
  g_free (job->before_key);
  g_free (job->error);
  g_free (job);
}

/* "Before" = default development with the same geometry, so both halves
 * of the comparison line up.
 */
static void
before_settings (const RawSettings *s,
                 const RawSettings *snapshot,
                 RawSettings       *b)
{
  if (snapshot)
    *b = *snapshot;
  else
    raw_settings_defaults (b);
  b->auto_rotate = s->auto_rotate;
  b->camera_crop = s->camera_crop;
  b->color_space = s->color_space;
  b->straighten  = s->straighten;
  memcpy (b->spot, s->spot, sizeof b->spot);
  memcpy (b->crop, s->crop, sizeof b->crop);
}

/* Develop a preview that, after cropping, still fills the preview box. */
static RawImage *
develop_preview (RawSession        *ses,
                 const RawSettings *s,
                 gint               box_w,
                 gint               box_h,
                 gboolean           crop_tool,
                 GError           **error)
{
  RawImage *img;
  gint      bw = box_w, bh = box_h;

  if (! crop_tool)
    {
      bw = MIN (PREVIEW_MAX, (gint) (box_w / MAX (0.05, s->crop[2])));
      bh = MIN (PREVIEW_MAX, (gint) (box_h / MAX (0.05, s->crop[3])));
    }

  img = raw_session_develop_box (ses, s, bw, bh, NULL, NULL, error);
  if (img && ! rawheic_geometry_apply (img, s, crop_tool))
    {
      raw_image_free (img);
      img = NULL;
      g_set_error_literal (error, G_FILE_ERROR, G_FILE_ERROR_NOMEM,
                           _("Not enough memory for the preview."));
    }

  /* a crop can still exceed the box in the other direction: shrink */
  if (img && img->pixels && (img->width > box_w || img->height > box_h))
    {
      gint    f = 2, ow, oh, x, y, c, dx, dy;
      gfloat *dst;

      while (img->width / f > box_w || img->height / f > box_h)
        f++;
      ow  = MAX (1, img->width / f);
      oh  = MAX (1, img->height / f);
      dst = g_new0 (gfloat, (gsize) ow * oh * 3);
      for (y = 0; y < oh; y++)
        for (x = 0; x < ow; x++)
          for (c = 0; c < 3; c++)
            {
              gdouble acc = 0;

              for (dy = 0; dy < f; dy++)
                for (dx = 0; dx < f; dx++)
                  acc += img->pixels[(((gsize) y * f + dy) * img->width + x * f + dx) * 3 + c];
              dst[((gsize) y * ow + x) * 3 + c] = (gfloat) (acc / (f * f));
            }
      g_free (img->pixels);
      img->pixels = dst;
      img->width  = ow;
      img->height = oh;
    }

  return img;
}

static void
loupe_region (gdouble  cx,
              gdouble  cy,
              gint     full_w,
              gint     full_h,
              gint     view_w,
              gint     view_h,
              gdouble  region[4])
{
  gdouble w = full_w > 0 ? MIN (1.0, (gdouble) view_w / full_w) : 1.0;
  gdouble h = full_h > 0 ? MIN (1.0, (gdouble) view_h / full_h) : 1.0;

  region[0] = CLAMP (cx - w / 2, 0.0, 1.0 - w);
  region[1] = CLAMP (cy - h / 2, 0.0, 1.0 - h);
  region[2] = w;
  region[3] = h;
}

static void
render_thread (GTask        *task,
               gpointer      source,
               gpointer      task_data,
               GCancellable *cancellable)
{
  PreviewUI *ui;
  RenderJob *job = task_data;
  GError    *error = NULL;
  gint64     t0 = g_get_monotonic_time ();

  ui = g_object_get_data (G_OBJECT (task), "ui");

  if (! ui->session && ! ui->session_failed)
    {
      ui->session = raw_session_open (ui->path, &error);
      if (! ui->session)
        {
          ui->session_failed = TRUE;
          ui->open_error = g_strdup (error ? error->message : "");
        }
    }
  else if (ui->session_failed && ! error)
    {
      /* keep showing why the preview is unavailable */
      job->error = g_strdup (ui->open_error);
    }

  if (ui->session)
    {
      raw_session_size (ui->session, &job->settings, &job->full_w, &job->full_h);

      if (job->loupe)
        {
          /* a full preview first: it measures automatic white balance,
           * which the 100% crop then reuses
           */
          if (job->settings.wb_mode == WB_AUTO || job->settings.wb_mode == WB_SPOT)
            {
              RawImage *full = raw_session_develop_box (ui->session, &job->settings,
                                                        job->box_w, job->box_h,
                                                        NULL, NULL, NULL);
              raw_image_free (full);
            }
          job->image = raw_session_develop_region (ui->session, &job->settings,
                                                   job->region, &error);
        }
      else
        {
          job->image = develop_preview (ui->session, &job->settings,
                                        job->box_w, job->box_h, job->crop_tool, &error);
        }

      if (job->image && job->want_before)
        {
          RawSettings b;

          before_settings (&job->settings, job->use_snapshot ? &job->snapshot : NULL, &b);
          job->before = job->loupe ?
                        raw_session_develop_region (ui->session, &b, job->region, NULL) :
                        develop_preview (ui->session, &b, job->box_w, job->box_h,
                                         job->crop_tool, NULL);
        }
    }

  if (error)
    {
      job->error = g_strdup (error->message);
      g_error_free (error);
    }

  job->usecs = g_get_monotonic_time () - t0;
}

static void
shot_from_image (Shot           *shot,
                 const RawImage *img,
                 ColorSpace      cs)
{
  GimpColorProfile *profile = rawheic_profile_new (cs, TRUE);
  const Babl       *src;
  gsize             n = (gsize) img->width * img->height;

  src = gimp_color_profile_get_format (profile, babl_format ("RGB float"),
                                       GIMP_COLOR_RENDERING_INTENT_RELATIVE_COLORIMETRIC,
                                       NULL);
  g_object_unref (profile);

  g_free (shot->rgb);
  shot->rgb = g_malloc (n * 3);
  shot->w   = img->width;
  shot->h   = img->height;
  if (src && img->pixels)
    babl_process (babl_fish (src, babl_format ("R'G'B' u8")), img->pixels, shot->rgb, n);
  else
    memset (shot->rgb, 128, n * 3);
}

static gboolean
compare_on (PreviewUI *ui)
{
  return gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->compare_toggle));
}

/* Where the preview shows the image: offset inside the area. */
static void
preview_origin (PreviewUI *ui,
                gint      *ox,
                gint      *oy)
{
  *ox = (ui->view_w - ui->after.w) / 2;
  *oy = (ui->view_h - ui->after.h) / 2;
}

/* A fraction of the image before straightening/cropping -> preview pixel. */
static void
source_to_preview (PreviewUI *ui,
                   gdouble    su,
                   gdouble    sv,
                   gint      *px,
                   gint      *py)
{
  gdouble u = su, v = sv;
  gint    ox, oy;

  if (ui->shown_geometry && ui->full_w > 0)
    rawheic_geometry_from_source (&ui->shown, ui->full_w, ui->full_h,
                                  ui->shown_uncropped, su, sv, &u, &v);
  preview_origin (ui, &ox, &oy);
  *px = ox + (gint) floor (u * ui->after.w);
  *py = oy + (gint) floor (v * ui->after.h);
}

static void
current_crop (PreviewUI *ui,
              gdouble    crop[4])
{
  if (ui->dragging)
    {
      crop[0] = MIN (ui->drag_x0, ui->drag_x1);
      crop[1] = MIN (ui->drag_y0, ui->drag_y1);
      crop[2] = fabs (ui->drag_x1 - ui->drag_x0);
      crop[3] = fabs (ui->drag_y1 - ui->drag_y0);
    }
  else
    {
      g_object_get (ui->config,
                    "crop-x", &crop[0], "crop-y", &crop[1],
                    "crop-width", &crop[2], "crop-height", &crop[3], NULL);
    }
}

static void
draw_preview (PreviewUI *ui)
{
  GimpPreviewArea *area = GIMP_PREVIEW_AREA (ui->area);
  RawSettings      s;
  gint             ox, oy, w, h;
  gsize            n, i;
  guchar          *disp;

  gimp_preview_area_fill (area, 0, 0, ui->view_w, ui->view_h, 128, 128, 128);

  if (! ui->after.rgb)
    return;

  preview_origin (ui, &ox, &oy);
  w    = ui->after.w;
  h    = ui->after.h;
  n    = (gsize) w * h;
  disp = g_memdup2 (ui->after.rgb, n * 3);

  /* split view: left half before, right half after */
  if (compare_on (ui) && ui->before.rgb && ui->before.w == w && ui->before.h == h)
    {
      gint y;

      for (y = 0; y < h; y++)
        memcpy (disp + (gsize) y * w * 3, ui->before.rgb + (gsize) y * w * 3,
                (gsize) (w / 2) * 3);
    }

  if (gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->clip_toggle)))
    {
      /* clipping warning: red = a channel at white, blue = all near black */
      for (i = 0; i < n; i++)
        {
          guchar *p = disp + i * 3;

          if (p[0] == 255 || p[1] == 255 || p[2] == 255)
            { p[0] = 255; p[1] = 0; p[2] = 0; }
          else if (p[0] <= 2 && p[1] <= 2 && p[2] <= 2)
            { p[0] = 0; p[1] = 64; p[2] = 255; }
        }
    }

  /* crop tool: the whole straightened image, outside the crop darkened */
  if (ui->shown_geometry && ui->shown_uncropped)
    {
      gdouble crop[4];
      gint    x0, y0, x1, y1, x, y;

      current_crop (ui, crop);
      x0 = (gint) (crop[0] * w);
      y0 = (gint) (crop[1] * h);
      x1 = (gint) ((crop[0] + crop[2]) * w);
      y1 = (gint) ((crop[1] + crop[3]) * h);

      for (y = 0; y < h; y++)
        for (x = 0; x < w; x++)
          if (x < x0 || x >= x1 || y < y0 || y >= y1)
            {
              guchar *p = disp + ((gsize) y * w + x) * 3;

              p[0] /= 3; p[1] /= 3; p[2] /= 3;
            }

      gimp_preview_area_draw (area, ox, oy, w, h, GIMP_RGB_IMAGE, disp, w * 3);

      /* rule of thirds inside the crop */
      for (i = 1; i < 3; i++)
        {
          gint gx = x0 + (gint) ((x1 - x0) * i / 3);
          gint gy = y0 + (gint) ((y1 - y0) * i / 3);

          gimp_preview_area_fill (area, ox + gx, oy + y0, 1, y1 - y0, 200, 200, 200);
          gimp_preview_area_fill (area, ox + x0, oy + gy, x1 - x0, 1, 200, 200, 200);
        }
      gimp_preview_area_fill (area, ox + x0, oy + y0, x1 - x0, 1, 255, 255, 255);
      gimp_preview_area_fill (area, ox + x0, oy + y1 - 1, x1 - x0, 1, 255, 255, 255);
      gimp_preview_area_fill (area, ox + x0, oy + y0, 1, y1 - y0, 255, 255, 255);
      gimp_preview_area_fill (area, ox + x1 - 1, oy + y0, 1, y1 - y0, 255, 255, 255);
    }
  else
    {
      gimp_preview_area_draw (area, ox, oy, w, h, GIMP_RGB_IMAGE, disp, w * 3);
    }

  g_free (disp);

  if (compare_on (ui) && ui->before.rgb && ui->before.w == w && ui->before.h == h)
    gimp_preview_area_fill (area, ox + w / 2, oy, 1, h, 255, 255, 255);

  raw_settings_from_config (&s, ui->config);
  if (s.wb_mode == WB_SPOT && ! ui->loupe_active)
    {
      gint x0, y0, x1, y1;

      source_to_preview (ui, s.spot[0], s.spot[1], &x0, &y0);
      source_to_preview (ui, s.spot[0] + s.spot[2], s.spot[1] + s.spot[3], &x1, &y1);
      if (x1 < x0) { gint t = x0; x0 = x1; x1 = t; }
      if (y1 < y0) { gint t = y0; y0 = y1; y1 = t; }
      x1 = MAX (x1, x0 + 3);
      y1 = MAX (y1, y0 + 3);

      gimp_preview_area_fill (area, x0, y0, x1 - x0, 1, 255, 255, 0);
      gimp_preview_area_fill (area, x0, y1 - 1, x1 - x0, 1, 255, 255, 0);
      gimp_preview_area_fill (area, x0, y0, 1, y1 - y0, 255, 255, 0);
      gimp_preview_area_fill (area, x1 - 1, y0, 1, y1 - y0, 255, 255, 0);
    }
}

/* --- histogram ----------------------------------------------------------- */

static void
histogram_update (PreviewUI *ui)
{
  gsize   n = (gsize) ui->after.w * ui->after.h, i;
  guint64 hi = 0, lo = 0;
  gchar  *text;

  memset (ui->hist, 0, sizeof ui->hist);
  ui->hist_valid = ui->after.rgb && n > 0;
  if (! ui->hist_valid)
    return;

  for (i = 0; i < n; i++)
    {
      const guchar *p = ui->after.rgb + i * 3;

      ui->hist[0][p[0]]++;
      ui->hist[1][p[1]]++;
      ui->hist[2][p[2]]++;
      if (p[0] == 255 || p[1] == 255 || p[2] == 255)
        hi++;
      else if (p[0] <= 2 && p[1] <= 2 && p[2] <= 2)
        lo++;
    }

  text = g_strdup_printf (_("Clipped: %.1f%% highlights, %.1f%% shadows"),
                          100.0 * hi / n, 100.0 * lo / n);
  gtk_label_set_text (GTK_LABEL (ui->hist_label), text);
  g_free (text);

  gtk_widget_queue_draw (ui->histogram);
}

static gboolean
histogram_draw (GtkWidget *widget,
                cairo_t   *cr,
                PreviewUI *ui)
{
  gint    w = gtk_widget_get_allocated_width (widget);
  gint    h = gtk_widget_get_allocated_height (widget);
  gdouble peak = 1.0;
  gint    c, i;

  cairo_set_source_rgb (cr, 0.13, 0.13, 0.13);
  cairo_paint (cr);

  if (! ui->hist_valid)
    return TRUE;

  /* scale to the highest inner bin: the end bins hold the clipped pixels */
  for (c = 0; c < 3; c++)
    for (i = 1; i < 255; i++)
      peak = MAX (peak, ui->hist[c][i]);

  cairo_set_operator (cr, CAIRO_OPERATOR_ADD);
  for (c = 0; c < 3; c++)
    {
      cairo_set_source_rgba (cr, c == 0 ? 0.85 : 0.1, c == 1 ? 0.75 : 0.1,
                             c == 2 ? 0.95 : 0.1, 0.9);
      cairo_move_to (cr, 0, h);
      for (i = 0; i < 256; i++)
        {
          /* square root: keeps small counts visible */
          gdouble v = sqrt (MIN (1.0, ui->hist[c][i] / peak));

          cairo_line_to (cr, (i + 0.5) * w / 256.0, h - v * (h - 2));
        }
      cairo_line_to (cr, w, h);
      cairo_close_path (cr);
      cairo_fill (cr);
    }

  return TRUE;
}

static void
area_size_allocate (GtkWidget     *widget,
                    GtkAllocation *alloc,
                    PreviewUI     *ui)
{
  gint w = CLAMP (alloc->width,  PREVIEW_W / 2, PREVIEW_MAX);
  gint h = CLAMP (alloc->height, PREVIEW_H / 2, PREVIEW_MAX);

  /* a new size needs a preview developed for it */
  if (ABS (w - ui->view_w) > 8 || ABS (h - ui->view_h) > 8)
    {
      ui->view_w = w;
      ui->view_h = h;
      schedule_render (ui, 200);
    }

  /* the area's buffer was reallocated: show the old preview meanwhile */
  draw_preview (ui);
}

static void
update_status (PreviewUI      *ui,
               const RawImage *img,
               gint            ms)
{
  GString *msg = g_string_new (img->camera);

  if (img->lens)
    g_string_append_printf (msg, img->lens_known ? _(", %s (lensfun ✓)")
                                                  : _(", %s (not in lensfun)"),
                            img->lens);

  if (img->profile)
    g_string_append_printf (msg, _(", profile %s"), img->profile);

  g_string_append_printf (msg, _(" — %d ms"), ms);
  if (ui->loupe_active)
    g_string_append (msg, _(" — 100% (click to return)"));
  else if (gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->loupe_toggle)))
    g_string_append (msg, _(" — click a spot to see it at 100%"));
  if (compare_on (ui))
    g_string_append (msg, gtk_combo_box_get_active (GTK_COMBO_BOX (ui->compare_with)) == 1 ?
                          _(" — left: snapshot, right: your settings") :
                          _(" — left: default, right: your settings"));

  gtk_label_set_text (GTK_LABEL (ui->status), msg->str);
  g_string_free (msg, TRUE);
}

static void
render_done (GObject      *source,
             GAsyncResult *result,
             gpointer      data)
{
  PreviewUI *ui  = data;
  RenderJob *job = g_task_get_task_data (G_TASK (result));

  ui->busy = FALSE;

  if (ui->closing)
    return;

  if (job->full_w > 0)
    {
      ui->full_w = job->full_w;
      ui->full_h = job->full_h;
    }

  if (job->image)
    {
      shot_from_image (&ui->after, job->image, job->settings.color_space);
      ui->shown           = job->settings;
      ui->shown_geometry  = ! job->loupe;
      ui->shown_uncropped = job->crop_tool;
      histogram_update (ui);

      if (job->before)
        {
          shot_from_image (&ui->before, job->before, job->settings.color_space);
          g_free (ui->before_key);
          ui->before_key = g_strdup (job->before_key);
        }

      update_status (ui, job->image, (gint) (job->usecs / 1000));
    }
  else if (job->error)
    {
      gtk_label_set_text (GTK_LABEL (ui->status), job->error);
    }

  draw_preview (ui);

  if (ui->pending)
    {
      ui->pending = FALSE;
      render_start (ui);
    }
}

static void
render_start (PreviewUI *ui)
{
  GTask     *task;
  RenderJob *job;

  if (ui->busy)
    {
      ui->pending = TRUE;
      return;
    }

  job = g_new0 (RenderJob, 1);
  raw_settings_from_config (&job->settings, ui->config);

  job->box_w     = ui->view_w;
  job->box_h     = ui->view_h;
  job->loupe     = ui->loupe_active;
  job->crop_tool = gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->crop_toggle));
  if (job->loupe)
    loupe_region (ui->loupe_cx, ui->loupe_cy, ui->full_w, ui->full_h,
                  ui->view_w, ui->view_h, job->region);

  /* "before" only changes with the view and the geometry */
  job->before_key = g_strdup_printf ("%d %.4f %.4f %d %d %d %d %.3f %.4f %.4f %.4f %.4f %dx%d",
                                     job->loupe,
                                     job->loupe ? job->region[0] : 0.0,
                                     job->loupe ? job->region[1] : 0.0,
                                     job->settings.auto_rotate,
                                     job->settings.camera_crop,
                                     job->settings.color_space,
                                     job->crop_tool,
                                     job->settings.straighten,
                                     job->settings.crop[0], job->settings.crop[1],
                                     job->settings.crop[2], job->settings.crop[3],
                                     job->box_w, job->box_h);
  job->use_snapshot = ui->have_snapshot &&
                      gtk_combo_box_get_active (GTK_COMBO_BOX (ui->compare_with)) == 1;
  if (job->use_snapshot)
    {
      gchar *key = g_strdup_printf ("%s snap%d", job->before_key, ui->snapshot_serial);

      job->snapshot = ui->snapshot;
      g_free (job->before_key);
      job->before_key = key;
    }
  job->want_before = compare_on (ui) &&
                     (! ui->before.rgb || g_strcmp0 (ui->before_key, job->before_key));

  ui->busy = TRUE;
  gtk_label_set_text (GTK_LABEL (ui->status),
                      job->loupe ? _("Developing the 100% view…") : _("Developing preview…"));

  task = g_task_new (NULL, NULL, render_done, ui);
  g_object_set_data (G_OBJECT (task), "ui", ui);
  g_task_set_task_data (task, job, (GDestroyNotify) render_job_free);
  g_task_run_in_thread (task, render_thread);
  g_object_unref (task);
}

static gboolean
render_timeout (gpointer data)
{
  PreviewUI *ui = data;

  ui->timeout_id = 0;
  render_start (ui);

  return G_SOURCE_REMOVE;
}

static void
schedule_render (PreviewUI *ui,
                 guint      delay)
{
  if (ui->timeout_id)
    g_source_remove (ui->timeout_id);

  ui->timeout_id = g_timeout_add (delay, render_timeout, ui);
}

static void
config_changed (GObject    *config,
                GParamSpec *pspec,
                PreviewUI  *ui)
{
  /* properties that never change the preview */
  if (! strcmp (pspec->name, "ask-dialog")     ||
      ! strcmp (pspec->name, "redevelop-mode") ||
      ! strcmp (pspec->name, "preset")         ||
      ! strcmp (pspec->name, "depth")          ||
      ! strcmp (pspec->name, "half-size")      ||
      ! strcmp (pspec->name, "linear"))
    return;

  /* the crop tool shows the whole canvas: a new crop only redraws */
  if (g_str_has_prefix (pspec->name, "crop-") &&
      gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->crop_toggle)))
    {
      draw_preview (ui);
      return;
    }

  /* only visible at 100% */
  if (! ui->loupe_active &&
      (! strcmp (pspec->name, "demosaic") || ! strcmp (pspec->name, "median-passes")))
    return;

  schedule_render (ui, 250);
}

static void
view_toggled (GtkToggleButton *button,
              PreviewUI       *ui)
{
  if (GTK_WIDGET (button) == ui->loupe_toggle && ! gtk_toggle_button_get_active (button))
    ui->loupe_active = FALSE;

  schedule_render (ui, 10);
}

static gboolean
area_clicked (GtkWidget      *widget,
              GdkEventButton *event,
              PreviewUI      *ui)
{
  gdouble fx, fy;

  if (event->button != 1 || ! ui->after.rgb)
    return FALSE;

  /* in the 100% view a click goes back to the whole image */
  if (ui->loupe_active)
    {
      ui->loupe_active = FALSE;
      schedule_render (ui, 10);
      return TRUE;
    }

  fx = (event->x - (ui->view_w - ui->after.w) / 2) / ui->after.w;
  fy = (event->y - (ui->view_h - ui->after.h) / 2) / ui->after.h;

  if (fx < 0 || fy < 0 || fx > 1 || fy > 1)
    return FALSE;

  /* crop tool: start a new rectangle (fractions of the whole canvas) */
  if (ui->shown_geometry && ui->shown_uncropped)
    {
      ui->dragging = TRUE;
      ui->drag_x0  = ui->drag_x1 = fx;
      ui->drag_y0  = ui->drag_y1 = fy;
      return TRUE;
    }

  /* the preview may be straightened and cropped: positions are stored in
   * the coordinates of the image before that
   */
  if (ui->shown_geometry && ui->full_w > 0)
    {
      gdouble sx, sy;

      rawheic_geometry_to_source (&ui->shown, ui->full_w, ui->full_h, FALSE,
                                  fx, fy, &sx, &sy);
      fx = CLAMP (sx, 0.0, 1.0);
      fy = CLAMP (sy, 0.0, 1.0);
    }

  if (gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->loupe_toggle)))
    {
      ui->loupe_active = TRUE;
      ui->loupe_cx     = fx;
      ui->loupe_cy     = fy;
      schedule_render (ui, 10);
      return TRUE;
    }

  g_object_set (ui->config,
                "spot-x",      CLAMP (fx - SPOT_SIZE / 2, 0.0, 1.0 - SPOT_SIZE),
                "spot-y",      CLAMP (fy - SPOT_SIZE / 2, 0.0, 1.0 - SPOT_SIZE),
                "spot-width",  SPOT_SIZE,
                "spot-height", SPOT_SIZE,
                "wb-mode",     "spot",
                NULL);

  return TRUE;
}

static void
drag_update (PreviewUI *ui,
             gdouble    x,
             gdouble    y)
{
  ui->drag_x1 = CLAMP ((x - (ui->view_w - ui->after.w) / 2) / MAX (1, ui->after.w), 0.0, 1.0);
  ui->drag_y1 = CLAMP ((y - (ui->view_h - ui->after.h) / 2) / MAX (1, ui->after.h), 0.0, 1.0);
}

static gboolean
area_motion (GtkWidget      *widget,
             GdkEventMotion *event,
             PreviewUI      *ui)
{
  if (! ui->dragging)
    return FALSE;

  drag_update (ui, event->x, event->y);
  draw_preview (ui);

  return TRUE;
}

static gboolean
area_released (GtkWidget      *widget,
               GdkEventButton *event,
               PreviewUI      *ui)
{
  gdouble crop[4];

  if (event->button != 1 || ! ui->dragging)
    return FALSE;

  drag_update (ui, event->x, event->y);
  current_crop (ui, crop);
  ui->dragging = FALSE;

  /* a click without dragging resets the crop */
  if (crop[2] < 0.02 || crop[3] < 0.02)
    {
      crop[0] = crop[1] = 0.0;
      crop[2] = crop[3] = 1.0;
    }

  g_object_set (ui->config,
                "crop-width",  crop[2], "crop-height", crop[3],
                "crop-x",      crop[0], "crop-y",      crop[1], NULL);
  draw_preview (ui);

  return TRUE;
}

/* Remember the current settings as the "before" of the comparison. */
static void
snapshot_clicked (GtkButton *button,
                  PreviewUI *ui)
{
  raw_settings_from_config (&ui->snapshot, ui->config);
  ui->have_snapshot = TRUE;
  ui->snapshot_serial++;

  gtk_widget_set_sensitive (ui->compare_with, TRUE);
  gtk_combo_box_set_active (GTK_COMBO_BOX (ui->compare_with), 1);
  if (! compare_on (ui))
    gtk_toggle_button_set_active (GTK_TOGGLE_BUTTON (ui->compare_toggle), TRUE);
  else
    schedule_render (ui, 10);
}

static void
compare_with_changed (GtkComboBox *combo,
                      PreviewUI   *ui)
{
  if (compare_on (ui))
    schedule_render (ui, 10);
}

static void
xmp_save_clicked (GtkButton *button,
                  PreviewUI *ui)
{
  RawSettings s;
  GError     *error = NULL;

  raw_settings_from_config (&s, ui->config);
  if (rawheic_xmp_write (ui->path, &s, &error))
    {
      gchar *target = rawheic_xmp_target (ui->path);
      gchar *base   = g_path_get_basename (target);
      gchar *msg    = g_strdup_printf (_("Settings saved to %s"), base);

      gtk_label_set_text (GTK_LABEL (ui->status), msg);
      g_free (msg);
      g_free (base);
      g_free (target);
    }
  else
    {
      gimp_message (error->message);
      g_error_free (error);
    }
}

static void
crop_reset_clicked (GtkButton *button,
                    PreviewUI *ui)
{
  g_object_set (ui->config, "straighten", 0.0,
                "crop-x", 0.0, "crop-y", 0.0,
                "crop-width", 1.0, "crop-height", 1.0, NULL);
}

/* @property is sensitive only while @choice_property is one of the
 * NULL-terminated nicks.
 */
static void
set_sensitive_if (GimpProcedureDialog *dialog,
                  const gchar         *property,
                  const gchar         *choice_property,
                  ...)
{
  GimpValueArray *values = gimp_value_array_new (1);
  const gchar    *nick;
  va_list         args;

  va_start (args, choice_property);
  while ((nick = va_arg (args, const gchar *)))
    {
      GValue v = G_VALUE_INIT;

      g_value_init (&v, G_TYPE_STRING);
      g_value_set_string (&v, nick);
      gimp_value_array_append (values, &v);
      g_value_unset (&v);
    }
  va_end (args);

  gimp_procedure_dialog_set_sensitive_if_in (dialog, property, NULL,
                                             choice_property, values, TRUE);
}


/* --- presets ------------------------------------------------------------ */

typedef struct
{
  GimpProcedureConfig *config;
  GtkWidget           *combo;
  GtkWidget           *delete_button;
  gboolean             filling;
} PresetUI;

static void
presets_fill (PresetUI    *pui,
              const gchar *select)
{
  GList *names = raw_presets_list ();
  GList *l;
  gint   i = 1, active = 0;

  pui->filling = TRUE;
  gtk_combo_box_text_remove_all (GTK_COMBO_BOX_TEXT (pui->combo));
  gtk_combo_box_text_append_text (GTK_COMBO_BOX_TEXT (pui->combo), _("Presets…"));

  for (l = names; l; l = l->next, i++)
    {
      gtk_combo_box_text_append_text (GTK_COMBO_BOX_TEXT (pui->combo), l->data);
      if (select && ! g_strcmp0 (select, l->data))
        active = i;
    }

  gtk_combo_box_set_active (GTK_COMBO_BOX (pui->combo), active);
  gtk_widget_set_sensitive (pui->delete_button,
                            select && active > 0 && ! raw_presets_is_builtin (select));
  pui->filling = FALSE;

  g_list_free_full (names, g_free);
}

static void
preset_selected (GtkComboBox *combo,
                 PresetUI    *pui)
{
  gchar       *name;
  RawSettings  s;

  if (pui->filling || gtk_combo_box_get_active (combo) <= 0)
    {
      gtk_widget_set_sensitive (pui->delete_button, FALSE);
      return;
    }

  name = gtk_combo_box_text_get_active_text (GTK_COMBO_BOX_TEXT (combo));
  raw_settings_from_config (&s, pui->config);
  if (raw_presets_load (name, &s))
    raw_settings_to_config (&s, pui->config);

  gtk_widget_set_sensitive (pui->delete_button, ! raw_presets_is_builtin (name));
  g_free (name);
}

static void
preset_save_clicked (GtkButton *button,
                     PresetUI  *pui)
{
  GtkWidget *dialog, *entry, *box;
  gchar     *current;

  dialog = gtk_dialog_new_with_buttons (_("Save preset"),
                                        GTK_WINDOW (gtk_widget_get_toplevel (GTK_WIDGET (button))),
                                        GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT,
                                        _("_Cancel"), GTK_RESPONSE_CANCEL,
                                        _("_Save"),   GTK_RESPONSE_OK,
                                        NULL);
  gtk_dialog_set_default_response (GTK_DIALOG (dialog), GTK_RESPONSE_OK);

  box = gtk_dialog_get_content_area (GTK_DIALOG (dialog));
  gtk_container_set_border_width (GTK_CONTAINER (box), 12);
  gtk_box_pack_start (GTK_BOX (box), gtk_label_new (_("Preset name:")), FALSE, FALSE, 0);

  entry = gtk_entry_new ();
  gtk_entry_set_max_length (GTK_ENTRY (entry), 64);
  gtk_entry_set_activates_default (GTK_ENTRY (entry), TRUE);
  current = gtk_combo_box_text_get_active_text (GTK_COMBO_BOX_TEXT (pui->combo));
  if (current && gtk_combo_box_get_active (GTK_COMBO_BOX (pui->combo)) > 0 &&
      ! raw_presets_is_builtin (current))
    gtk_entry_set_text (GTK_ENTRY (entry), current);
  g_free (current);
  gtk_box_pack_start (GTK_BOX (box), entry, FALSE, FALSE, 6);
  gtk_widget_show_all (box);

  while (gtk_dialog_run (GTK_DIALOG (dialog)) == GTK_RESPONSE_OK)
    {
      const gchar *name = gtk_entry_get_text (GTK_ENTRY (entry));
      RawSettings  s;
      GError      *error = NULL;

      raw_settings_from_config (&s, pui->config);
      if (raw_presets_save (name, &s, &error))
        {
          presets_fill (pui, name);
          break;
        }

      gimp_message (error->message);
      g_error_free (error);
    }

  gtk_widget_destroy (dialog);
}

static void
preset_delete_clicked (GtkButton *button,
                       PresetUI  *pui)
{
  gchar     *name = gtk_combo_box_text_get_active_text (GTK_COMBO_BOX_TEXT (pui->combo));
  GtkWidget *ask;

  if (! name || raw_presets_is_builtin (name))
    {
      g_free (name);
      return;
    }

  ask = gtk_message_dialog_new (GTK_WINDOW (gtk_widget_get_toplevel (GTK_WIDGET (button))),
                                GTK_DIALOG_MODAL, GTK_MESSAGE_QUESTION, GTK_BUTTONS_YES_NO,
                                _("Delete the preset '%s'?"), name);
  if (gtk_dialog_run (GTK_DIALOG (ask)) == GTK_RESPONSE_YES)
    {
      raw_presets_delete (name);
      presets_fill (pui, NULL);
    }
  gtk_widget_destroy (ask);
  g_free (name);
}

static GtkWidget *
presets_row (PresetUI *pui)
{
  GtkWidget *row  = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 6);
  GtkWidget *save = gtk_button_new_with_mnemonic (_("Save as…"));

  pui->combo         = gtk_combo_box_text_new ();
  pui->delete_button = gtk_button_new_with_mnemonic (_("Delete"));

  gtk_widget_set_tooltip_text (pui->combo,
                               _("Apply a saved set of development settings"));
  gtk_box_pack_start (GTK_BOX (row), pui->combo, TRUE, TRUE, 0);
  gtk_box_pack_start (GTK_BOX (row), save, FALSE, FALSE, 0);
  gtk_box_pack_start (GTK_BOX (row), pui->delete_button, FALSE, FALSE, 0);

  g_signal_connect (pui->combo, "changed", G_CALLBACK (preset_selected), pui);
  g_signal_connect (save, "clicked", G_CALLBACK (preset_save_clicked), pui);
  g_signal_connect (pui->delete_button, "clicked", G_CALLBACK (preset_delete_clicked), pui);

  presets_fill (pui, NULL);

  return row;
}

gboolean
raw_dialog_run (GimpProcedure       *procedure,
                GimpProcedureConfig *config,
                const gchar         *path,
                const gchar         *title)
{
  GimpProcedureDialog *dialog;
  PreviewUI            ui = { 0 };
  PresetUI             pui = { 0 };
  GtkWidget           *hbox, *vbox, *frame, *right;
  gboolean             run;
  gulong               handler;

  gimp_ui_init (PLUGIN_NAME);

  ui.config = config;
  ui.path   = g_strdup (path);

  dialog = GIMP_PROCEDURE_DIALOG (gimp_procedure_dialog_new (procedure, config, title));
  gimp_procedure_dialog_set_ok_label (dialog, _("_Develop"));

  /* settings pages */
  gimp_procedure_dialog_get_label (dialog, "wb-label",  _("White balance"), FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "exp-label", _("Exposure"),      FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "det-label", _("Detail"),        FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "out-label", _("Output"),        FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "lens-label", _("Lens"),         FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "col-label", _("Colour"),        FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "geo-label", _("Geometry"),      FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "geo-hint",
                                   _("Turn on \"Crop\" under the preview and drag a "
                                     "rectangle. Straightening enlarges the image so "
                                     "that no empty corners appear."),
                                   FALSE, FALSE);
  gimp_procedure_dialog_get_label (dialog, "lens-hint",
                                   rawheic_lens_db_available () ?
                                   _("Corrections come from the lensfun database; the "
                                     "detected lens is shown under the preview.") :
                                   _("The lensfun database was not found: lens "
                                     "corrections are unavailable."),
                                   FALSE, FALSE);

  gimp_procedure_dialog_get_label (dialog, "wb-hint",
                                   _("Tip: click the preview to pick a neutral (grey) area."),
                                   FALSE, FALSE);

  gimp_procedure_dialog_fill_box (dialog, "wb-box",
                                  "wb-mode", "wb-temperature", "wb-tint",
                                  "wb-mul-red", "wb-mul-blue", "wb-hint", NULL);
  gimp_procedure_dialog_fill_box (dialog, "exp-box",
                                  "exposure", "exposure-preserve", "highlight",
                                  "rebuild-level", "highlight-compensate",
                                  "brightness", "auto-bright", "tone-curve", NULL);
  gimp_procedure_dialog_fill_box (dialog, "det-box",
                                  "demosaic", "denoise", "fbdd", "ca-red", "ca-blue",
                                  "hot-pixels", "median-passes", NULL);
  gimp_procedure_dialog_fill_box (dialog, "out-box",
                                  "color-space", "linear", "depth", "half-size",
                                  "auto-rotate", "camera-crop", NULL);

  gimp_procedure_dialog_fill_box (dialog, "lens-box",
                                  "lens-vignetting", "lens-distortion", "lens-tca",
                                  "lens-hint", NULL);

  gimp_procedure_dialog_fill_box (dialog, "col-box",
                                  "camera-profile", "camera-profile-look",
                                  "auto-profile", "profile-folder", NULL);

  {
    GtkWidget *geo   = gimp_procedure_dialog_fill_box (dialog, "geo-box",
                                                       "straighten", "crop-x", "crop-y",
                                                       "crop-width", "crop-height",
                                                       "geo-hint", NULL);
    GtkWidget *reset = gtk_button_new_with_mnemonic (_("_Reset geometry"));

    gtk_widget_set_halign (reset, GTK_ALIGN_START);
    g_signal_connect (reset, "clicked", G_CALLBACK (crop_reset_clicked), &ui);
    gtk_box_pack_start (GTK_BOX (geo), reset, FALSE, FALSE, 0);
    gtk_widget_show (reset);
  }

  gimp_procedure_dialog_fill_notebook (dialog, "settings",
                                       "wb-label",   "wb-box",
                                       "exp-label",  "exp-box",
                                       "det-label",  "det-box",
                                       "lens-label", "lens-box",
                                       "col-label",  "col-box",
                                       "geo-label",  "geo-box",
                                       "out-label",  "out-box",
                                       NULL);

  set_sensitive_if (dialog, "wb-temperature", "wb-mode", "manual", NULL);
  set_sensitive_if (dialog, "wb-tint",        "wb-mode", "manual", NULL);
  set_sensitive_if (dialog, "wb-mul-red",     "wb-mode", "multipliers", NULL);
  set_sensitive_if (dialog, "wb-mul-blue",    "wb-mode", "multipliers", NULL);
  set_sensitive_if (dialog, "rebuild-level",  "highlight", "rebuild", NULL);
  set_sensitive_if (dialog, "highlight-compensate", "highlight",
                    "unclip", "blend", "rebuild", NULL);

  if (g_object_class_find_property (G_OBJECT_GET_CLASS (config), "ask-dialog"))
    right = gimp_procedure_dialog_fill_box (dialog, "right", "settings", "ask-dialog", NULL);
  else if (g_object_class_find_property (G_OBJECT_GET_CLASS (config), "redevelop-mode"))
    {
      const gchar *fixed[] = { "color-space", "linear", "depth", NULL };
      gint         i;

      right = gimp_procedure_dialog_fill_box (dialog, "right", "settings", "redevelop-mode", NULL);

      /* developing again writes into the existing image: its colour
       * space and precision do not change
       */
      for (i = 0; fixed[i]; i++)
        {
          GtkWidget *w = gimp_procedure_dialog_get_widget (dialog, fixed[i], G_TYPE_NONE);

          if (w)
            {
              gtk_widget_set_sensitive (w, FALSE);
              gtk_widget_set_tooltip_text (w, _("Kept from the image; use Image > Precision "
                                                "or Image > Color Management to change it."));
            }
        }
    }
  else
    right = gimp_procedure_dialog_fill_box (dialog, "right", "settings", NULL);

  /* preview */
  hbox = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 12);
  gtk_container_set_border_width (GTK_CONTAINER (hbox), 12);
  gtk_box_pack_start (GTK_BOX (gtk_dialog_get_content_area (GTK_DIALOG (dialog))),
                      hbox, TRUE, TRUE, 0);

  vbox = gtk_box_new (GTK_ORIENTATION_VERTICAL, 6);
  gtk_box_pack_start (GTK_BOX (hbox), vbox, TRUE, TRUE, 0);

  frame = gtk_frame_new (NULL);
  gtk_frame_set_shadow_type (GTK_FRAME (frame), GTK_SHADOW_IN);
  gtk_box_pack_start (GTK_BOX (vbox), frame, TRUE, TRUE, 0);

  /* the preview grows with the dialog; it is developed for its size */
  ui.view_w = PREVIEW_W;
  ui.view_h = PREVIEW_H;
  ui.area   = gimp_preview_area_new ();
  gimp_preview_area_set_max_size (GIMP_PREVIEW_AREA (ui.area), PREVIEW_MAX, PREVIEW_MAX);
  gtk_widget_set_size_request (ui.area, PREVIEW_W / 2, PREVIEW_H / 2);
  gtk_widget_add_events (ui.area, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK |
                                  GDK_BUTTON1_MOTION_MASK);
  g_signal_connect (ui.area, "button-press-event", G_CALLBACK (area_clicked), &ui);
  g_signal_connect (ui.area, "motion-notify-event", G_CALLBACK (area_motion), &ui);
  g_signal_connect (ui.area, "button-release-event", G_CALLBACK (area_released), &ui);
  g_signal_connect (ui.area, "size-allocate", G_CALLBACK (area_size_allocate), &ui);
  g_signal_connect_swapped (ui.area, "realize", G_CALLBACK (draw_preview), &ui);
  gtk_container_add (GTK_CONTAINER (frame), ui.area);

  {
    GtkWidget *tools = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 6);

    /* xgettext:no-c-format */
    ui.loupe_toggle   = gtk_toggle_button_new_with_label (_("100% loupe"));
    ui.compare_toggle = gtk_toggle_button_new_with_label (_("Before / after"));
    gtk_widget_set_tooltip_text (ui.loupe_toggle,
                                 _("When on, click the preview to see that spot at full "
                                   "resolution (noise, sharpness, demosaicing)"));
    gtk_widget_set_tooltip_text (ui.compare_toggle,
                                 _("Split view: left half with default settings, right "
                                   "half with your settings"));
    ui.crop_toggle = gtk_toggle_button_new_with_label (_("Crop"));
    gtk_widget_set_tooltip_text (ui.crop_toggle,
                                 _("Drag a rectangle on the preview to crop; a click "
                                   "without dragging removes the crop"));
    g_signal_connect (ui.crop_toggle, "toggled", G_CALLBACK (view_toggled), &ui);
    ui.clip_toggle = gtk_toggle_button_new_with_label (_("Clipping"));
    gtk_widget_set_tooltip_text (ui.clip_toggle,
                                 _("Show clipped highlights in red and crushed shadows "
                                   "in blue"));
    gtk_box_pack_start (GTK_BOX (tools), ui.loupe_toggle, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (tools), ui.compare_toggle, FALSE, FALSE, 0);

    ui.compare_with = gtk_combo_box_text_new ();
    gtk_combo_box_text_append_text (GTK_COMBO_BOX_TEXT (ui.compare_with), _("with defaults"));
    gtk_combo_box_text_append_text (GTK_COMBO_BOX_TEXT (ui.compare_with), _("with snapshot"));
    gtk_combo_box_set_active (GTK_COMBO_BOX (ui.compare_with), 0);
    gtk_widget_set_sensitive (ui.compare_with, FALSE);
    gtk_widget_set_tooltip_text (ui.compare_with,
                                 _("What the left half of the comparison shows"));
    g_signal_connect (ui.compare_with, "changed", G_CALLBACK (compare_with_changed), &ui);
    gtk_box_pack_start (GTK_BOX (tools), ui.compare_with, FALSE, FALSE, 0);

    ui.snapshot_button = gtk_button_new_with_label (_("Snapshot"));
    gtk_widget_set_tooltip_text (ui.snapshot_button,
                                 _("Remember the current settings and compare later "
                                   "changes with them"));
    g_signal_connect (ui.snapshot_button, "clicked", G_CALLBACK (snapshot_clicked), &ui);
    gtk_box_pack_start (GTK_BOX (tools), ui.snapshot_button, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (tools), ui.crop_toggle, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (tools), ui.clip_toggle, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (vbox), tools, FALSE, FALSE, 0);
    g_signal_connect (ui.loupe_toggle, "toggled", G_CALLBACK (view_toggled), &ui);
    g_signal_connect (ui.compare_toggle, "toggled", G_CALLBACK (view_toggled), &ui);
    g_signal_connect_swapped (ui.clip_toggle, "toggled", G_CALLBACK (draw_preview), &ui);
  }

  ui.status = gtk_label_new ("");
  gtk_label_set_xalign (GTK_LABEL (ui.status), 0.0);
  gtk_label_set_ellipsize (GTK_LABEL (ui.status), PANGO_ELLIPSIZE_END);
  gtk_box_pack_start (GTK_BOX (vbox), ui.status, FALSE, FALSE, 0);

  {
    GtkWidget *hrow = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 12);

    ui.histogram = gtk_drawing_area_new ();
    gtk_widget_set_size_request (ui.histogram, HIST_W, HIST_H);
    g_signal_connect (ui.histogram, "draw", G_CALLBACK (histogram_draw), &ui);
    ui.hist_label = gtk_label_new ("");
    gtk_label_set_xalign (GTK_LABEL (ui.hist_label), 0.0);
    gtk_label_set_line_wrap (GTK_LABEL (ui.hist_label), TRUE);
    gtk_box_pack_start (GTK_BOX (hrow), ui.histogram, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (hrow), ui.hist_label, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (vbox), hrow, FALSE, FALSE, 0);
  }

  pui.config = config;
  {
    GtkWidget *row = presets_row (&pui);

    gtk_box_pack_start (GTK_BOX (right), row, FALSE, FALSE, 0);
    gtk_box_reorder_child (GTK_BOX (right), row, 0);

    /* one photo (not a batch): its settings can go into its sidecar */
    if (g_object_class_find_property (G_OBJECT_GET_CLASS (config), "ask-dialog") ||
        g_object_class_find_property (G_OBJECT_GET_CLASS (config), "redevelop-mode"))
      {
        GtkWidget *xmp = gtk_button_new_with_mnemonic (_("Save to _XMP sidecar"));

        gtk_widget_set_tooltip_text (xmp,
                                     _("Write these settings to photo.xmp next to the RAW "
                                       "file (readable by Lightroom / Camera Raw and by "
                                       "this plug-in); another program's sidecar is never "
                                       "replaced"));
        gtk_widget_set_halign (xmp, GTK_ALIGN_START);
        g_signal_connect (xmp, "clicked", G_CALLBACK (xmp_save_clicked), &ui);
        gtk_box_pack_start (GTK_BOX (right), xmp, FALSE, FALSE, 0);
        gtk_box_reorder_child (GTK_BOX (right), xmp, 1);
      }
  }

  gtk_box_pack_start (GTK_BOX (hbox), right, FALSE, FALSE, 0);
  gtk_widget_show_all (hbox);
  gtk_window_set_default_size (GTK_WINDOW (dialog), 1200, 760);

  handler = g_signal_connect (config, "notify", G_CALLBACK (config_changed), &ui);
  render_start (&ui);

  run = gimp_procedure_dialog_run (dialog);

  g_signal_handler_disconnect (config, handler);
  if (ui.timeout_id)
    g_source_remove (ui.timeout_id);

  /* the worker thread uses the session: wait for it */
  ui.closing = TRUE;
  while (ui.busy)
    g_main_context_iteration (NULL, TRUE);

  gtk_widget_destroy (GTK_WIDGET (dialog));

  raw_session_free (ui.session);
  g_free (ui.after.rgb);
  g_free (ui.before.rgb);
  g_free (ui.before_key);
  g_free (ui.path);
  g_free (ui.open_error);

  return run;
}
