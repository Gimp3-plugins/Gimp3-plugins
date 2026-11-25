/* gimp-raw-heic -- development settings from XMP sidecars
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Lightroom / Adobe Camera Raw write "crs:" properties; darktable writes
 * its module history ("darktable:history") with binary module parameters.
 * Only settings with a clear counterpart are taken over:
 *
 *   white balance (as shot, auto, temperature/tint, darktable multipliers)
 *   exposure (beyond LibRaw's +3 EV the rest goes to brightness)
 *   lens corrections, lateral CA, luminance noise reduction (Lightroom)
 *
 * The file is untrusted: sizes are limited and parameters checked.
 */

#include "config.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <gio/gio.h>
#include <glib/gstdio.h>

#include "rawheic.h"

#define MAX_XMP_SIZE (8 * 1024 * 1024)

typedef struct
{
  GHashTable *crs;            /* crs:Name -> value */
  /* darktable: last enabled entry per operation within history_end */
  gint        history_end;
  gint        index;
  gchar      *dt_params[3];   /* temperature, exposure, lens */
  gint        dt_version[3];
  gboolean    dt_seen;
  /* element text capture (crs values written as elements) */
  gchar      *element;
  gboolean    in_li;
  gchar      *li_op, *li_params;
  gint        li_version, li_enabled, li_num;
  gchar      *own;            /* rawheic:settings, base64 key file */
} XmpParse;

static const gchar *dt_ops[3] = { "temperature", "exposure", "lens" };

static void
dt_record (XmpParse    *xp,
           const gchar *op,
           const gchar *params,
           gint         version,
           gint         enabled,
           gint         num)
{
  gint i;

  if (! op || ! params)
    return;

  xp->dt_seen = TRUE;
  if (xp->history_end >= 0 && num >= xp->history_end)
    return;

  for (i = 0; i < 3; i++)
    if (! strcmp (op, dt_ops[i]))
      {
        g_free (xp->dt_params[i]);
        /* a later disabled entry switches the module off */
        xp->dt_params[i]  = enabled ? g_strdup (params) : NULL;
        xp->dt_version[i] = version;
      }
}

static void
start_element (GMarkupParseContext *ctx,
               const gchar         *name,
               const gchar        **names,
               const gchar        **values,
               gpointer             data,
               GError             **error)
{
  XmpParse *xp = data;
  gint      i;

  for (i = 0; names[i]; i++)
    {
      if (g_str_has_prefix (names[i], "crs:"))
        g_hash_table_replace (xp->crs, g_strdup (names[i] + 4), g_strdup (values[i]));
      else if (! strcmp (names[i], "darktable:history_end"))
        xp->history_end = atoi (values[i]);
      else if (! strcmp (names[i], "rawheic:settings") && ! xp->own)
        xp->own = g_strdup (values[i]);
    }

  if (! strcmp (name, "rdf:li"))
    {
      const gchar *op = NULL, *params = NULL;
      gint         version = 0, enabled = 1, num = -1;

      for (i = 0; names[i]; i++)
        {
          if (! strcmp (names[i], "darktable:operation"))       op = values[i];
          else if (! strcmp (names[i], "darktable:params"))     params = values[i];
          else if (! strcmp (names[i], "darktable:modversion")) version = atoi (values[i]);
          else if (! strcmp (names[i], "darktable:enabled"))    enabled = atoi (values[i]);
          else if (! strcmp (names[i], "darktable:num"))        num = atoi (values[i]);
        }
      if (op)
        {
          dt_record (xp, op, params, version, enabled, num >= 0 ? num : xp->index);
          xp->index++;
        }
    }

  if (g_str_has_prefix (name, "crs:"))
    {
      g_free (xp->element);
      xp->element = g_strdup (name + 4);
    }
}

static void
end_element (GMarkupParseContext *ctx,
             const gchar         *name,
             gpointer             data,
             GError             **error)
{
  XmpParse *xp = data;

  if (g_str_has_prefix (name, "crs:"))
    g_clear_pointer (&xp->element, g_free);
}

static void
text (GMarkupParseContext *ctx,
      const gchar         *txt,
      gsize                len,
      gpointer             data,
      GError             **error)
{
  XmpParse *xp = data;

  if (xp->element && len > 0 && len < 256)
    {
      gchar *v = g_strstrip (g_strndup (txt, len));

      if (*v)
        g_hash_table_replace (xp->crs, g_strdup (xp->element), v);
      else
        g_free (v);
    }
}

