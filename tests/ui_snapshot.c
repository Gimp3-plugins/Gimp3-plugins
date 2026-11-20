/* Headless UI test: builds the manager window off-screen, adds a directory (async scan), waits for it,
 * checks the model and writes a PNG snapshot. Usage: ui_snapshot OUT.png LANG(pl|en) DIR...
 * Env: PSHOST_CONFIG_DIR (isolated config), PSHOST_RUNNER. */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>
#include "../src/plugin/config.h"
#include "../src/plugin/ui.h"

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
  printf ("items=%u ok=%d warn=%d no=%d dirs=%u png=%s\n", cfg->items->len, ok, warn, no, cfg->dirs->len, pb ? "yes" : "no");
  ps_config_free (cfg);
  return 0;
}
