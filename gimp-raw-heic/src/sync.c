/* gimp-raw-heic -- Filters > RAW > Apply these settings to other RAW files
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Takes the development settings stored in the current image (the
 * "gimp-raw-heic-source" parasite) and opens other RAW files with them,
 * through the batch-open procedure.  What belongs to one photo is not
 * copied unless asked: the crop and straightening, and the neutral point
 * (its measured multipliers are used instead).
 */

#include "config.h"

#include <string.h>

#include <libgimp/gimpui.h>

#include "rawheic.h"

static GimpValueArray * sync_run (GimpProcedure        *procedure,
                                  GimpRunMode           run_mode,
                                  GimpImage            *image,
                                  GimpDrawable        **drawables,
                                  GimpProcedureConfig  *config,
                                  gpointer              run_data);

GimpProcedure *
sync_procedure_new (GimpPlugIn  *plug_in,
                    const gchar *name)
{
  GimpProcedure *procedure;

  procedure = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN,
                                        sync_run, NULL, NULL);

  gimp_procedure_set_image_types (procedure, "RGB*");
  gimp_procedure_set_sensitivity_mask (procedure,
                                       GIMP_PROCEDURE_SENSITIVE_DRAWABLE  |
                                       GIMP_PROCEDURE_SENSITIVE_DRAWABLES |
                                       GIMP_PROCEDURE_SENSITIVE_NO_DRAWABLES);
  gimp_procedure_set_menu_label (procedure, _("Apply these settings to RAW files..."));
  gimp_procedure_add_menu_path (procedure, "<Image>/Filters/RAW");
  gimp_procedure_set_documentation (procedure,
                                    _("Open other RAW files with this image's development settings"),
                                    _("Copies the RAW development settings stored in this "
                                      "image (white balance, exposure, detail, lens, colour, "
                                      "output) to other RAW files and opens them."),
                                    name);
  gimp_procedure_set_attribution (procedure, "Marek Zettel", "Marek Zettel", "2026");

  gimp_procedure_add_string_array_argument (procedure, "files", _("Files"),
                                            _("Paths of the RAW files to open"),
                                            G_PARAM_READWRITE);
  gimp_procedure_add_boolean_argument (procedure, "include-geometry",
                                       _("Also copy crop and straightening"),
                                       _("Off: the other photos keep their full frame"),
                                       FALSE, G_PARAM_READWRITE);
  gimp_procedure_add_core_object_array_return_value (procedure, "images", _("Images"),
                                                     _("The opened images"),
                                                     GIMP_TYPE_IMAGE, G_PARAM_READWRITE);

  return procedure;
}

/* Settings of @image prepared for other photos.  FALSE if it has none. */
gboolean
rawheic_settings_for_other_photos (GimpImage   *image,
                                   gboolean     include_geometry,
                                   RawSettings *s)
{
  GimpParasite *parasite = gimp_image_get_parasite (image, SOURCE_PARASITE);
  gconstpointer data;
  guint32       size = 0;
  gchar        *text;
  gboolean      ok;

  if (! parasite)
    return FALSE;

  data = gimp_parasite_get_data (parasite, &size);
  text = g_strndup (data, size);
  gimp_parasite_free (parasite);
  ok = raw_settings_deserialize (s, text, NULL);
  g_free (text);

  if (! ok)
    return FALSE;

  /* the neutral point was measured on this photo: use its multipliers */
  if (s->wb_mode == WB_SPOT)
    s->wb_mode = WB_MULTIPLIERS;

  if (! include_geometry)
    {
      RawSettings d;

      raw_settings_defaults (&d);
      s->straighten = d.straighten;
      memcpy (s->crop, d.crop, sizeof s->crop);
      memcpy (s->spot, d.spot, sizeof s->spot);
    }

  return TRUE;
}

