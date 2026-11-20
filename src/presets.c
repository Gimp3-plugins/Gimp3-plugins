/* gimp-raw-heic -- named development presets
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Built-in presets live in code; user presets are key files in
 * <gimp profile>/gimp-raw-heic/presets/.  A preset never stores the
 * neutral-point rectangle: that belongs to one particular photo.
 */

#include "config.h"

#include <string.h>

#include <glib/gstdio.h>

#include "rawheic.h"

#define PRESET_GROUP "preset"
#define MAX_NAME     64

typedef struct
{
  const gchar *name;
  void       (*apply) (RawSettings *s);
} BuiltinPreset;

static void
builtin_default (RawSettings *s)
{
  raw_settings_defaults (s);
}

static void
builtin_night (RawSettings *s)
{
  raw_settings_defaults (s);
  s->denoise       = 400.0;
  s->fbdd          = 1;
  s->hot_pixels    = TRUE;
  s->median_passes = 1;
  s->highlight     = HL_BLEND;
}

static void
builtin_fast (RawSettings *s)
{
  raw_settings_defaults (s);
  s->half_size = TRUE;
  s->demosaic  = 0;
}

static const BuiltinPreset builtins[] =
{
  { N_("Default"),             builtin_default },
  { N_("Night / high ISO"),    builtin_night   },
  { N_("Fast preview"),        builtin_fast    },
};

static gchar *
presets_dir (void)
{
  return g_build_filename (gimp_directory (), "gimp-raw-heic", "presets", NULL);
}

/* A safe file name: no path separators, reserved characters, control
 * characters, leading dots or trailing dots/spaces (Windows).
 */
gchar *
raw_presets_file_name (const gchar *name)
{
  GString     *out = g_string_new (NULL);
  const gchar *p;
  gsize        n = 0;

  for (p = name; p && *p && n < MAX_NAME; p = g_utf8_next_char (p), n++)
    {
      gunichar c = g_utf8_get_char (p);

      if (c < 0x20 || strchr ("\\/:*?\"<>|", (gint) c) != NULL)
        g_string_append_c (out, '_');
      else
        g_string_append_unichar (out, c);
    }

  while (out->len && (out->str[out->len - 1] == '.' || out->str[out->len - 1] == ' '))
    g_string_truncate (out, out->len - 1);
  while (out->len && (out->str[0] == '.' || out->str[0] == ' '))
    g_string_erase (out, 0, 1);

  if (out->len == 0)
    {
      g_string_free (out, TRUE);
      return NULL;
    }

  g_string_append (out, ".ini");

  return g_string_free (out, FALSE);
}

static gchar *
preset_path (const gchar *name)
{
  gchar *file = raw_presets_file_name (name);
  gchar *dir, *path;

  if (! file)
    return NULL;

  dir  = presets_dir ();
  path = g_build_filename (dir, file, NULL);
  g_free (dir);
  g_free (file);

  return path;
}

gboolean
raw_presets_is_builtin (const gchar *name)
{
  gint i;

  for (i = 0; i < (gint) G_N_ELEMENTS (builtins); i++)
    if (! g_strcmp0 (name, _(builtins[i].name)) || ! g_strcmp0 (name, builtins[i].name))
      return TRUE;

  return FALSE;
}

static gint
compare_names (gconstpointer a,
               gconstpointer b)
{
  return g_utf8_collate (a, b);
}

/* Built-in presets first (in their order), then user presets sorted. */
GList *
raw_presets_list (void)
{
  GList *list = NULL, *user = NULL;
  gchar *dir  = presets_dir ();
  GDir  *d;
  gint   i;

  for (i = 0; i < (gint) G_N_ELEMENTS (builtins); i++)
    list = g_list_append (list, g_strdup (_(builtins[i].name)));

  d = g_dir_open (dir, 0, NULL);
  if (d)
    {
      const gchar *fn;

      while ((fn = g_dir_read_name (d)))
        {
          gchar    *path;
          GKeyFile *kf;
          gchar    *name;

          if (! g_str_has_suffix (fn, ".ini"))
            continue;

          path = g_build_filename (dir, fn, NULL);
          kf   = g_key_file_new ();
          if (g_key_file_load_from_file (kf, path, 0, NULL) &&
              (name = g_key_file_get_string (kf, PRESET_GROUP, "name", NULL)))
            {
              if (raw_presets_is_builtin (name))
                g_free (name);
              else
                user = g_list_insert_sorted (user, name, compare_names);
            }
          g_key_file_free (kf);
          g_free (path);
        }
      g_dir_close (d);
    }

  g_free (dir);

  return g_list_concat (list, user);
}

/* Keeps @s->spot: the neutral point belongs to the photo. */
gboolean
raw_presets_load (const gchar *name,
                  RawSettings *s)
{
  gdouble  spot[4];
  gchar   *path, *data = NULL;
  gboolean ok = FALSE;
  gint     i;

  memcpy (spot, s->spot, sizeof spot);

  for (i = 0; i < (gint) G_N_ELEMENTS (builtins); i++)
    if (! g_strcmp0 (name, _(builtins[i].name)) || ! g_strcmp0 (name, builtins[i].name))
      {
        builtins[i].apply (s);
        memcpy (s->spot, spot, sizeof spot);
        return TRUE;
      }

  path = preset_path (name);
  if (path && g_file_get_contents (path, &data, NULL, NULL))
    {
      ok = raw_settings_deserialize (s, data, NULL);
      memcpy (s->spot, spot, sizeof spot);
    }

  g_free (data);
  g_free (path);

  return ok;
}

gboolean
raw_presets_save (const gchar        *name,
                  const RawSettings  *s,
                  GError            **error)
{
  gchar    *path, *dir, *text, *data;
  GKeyFile *kf;
  gboolean  ok;

  if (! name || ! *name || g_utf8_strlen (name, -1) > MAX_NAME)
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                   _("A preset name must have 1 to %d characters."), MAX_NAME);
      return FALSE;
    }
  if (raw_presets_is_builtin (name))
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_EXIST,
                   _("'%s' is a built-in preset; choose another name."), name);
      return FALSE;
    }

  path = preset_path (name);
  if (! path)
    {
      g_set_error (error, G_FILE_ERROR, G_FILE_ERROR_INVAL,
                   _("'%s' cannot be used as a preset name."), name);
      return FALSE;
    }

  dir = presets_dir ();
  g_mkdir_with_parents (dir, 0700);
  g_free (dir);

  text = raw_settings_serialize (s, "");
  kf   = g_key_file_new ();
  g_key_file_load_from_data (kf, text, -1, 0, NULL);
  g_key_file_remove_key (kf, "raw", "source", NULL);
  g_key_file_remove_key (kf, "raw", "spot", NULL);
  g_key_file_set_string (kf, PRESET_GROUP, "name", name);
  data = g_key_file_to_data (kf, NULL, NULL);

  ok = g_file_set_contents (path, data, -1, error);

  g_free (data);
  g_key_file_free (kf);
  g_free (text);
  g_free (path);

  return ok;
}

gboolean
raw_presets_delete (const gchar *name)
{
  gchar   *path;
  gboolean ok;

  if (raw_presets_is_builtin (name))
    return FALSE;

  path = preset_path (name);
  ok   = path && g_remove (path) == 0;
  g_free (path);

  return ok;
}
