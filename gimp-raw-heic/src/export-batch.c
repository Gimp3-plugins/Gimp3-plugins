/* gimp-raw-heic -- File > Export > Develop RAW files to a folder
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Develops a list of RAW files with one set of settings and exports each
 * one straight to a folder (TIFF / JPEG / PNG / AVIF / XCF), closing it
 * again, so hundreds of files never pile up as open images.  Every file
 * goes through GIMP's normal file loading (see raw_batch_session_*), so
 * metadata and colour handling are the same as File > Open.
 */

#include "config.h"

#include <string.h>

#include <libgimp/gimpui.h>

#include "rawheic.h"

enum
{
  FMT_TIFF16,
  FMT_JPEG,
  FMT_PNG16,
  FMT_AVIF,
  FMT_XCF
};

typedef struct
{
  const gchar *nick;
  gint         id;
  const gchar *label;
  const gchar *ext;
  const gchar *proc;
} Format;

static const Format formats[] =
{
  { "tiff16", FMT_TIFF16, N_("TIFF, 16-bit"),          "tif",  "file-tiff-export"     },
  { "jpeg",   FMT_JPEG,   N_("JPEG, 8-bit"),           "jpg",  "file-jpeg-export"     },
  { "png16",  FMT_PNG16,  N_("PNG, 16-bit"),           "png",  "file-png-export"      },
  { "avif",   FMT_AVIF,   N_("AVIF, 10-bit"),          "avif", "file-heif-av1-export" },
  { "xcf",    FMT_XCF,    N_("GIMP XCF (keeps float and re-develop data)"), "xcf", "gimp-xcf-save" },
};

static GimpValueArray * export_run (GimpProcedure       *procedure,
                                    GimpProcedureConfig *config,
                                    gpointer             run_data);

GimpProcedure *
export_batch_procedure_new (GimpPlugIn  *plug_in,
                            const gchar *name)
{
  GimpProcedure *procedure;
  GimpChoice    *choice = gimp_choice_new ();
  gint           i;

  procedure = gimp_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN,
                                  export_run, NULL, NULL);

  gimp_procedure_set_menu_label (procedure, _("Develop RAW files to a folder..."));
  gimp_procedure_add_menu_path (procedure, "<Image>/File/Export");
  gimp_procedure_set_sensitivity_mask (procedure,
                                       GIMP_PROCEDURE_SENSITIVE_NO_IMAGE      |
                                       GIMP_PROCEDURE_SENSITIVE_NO_DRAWABLES  |
                                       GIMP_PROCEDURE_SENSITIVE_DRAWABLE      |
                                       GIMP_PROCEDURE_SENSITIVE_DRAWABLES);
  gimp_procedure_set_documentation (procedure,
                                    _("Develop many RAW files straight to image files"),
                                    _("Develops RAW files with one set of settings and "
                                      "exports each one to a folder without keeping it "
                                      "open in GIMP."),
                                    name);
  gimp_procedure_set_attribution (procedure, "Marek Zettel", "Marek Zettel", "2026");

  for (i = 0; i < (gint) G_N_ELEMENTS (formats); i++)
    gimp_choice_add (choice, formats[i].nick, formats[i].id, _(formats[i].label), NULL);

  gimp_procedure_add_enum_argument (procedure, "run-mode", "Run mode", "The run mode",
                                    GIMP_TYPE_RUN_MODE, GIMP_RUN_INTERACTIVE,
                                    G_PARAM_READWRITE);
  gimp_procedure_add_string_array_argument (procedure, "files", _("Files"),
                                            _("Paths of the RAW files to develop"),
                                            G_PARAM_READWRITE);
  gimp_procedure_add_file_argument (procedure, "output-folder", _("Output folder"),
                                    _("Folder for the developed files"),
                                    GIMP_FILE_CHOOSER_ACTION_SELECT_FOLDER, TRUE, NULL,
                                    G_PARAM_READWRITE);
  gimp_procedure_add_choice_argument (procedure, "format", _("Format"),
                                      _("File format of the developed images"),
                                      choice, "tiff16", G_PARAM_READWRITE);
  gimp_procedure_add_int_argument (procedure, "quality", _("Quality"),
                                   _("JPEG / AVIF quality"), 1, 100, 92,
                                   G_PARAM_READWRITE);
  gimp_procedure_add_boolean_argument (procedure, "overwrite", _("Overwrite existing files"),
                                       _("Otherwise a number is added to the file name"),
                                       FALSE, G_PARAM_READWRITE);
  raw_settings_add_arguments (procedure);
  gimp_procedure_add_string_argument (procedure, "preset", _("Preset"),
                                      _("Name of a development preset applied in "
                                        "non-interactive mode (empty = use the arguments)"),
                                      "", G_PARAM_READWRITE);

  return procedure;
}