/* darktable params: hex, or "gz" + 2 digits + base64(zlib) */
static guint8 *
dt_decode (const gchar *s,
           gsize       *len)
{
  if (g_str_has_prefix (s, "gz") && strlen (s) > 4)
    {
      gsize             zlen;
      guchar           *z = g_base64_decode (s + 4, &zlen);
      GConverter       *conv;
      guint8           *out;
      gsize             read = 0, written = 0;
      GConverterResult  r;

      if (! z || zlen == 0)
        {
          g_free (z);
          return NULL;
        }
      conv = G_CONVERTER (g_zlib_decompressor_new (G_ZLIB_COMPRESSOR_FORMAT_ZLIB));
      out  = g_malloc (4096);
      r = g_converter_convert (conv, z, zlen, out, 4096, G_CONVERTER_INPUT_AT_END,
                               &read, &written, NULL);
      g_object_unref (conv);
      g_free (z);
      if (r == G_CONVERTER_ERROR || written == 0)
        {
          g_free (out);
          return NULL;
        }
      *len = written;
      return out;
    }
  else
    {
      gsize   n = strlen (s), i;
      guint8 *out;

      if (n == 0 || n % 2 || n > 8192)
        return NULL;
      out = g_malloc (n / 2);
      for (i = 0; i < n / 2; i++)
        {
          gint hi = g_ascii_xdigit_value (s[i * 2]);
          gint lo = g_ascii_xdigit_value (s[i * 2 + 1]);

          if (hi < 0 || lo < 0)
            {
              g_free (out);
              return NULL;
            }
          out[i] = (guint8) (hi << 4 | lo);
        }
      *len = n / 2;
      return out;
    }
}

static gfloat
le_float (const guint8 *p)
{
  guint32 u = (guint32) p[0] | (guint32) p[1] << 8 | (guint32) p[2] << 16 | (guint32) p[3] << 24;
  gfloat  f;

  memcpy (&f, &u, 4);
  return f;
}

static void
set_exposure (RawSettings *s,
              gdouble      ev)
{
  if (! isfinite (ev))
    return;
  ev = CLAMP (ev, -5.0, 5.0);
  /* LibRaw's exposure correction covers -2..+3 EV; the rest is a plain
   * brightness factor
   */
  s->exposure   = CLAMP (ev, -2.0, 3.0);
  s->brightness = CLAMP (pow (2.0, ev - s->exposure), 0.25, 4.0);
}

static gboolean
crs_double (GHashTable  *crs,
            const gchar *key,
            gdouble     *out)
{
  const gchar *v = g_hash_table_lookup (crs, key);
  gchar       *end;

  if (! v)
    return FALSE;
  *out = g_ascii_strtod (v, &end);
  return end != v && isfinite (*out);
}

/* Apply the sidecar's settings to @s.  Returns a translated description
 * of the source ("Lightroom", "darktable") or NULL when nothing applied.
 */
