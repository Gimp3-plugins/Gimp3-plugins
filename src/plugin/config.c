#include "config.h"
#include <json-glib/json-glib.h>
#include <string.h>
#include <gio/gio.h>

#ifdef PSHOST_STANDALONE
static char *base_dir (void) { return g_build_filename (g_get_user_config_dir (), "GIMP", "3.2", NULL); }
#else
#include <libgimp/gimp.h>
static char *base_dir (void) { return g_strdup (gimp_directory ()); }
#endif

char *ps_config_dir (void) {
  const char *o = g_getenv ("PSHOST_CONFIG_DIR");
  if (o && *o) return g_strdup (o);
  char *b = base_dir (), *d = g_build_filename (b, "pshost", NULL); g_free (b); return d;
}

PsDir *ps_dir_new (const char *path, gboolean recursive) { PsDir *d = g_new0 (PsDir, 1); d->path = g_strdup (path); d->recursive = recursive; return d; }
void ps_dir_free (PsDir *d) { if (d) { g_free (d->path); g_free (d); } }
void ps_item_free (PsItem *i) {
  if (!i) return;
  g_free (i->path); g_free (i->name); g_free (i->category); g_free (i->entry); g_free (i->kind); g_free (i->detail); g_free (i->proc_name); g_free (i);
}

char *ps_item_proc_name (const char *path, const char *entry, const char *name) {
  char *key = g_strdup_printf ("%s|%s|%s", path ? path : "", entry ? entry : "", name ? name : "");
  char *h = g_compute_checksum_for_string (G_CHECKSUM_MD5, key, -1);
  char *r = g_strdup_printf ("pshost-filter-%.12s", h);
  g_free (key); g_free (h); return r;
}

static void ignored_free (PsIgnored *i) { if (i) { g_free (i->path); g_free (i->name); g_free (i); } }

static PsConfig *defaults (void) {
  PsConfig *c = g_new0 (PsConfig, 1);
  c->dirs = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_dir_free);
  c->items = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_item_free);
  c->ignored = g_ptr_array_new_with_free_func ((GDestroyNotify) ignored_free);
  c->language = g_strdup ("auto"); c->probe_timeout_ms = 10000; c->default_recursive = TRUE;
  return c;
}

void ps_config_free (PsConfig *c) {
  if (!c) return;
  g_ptr_array_free (c->dirs, TRUE); g_ptr_array_free (c->items, TRUE); g_ptr_array_free (c->ignored, TRUE); g_free (c->language); g_free (c);
}

static Pe8Verdict verdict_from (const char *s) { return !g_strcmp0 (s, "OK") ? PE8_VERDICT_OK : !g_strcmp0 (s, "WARN") ? PE8_VERDICT_WARN : PE8_VERDICT_NO; }
static Pe8Reason reason_from (const char *s) {
  for (int r = 0; r <= PE8_R_UNSUPPORTED_CB; r++) if (!g_strcmp0 (pe8_reason_key ((Pe8Reason) r), s)) return (Pe8Reason) r;
  return PE8_R_NONE;
}
/* Type-safe accessors: a hand-edited or corrupted config.json must never trigger json-glib assertions. */
static JsonNode *member (JsonObject *o, const char *k) { return json_object_has_member (o, k) ? json_object_get_member (o, k) : NULL; }
static const char *obj_str (JsonObject *o, const char *k) {
  JsonNode *n = member (o, k);
  return n && JSON_NODE_HOLDS_VALUE (n) && json_node_get_value_type (n) == G_TYPE_STRING ? json_node_get_string (n) : NULL;
}
static gboolean obj_int (JsonObject *o, const char *k, gint64 *out) {
  JsonNode *n = member (o, k);
  if (!n || !JSON_NODE_HOLDS_VALUE (n) || json_node_get_value_type (n) != G_TYPE_INT64) return FALSE;
  *out = json_node_get_int (n); return TRUE;
}
static gboolean obj_bool (JsonObject *o, const char *k, gboolean *out) {
  JsonNode *n = member (o, k);
  if (!n || !JSON_NODE_HOLDS_VALUE (n) || json_node_get_value_type (n) != G_TYPE_BOOLEAN) return FALSE;
  *out = json_node_get_boolean (n); return TRUE;
}
static JsonArray *obj_array (JsonObject *o, const char *k) { JsonNode *n = member (o, k); return n && JSON_NODE_HOLDS_ARRAY (n) ? json_node_get_array (n) : NULL; }
static JsonObject *arr_object (JsonArray *a, guint i) { JsonNode *n = json_array_get_element (a, i); return n && JSON_NODE_HOLDS_OBJECT (n) ? json_node_get_object (n) : NULL; }

