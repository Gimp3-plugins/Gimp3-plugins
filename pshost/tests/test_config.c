/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* Unit tests: config.json (de)serialization, corrupt input, path helpers, filter registry (labels/menu/signature),
 * scan-result merge. Run with GIMP's GTK/GLib runtime on PATH (see tests/test_runner.py). */
#include <glib.h>
#include <glib/gstdio.h>
#include <stdio.h>
#include <string.h>
#include "../src/plugin/config.h"
#include "../src/plugin/registry.h"
#include "../src/plugin/scan.h"

static int failures = 0, checks = 0;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf ("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); } } while (0)

static PsItem *mk (const char *path, const char *name, const char *cat, Pe8Verdict v, Pe8Reason r, gboolean enabled) {
  PsItem *it = g_new0 (PsItem, 1);
  it->path = g_strdup (path); it->name = g_strdup (name); it->category = g_strdup (cat); it->entry = g_strdup ("PluginMain"); it->kind = g_strdup ("8BFM");
  it->verdict = v; it->reason = r; it->detail = g_strdup (""); it->enabled = enabled; it->mtime = 123456; it->size = 4242;
  it->proc_name = ps_item_proc_name (it->path, it->entry, it->name);
  return it;
}

static void write_text (const char *dir, const char *text) {
  g_mkdir_with_parents (dir, 0700); char *f = g_build_filename (dir, "config.json", NULL);
  g_file_set_contents (f, text, -1, NULL); g_free (f);
}

int main (void) {
  char *tmp = g_dir_make_tmp ("pshost_cfg_XXXXXX", NULL);
  g_setenv ("PSHOST_CONFIG_DIR", tmp, TRUE);

  /* --- defaults when nothing exists */
  PsConfig *c = ps_config_load ();
  CHECK (c->dirs->len == 0 && c->items->len == 0 && c->ignored->len == 0);
  CHECK (!g_strcmp0 (c->language, "auto") && c->probe_timeout_ms == 10000 && c->default_recursive);

  /* --- round trip with Polish characters */
  g_ptr_array_add (c->dirs, ps_dir_new ("C:\\Wtyczki\\za\xC5\xBC\xC3\xB3\xC5\x82\xC4\x87 g\xC4\x99\xC5\x9Bl\xC4\x85", TRUE));
  g_ptr_array_add (c->dirs, ps_dir_new ("D:\\Plugins", FALSE));
  g_ptr_array_add (c->items, mk ("C:\\Wtyczki\\za\xC5\xBC\xC3\xB3\xC5\x82\xC4\x87 g\xC4\x99\xC5\x9Bl\xC4\x85\\a.8bf", "Filtr \xC5\x81\xC3\x93\x44\xC5\xB9", "Zetmar", PE8_VERDICT_OK, PE8_R_NONE, TRUE));
  g_ptr_array_add (c->items, mk ("D:\\Plugins\\b.8bf", "B", "", PE8_VERDICT_WARN, PE8_R_UNSUPPORTED_CB, FALSE));
  PsItem *no = mk ("D:\\Plugins\\c.8bf", "C", "Nik", PE8_VERDICT_NO, PE8_R_32BIT, FALSE); g_free (no->detail); no->detail = g_strdup ("x.dll");
  g_ptr_array_add (c->items, no);
  PsIgnored *ig = g_new0 (PsIgnored, 1); ig->path = g_strdup ("D:\\Plugins\\old.8bf"); ig->name = g_strdup ("Old"); g_ptr_array_add (c->ignored, ig);
  g_free (c->language); c->language = g_strdup ("pl"); c->probe_timeout_ms = 25000; c->default_recursive = FALSE;
  CHECK (ps_config_save (c));
  ps_config_free (c);

  c = ps_config_load ();
  CHECK (c->dirs->len == 2 && c->items->len == 3 && c->ignored->len == 1);
  CHECK (!g_strcmp0 (c->language, "pl") && c->probe_timeout_ms == 25000 && !c->default_recursive);
  PsDir *d0 = g_ptr_array_index (c->dirs, 0), *d1 = g_ptr_array_index (c->dirs, 1);
  CHECK (strstr (d0->path, "za\xC5\xBC\xC3\xB3\xC5\x82\xC4\x87") != NULL && d0->recursive && !d1->recursive);
  PsItem *a = g_ptr_array_index (c->items, 0), *b = g_ptr_array_index (c->items, 1), *n = g_ptr_array_index (c->items, 2);
  CHECK (!g_strcmp0 (a->name, "Filtr \xC5\x81\xC3\x93\x44\xC5\xB9") && a->verdict == PE8_VERDICT_OK && a->enabled && a->mtime == 123456 && a->size == 4242);
  CHECK (b->verdict == PE8_VERDICT_WARN && b->reason == PE8_R_UNSUPPORTED_CB && !b->enabled);
  CHECK (n->verdict == PE8_VERDICT_NO && n->reason == PE8_R_32BIT && !g_strcmp0 (n->detail, "x.dll") && !n->enabled);
  CHECK (a->proc_name && g_str_has_prefix (a->proc_name, "pshost-filter-") && strlen (a->proc_name) == strlen ("pshost-filter-") + 12);
  CHECK (ps_config_is_ignored (c, "d:\\plugins\\OLD.8bf", "Old") && !ps_config_is_ignored (c, "D:\\Plugins\\old.8bf", "Other"));

  /* --- every reason survives the round trip (no enum drift between save and load) */
  for (int r = 0; r <= PE8_R_UNSUPPORTED_CB; r++) { char nm[16]; g_snprintf (nm, sizeof nm, "R%d", r); g_ptr_array_add (c->items, mk ("D:\\Plugins\\r.8bf", nm, "T", PE8_VERDICT_NO, (Pe8Reason) r, FALSE)); }
  CHECK (ps_config_save (c)); ps_config_free (c); c = ps_config_load ();
  gboolean reasons_ok = TRUE;
  for (int r = 0; r <= PE8_R_UNSUPPORTED_CB; r++) { char nm[16]; g_snprintf (nm, sizeof nm, "R%d", r); PsItem *x = ps_config_find_item (c, "D:\\Plugins\\r.8bf", "PluginMain", nm); if (!x || x->reason != (Pe8Reason) r) reasons_ok = FALSE; }
  CHECK (reasons_ok);
  ps_config_free (c);

  /* --- corrupt / hostile input must never crash and falls back to safe defaults */
  write_text (tmp, "{ this is not json");
  c = ps_config_load (); CHECK (c->dirs->len == 0 && !g_strcmp0 (c->language, "auto")); ps_config_free (c);
  write_text (tmp, "[1,2,3]");
  c = ps_config_load (); CHECK (c->items->len == 0); ps_config_free (c);
  write_text (tmp, "{\"language\":\"klingon\",\"probe_timeout_ms\":1,\"directories\":[{\"nope\":1}],\"plugins\":[{\"name\":\"no path\"},42],\"ignored\":\"x\"}");
  c = ps_config_load ();
  CHECK (!g_strcmp0 (c->language, "auto") && c->probe_timeout_ms == 10000 && c->dirs->len == 0 && c->items->len == 0);
  ps_config_free (c);
  write_text (tmp, "{\"probe_timeout_ms\":99999999}");
  c = ps_config_load (); CHECK (c->probe_timeout_ms == 10000); ps_config_free (c);

  /* --- path helper */
  CHECK (ps_path_is_under ("C:\\a\\b\\x.8bf", "C:\\a") && ps_path_is_under ("C:\\a\\b\\x.8bf", "c:\\A\\") && ps_path_is_under ("C:/a/b/x.8bf", "C:\\a"));
  CHECK (!ps_path_is_under ("C:\\ab\\x.8bf", "C:\\a") && !ps_path_is_under ("C:\\a", "C:\\a"));

  /* --- registry: labels, menu, signature, restart detection */
  c = ps_config_load ();
  char *f1 = g_build_filename (tmp, "one.8bf", NULL), *f2 = g_build_filename (tmp, "two.8bf", NULL), *f3 = g_build_filename (tmp, "three.8bf", NULL);
  g_file_set_contents (f1, "x", 1, NULL); g_file_set_contents (f2, "x", 1, NULL); g_file_set_contents (f3, "x", 1, NULL);
  ps_set_language (PE8_LANG_EN);
  g_ptr_array_add (c->items, mk (f1, "Same Name", "Cat/Egory", PE8_VERDICT_OK, PE8_R_NONE, TRUE));
  g_ptr_array_add (c->items, mk (f2, "Same Name", "Cat/Egory", PE8_VERDICT_OK, PE8_R_NONE, TRUE));
  g_ptr_array_add (c->items, mk (f3, "Under_score", "", PE8_VERDICT_WARN, PE8_R_UNSUPPORTED_CB, TRUE));
  g_ptr_array_add (c->items, mk ("Z:\\missing\\file.8bf", "Missing", "Cat", PE8_VERDICT_OK, PE8_R_NONE, TRUE));       /* file absent  */
  g_ptr_array_add (c->items, mk (f1, "Disabled", "Cat", PE8_VERDICT_OK, PE8_R_NONE, FALSE));                           /* user off     */
  g_ptr_array_add (c->items, mk (f1, "Rejected", "Cat", PE8_VERDICT_NO, PE8_R_32BIT, TRUE));                           /* rejected     */
  GPtrArray *regs = ps_registry_build (c);
  CHECK (regs->len == 3);
  gboolean s1 = FALSE, s2 = FALSE, us = FALSE; char *label_us = NULL;
  for (guint i = 0; i < regs->len; i++) {
    PsReg *r = g_ptr_array_index (regs, i);
    if (g_str_has_prefix (r->label, "Same Name (one.8bf)") && !g_strcmp0 (r->menu, "<Image>/Filters/Photoshop/Cat-Egory")) s1 = TRUE;
    if (g_str_has_prefix (r->label, "Same Name (two.8bf)")) s2 = TRUE;
    if (!g_strcmp0 (r->label, "Under_score") && !g_strcmp0 (r->menu, "<Image>/Filters/Photoshop/Other")) { us = TRUE; label_us = ps_escape_mnemonic (r->label); }
  }
  CHECK (s1 && s2 && us);
  CHECK (label_us && !g_strcmp0 (label_us, "Under__score"));
  g_free (label_us);
  char *sig_en = ps_registry_signature (regs, PE8_LANG_EN), *sig_en2 = ps_registry_signature (regs, PE8_LANG_EN), *sig_pl = ps_registry_signature (regs, PE8_LANG_PL);
  CHECK (!g_strcmp0 (sig_en, sig_en2) && g_strcmp0 (sig_en, sig_pl));
  ps_registry_free (regs);
  ((PsItem *) g_ptr_array_index (c->items, c->items->len - 2))->enabled = TRUE;   /* "Disabled" -> enabled */
  regs = ps_registry_build (c); char *sig_more = ps_registry_signature (regs, PE8_LANG_EN);
  CHECK (regs->len == 4 && g_strcmp0 (sig_en, sig_more));
  ps_registry_free (regs);
  g_free (sig_en); g_free (sig_en2); g_free (sig_pl); g_free (sig_more);

  /* needs_restart: no state file -> yes (filters exist); after writing the state -> no; after a change -> yes again */
  CHECK (ps_registry_needs_restart (c));
  regs = ps_registry_build (c); CHECK (ps_registry_write_state (regs, ps_config_language (c))); ps_registry_free (regs);
  CHECK (!ps_registry_needs_restart (c));
  ((PsItem *) g_ptr_array_index (c->items, c->items->len - 2))->enabled = FALSE;
  CHECK (ps_registry_needs_restart (c));

  /* --- scan merge keeps the user's on/off choice, drops stale entries, never re-adds ignored ones */
  PsConfig *m = ps_config_load (); g_ptr_array_set_size (m->items, 0);
  char *dir = g_build_filename (tmp, "scan", NULL); g_mkdir_with_parents (dir, 0700);
  char *pf = g_build_filename (dir, "p.8bf", NULL), *gone = g_build_filename (dir, "gone.8bf", NULL), *hid = g_build_filename (dir, "hid.8bf", NULL);
  g_ptr_array_add (m->items, mk (pf, "P", "C", PE8_VERDICT_OK, PE8_R_NONE, FALSE));          /* user switched it off */
  g_ptr_array_add (m->items, mk (gone, "Gone", "C", PE8_VERDICT_OK, PE8_R_NONE, TRUE));       /* no longer present    */
  PsIgnored *h = g_new0 (PsIgnored, 1); h->path = g_strdup (hid); h->name = g_strdup ("Hid"); g_ptr_array_add (m->ignored, h);
  GPtrArray *fresh = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_item_free);
  g_ptr_array_add (fresh, mk (pf, "P", "C", PE8_VERDICT_OK, PE8_R_NONE, TRUE));
  g_ptr_array_add (fresh, mk (hid, "Hid", "C", PE8_VERDICT_OK, PE8_R_NONE, TRUE));
  ps_config_merge_scan (m, dir, fresh);
  CHECK (m->items->len == 1 && !((PsItem *) g_ptr_array_index (m->items, 0))->enabled);
  ps_config_free (m); g_free (dir); g_free (pf); g_free (gone); g_free (hid);

  ps_config_free (c); g_free (f1); g_free (f2); g_free (f3); g_free (tmp);
  printf ("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