const gchar *
rawheic_xmp_apply_data (const gchar *xml,
                        gsize        len,
                        RawSettings *s)
{
  GMarkupParser        parser = { start_element, end_element, text, NULL, NULL };
  GMarkupParseContext *ctx;
  XmpParse             xp = { 0 };
  const gchar         *source = NULL;
  gdouble              v;
  gint                 i;

  xp.crs         = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);
  xp.history_end = -1;

  ctx = g_markup_parse_context_new (&parser, 0, &xp, NULL);
  if (! g_markup_parse_context_parse (ctx, xml, (gssize) len, NULL) ||
      ! g_markup_parse_context_end_parse (ctx, NULL))
    {
      /* keep whatever was understood before the error */
    }
  g_markup_parse_context_free (ctx);

  /* --- written by this plug-in: everything, exactly --- */
  if (xp.own)
    {
      gsize    n = 0;
      guchar  *raw = g_base64_decode (xp.own, &n);
      gchar   *text = raw && n < 64 * 1024 ? g_strndup ((const gchar *) raw, n) : NULL;
      RawSettings own;

      if (text && raw_settings_deserialize (&own, text, NULL))
        {
          /* the sidecar comes with the photo: never follow paths in it
           * to other machines
           */
          if (own.camera_profile[0] && rawheic_path_is_remote (own.camera_profile))
            own.camera_profile[0] = '\0';
          if (own.profile_dir[0] && rawheic_path_is_remote (own.profile_dir))
            own.profile_dir[0] = '\0';
          *s     = own;
          source = _("gimp-raw-heic");
        }
      g_free (text);
      g_free (raw);
      g_clear_pointer (&xp.own, g_free);

      if (source)
        goto done;
      /* damaged: fall back to the Lightroom / darktable values */
    }

  /* --- Lightroom / Camera Raw --- */
  if (g_hash_table_size (xp.crs))
    {
      const gchar *wb = g_hash_table_lookup (xp.crs, "WhiteBalance");
      gboolean     any = FALSE;

      if (wb && ! strcmp (wb, "As Shot"))
        { s->wb_mode = WB_CAMERA; any = TRUE; }
      else if (wb && ! strcmp (wb, "Auto"))
        { s->wb_mode = WB_AUTO; any = TRUE; }
      else if (crs_double (xp.crs, "Temperature", &v))
        {
          s->wb_mode        = WB_MANUAL;
          s->wb_temperature = CLAMP (v, 2000.0, 25000.0);
          if (crs_double (xp.crs, "Tint", &v))
            s->wb_tint = CLAMP (v, -100.0, 100.0);
          any = TRUE;
        }

      if (crs_double (xp.crs, "Exposure2012", &v) || crs_double (xp.crs, "Exposure", &v))
        { set_exposure (s, v); any = TRUE; }

      if (crs_double (xp.crs, "LensProfileEnable", &v))
        { s->lens_distortion = s->lens_vignetting = v >= 1.0; any = TRUE; }
      if (crs_double (xp.crs, "AutoLateralCA", &v))
        { s->lens_tca = v >= 1.0; any = TRUE; }

      if (crs_double (xp.crs, "LuminanceSmoothing", &v))
        { s->denoise = CLAMP (v, 0.0, 100.0) * 10.0; any = TRUE; }

      /* crop: exact without rotation, close with a small angle (Lightroom
       * measures the rectangle before rotating, this plug-in after)
       */
      {
        const gchar *has = g_hash_table_lookup (xp.crs, "HasCrop");
        gdouble      l, t, r, b, angle = 0.0;

        if (has && ! g_ascii_strcasecmp (has, "True") &&
            crs_double (xp.crs, "CropLeft", &l) && crs_double (xp.crs, "CropTop", &t) &&
            crs_double (xp.crs, "CropRight", &r) && crs_double (xp.crs, "CropBottom", &b) &&
            r - l >= 0.02 && b - t >= 0.02)
          {
            crs_double (xp.crs, "CropAngle", &angle);
            s->crop[0]    = CLAMP (l, 0.0, 1.0);
            s->crop[1]    = CLAMP (t, 0.0, 1.0);
            s->crop[2]    = CLAMP (r - l, 0.02, 1.0 - s->crop[0]);
            s->crop[3]    = CLAMP (b - t, 0.02, 1.0 - s->crop[1]);
            s->straighten = CLAMP (-angle, -45.0, 45.0);
            any = TRUE;
          }
      }

      if (any)
        source = _("Lightroom / Camera Raw");
    }

  /* --- darktable --- */
  if (xp.dt_seen)
    {
      gboolean any = FALSE;

      for (i = 0; i < 3; i++)
        {
          guint8 *p;
          gsize   n = 0;

          if (! xp.dt_params[i] || ! (p = dt_decode (xp.dt_params[i], &n)))
            continue;

          if (i == 0 && n >= 12)                         /* temperature */
            {
              gfloat r = le_float (p), g = le_float (p + 4), b = le_float (p + 8);

              gdouble mr = (gdouble) r / g, mb = (gdouble) b / g;

              if (isfinite (r) && isfinite (g) && isfinite (b) &&
                  g >= 1e-3f && r > 0 && b > 0 && r < 64 && g < 64 && b < 64 &&
                  isfinite (mr) && isfinite (mb))
                {
                  s->wb_mode   = WB_MULTIPLIERS;
                  s->wb_mul[0] = CLAMP (mr, 0.05, 20.0);
                  s->wb_mul[1] = 1.0;
                  s->wb_mul[2] = CLAMP (mb, 0.05, 20.0);
                  any = TRUE;
                }
            }
          else if (i == 1 && n >= 12 && xp.dt_version[1] >= 5)   /* exposure */
            {
              gfloat ev = le_float (p + 8);   /* mode, black, exposure, ... */

              if (isfinite (ev) && fabsf (ev) <= 18.0f)
                {
                  set_exposure (s, ev);
                  any = TRUE;
                }
            }
          else if (i == 2)                                       /* lens */
            {
              s->lens_distortion = s->lens_vignetting = s->lens_tca = TRUE;
              any = TRUE;
            }

          g_free (p);
        }

      if (any)
        source = source ? _("Lightroom and darktable") : _("darktable");
    }