PsConfig *ps_config_load (void) {
  PsConfig *c = defaults ();
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "config.json", NULL);
  JsonParser *p = json_parser_new ();
  GError *err = NULL;
  if (json_parser_load_from_file (p, file, &err)) {
    JsonNode *root = json_parser_get_root (p);
    if (root && JSON_NODE_HOLDS_OBJECT (root)) {
      JsonObject *o = json_node_get_object (root);
      const char *s; gint64 iv; gboolean bv; JsonArray *a;
      if ((s = obj_str (o, "language")) && (!strcmp (s, "pl") || !strcmp (s, "en") || !strcmp (s, "auto"))) { g_free (c->language); c->language = g_strdup (s); }
      if (obj_int (o, "probe_timeout_ms", &iv) && iv >= 1000 && iv <= 300000) c->probe_timeout_ms = (int) iv;
      if (obj_bool (o, "default_recursive", &bv)) c->default_recursive = bv;
      if ((a = obj_array (o, "directories")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = arr_object (a, i);
          if (d && obj_str (d, "path")) { gboolean rec = TRUE; obj_bool (d, "recursive", &rec); g_ptr_array_add (c->dirs, ps_dir_new (obj_str (d, "path"), rec)); }
        }
      if ((a = obj_array (o, "ignored")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = arr_object (a, i);
          if (d && obj_str (d, "path")) { PsIgnored *ig = g_new0 (PsIgnored, 1); ig->path = g_strdup (obj_str (d, "path")); ig->name = g_strdup (obj_str (d, "name") ? obj_str (d, "name") : ""); g_ptr_array_add (c->ignored, ig); }
        }
      if ((a = obj_array (o, "plugins")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = arr_object (a, i);
          if (!d || !obj_str (d, "path")) continue;
          PsItem *it = g_new0 (PsItem, 1);
          it->path = g_strdup (obj_str (d, "path")); it->name = g_strdup (obj_str (d, "name")); it->category = g_strdup (obj_str (d, "category"));
          it->entry = g_strdup (obj_str (d, "entry")); it->kind = g_strdup (obj_str (d, "kind")); it->detail = g_strdup (obj_str (d, "detail"));
          it->verdict = verdict_from (obj_str (d, "verdict")); it->reason = reason_from (obj_str (d, "reason"));
          if (!obj_bool (d, "enabled", &it->enabled)) it->enabled = it->verdict != PE8_VERDICT_NO;
          if (obj_int (d, "mtime", &iv)) it->mtime = iv;
          if (obj_int (d, "size", &iv)) it->size = iv;
          it->proc_name = ps_item_proc_name (it->path, it->entry, it->name);
          g_ptr_array_add (c->items, it);
        }
    }
  } else if (err && !g_error_matches (err, G_FILE_ERROR, G_FILE_ERROR_NOENT)) {
    g_printerr ("pshost: cannot read config (%s), using defaults\n", err->message);
  }
  g_clear_error (&err); g_object_unref (p); g_free (file); g_free (dir);
  return c;
}

gboolean ps_config_save (const PsConfig *c) {
  JsonBuilder *b = json_builder_new ();
  json_builder_begin_object (b);
  json_builder_set_member_name (b, "version"); json_builder_add_int_value (b, 1);
  json_builder_set_member_name (b, "language"); json_builder_add_string_value (b, c->language);
  json_builder_set_member_name (b, "probe_timeout_ms"); json_builder_add_int_value (b, c->probe_timeout_ms);
  json_builder_set_member_name (b, "default_recursive"); json_builder_add_boolean_value (b, c->default_recursive);
  json_builder_set_member_name (b, "directories"); json_builder_begin_array (b);
  for (guint i = 0; i < c->dirs->len; i++) {
    PsDir *d = g_ptr_array_index (c->dirs, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, d->path);
    json_builder_set_member_name (b, "recursive"); json_builder_add_boolean_value (b, d->recursive);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_set_member_name (b, "ignored"); json_builder_begin_array (b);
  for (guint i = 0; i < c->ignored->len; i++) {
    PsIgnored *ig = g_ptr_array_index (c->ignored, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, ig->path);
    json_builder_set_member_name (b, "name"); json_builder_add_string_value (b, ig->name);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_set_member_name (b, "plugins"); json_builder_begin_array (b);
  for (guint i = 0; i < c->items->len; i++) {
    PsItem *it = g_ptr_array_index (c->items, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, it->path);
    json_builder_set_member_name (b, "name"); json_builder_add_string_value (b, it->name ? it->name : "");
    json_builder_set_member_name (b, "category"); json_builder_add_string_value (b, it->category ? it->category : "");
    json_builder_set_member_name (b, "entry"); json_builder_add_string_value (b, it->entry ? it->entry : "");
    json_builder_set_member_name (b, "kind"); json_builder_add_string_value (b, it->kind ? it->kind : "");
    json_builder_set_member_name (b, "verdict"); json_builder_add_string_value (b, pe8_verdict_key (it->verdict));
    json_builder_set_member_name (b, "reason"); json_builder_add_string_value (b, pe8_reason_key (it->reason));
    json_builder_set_member_name (b, "detail"); json_builder_add_string_value (b, it->detail ? it->detail : "");
    json_builder_set_member_name (b, "enabled"); json_builder_add_boolean_value (b, it->enabled);
    json_builder_set_member_name (b, "mtime"); json_builder_add_int_value (b, it->mtime);
    json_builder_set_member_name (b, "size"); json_builder_add_int_value (b, it->size);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_end_object (b);
  JsonGenerator *g = json_generator_new ();
  JsonNode *root = json_builder_get_root (b);
  json_generator_set_root (g, root); json_generator_set_pretty (g, TRUE);
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "config.json", NULL), *tmp = g_strconcat (file, ".tmp", NULL);
  g_mkdir_with_parents (dir, 0700);
  gboolean ok = json_generator_to_file (g, tmp, NULL);
  if (ok) { GFile *a = g_file_new_for_path (tmp), *z = g_file_new_for_path (file); ok = g_file_move (a, z, G_FILE_COPY_OVERWRITE, NULL, NULL, NULL, NULL); g_object_unref (a); g_object_unref (z); }
  json_node_unref (root); g_object_unref (g); g_object_unref (b); g_free (tmp); g_free (file); g_free (dir);
  return ok;
}

PsItem *ps_config_find_item (const PsConfig *c, const char *path, const char *entry, const char *name) {
  for (guint i = 0; i < c->items->len; i++) {
    PsItem *it = g_ptr_array_index (c->items, i);
    if (!g_strcmp0 (it->path, path) && !g_strcmp0 (it->entry, entry) && !g_strcmp0 (it->name, name)) return it;
  }
  return NULL;
}

gboolean ps_config_is_ignored (const PsConfig *c, const char *path, const char *name) {
  for (guint i = 0; i < c->ignored->len; i++) {
    PsIgnored *ig = g_ptr_array_index (c->ignored, i);
    if (!g_ascii_strcasecmp (ig->path, path) && !g_strcmp0 (ig->name, name ? name : "")) return TRUE;
  }
  return FALSE;
}
void ps_config_ignore_item (PsConfig *c, const PsItem *it) {
  if (!ps_config_is_ignored (c, it->path, it->name)) {
    PsIgnored *ig = g_new0 (PsIgnored, 1); ig->path = g_strdup (it->path); ig->name = g_strdup (it->name ? it->name : ""); g_ptr_array_add (c->ignored, ig);
  }
  for (guint i = 0; i < c->items->len; i++) if (g_ptr_array_index (c->items, i) == it) { g_ptr_array_remove_index (c->items, i); break; }
}
void ps_config_clear_ignored (PsConfig *c) { g_ptr_array_set_size (c->ignored, 0); }

static gboolean sep (char ch) { return ch == '\\' || ch == '/'; }
/* TRUE when `path` is located below `dir` (case-insensitive, "/" and "\" are equivalent, trailing separators ignored). */
gboolean ps_path_is_under (const char *path, const char *dir) {
  size_t n = strlen (dir);
  while (n > 0 && sep (dir[n - 1])) n--;
  if (n == 0 || strlen (path) <= n) return FALSE;
  for (size_t i = 0; i < n; i++) {
    if (sep (dir[i]) && sep (path[i])) continue;
    if (g_ascii_tolower (dir[i]) != g_ascii_tolower (path[i])) return FALSE;
  }
  return sep (path[n]);
}

void ps_config_prune_items (PsConfig *c) {
  for (guint i = c->items->len; i-- > 0;) {
    PsItem *it = g_ptr_array_index (c->items, i); gboolean keep = FALSE;
    for (guint k = 0; k < c->dirs->len && !keep; k++) keep = ps_path_is_under (it->path, ((PsDir *) g_ptr_array_index (c->dirs, k))->path);
    if (!keep) g_ptr_array_remove_index (c->items, i);
  }
}

/* ------------------------------------------------------------------ language & translations */
Pe8Lang ps_config_language (const PsConfig *c) {
  if (!g_strcmp0 (c->language, "pl")) return PE8_LANG_PL;
  if (!g_strcmp0 (c->language, "en")) return PE8_LANG_EN;
  const char *const *names = g_get_language_names ();
  for (int i = 0; names[i]; i++) { if (g_str_has_prefix (names[i], "pl")) return PE8_LANG_PL; if (g_str_has_prefix (names[i], "en")) return PE8_LANG_EN; }
  return PE8_LANG_EN;
}

