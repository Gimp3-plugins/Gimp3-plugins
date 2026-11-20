/* Headless UI test: builds the manager window off-screen, adds a directory (async scan), waits for it,
 * checks the model and writes a PNG snapshot. Usage: ui_snapshot OUT.png LANG(pl|en) DIR...
 * Env: PSHOST_CONFIG_DIR (isolated config), PSHOST_RUNNER. */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>
#include "../src/plugin/config.h"
#include "../src/plugin/ui.h"

static int restart_calls = 0, dirty_asked = 0;
static char **stub_dirty (gpointer d) { (void) d; dirty_asked++; char **v = g_new0 (char *, 3); v[0] = g_strdup ("a.xcf"); v[1] = g_strdup ("b.xcf"); return v; }
static gboolean stub_restart (char **err, gpointer d) { (void) err; (void) d; restart_calls++; return TRUE; }
static gboolean emit_close (gpointer dlg) { gtk_dialog_response (GTK_DIALOG (dlg), GTK_RESPONSE_CLOSE); return G_SOURCE_REMOVE; }

int main (int argc, char **argv) {
  gtk_init (&argc, &argv);
  if (argc < 4) { g_printerr ("usage: ui_snapshot OUT.png pl|en DIR...\n"); return 2; }
  PsConfig *cfg = ps_config_load ();
  g_free (cfg->language); cfg->language = g_strdup (argv[2]);
  ps_ui_set_silent (TRUE);
  GtkWidget *dlg = ps_manage_dialog_new (NULL, cfg);
  for (int i = 3; i < argc; i++) {
    ps_manage_add_directory (dlg, argv[i], TRUE);
    while (ps_manage_is_busy (dlg)) g_main_context_iteration (NULL, TRUE);
  }
  {
    const char *t = g_getenv ("PSHOST_TEST");
    gchar **acts = t ? g_strsplit (t, ",", -1) : NULL;
    for (int i = 0; acts && acts[i]; i++) {
      if (!strcmp (acts[i], "remove-rejected")) ps_manage_remove_rejected (dlg);
      else if (!strcmp (acts[i], "close-later") || !strcmp (acts[i], "close-restart")) {
        /* simulate closing the window with the consent dialog answered "later" / "restart now" */
        ps_ui_set_auto_restart_answer (!strcmp (acts[i], "close-restart") ? 1 : 0);
        ps_manage_set_restart_hooks (dlg, stub_dirty, stub_restart, NULL);
        g_idle_add (emit_close, dlg);
        ps_manage_dialog_run (dlg);
        printf ("restart_calls=%d dirty_asked=%d\n", restart_calls, dirty_asked);
        ps_config_free (cfg);
        return 0;
      }
      else if (!strcmp (acts[i], "tab2")) ps_manage_show_tab (dlg, 1);
      else if (!strcmp (acts[i], "launcher")) ps_manage_set_launcher (dlg, NULL, NULL, "photo.xcf / Layer 1");
      else if (!strcmp (acts[i], "rescan")) ps_manage_rescan (dlg);
      else if (!strcmp (acts[i], "restore")) ps_manage_restore_removed (dlg);
      while (ps_manage_is_busy (dlg)) g_main_context_iteration (NULL, TRUE);
    }
    g_strfreev (acts);
  }
  /* render off-screen */
  GtkWidget *ow = gtk_offscreen_window_new ();
  gtk_window_set_default_size (GTK_WINDOW (ow), 980, 720);
  GtkWidget *content = gtk_dialog_get_content_area (GTK_DIALOG (dlg));
  g_object_ref (content); gtk_container_remove (GTK_CONTAINER (dlg), content); /* detach the dialog content */
  gtk_container_add (GTK_CONTAINER (ow), content); g_object_unref (content);
  gtk_widget_show_all (ow);
  for (int i = 0; i < 50; i++) g_main_context_iteration (NULL, FALSE);
  GdkPixbuf *pb = gtk_offscreen_window_get_pixbuf (GTK_OFFSCREEN_WINDOW (ow));
  if (pb) gdk_pixbuf_save (pb, argv[1], "png", NULL, NULL);
  int ok = 0, warn = 0, no = 0;
  for (guint i = 0; i < cfg->items->len; i++) { PsItem *p = g_ptr_array_index (cfg->items, i); if (p->verdict == PE8_VERDICT_OK) ok++; else if (p->verdict == PE8_VERDICT_WARN) warn++; else no++; }
  printf ("items=%u ok=%d warn=%d no=%d dirs=%u ignored=%u needs_restart=%d png=%s\n", cfg->items->len, ok, warn, no, cfg->dirs->len, cfg->ignored->len, ps_manage_needs_restart (dlg), pb ? "yes" : "no");
  ps_config_free (cfg);
  return 0;
}
