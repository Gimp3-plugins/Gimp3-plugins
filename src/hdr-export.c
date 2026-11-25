/* gimp-raw-heic -- HDR export: HEIF/HEIC (HEVC) or AVIF (AV1), PQ or HLG
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The inverse of the HDR loader in heif-load.c: the image is converted to
 * linear Rec. 2020 (scene-linear, SDR reference white = 1.0, values above
 * 1.0 are highlights), encoded with the SMPTE ST 2084 (PQ) or ARIB STD-B67
 * (HLG) transfer function at 10 or 12 bits and tagged with an nclx colour
 * box (BT.2020 primaries and matrix), as HDR displays and phones expect.
 *
 * GIMP's own HEIF exporter stays the default for .heic/.avif: this one has
 * a lower priority and is picked in the export dialog ("Select File Type").
 */

#include "config.h"

#include <math.h>
#include <string.h>

#include <libheif/heif.h>
#include <libgimp/gimpui.h>

#include "rawheic.h"

#define REFERENCE_WHITE_NITS 203.0

enum
{
  TRANSFER_PQ,
  TRANSFER_HLG
};

static GimpValueArray * hdr_export_run (GimpProcedure        *procedure,
                                        GimpRunMode           run_mode,
                                        GimpImage            *image,
                                        GFile                *file,
                                        GimpExportOptions    *options,
                                        GimpMetadata         *metadata,
                                        GimpProcedureConfig  *config,
                                        gpointer              run_data);

GimpProcedure *
hdr_export_procedure_new (GimpPlugIn  *plug_in,
                          const gchar *name)
{
  GimpProcedure *procedure;

  procedure = gimp_export_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN,
                                         FALSE, hdr_export_run, NULL, NULL);

  gimp_procedure_set_image_types (procedure, "RGB*");
  gimp_procedure_set_menu_label (procedure, _("HEIF/AVIF HDR (PQ/HLG)"));
  gimp_procedure_set_documentation (procedure,
                                    _("Export an HDR image as HEIF/HEIC or AVIF with PQ or HLG"),
                                    _("Encodes linear light (1.0 = SDR white, brighter "
                                      "values kept) in BT.2100 PQ or HLG at 10 or 12 bits "
                                      "with BT.2020 primaries: .heic/.heif use HEVC, .avif "
                                      "uses AV1."),
                                    name);
  gimp_procedure_set_attribution (procedure, "Marek Zettel", "Marek Zettel", "2026");

  gimp_file_procedure_set_format_name (GIMP_FILE_PROCEDURE (procedure), _("HEIF/AVIF HDR"));
  gimp_file_procedure_set_mime_types  (GIMP_FILE_PROCEDURE (procedure),
                                       "image/heif,image/heic,image/avif");
  gimp_file_procedure_set_extensions  (GIMP_FILE_PROCEDURE (procedure), "heic,heif,hif,avif");
  /* GIMP's own exporter stays the default for these extensions */
  gimp_file_procedure_set_priority    (GIMP_FILE_PROCEDURE (procedure), 100);

  gimp_export_procedure_set_capabilities (GIMP_EXPORT_PROCEDURE (procedure),
                                          GIMP_EXPORT_CAN_HANDLE_RGB |
                                          GIMP_EXPORT_CAN_HANDLE_ALPHA,
                                          NULL, NULL, NULL);

  gimp_procedure_add_choice_argument (procedure, "transfer", _("Transfer function"),
                                      _("PQ (absolute, HDR10 style) or HLG (relative, broadcast)"),
                                      gimp_choice_new_with_values (
                                        "pq",  TRANSFER_PQ,  _("PQ (SMPTE ST 2084)"), NULL,
                                        "hlg", TRANSFER_HLG, _("HLG (ARIB STD-B67)"), NULL,
                                        NULL),
                                      "pq", G_PARAM_READWRITE);
  gimp_procedure_add_int_argument (procedure, "bit-depth", _("Bit depth"),
                                   _("10 or 12 bits per channel"), 10, 12, 10,
                                   G_PARAM_READWRITE);
  gimp_procedure_add_int_argument (procedure, "quality", _("Quality"),
                                   _("Encoder quality, 100 = lossless"), 1, 100, 90,
                                   G_PARAM_READWRITE);
  gimp_procedure_add_double_argument (procedure, "exposure", _("Exposure (EV)"),
                                      _("Applied before encoding"), -6.0, 6.0, 0.0,
                                      G_PARAM_READWRITE);

  return procedure;
}

