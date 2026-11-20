#include "scan.h"
#include <string.h>
#include <glib/gstdio.h>
#ifdef _WIN32
#include <windows.h>
#endif

static void collect (const char *dir, gboolean recursive, GPtrArray *out, int depth) {
  GDir *d = g_dir_open (dir, 0, NULL);
  if (!d || depth > 16) { if (d) g_dir_close (d); return; }
  const char *n;
  while ((n = g_dir_read_name (d)) != NULL) {
    char *full = g_build_filename (dir, n, NULL);
    if (g_file_test (full, G_FILE_TEST_IS_DIR)) {
      if (recursive && !g_file_test (full, G_FILE_TEST_IS_SYMLINK)) collect (full, recursive, out, depth + 1);
      g_free (full);
    } else if (g_str_has_suffix (n, ".8bf") || g_str_has_suffix (n, ".8BF") || g_ascii_strcasecmp (n + (strlen (n) > 4 ? strlen (n) - 4 : 0), ".8bf") == 0) {
      g_ptr_array_add (out, full);
    } else g_free (full);
  }
  g_dir_close (d);
}

static gint cmp_str (gconstpointer a, gconstpointer b) { return g_ascii_strcasecmp (*(char *const *) a, *(char *const *) b); }

GPtrArray *ps_collect_files (const char *dir, gboolean recursive) {
  GPtrArray *a = g_ptr_array_new_with_free_func (g_free);
  collect (dir, recursive, a, 0);
  g_ptr_array_sort (a, cmp_str);
  return a;
}

static PsItem *item_from (const Pe8Plugin *p, const char *path, const char *fallback_name, Pe8Reason file_reason, GStatBuf *st) {
  PsItem *it = g_new0 (PsItem, 1);
  it->path = g_strdup (path);
  it->name = g_strdup (p && p->name ? p->name : fallback_name);
  it->category = g_strdup (p && p->category ? p->category : "");
  it->entry = g_strdup (p && p->entry ? p->entry : "");
  it->kind = g_strdup (p ? p->kind : "");
  it->verdict = p ? p->verdict : PE8_VERDICT_NO;
  it->reason = p ? p->reason : file_reason;
  it->detail = g_strdup (p && p->reason_detail ? p->reason_detail : "");
  it->enabled = it->verdict != PE8_VERDICT_NO;
  if (st) { it->mtime = (gint64) st->st_mtime; it->size = (gint64) st->st_size; }
  it->proc_name = ps_item_proc_name (it->path, it->entry, it->name);
  return it;
}

GPtrArray *ps_scan_files (GPtrArray *files, const char *runner, int timeout_ms, PsScanProgress cb, gpointer user) {
  GPtrArray *res = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_item_free);
  for (guint i = 0; i < files->len; i++) {
    const char *path = g_ptr_array_index (files, i);
    if (cb) cb (path, (int) i, (int) files->len, user);
    GStatBuf st; memset (&st, 0, sizeof st); g_stat (path, &st);
    Pe8File f; pe8_analyze_file (path, &f);
    pe8_check_dependencies (&f, path);
    pe8_probe_all (&f, runner, timeout_ms);
    if (f.count == 0) {
      char *base = g_path_get_basename (path);
      g_ptr_array_add (res, item_from (NULL, path, base, f.file_reason, &st));
      g_free (base);
    }
    for (size_t k = 0; k < f.count; k++) g_ptr_array_add (res, item_from (&f.items[k], path, "?", PE8_R_NONE, &st));
    pe8_free (&f);
  }
  if (cb) cb (NULL, (int) files->len, (int) files->len, user);
  return res;
}

void ps_config_merge_scan (PsConfig *c, const char *dir, GPtrArray *fresh) {
  /* 0) entries the user removed from the list are not brought back */
  for (guint i = fresh->len; i-- > 0;) { PsItem *n = g_ptr_array_index (fresh, i); if (ps_config_is_ignored (c, n->path, n->name)) g_ptr_array_remove_index (fresh, i); }
  /* 1) carry over the user's on/off choice from the entries being replaced */
  for (guint i = 0; i < fresh->len; i++) {
    PsItem *n = g_ptr_array_index (fresh, i);
    PsItem *o = ps_config_find_item (c, n->path, n->entry, n->name);
    if (o && n->verdict != PE8_VERDICT_NO) n->enabled = o->enabled;
  }
  /* 2) drop the old entries under dir (this frees them) */
  for (guint i = c->items->len; i-- > 0;) {
    PsItem *it = g_ptr_array_index (c->items, i);
    if (ps_path_is_under (it->path, dir)) g_ptr_array_remove_index (c->items, i);
  }
  /* 3) append the fresh ones */
  for (guint i = 0; i < fresh->len; i++) g_ptr_array_add (c->items, g_ptr_array_index (fresh, i));
  g_ptr_array_set_free_func (fresh, NULL);
  g_ptr_array_free (fresh, TRUE);
}

char *ps_runner_path (void) {
  const char *o = g_getenv ("PSHOST_RUNNER");
  if (o && *o) return g_strdup (o);
#ifdef _WIN32
  wchar_t w[2048];
  DWORD n = GetModuleFileNameW (NULL, w, 2048);
  if (n > 0 && n < 2048) {
    char *exe = g_utf16_to_utf8 ((gunichar2 *) w, -1, NULL, NULL, NULL);
    if (exe) { char *dir = g_path_get_dirname (exe), *r = g_build_filename (dir, "pshost_runner.exe", NULL); g_free (dir); g_free (exe); return r; }
  }
#endif
  return g_strdup ("pshost_runner.exe");
}

void ps_item_sentence (const PsItem *it, Pe8Lang lang, char *buf, size_t n) {
  Pe8Plugin p; memset (&p, 0, sizeof p);
  p.name = it->name; p.verdict = it->verdict; p.reason = it->reason; p.reason_detail = it->detail && *it->detail ? it->detail : NULL;
  pe8_summary (&p, lang, buf, n);
}