done:
  for (i = 0; i < 3; i++)
    g_free (xp.dt_params[i]);
  g_free (xp.element);
  g_hash_table_unref (xp.crs);

  return source;
}

/* Sidecar next to @raw_path: darktable "name.ext.xmp", then Lightroom
 * "name.xmp" (any case).  Returns the path or NULL.
 */
gchar *
rawheic_xmp_find (const gchar *raw_path)
{
  gchar *cand[4];
  gchar *dot, *base;
  gint   i;

  cand[0] = g_strconcat (raw_path, ".xmp", NULL);
  cand[1] = g_strconcat (raw_path, ".XMP", NULL);
  base    = g_strdup (raw_path);
  dot     = strrchr (base, '.');
  if (dot && ! strpbrk (dot, "\\/"))
    *dot = '\0';
  cand[2] = g_strconcat (base, ".xmp", NULL);
  cand[3] = g_strconcat (base, ".XMP", NULL);
  g_free (base);

  for (i = 0; i < 4; i++)
    if (g_file_test (cand[i], G_FILE_TEST_IS_REGULAR))
      {
        gchar *found = g_strdup (cand[i]);
        gint   k;

        for (k = 0; k < 4; k++)
          g_free (cand[k]);
        return found;
      }

  for (i = 0; i < 4; i++)
    g_free (cand[i]);

  return NULL;
}

const gchar *
rawheic_xmp_apply (const gchar *raw_path,
                   RawSettings *s)
{
  gchar       *xmp = rawheic_xmp_find (raw_path);
  gchar       *data = NULL;
  gsize        len = 0;
  const gchar *source = NULL;

  GStatBuf     st;

  /* check the size first: never read a huge "sidecar" into memory */
  if (xmp && g_stat (xmp, &st) == 0 && st.st_size >= 0 && st.st_size <= MAX_XMP_SIZE &&
      g_file_get_contents (xmp, &data, &len, NULL) && len <= MAX_XMP_SIZE)
    source = rawheic_xmp_apply_data (data, len, s);

  g_free (data);
  g_free (xmp);

  return source;
}

/* --- writing ------------------------------------------------------------- */

#define XMP_MARKER "gimp-raw-heic"

/* "photo.xmp" next to @raw_path (Lightroom's convention). */
gchar *
rawheic_xmp_target (const gchar *raw_path)
{
  gchar *base = g_strdup (raw_path);
  gchar *dot  = strrchr (base, '.');
  gchar *out;

  if (dot && ! strpbrk (dot, "\\/"))
    *dot = '\0';
  out = g_strconcat (base, ".xmp", NULL);
  g_free (base);

  return out;
}

/* Write the settings into a sidecar Lightroom / Camera Raw and this
 * plug-in can read.  A sidecar written by another program is never
 * replaced: it may hold someone's whole edit.
 */
