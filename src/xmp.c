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

              if (isfinite (r) && isfinite (g) && isfinite (b) &&
                  r > 0 && g > 0 && b > 0 && r < 64 && g < 64 && b < 64)
                {
                  s->wb_mode   = WB_MULTIPLIERS;
                  s->wb_mul[0] = r / g;
                  s->wb_mul[1] = 1.0;
                  s->wb_mul[2] = b / g;
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

  if (xmp && g_file_get_contents (xmp, &data, &len, NULL) && len <= MAX_XMP_SIZE)
    source = rawheic_xmp_apply_data (data, len, s);

  g_free (data);
  g_free (xmp);

  return source;
}