static GimpValueArray *
sync_run (GimpProcedure        *procedure,
          GimpRunMode           run_mode,
          GimpImage            *image,
          GimpDrawable        **drawables,
          GimpProcedureConfig  *config,
          gpointer              run_data)
{
  GimpProcedure       *batch;
  GimpProcedureConfig *bcfg;
  GimpValueArray      *ret, *out;
  GimpPDBStatusType    status;
  RawSettings          s;
  gchar              **files = NULL;
  gboolean             geometry = FALSE;
  GError              *error = NULL;

  if (run_mode == GIMP_RUN_INTERACTIVE)
    {
      GtkWidget *dialog;
      gboolean   ok;

      gimp_ui_init (PLUGIN_NAME);
      dialog = gimp_procedure_dialog_new (procedure, config,
                                          _("Apply these settings to RAW files"));
      gimp_procedure_dialog_fill (GIMP_PROCEDURE_DIALOG (dialog), "include-geometry", NULL);
      ok = gimp_procedure_dialog_run (GIMP_PROCEDURE_DIALOG (dialog));
      gtk_widget_destroy (dialog);
      if (! ok)
        return gimp_procedure_new_return_values (procedure, GIMP_PDB_CANCEL, NULL);
    }

  g_object_get (config, "files", &files, "include-geometry", &geometry, NULL);

  if (! rawheic_settings_for_other_photos (image, geometry, &s))
    {
      g_strfreev (files);
      g_set_error (&error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                   _("This image was not loaded from a RAW file by gimp-raw-heic, "
                     "so it has no settings to apply."));
      return gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, error);
    }

  /* the settings come from the image file: never touch network paths in
   * them unasked (Windows would authenticate to that server)
   */
  if (s.camera_profile[0] && rawheic_path_is_remote (s.camera_profile) &&
      (run_mode != GIMP_RUN_INTERACTIVE || ! rawheic_confirm_remote (s.camera_profile)))
    s.camera_profile[0] = '\0';
  if (s.profile_dir[0] && rawheic_path_is_remote (s.profile_dir) &&
      (run_mode != GIMP_RUN_INTERACTIVE || ! rawheic_confirm_remote (s.profile_dir)))
    s.profile_dir[0] = '\0';

  if (run_mode == GIMP_RUN_INTERACTIVE && (! files || ! files[0]))
    {
      g_strfreev (files);
      files = rawheic_choose_raw_files (_("Apply these settings to RAW files"));
    }

  if (! files || ! files[0])
    {
      g_strfreev (files);
      if (run_mode == GIMP_RUN_INTERACTIVE)
        return gimp_procedure_new_return_values (procedure, GIMP_PDB_CANCEL, NULL);
      g_set_error_literal (&error, G_FILE_ERROR, G_FILE_ERROR_INVAL, _("No files were given."));
      return gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, error);
    }

  batch = gimp_pdb_lookup_procedure (gimp_get_pdb (), BATCH_PROC);
  bcfg  = gimp_procedure_create_config (batch);
  raw_settings_to_config (&s, bcfg);
  g_object_set (bcfg, "run-mode", GIMP_RUN_NONINTERACTIVE, "files", files, NULL);
  ret = gimp_procedure_run_config (batch, bcfg);
  g_object_unref (bcfg);
  g_strfreev (files);

  status = GIMP_VALUES_GET_ENUM (ret, 0);
  if (status != GIMP_PDB_SUCCESS)
    {
      if (status != GIMP_PDB_CANCEL)
        g_set_error (&error, G_FILE_ERROR, G_FILE_ERROR_FAILED, "%s",
                     gimp_pdb_get_last_error (gimp_get_pdb ()));
      gimp_value_array_unref (ret);
      return gimp_procedure_new_return_values (procedure, status, error);
    }

  out = gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
  {
    GimpImage **images = GIMP_VALUES_GET_CORE_OBJECT_ARRAY (ret, 1);
    gint        i;

    if (images && run_mode == GIMP_RUN_INTERACTIVE)
      {
        for (i = 0; images[i]; i++)
          gimp_display_new (images[i]);
        gimp_displays_flush ();
      }
    GIMP_VALUES_SET_CORE_OBJECT_ARRAY (out, 1, images);
  }
  gimp_value_array_unref (ret);

  return out;
}