gboolean
rawheic_xmp_write (const gchar        *raw_path,
                   const RawSettings  *s,
                   GError            **error)
{
  gchar       *target = rawheic_xmp_target (raw_path);
  gchar       *old = NULL, *text, *b64, *xml;
  const gchar *wb;
  gchar        temp[G_ASCII_DTOSTR_BUF_SIZE], tint[G_ASCII_DTOSTR_BUF_SIZE];
  gchar        ev[G_ASCII_DTOSTR_BUF_SIZE], nr[G_ASCII_DTOSTR_BUF_SIZE];
  gchar        cl[G_ASCII_DTOSTR_BUF_SIZE], ct[G_ASCII_DTOSTR_BUF_SIZE];
  gchar        cr[G_ASCII_DTOSTR_BUF_SIZE], cb[G_ASCII_DTOSTR_BUF_SIZE];
  gchar        ca[G_ASCII_DTOSTR_BUF_SIZE];
  gboolean     ok;

  if (g_file_get_contents (target, &old, NULL, NULL) && ! strstr (old, XMP_MARKER))
    {
      gchar *name = g_filename_display_name (target);

      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_EXIST,
                   _("'%s' was written by another program and is kept. Remove it "
                     "first to save this plug-in's settings there."), name);
      g_free (name);
      g_free (old);
      g_free (target);
      return FALSE;
    }
  g_free (old);

  /* the full settings, without the RAW path */
  text = raw_settings_serialize (s, "");
  b64  = g_base64_encode ((const guchar *) text, strlen (text));
  g_free (text);

  switch (s->wb_mode)
    {
    case WB_CAMERA: wb = "As Shot"; break;
    case WB_AUTO:   wb = "Auto";    break;
    default:        wb = "Custom";  break;
    }

  g_ascii_formatd (temp, sizeof temp, "%.0f", s->wb_temperature);
  g_ascii_formatd (tint, sizeof tint, "%.0f", s->wb_tint);
  g_ascii_formatd (ev,   sizeof ev,   "%.2f",
                   s->exposure + log2 (MAX (s->brightness, 0.01)));
  g_ascii_formatd (nr,   sizeof nr,   "%.0f", CLAMP (s->denoise / 10.0, 0.0, 100.0));
  g_ascii_formatd (cl,   sizeof cl,   "%.6f", s->crop[0]);
  g_ascii_formatd (ct,   sizeof ct,   "%.6f", s->crop[1]);
  g_ascii_formatd (cr,   sizeof cr,   "%.6f", s->crop[0] + s->crop[2]);
  g_ascii_formatd (cb,   sizeof cb,   "%.6f", s->crop[1] + s->crop[3]);
  g_ascii_formatd (ca,   sizeof ca,   "%.3f", -s->straighten);

  xml = g_strdup_printf (
    "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" x:xmptk=\"" XMP_MARKER " " PLUGIN_VERSION "\">\n"
    " <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n"
    "  <rdf:Description rdf:about=\"\"\n"
    "    xmlns:crs=\"http://ns.adobe.com/camera-raw-settings/1.0/\"\n"
    "    xmlns:rawheic=\"https://github.com/gimp-raw-heic/ns/1.0/\"\n"
    "    crs:Version=\"15.0\"\n"
    "    crs:ProcessVersion=\"11.0\"\n"
    "    crs:WhiteBalance=\"%s\"\n"
    "%s%s%s%s%s"
    "    crs:Exposure2012=\"%s\"\n"
    "    crs:LuminanceSmoothing=\"%s\"\n"
    "    crs:LensProfileEnable=\"%d\"\n"
    "    crs:AutoLateralCA=\"%d\"\n"
    "    crs:HasCrop=\"%s\"\n"
    "    crs:CropLeft=\"%s\" crs:CropTop=\"%s\" crs:CropRight=\"%s\" crs:CropBottom=\"%s\"\n"
    "    crs:CropAngle=\"%s\"\n"
    "    rawheic:settings=\"%s\"/>\n"
    " </rdf:RDF>\n"
    "</x:xmpmeta>\n",
    wb,
    s->wb_mode == WB_MANUAL ? "    crs:Temperature=\"" : "",
    s->wb_mode == WB_MANUAL ? temp : "",
    s->wb_mode == WB_MANUAL ? "\" crs:Tint=\"" : "",
    s->wb_mode == WB_MANUAL ? tint : "",
    s->wb_mode == WB_MANUAL ? "\"\n" : "",
    ev, nr,
    (s->lens_distortion || s->lens_vignetting) ? 1 : 0,
    s->lens_tca ? 1 : 0,
    rawheic_geometry_active (s) ? "True" : "False",
    cl, ct, cr, cb, ca, b64);

  ok = g_file_set_contents (target, xml, -1, error);

  g_free (xml);
  g_free (b64);
  g_free (target);

  return ok;
}