/* linear (1.0 = 203 cd/m²) -> PQ signal 0..1 */
gdouble
rawheic_pq_encode (gdouble l)
{
  const gdouble m1 = 2610.0 / 16384.0;
  const gdouble m2 = 2523.0 / 4096.0 * 128.0;
  const gdouble c1 = 3424.0 / 4096.0;
  const gdouble c2 = 2413.0 / 4096.0 * 32.0;
  const gdouble c3 = 2392.0 / 4096.0 * 32.0;
  gdouble       y  = CLAMP (l * REFERENCE_WHITE_NITS / 10000.0, 0.0, 1.0);
  gdouble       p  = pow (y, m1);

  return pow ((c1 + c2 * p) / (1.0 + c3 * p), m2);
}

/* linear (1.0 = HLG reference white, 75 % signal) -> HLG signal 0..1 */
gdouble
rawheic_hlg_encode (gdouble l)
{
  const gdouble a = 0.17883277, b = 0.28466892, c = 0.55991073;
  const gdouble ref = (exp ((0.75 - c) / a) + b) / 12.0;
  gdouble       E   = CLAMP (l * ref, 0.0, 1.0);

  return E <= 1.0 / 12.0 ? sqrt (3.0 * E) : a * log (12.0 * E - b) + c;
}

static heif_error
write_cb (heif_context *ctx,
          const void   *data,
          size_t        size,
          void         *userdata)
{
  GOutputStream *out   = userdata;
  GError        *error = NULL;
  heif_error     err   = { heif_error_Ok, heif_suberror_Unspecified, "" };

  if (! g_output_stream_write_all (out, data, size, NULL, NULL, &error))
    {
      static gchar msg[256];

      g_strlcpy (msg, error->message, sizeof msg);
      g_error_free (error);
      err.code    = heif_error_Encoding_error;
      err.message = msg;
    }

  return err;
}