/* <folder>/<name>.<ext>, or <name>-2.<ext>, -3 ... when it exists;
 * NULL when no free name is left
 */
static GFile *
output_file (GFile       *folder,
             const gchar *src_path,
             const gchar *ext,
             gboolean     overwrite)
{
  gchar *base = g_path_get_basename (src_path);
  gchar *dot  = strrchr (base, '.');
  GFile *out;
  gint   n;

  if (dot)
    *dot = '\0';

  for (n = 1; ; n++)
    {
      gchar *name = n == 1 ? g_strdup_printf ("%s.%s", base, ext)
                           : g_strdup_printf ("%s-%d.%s", base, n, ext);

      out = g_file_get_child (folder, name);
      g_free (name);

      if (overwrite || ! g_file_query_exists (out, NULL))
        break;
      g_clear_object (&out);

      /* never overwrite when the user said not to */
      if (n >= 9999)
        break;
    }

  g_free (base);

  return out;
}

static gboolean
export_image (GimpImage          *image,
              const Format       *fmt,
              const RawSettings  *s,
              gint                quality,
              GFile              *out,
              gchar             **error_msg)
{
  GimpProcedure       *proc = gimp_pdb_lookup_procedure (gimp_get_pdb (), fmt->proc);
  GimpProcedureConfig *cfg;
  GimpValueArray      *ret;
  gboolean             ok;

  if (! proc)
    {
      *error_msg = g_strdup_printf (_("GIMP has no '%s' procedure."), fmt->proc);
      return FALSE;
    }

  /* other programs expect tone-curve encoded data in 8/16-bit files */
  if (fmt->id != FMT_XCF)
    {
      GimpColorProfile *gamma = rawheic_profile_new (s->color_space, FALSE);

      gimp_image_convert_color_profile (image, gamma,
                                        GIMP_COLOR_RENDERING_INTENT_RELATIVE_COLORIMETRIC, TRUE);
      gimp_image_convert_precision (image, fmt->id == FMT_JPEG ? GIMP_PRECISION_U8_NON_LINEAR
                                                               : GIMP_PRECISION_U16_NON_LINEAR);
      g_object_unref (gamma);
    }

  cfg = gimp_procedure_create_config (proc);
  g_object_set (cfg, "run-mode", GIMP_RUN_NONINTERACTIVE, "image", image, "file", out, NULL);

  if (g_object_class_find_property (G_OBJECT_GET_CLASS (cfg), "include-exif"))
    g_object_set (cfg, "include-exif", TRUE, NULL);
  if (g_object_class_find_property (G_OBJECT_GET_CLASS (cfg), "include-xmp"))
    g_object_set (cfg, "include-xmp", TRUE, NULL);
  if (g_object_class_find_property (G_OBJECT_GET_CLASS (cfg), "include-color-profile"))
    g_object_set (cfg, "include-color-profile", TRUE, NULL);

  if (fmt->id == FMT_JPEG)
    g_object_set (cfg, "quality", quality / 100.0, NULL);
  else if (fmt->id == FMT_AVIF)
    g_object_set (cfg, "quality", quality, "save-bit-depth", 10, NULL);

  ret = gimp_procedure_run_config (proc, cfg);
  ok  = GIMP_VALUES_GET_ENUM (ret, 0) == GIMP_PDB_SUCCESS;
  if (! ok)
    *error_msg = g_strdup (gimp_pdb_get_last_error (gimp_get_pdb ()));

  gimp_value_array_unref (ret);
  g_object_unref (cfg);

  return ok;
}

