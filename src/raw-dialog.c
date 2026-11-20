/* gimp-raw-heic -- RAW import / re-develop dialog with live preview
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "config.h"

#include <string.h>

#include <libgimp/gimpui.h>

#include "rawheic.h"

#define PREVIEW_W     640
#define PREVIEW_H     480
#define PREVIEW_SIZE  640
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
  gchar       *error;
  gint64       usecs;
} RenderJob;


static void render_start (PreviewUI *ui);


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
                 RawSettings       *b)
{
  raw_settings_defaults (b);
  b->auto_rotate = s->auto_rotate;
  b->camera_crop = s->camera_crop;
  b->color_space = s->color_space;
  memcpy (b->spot, s->spot, sizeof b->spot);
}

static void
loupe_region (gdouble  cx,
              gdouble  cy,
              gint     full_w,
              gint     full_h,
              gdouble  region[4])
{
  gdouble w = full_w > 0 ? MIN (1.0, (gdouble) PREVIEW_W / full_w) : 1.0;
  gdouble h = full_h > 0 ? MIN (1.0, (gdouble) PREVIEW_H / full_h) : 1.0;

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
          RawImage *full = raw_session_develop (ui->session, &job->settings,
                                                PREVIEW_SIZE, NULL, NULL, NULL);
          raw_image_free (full);
          job->image = raw_session_develop_region (ui->session, &job->settings,
                                                   job->region, &error);
        }
      else
        {
          job->image = raw_session_develop (ui->session, &job->settings,
                                            PREVIEW_SIZE, NULL, NULL, &error);
        }

      if (job->image && job->want_before)
        {
          RawSettings b;

          before_settings (&job->settings, &b);
          job->before = job->loupe ?
                        raw_session_develop_region (ui->session, &b, job->region, NULL) :
                        raw_session_develop (ui->session, &b, PREVIEW_SIZE, NULL, NULL, NULL);
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
  babl_process (babl_fish (src, babl_format ("R'G'B' u8")), img->pixels, shot->rgb, n);
}

static gboolean
compare_on (PreviewUI *ui)
{
  return gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->compare_toggle));
}

static void
draw_preview (PreviewUI *ui)
{
  GimpPreviewArea *area = GIMP_PREVIEW_AREA (ui->area);
  RawSettings      s;
  gint             ox, oy;

  gimp_preview_area_fill (area, 0, 0, PREVIEW_W, PREVIEW_H, 128, 128, 128);

  if (! ui->after.rgb)
    return;

  ox = (PREVIEW_W - ui->after.w) / 2;
  oy = (PREVIEW_H - ui->after.h) / 2;

  gimp_preview_area_draw (area, ox, oy, ui->after.w, ui->after.h,
                          GIMP_RGB_IMAGE, ui->after.rgb, ui->after.w * 3);

  /* split view: left half before, right half after */
  if (compare_on (ui) && ui->before.rgb &&
      ui->before.w == ui->after.w && ui->before.h == ui->after.h)
    {
      gint half = ui->after.w / 2;

      gimp_preview_area_draw (area, ox, oy, half, ui->before.h,
                              GIMP_RGB_IMAGE, ui->before.rgb, ui->before.w * 3);
      gimp_preview_area_fill (area, ox + half, oy, 1, ui->after.h, 255, 255, 255);
    }

  raw_settings_from_config (&s, ui->config);
  if (s.wb_mode == WB_SPOT && ! ui->loupe_active)
    {
      gint x = ox + (gint) (s.spot[0] * ui->after.w);
      gint y = oy + (gint) (s.spot[1] * ui->after.h);
      gint w = MAX (3, (gint) (s.spot[2] * ui->after.w));
      gint h = MAX (3, (gint) (s.spot[3] * ui->after.h));

      gimp_preview_area_fill (area, x, y, w, 1, 255, 255, 0);
      gimp_preview_area_fill (area, x, y + h - 1, w, 1, 255, 255, 0);
      gimp_preview_area_fill (area, x, y, 1, h, 255, 255, 0);
      gimp_preview_area_fill (area, x + w - 1, y, 1, h, 255, 255, 0);
    }
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

  g_string_append_printf (msg, _(" — %d ms"), ms);
  if (ui->loupe_active)
    g_string_append (msg, _(" — 100% (click to return)"));
  else if (gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->loupe_toggle)))
    g_string_append (msg, _(" — click a spot to see it at 100%"));
  if (compare_on (ui))
    g_string_append (msg, _(" — left: default, right: your settings"));

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

  job->loupe = ui->loupe_active;
  if (job->loupe)
    loupe_region (ui->loupe_cx, ui->loupe_cy, ui->full_w, ui->full_h, job->region);

  /* "before" only changes with the view and the geometry */
  job->before_key = g_strdup_printf ("%d %.4f %.4f %d %d %d",
                                     job->loupe,
                                     job->loupe ? job->region[0] : 0.0,
                                     job->loupe ? job->region[1] : 0.0,
                                     job->settings.auto_rotate,
                                     job->settings.camera_crop,
                                     job->settings.color_space);
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

  fx = (event->x - (PREVIEW_W - ui->after.w) / 2) / ui->after.w;
  fy = (event->y - (PREVIEW_H - ui->after.h) / 2) / ui->after.h;

  if (fx < 0 || fy < 0 || fx > 1 || fy > 1)
    return FALSE;

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
                                  "brightness", "auto-bright", NULL);
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
                                  "camera-profile", "camera-profile-look", NULL);

  gimp_procedure_dialog_fill_notebook (dialog, "settings",
                                       "wb-label",   "wb-box",
                                       "exp-label",  "exp-box",
                                       "det-label",  "det-box",
                                       "lens-label", "lens-box",
                                       "col-label",  "col-box",
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
    right = gimp_procedure_dialog_fill_box (dialog, "right", "settings", "redevelop-mode", NULL);
  else
    right = gimp_procedure_dialog_fill_box (dialog, "right", "settings", NULL);

  /* preview */
  hbox = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 12);
  gtk_container_set_border_width (GTK_CONTAINER (hbox), 12);
  gtk_box_pack_start (GTK_BOX (gtk_dialog_get_content_area (GTK_DIALOG (dialog))),
                      hbox, TRUE, TRUE, 0);

  vbox = gtk_box_new (GTK_ORIENTATION_VERTICAL, 6);
  gtk_box_pack_start (GTK_BOX (hbox), vbox, FALSE, FALSE, 0);

  frame = gtk_frame_new (NULL);
  gtk_frame_set_shadow_type (GTK_FRAME (frame), GTK_SHADOW_IN);
  gtk_box_pack_start (GTK_BOX (vbox), frame, FALSE, FALSE, 0);

  ui.area = gimp_preview_area_new ();
  gtk_widget_set_size_request (ui.area, PREVIEW_W, PREVIEW_H);
  gtk_widget_add_events (ui.area, GDK_BUTTON_PRESS_MASK);
  g_signal_connect (ui.area, "button-press-event", G_CALLBACK (area_clicked), &ui);
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
    gtk_box_pack_start (GTK_BOX (tools), ui.loupe_toggle, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (tools), ui.compare_toggle, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (vbox), tools, FALSE, FALSE, 0);
    g_signal_connect (ui.loupe_toggle, "toggled", G_CALLBACK (view_toggled), &ui);
    g_signal_connect (ui.compare_toggle, "toggled", G_CALLBACK (view_toggled), &ui);
  }

  ui.status = gtk_label_new ("");
  gtk_label_set_xalign (GTK_LABEL (ui.status), 0.0);
  gtk_label_set_ellipsize (GTK_LABEL (ui.status), PANGO_ELLIPSIZE_END);
  gtk_box_pack_start (GTK_BOX (vbox), ui.status, FALSE, FALSE, 0);

  pui.config = config;
  {
    GtkWidget *row = presets_row (&pui);

    gtk_box_pack_start (GTK_BOX (right), row, FALSE, FALSE, 0);
    gtk_box_reorder_child (GTK_BOX (right), row, 0);
  }

  gtk_box_pack_start (GTK_BOX (hbox), right, TRUE, TRUE, 0);
  gtk_widget_show_all (hbox);

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