static gboolean
export_hdr (GimpDrawable  *drawable,
            GFile         *file,
            gint           transfer,
            gint           bits,
            gint           quality,
            gdouble        exposure,
            GError       **error)
{
  gint                     w = gimp_drawable_get_width (drawable);
  gint                     h = gimp_drawable_get_height (drawable);
  gboolean                 alpha = gimp_drawable_has_alpha (drawable);
  gint                     ch = alpha ? 4 : 3;
  gchar                   *base = g_file_get_basename (file);
  gchar                   *lower = g_ascii_strdown (base, -1);
  gboolean                 avif = g_str_has_suffix (lower, ".avif");
  heif_compression_format  fmt = avif ? heif_compression_AV1 : heif_compression_HEVC;
  GimpColorProfile        *rec2020 = rawheic_profile_rec2100_linear ();
  const Babl              *babl_fmt;
  GeglBuffer              *buffer;
  heif_context            *ctx = NULL;
  heif_image              *img = NULL;
  heif_encoder            *enc = NULL;
  heif_encoding_options   *opts = NULL;
  heif_color_profile_nclx *nclx = NULL;
  heif_error               err;
  GFileOutputStream       *out = NULL;
  gfloat                  *row;
  guint16                 *lut;
  guint8                  *plane;
  gint                     stride = 0, y, maxv = (1 << bits) - 1, nlut = 65536;
  gfloat                   gain = (gfloat) pow (2.0, exposure);
  gboolean                 ok = FALSE;

  g_free (lower);
  g_free (base);

  if (! heif_have_encoder_for_format (fmt))
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                   _("This libheif has no %s encoder."), avif ? "AV1" : "HEVC");
      g_object_unref (rec2020);
      return FALSE;
    }

  babl_fmt = gimp_color_profile_get_format (rec2020, babl_format (alpha ? "RGBA float"
                                                                        : "RGB float"),
                                            GIMP_COLOR_RENDERING_INTENT_RELATIVE_COLORIMETRIC,
                                            error);
  g_object_unref (rec2020);
  if (! babl_fmt)
    return FALSE;

  /* the transfer function as a table over linear values 0 .. 64, indexed
   * by sqrt (l / 64) so that the shadows get fine steps
   */
  lut = g_new (guint16, nlut);
  for (y = 0; y < nlut; y++)
    {
      gdouble t = (gdouble) y / (nlut - 1);
      gdouble l = 64.0 * t * t;
      gdouble e = transfer == TRANSFER_PQ ? rawheic_pq_encode (l) : rawheic_hlg_encode (l);

      lut[y] = (guint16) CLAMP (e * maxv + 0.5, 0, maxv);
    }

  err = heif_image_create (w, h, heif_colorspace_RGB,
                           alpha ? heif_chroma_interleaved_RRGGBBAA_LE
                                 : heif_chroma_interleaved_RRGGBB_LE, &img);
  if (err.code == heif_error_Ok)
    err = heif_image_add_plane (img, heif_channel_interleaved, w, h, bits);
  if (err.code != heif_error_Ok)
    goto heif_fail;

  {
    size_t s = 0;

    plane  = heif_image_get_plane2 (img, heif_channel_interleaved, &s);
    stride = (gint) s;
  }
  if (! plane)
    {
      err.message = "no image plane";
      goto heif_fail;
    }

  buffer = gimp_drawable_get_buffer (drawable);
  row    = g_new (gfloat, (gsize) w * ch);
  for (y = 0; y < h; y++)
    {
      guint16 *dst = (guint16 *) (plane + (gsize) y * stride);
      gint     x, c;

      gegl_buffer_get (buffer, GEGL_RECTANGLE (0, y, w, 1), 1.0, babl_fmt, row,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < w; x++)
        for (c = 0; c < ch; c++)
          {
            gfloat v = row[x * ch + c];

            if (c == 3)
              {
                dst[x * ch + c] = GUINT16_TO_LE ((guint16) CLAMP (v * maxv + 0.5f, 0, maxv));
              }
            else
              {
                gfloat l = isfinite (v) ? CLAMP (v * gain, 0.0f, 64.0f) : 0.0f;
                gint   i = (gint) (sqrtf (l / 64.0f) * (nlut - 1) + 0.5f);

                dst[x * ch + c] = GUINT16_TO_LE (lut[i]);
              }
          }

      if (y % 64 == 0)
        gimp_progress_update ((gdouble) y / h * 0.5);
    }
  g_free (row);
  g_object_unref (buffer);

  nclx = heif_nclx_color_profile_alloc ();
  nclx->color_primaries          = heif_color_primaries_ITU_R_BT_2020_2_and_2100_0;
  nclx->transfer_characteristics = transfer == TRANSFER_PQ ?
                                   heif_transfer_characteristic_ITU_R_BT_2100_0_PQ :
                                   heif_transfer_characteristic_ITU_R_BT_2100_0_HLG;
  nclx->matrix_coefficients      = heif_matrix_coefficients_ITU_R_BT_2020_2_non_constant_luminance;
  nclx->full_range_flag          = 1;
  heif_image_set_nclx_color_profile (img, nclx);

  ctx = heif_context_alloc ();
  err = heif_context_get_encoder_for_format (ctx, fmt, &enc);
  if (err.code != heif_error_Ok)
    goto heif_fail;

  if (quality >= 100)
    heif_encoder_set_lossless (enc, 1);
  else
    heif_encoder_set_lossy_quality (enc, quality);
  /* full chroma at high quality: HDR highlights are often saturated */
  if (quality >= 90)
    heif_encoder_set_parameter_string (enc, "chroma", "444");

  opts = heif_encoding_options_alloc ();
  opts->output_nclx_profile = nclx;

  gimp_progress_update (0.6);
  err = heif_context_encode_image (ctx, img, enc, opts, NULL);
  if (err.code != heif_error_Ok)
    goto heif_fail;

  out = g_file_replace (file, NULL, FALSE, G_FILE_CREATE_NONE, NULL, error);
  if (! out)
    goto done;

  {
    heif_writer writer = { 1, write_cb };

    err = heif_context_write (ctx, &writer, out);
  }
  if (err.code != heif_error_Ok)
    {
      g_output_stream_close (G_OUTPUT_STREAM (out), NULL, NULL);
      goto heif_fail;
    }
  ok = g_output_stream_close (G_OUTPUT_STREAM (out), NULL, error);
  gimp_progress_update (1.0);
  goto done;