static GimpValueArray *
export_run (GimpProcedure       *procedure,
            GimpProcedureConfig *config,
            gpointer             run_data)
{
  GimpRunMode   run_mode;
  RawSettings   s;
  gchar       **files = NULL;
  GFile        *folder = NULL;
  const Format *fmt;
  GString      *errors = g_string_new (NULL);
  gint          quality, n, i, done = 0, fmt_id;
  gboolean      overwrite, cancelled = FALSE;
  GError       *error = NULL;

  g_object_get (config, "run-mode", &run_mode, "files", &files, NULL);

  if (run_mode == GIMP_RUN_INTERACTIVE)
    {
      GtkWidget *dialog;
      gboolean   ok;

      gimp_ui_init (PLUGIN_NAME);

      if (! files || ! files[0])
        {
          g_strfreev (files);
          files = rawheic_choose_raw_files (_("Develop RAW files to a folder"));
        }
      if (! files || ! files[0])
        goto cancel;

      dialog = gimp_procedure_dialog_new (procedure, config,
                                          _("Develop RAW files to a folder"));
      gimp_procedure_dialog_fill (GIMP_PROCEDURE_DIALOG (dialog),
                                  "output-folder", "format", "quality", "overwrite", NULL);
      ok = gimp_procedure_dialog_run (GIMP_PROCEDURE_DIALOG (dialog));
      gtk_widget_destroy (dialog);
      if (! ok)
        goto cancel;

      {
        gint      count = g_strv_length (files);
        gchar    *title = g_strdup_printf (ngettext ("Develop %d RAW file",
                                                     "Develop %d RAW files", count), count);
        gboolean  dev   = raw_dialog_run (procedure, config, files[0], title);

        g_free (title);
        if (! dev)
          goto cancel;
      }
    }

  g_object_get (config, "output-folder", &folder, "quality", &quality,
                "overwrite", &overwrite, NULL);
  fmt_id = gimp_procedure_config_get_choice_id (config, "format");
  fmt    = &formats[CLAMP (fmt_id, 0, (gint) G_N_ELEMENTS (formats) - 1)];

  if (! files || ! files[0] || ! folder ||
      g_file_query_file_type (folder, G_FILE_QUERY_INFO_NONE, NULL) != G_FILE_TYPE_DIRECTORY)
    {
      error = g_error_new_literal (G_FILE_ERROR, G_FILE_ERROR_INVAL,
                                   _("Give the RAW files and an existing output folder."));
      g_strfreev (files);
      g_clear_object (&folder);
      g_string_free (errors, TRUE);
      return gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, error);
    }

  raw_settings_from_config (&s, config);
  if (run_mode != GIMP_RUN_INTERACTIVE)
    {
      gchar *preset = NULL;

      g_object_get (config, "preset", &preset, NULL);
      if (preset && *preset && ! raw_presets_load (preset, &s))
        {
          error = g_error_new (G_FILE_ERROR, G_FILE_ERROR_NOENT,
                               _("Unknown preset '%s'."), preset);
          g_free (preset);
          g_strfreev (files);
          g_clear_object (&folder);
          g_string_free (errors, TRUE);
          return gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, error);
        }
      g_free (preset);
    }

  n = g_strv_length (files);
  if (! raw_batch_session_begin (&s, files, &error))
    {
      g_strfreev (files);
      g_clear_object (&folder);
      g_string_free (errors, TRUE);
      return gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, error);
    }

  for (i = 0; i < n; i++)
    {
      gchar     *base = g_path_get_basename (files[i]);
      gchar     *err  = NULL;
      GFile     *in   = g_file_new_for_path (files[i]);
      GimpImage *image;

      gimp_progress_init_printf (_("(%d/%d) %s"), i + 1, n, base);
      if (! gimp_progress_update ((gdouble) i / n))
        {
          cancelled = TRUE;
          g_object_unref (in);
          g_free (base);
          break;
        }

      image = gimp_file_load (GIMP_RUN_NONINTERACTIVE, in);
      if (image)
        {
          GFile *out = output_file (folder, files[i], fmt->ext, overwrite);

          if (! out)
            g_string_append_printf (errors, "%s: %s\n", base,
                                    _("no free output file name"));
          else if (export_image (image, fmt, &s, quality, out, &err))
            done++;
          else
            g_string_append_printf (errors, "%s: %s\n", base, err ? err : "?");

          gimp_image_delete (image);
          g_clear_object (&out);
        }
      else
        {
          g_string_append_printf (errors, "%s: %s\n", base,
                                  gimp_pdb_get_last_error (gimp_get_pdb ()));
        }

      g_free (err);
      g_object_unref (in);
      g_free (base);
    }

  raw_batch_session_end ();
  gimp_progress_end ();

  if (run_mode == GIMP_RUN_INTERACTIVE)
    {
      gchar *msg = g_strdup_printf (_("Developed %d of %d files.%s%s"), done, n,
                                    errors->len ? "\n\n" : "", errors->str);
      gimp_message (msg);
      g_free (msg);
    }

  g_strfreev (files);
  g_clear_object (&folder);

  if (done == 0 && ! cancelled)
    {
      error = g_error_new (G_FILE_ERROR, G_FILE_ERROR_FAILED,
                           _("No file could be developed.\n%s"), errors->str);
      g_string_free (errors, TRUE);
      return gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, error);
    }

  g_string_free (errors, TRUE);

  return gimp_procedure_new_return_values (procedure,
                                           cancelled && done == 0 ? GIMP_PDB_CANCEL
                                                                  : GIMP_PDB_SUCCESS,
                                           NULL);

cancel:
  g_strfreev (files);
  g_string_free (errors, TRUE);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_CANCEL, NULL);
}
