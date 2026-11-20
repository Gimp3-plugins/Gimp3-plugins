#include "registry.h"
#include <json-glib/json-glib.h>
#include <string.h>
#include <glib/gstdio.h>

char *ps_escape_mnemonic (const char *s) {      /* '_' is the mnemonic marker in GIMP menu labels */
  GString *g = g_string_new (NULL);
  for (const char *p = s; *p; p++) { if (*p == '_') g_string_append (g, "__"); else g_string_append_c (g, *p); }
  return g_string_free (g, FALSE);
}

static char *menu_for (const PsItem *it) {
  const char *cat = it->category && *it->category && strcmp (it->category, "-") != 0 ? it->category : (ps_get_language () == PE8_LANG_PL ? "Inne" : "Other");
  char *c = g_strdup (cat);
  for (char *p = c; *p; p++) if (*p == '/' || *p == '\\') *p = '-';
  g_strstrip (c);
  char *m = g_strconcat ("<Image>/Filters/Photoshop/", c, NULL);
  g_free (c);
  return m;
}

static gint reg_cmp (gconstpointer a, gconstpointer b) {
  const PsReg *x = *(PsReg *const *) a, *y = *(PsReg *const *) b;
  int c = g_utf8_collate (x->menu, y->menu);
  return c ? c : g_utf8_collate (x->label, y->label);
}

GPtrArray *ps_registry_build (const PsConfig *c) {
  GPtrArray *regs = g_ptr_array_new_with_free_func (NULL);
  for (guint i = 0; i < c->items->len; i++) {
    const PsItem *it = g_ptr_array_index (c->items, i);
    if (it->verdict == PE8_VERDICT_NO || !it->enabled || !g_file_test (it->path, G_FILE_TEST_EXISTS)) continue;
    PsReg *r = g_new0 (PsReg, 1);
    r->proc = g_strdup (it->proc_name); r->menu = menu_for (it); r->item = it;
    r->label = g_strdup (it->name && *it->name ? it->name : "?");
    g_ptr_array_add (regs, r);
  }
  /* unique labels inside one menu: append the file name, then a counter */
  for (guint i = 0; i < regs->len; i++) {
    PsReg *a = g_ptr_array_index (regs, i); gboolean dup = FALSE;
    for (guint j = 0; j < regs->len; j++) { PsReg *b = g_ptr_array_index (regs, j); if (i != j && !g_strcmp0 (a->menu, b->menu) && !g_strcmp0 (a->label, b->label)) dup = TRUE; }
    if (dup) { char *base = g_path_get_basename (a->item->path), *n = g_strdup_printf ("%s (%s)", a->label, base); g_free (base); g_free (a->label); a->label = n; }
  }
  for (guint i = 0; i < regs->len; i++) {
    PsReg *a = g_ptr_array_index (regs, i); int n = 1;
    for (guint j = 0; j < i; j++) { PsReg *b = g_ptr_array_index (regs, j); if (!g_strcmp0 (a->menu, b->menu) && !g_strcmp0 (a->label, b->label)) n++; }
    if (n > 1) { char *l = g_strdup_printf ("%s #%d", a->label, n); g_free (a->label); a->label = l; }
  }
  g_ptr_array_sort (regs, reg_cmp);
  return regs;
}

void ps_registry_free (GPtrArray *regs) {
  if (!regs) return;
  for (guint i = 0; i < regs->len; i++) { PsReg *r = g_ptr_array_index (regs, i); g_free (r->proc); g_free (r->label); g_free (r->menu); g_free (r); }
  g_ptr_array_free (regs, TRUE);
}

static gint str_cmp (gconstpointer a, gconstpointer b) { return strcmp (*(char *const *) a, *(char *const *) b); }

char *ps_registry_signature (const GPtrArray *regs, Pe8Lang lang) {
  GPtrArray *lines = g_ptr_array_new_with_free_func (g_free);
  for (guint i = 0; i < regs->len; i++) { const PsReg *r = g_ptr_array_index (regs, i); g_ptr_array_add (lines, g_strdup_printf ("%s|%s|%s", r->proc, r->menu, r->label)); }
  g_ptr_array_sort (lines, str_cmp);
  GString *g = g_string_new (lang == PE8_LANG_PL ? "pl\n" : "en\n");
  for (guint i = 0; i < lines->len; i++) { g_string_append (g, g_ptr_array_index (lines, i)); g_string_append_c (g, '\n'); }
  char *sig = g_compute_checksum_for_string (G_CHECKSUM_SHA256, g->str, -1);
  g_string_free (g, TRUE); g_ptr_array_free (lines, TRUE);
  return sig;
}

gboolean ps_registry_write_state (const GPtrArray *regs, Pe8Lang lang) {
  char *sig = ps_registry_signature (regs, lang);
  JsonBuilder *b = json_builder_new ();
  json_builder_begin_object (b);
  json_builder_set_member_name (b, "signature"); json_builder_add_string_value (b, sig);
  json_builder_set_member_name (b, "language"); json_builder_add_string_value (b, lang == PE8_LANG_PL ? "pl" : "en");
  json_builder_set_member_name (b, "filters"); json_builder_begin_array (b);
  for (guint i = 0; i < regs->len; i++) {
    const PsReg *r = g_ptr_array_index (regs, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "proc"); json_builder_add_string_value (b, r->proc);
    json_builder_set_member_name (b, "menu"); json_builder_add_string_value (b, r->menu);
    json_builder_set_member_name (b, "label"); json_builder_add_string_value (b, r->label);
    json_builder_end_object (b);
  }
  json_builder_end_array (b); json_builder_end_object (b);
  JsonGenerator *g = json_generator_new (); JsonNode *root = json_builder_get_root (b);
  json_generator_set_root (g, root); json_generator_set_pretty (g, TRUE);
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "registered.json", NULL);
  g_mkdir_with_parents (dir, 0700);
  gboolean ok = json_generator_to_file (g, file, NULL);
  json_node_unref (root); g_object_unref (g); g_object_unref (b); g_free (file); g_free (dir); g_free (sig);
  return ok;
}

char *ps_registry_read_signature (void) {
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "registered.json", NULL), *sig = NULL;
  JsonParser *p = json_parser_new ();
  if (json_parser_load_from_file (p, file, NULL)) {
    JsonNode *root = json_parser_get_root (p);
    if (root && JSON_NODE_HOLDS_OBJECT (root)) { JsonObject *o = json_node_get_object (root); if (json_object_has_member (o, "signature")) sig = g_strdup (json_object_get_string_member (o, "signature")); }
  }
  g_object_unref (p); g_free (file); g_free (dir);
  return sig;
}

gboolean ps_registry_needs_restart (const PsConfig *c) {
  GPtrArray *regs = ps_registry_build (c);
  char *want = ps_registry_signature (regs, ps_config_language (c)), *have = ps_registry_read_signature ();
  gboolean needs = have ? g_strcmp0 (want, have) != 0 : regs->len > 0;
  g_free (want); g_free (have); ps_registry_free (regs);
  return needs;
}