heif_fail:
  g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
               _("Encoding the HDR image failed: %s"), err.message ? err.message : "?");

done:
  g_clear_object (&out);
  if (opts)
    heif_encoding_options_free (opts);
  if (enc)
    heif_encoder_release (enc);
  if (ctx)
    heif_context_free (ctx);
  if (nclx)
    heif_nclx_color_profile_free (nclx);
  if (img)
    heif_image_release (img);
  g_free (lut);

  return ok;
}

static GimpValueArray *
hdr_export_run (GimpProcedure        *procedure,
                GimpRunMode           run_mode,
                GimpImage            *image,
                GFile                *file,
                GimpExportOptions    *options,
                GimpMetadata         *metadata,
                GimpProcedureConfig  *config,
                gpointer              run_data)
{
  GimpExportReturn  export = GIMP_EXPORT_IGNORE;
  GimpLayer       **layers;
  GError           *error = NULL;
  gint              transfer, bits, quality;
  gdouble           exposure;
  gboolean          ok;

  if (run_mode == GIMP_RUN_INTERACTIVE)
    {
      GtkWidget *dialog;

      gimp_ui_init (PLUGIN_NAME);
      dialog = gimp_export_procedure_dialog_new (GIMP_EXPORT_PROCEDURE (procedure),
                                                 config, image);
      gimp_procedure_dialog_fill (GIMP_PROCEDURE_DIALOG (dialog),
                                  "transfer", "bit-depth", "quality", "exposure", NULL);
      ok = gimp_procedure_dialog_run (GIMP_PROCEDURE_DIALOG (dialog));
      gtk_widget_destroy (dialog);
      if (! ok)
        return gimp_procedure_new_return_values (procedure, GIMP_PDB_CANCEL, NULL);
    }

  transfer = gimp_procedure_config_get_choice_id (config, "transfer");
  g_object_get (config, "bit-depth", &bits, "quality", &quality, "exposure", &exposure, NULL);
  bits = bits >= 12 ? 12 : 10;

  gimp_progress_init (_("Exporting HDR image"));

  export = gimp_export_options_get_image (options, &image);
  layers = gimp_image_get_layers (image);
  ok     = layers && layers[0] &&
           export_hdr (GIMP_DRAWABLE (layers[0]), file, transfer, bits, quality, exposure, &error);
  g_free (layers);

  if (export == GIMP_EXPORT_EXPORT)
    gimp_image_delete (image);

  if (! ok && ! error)
    g_set_error_literal (&error, G_FILE_ERROR, G_FILE_ERROR_FAILED, _("Nothing to export."));

  return gimp_procedure_new_return_values (procedure,
                                           ok ? GIMP_PDB_SUCCESS : GIMP_PDB_EXECUTION_ERROR,
                                           error);
}
