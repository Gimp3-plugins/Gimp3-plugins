#include "ui.h"
#include "scan.h"
#include "registry.h"
#include <string.h>

static gboolean silent = FALSE;
static int auto_restart_answer = -1;
void ps_ui_set_auto_restart_answer (int a) { auto_restart_answer = a; }
void ps_ui_set_silent (gboolean s) { silent = s; }

enum { C_ENABLED, C_ACTIVATABLE, C_NAME, C_CATEGORY, C_FILE, C_RESULT, C_REASON, C_TOOLTIP, C_ITEM, C_N };
enum { D_PATH, D_RECURSIVE, D_N };
enum { R_NAME, R_FILE, R_NOTE, R_ITEM, R_N };

typedef struct {
  GtkWidget *restart_label; PsDirtyFunc dirty_func; PsRestartFunc restart_func; gpointer restart_data; gboolean restart_needed;
  GtkWidget *notebook, *run_view, *b_run, *run_hint, *run_target, *b_rm_rejected, *b_rm_selected, *b_restore;
  GtkTreeStore *run_store;
  PsRunFunc run_func; gpointer run_data; char *target; gboolean running;
  GtkWidget *dialog, *dir_view, *item_view, *summary, *progress, *b_add, *b_remove, *b_rescan, *c_recursive, *lang_combo, *spin_timeout, *details, *notice;
  GtkListStore *dir_store, *item_store;
  PsConfig *cfg;
  char *runner;
  gboolean busy, show_summary;
} Ui;

/* ----------------------------------------------------------------- scan job (worker thread) */
typedef struct { Ui *ui; GPtrArray *dirs; GPtrArray *per_dir_files; GPtrArray *results; char *runner; int timeout_ms; gboolean summary; int total_done, total; } Job;
typedef struct { Ui *ui; char *text; double frac; } ProgressMsg;

static gboolean progress_idle (gpointer p) {
  ProgressMsg *m = p;
  if (m->text) { gtk_progress_bar_set_text (GTK_PROGRESS_BAR (m->ui->progress), m->text); gtk_progress_bar_set_fraction (GTK_PROGRESS_BAR (m->ui->progress), m->frac); }
  g_free (m->text); g_free (m); return G_SOURCE_REMOVE;
}
static void progress_cb (const char *file, int done, int total, gpointer user) {
  Job *j = user; if (!file) return;
  ProgressMsg *m = g_new0 (ProgressMsg, 1); char *b = g_path_get_basename (file);
  m->ui = j->ui; m->text = g_strdup_printf ("%s  (%d/%d)", b, j->total_done + done + 1, j->total); m->frac = j->total ? (double) (j->total_done + done) / j->total : 0;
  g_free (b); g_idle_add (progress_idle, m);
}

static void refresh (Ui *ui);
static int no_rejected_count (Ui *ui) { int n = 0; for (guint i = 0; i < ui->cfg->items->len; i++) if (((PsItem *) g_ptr_array_index (ui->cfg->items, i))->verdict == PE8_VERDICT_NO) n++; return n; }
static PsItem *selected_run_item (Ui *ui) {
  GtkTreeModel *m; GtkTreeIter it; PsItem *p = NULL;
  if (gtk_tree_selection_get_selected (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->run_view)), &m, &it)) gtk_tree_model_get (m, &it, R_ITEM, &p, -1);
  return p;
}
static void update_run_sensitivity (Ui *ui) {
  gtk_widget_set_sensitive (ui->b_run, ui->run_func && ui->target && !ui->running && !ui->busy && selected_run_item (ui) != NULL);
}
static void show_summary_popup (Ui *ui, GPtrArray *items);

static gboolean job_done_idle (gpointer data) {
  Job *j = data; Ui *ui = j->ui;
  GPtrArray *summary_items = g_ptr_array_new ();
  for (guint d = 0; d < j->dirs->len; d++) {
    PsDir *dir = g_ptr_array_index (j->dirs, d);
    GPtrArray *fresh = g_ptr_array_index (j->results, d);
    for (guint i = 0; i < fresh->len; i++) g_ptr_array_add (summary_items, g_ptr_array_index (fresh, i));
    ps_config_merge_scan (ui->cfg, dir->path, fresh);   /* takes the items */
  }
  ps_config_prune_items (ui->cfg);
  ps_config_save (ui->cfg);
  ui->busy = FALSE;
  gtk_widget_set_visible (ui->progress, FALSE);
  refresh (ui);
  if (j->summary && !silent) show_summary_popup (ui, summary_items);
  g_ptr_array_free (summary_items, TRUE);   /* items now live in cfg */
  g_ptr_array_free (j->results, TRUE); g_ptr_array_free (j->dirs, TRUE); g_ptr_array_free (j->per_dir_files, TRUE); g_free (j->runner); g_free (j);
  return G_SOURCE_REMOVE;
}

static gpointer worker (gpointer data) {
  Job *j = data;
  for (guint d = 0; d < j->dirs->len; d++) {
    PsDir *dir = g_ptr_array_index (j->dirs, d);
    GPtrArray *files = ps_collect_files (dir->path, dir->recursive);
    g_ptr_array_add (j->per_dir_files, files); j->total += (int) files->len;
  }
  j->total_done = 0;
  for (guint d = 0; d < j->dirs->len; d++) {
    GPtrArray *files = g_ptr_array_index (j->per_dir_files, d);
    g_ptr_array_add (j->results, ps_scan_files (files, j->runner, j->timeout_ms, progress_cb, j));
    j->total_done += (int) files->len;
  }
  g_idle_add (job_done_idle, j);
  return NULL;
}

static void start_scan (Ui *ui, GPtrArray *dirs /* PsDir*, ownership taken */, gboolean summary) {
  if (ui->busy) { g_ptr_array_free (dirs, TRUE); return; }
  ui->busy = TRUE;
  Job *j = g_new0 (Job, 1);
  j->ui = ui; j->dirs = dirs; j->summary = summary; j->runner = g_strdup (ui->runner); j->timeout_ms = ui->cfg->probe_timeout_ms;
  j->per_dir_files = g_ptr_array_new_with_free_func ((GDestroyNotify) g_ptr_array_unref);
  j->results = g_ptr_array_new ();
  gtk_progress_bar_set_text (GTK_PROGRESS_BAR (ui->progress), _T ("Scanning..."));
  gtk_progress_bar_set_fraction (GTK_PROGRESS_BAR (ui->progress), 0);
  gtk_widget_set_visible (ui->progress, TRUE);
  gtk_widget_set_sensitive (ui->b_add, FALSE); gtk_widget_set_sensitive (ui->b_remove, FALSE); gtk_widget_set_sensitive (ui->b_rescan, FALSE);
  g_thread_unref (g_thread_new ("pshost-scan", worker, j));
}

/* ------------------------------------------------------------------------ view building */
static const char *result_text (Pe8Verdict v) { return v == PE8_VERDICT_OK ? _T ("OK") : v == PE8_VERDICT_WARN ? _T ("With reservations") : _T ("No"); }

static gint item_cmp (gconstpointer a, gconstpointer b) {
  const PsItem *x = *(PsItem *const *) a, *y = *(PsItem *const *) b;
  int ux = x->verdict == PE8_VERDICT_NO, uy = y->verdict == PE8_VERDICT_NO;
  if (ux != uy) return ux - uy;
  int c = g_utf8_collate (x->category ? x->category : "", y->category ? y->category : "");
  return c ? c : g_utf8_collate (x->name ? x->name : "", y->name ? y->name : "");
}

static void refresh (Ui *ui) {
  Pe8Lang lang = ps_get_language ();
  gtk_list_store_clear (ui->dir_store);
  for (guint i = 0; i < ui->cfg->dirs->len; i++) {
    PsDir *d = g_ptr_array_index (ui->cfg->dirs, i); GtkTreeIter it;
    gtk_list_store_append (ui->dir_store, &it); gtk_list_store_set (ui->dir_store, &it, D_PATH, d->path, D_RECURSIVE, d->recursive, -1);
  }
  g_ptr_array_sort (ui->cfg->items, item_cmp);
  gtk_list_store_clear (ui->item_store);
  GString *det = g_string_new (NULL);
  int ok = 0, warn = 0, no = 0;
  for (guint i = 0; i < ui->cfg->items->len; i++) {
    PsItem *p = g_ptr_array_index (ui->cfg->items, i); GtkTreeIter it;
    char why[512] = "", sentence[1024], *base = g_path_get_basename (p->path);
    if (p->verdict != PE8_VERDICT_OK) { pe8_reason_text (p->reason, p->detail && *p->detail ? p->detail : NULL, lang, why, sizeof why); if (why[0]) why[0] = (char) g_ascii_toupper (why[0]); }
    if (p->verdict == PE8_VERDICT_NO || !p->enabled) no++; else if (p->verdict == PE8_VERDICT_WARN) warn++; else ok++;
    gtk_list_store_append (ui->item_store, &it);
    gtk_list_store_set (ui->item_store, &it, C_ENABLED, p->enabled && p->verdict != PE8_VERDICT_NO, C_ACTIVATABLE, p->verdict != PE8_VERDICT_NO,
                        C_NAME, p->name, C_CATEGORY, p->category, C_FILE, base, C_RESULT, result_text (p->verdict), C_REASON, why, C_TOOLTIP, p->path, C_ITEM, p, -1);
    ps_item_sentence (p, lang, sentence, sizeof sentence);
    g_string_append_printf (det, "%s\n", p->verdict != PE8_VERDICT_NO && !p->enabled ? _T ("The plug-in is disabled") : sentence);
    g_free (base);
  }
  /* launcher list: usable + enabled items grouped by category */
  gtk_tree_store_clear (ui->run_store);
  {
    GHashTable *cats = g_hash_table_new (g_str_hash, g_str_equal); int n_run = 0;
    for (guint i = 0; i < ui->cfg->items->len; i++) {
      PsItem *p = g_ptr_array_index (ui->cfg->items, i);
      if (p->verdict == PE8_VERDICT_NO || !p->enabled) continue;
      const char *cat = p->category && *p->category ? p->category : "-";
      GtkTreeIter *par = g_hash_table_lookup (cats, cat);
      if (!par) { par = g_new0 (GtkTreeIter, 1); gtk_tree_store_append (ui->run_store, par, NULL); gtk_tree_store_set (ui->run_store, par, R_NAME, cat, R_ITEM, NULL, -1); g_hash_table_insert (cats, (gpointer) cat, par); }
      GtkTreeIter ch; char *base = g_path_get_basename (p->path);
      gtk_tree_store_append (ui->run_store, &ch, par);
      gtk_tree_store_set (ui->run_store, &ch, R_NAME, p->name, R_FILE, base, R_NOTE, p->verdict == PE8_VERDICT_WARN ? _T ("With reservations") : "", R_ITEM, p, -1);
      g_free (base); n_run++;
    }
    GHashTableIter hi; gpointer k, v; g_hash_table_iter_init (&hi, cats); while (g_hash_table_iter_next (&hi, &k, &v)) g_free (v);
    g_hash_table_destroy (cats);
    gtk_tree_view_expand_all (GTK_TREE_VIEW (ui->run_view));
    gtk_label_set_text (GTK_LABEL (ui->run_hint), n_run ? _T ("Select a filter and click Run to apply it to the active layer (double-click also works).") : _T ("No filters yet. Add a directory with plug-ins in the Manage tab."));
  }
  gtk_widget_set_sensitive (ui->b_rm_rejected, !ui->busy && no_rejected_count (ui) > 0);
  gtk_widget_set_sensitive (ui->b_restore, !ui->busy && ui->cfg->ignored->len > 0);
  update_run_sensitivity (ui);
  ui->restart_needed = ps_registry_needs_restart (ui->cfg);
  gtk_widget_set_visible (ui->restart_label, ui->restart_needed);
  char *sum;
  if (ui->cfg->items->len == 0) sum = g_strdup (_T ("No plug-ins found yet. Add a directory."));
  else sum = g_strdup_printf (_T ("Used: %d, with reservations: %d, skipped: %d"), ok, warn, no);
  char *full = g_strdup_printf ("%s\n%s", sum, pe8_caveat (lang));
  gtk_label_set_text (GTK_LABEL (ui->summary), full);
  gtk_text_buffer_set_text (gtk_text_view_get_buffer (GTK_TEXT_VIEW (ui->details)), det->str, -1);
  g_free (sum); g_free (full); g_string_free (det, TRUE);
  gtk_widget_set_sensitive (ui->b_add, !ui->busy); gtk_widget_set_sensitive (ui->b_rescan, !ui->busy && ui->cfg->dirs->len > 0);
  GtkTreeSelection *sel = gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->dir_view));
  gtk_widget_set_sensitive (ui->b_remove, !ui->busy && gtk_tree_selection_count_selected_rows (sel) > 0);
}

static void show_summary_popup (Ui *ui, GPtrArray *items) {
  Pe8Lang lang = ps_get_language ();
  GtkWindow *parent = GTK_WINDOW (ui->dialog);
  if (items->len == 0) {
    GtkWidget *m = gtk_message_dialog_new (parent, GTK_DIALOG_MODAL, GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s", _T ("No .8bf files were found in this directory."));
    gtk_window_set_title (GTK_WINDOW (m), _T ("Scan result")); gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m); return;
  }
  int ok = 0, warn = 0, no = 0; GString *det = g_string_new (NULL);
  for (guint i = 0; i < items->len; i++) {
    PsItem *p = g_ptr_array_index (items, i); char s[1024]; ps_item_sentence (p, lang, s, sizeof s);
    if (p->verdict == PE8_VERDICT_OK) ok++; else if (p->verdict == PE8_VERDICT_WARN) warn++; else no++;
    g_string_append_printf (det, "%s\n", s);
  }
  GtkWidget *m;
  if (items->len == 1) {
    PsItem *p = g_ptr_array_index (items, 0); char s[1024]; ps_item_sentence (p, lang, s, sizeof s);
    m = gtk_message_dialog_new (parent, GTK_DIALOG_MODAL, p->verdict == PE8_VERDICT_NO ? GTK_MESSAGE_WARNING : GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s", s);
    gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (m), "%s\n\n%s", pe8_caveat (lang), _T ("New filters appear in the Filters menu after GIMP is restarted."));
  } else {
    char *t = g_strdup_printf (_T ("Used: %d, with reservations: %d, skipped: %d"), ok, warn, no);
    m = gtk_message_dialog_new (parent, GTK_DIALOG_MODAL, GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s", t);
    gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (m), "%s\n\n%s", pe8_caveat (lang), _T ("New filters appear in the Filters menu after GIMP is restarted."));
    GtkWidget *ex = gtk_expander_new (_T ("Details")), *sw = gtk_scrolled_window_new (NULL, NULL), *tv = gtk_text_view_new ();
    gtk_text_view_set_editable (GTK_TEXT_VIEW (tv), FALSE); gtk_text_view_set_wrap_mode (GTK_TEXT_VIEW (tv), GTK_WRAP_WORD_CHAR);
    gtk_text_buffer_set_text (gtk_text_view_get_buffer (GTK_TEXT_VIEW (tv)), det->str, -1);
    gtk_container_add (GTK_CONTAINER (sw), tv); gtk_widget_set_size_request (sw, 640, 220); gtk_container_add (GTK_CONTAINER (ex), sw);
    gtk_box_pack_start (GTK_BOX (gtk_message_dialog_get_message_area (GTK_MESSAGE_DIALOG (m))), ex, TRUE, TRUE, 0);
    gtk_widget_show_all (ex); g_free (t);
  }
  gtk_window_set_title (GTK_WINDOW (m), _T ("Scan result"));
  gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m); g_string_free (det, TRUE);
}

/* -------------------------------------------------------------------------- callbacks */
void ps_manage_add_directory (GtkWidget *dlg, const char *path, gboolean recursive) {
  Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui");
  for (guint i = 0; i < ui->cfg->dirs->len; i++)
    if (!g_ascii_strcasecmp (((PsDir *) g_ptr_array_index (ui->cfg->dirs, i))->path, path)) {
      if (!silent) { GtkWidget *m = gtk_message_dialog_new (GTK_WINDOW (dlg), GTK_DIALOG_MODAL, GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s", _T ("This directory is already on the list.")); gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m); }
      return;
    }
  g_ptr_array_add (ui->cfg->dirs, ps_dir_new (path, recursive));
  ps_config_save (ui->cfg);
  GPtrArray *d = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_dir_free); g_ptr_array_add (d, ps_dir_new (path, recursive));
  refresh (ui);
  start_scan (ui, d, TRUE);
}
gboolean ps_manage_is_busy (GtkWidget *dlg) { Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui"); return ui->busy; }

static void on_add (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b;
  GtkFileChooserNative *c = gtk_file_chooser_native_new (_T ("Choose a directory with Photoshop plug-ins (.8bf)"), GTK_WINDOW (ui->dialog), GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER, NULL, NULL);
  if (gtk_native_dialog_run (GTK_NATIVE_DIALOG (c)) == GTK_RESPONSE_ACCEPT) {
    char *f = gtk_file_chooser_get_filename (GTK_FILE_CHOOSER (c));
    if (f) { ps_manage_add_directory (ui->dialog, f, gtk_toggle_button_get_active (GTK_TOGGLE_BUTTON (ui->c_recursive))); g_free (f); }
  }
  g_object_unref (c);
}

static void on_remove (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b; GtkTreeModel *m; GtkTreeIter it;
  if (!gtk_tree_selection_get_selected (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->dir_view)), &m, &it)) return;
  char *path; gtk_tree_model_get (m, &it, D_PATH, &path, -1);
  for (guint i = 0; i < ui->cfg->dirs->len; i++) if (!g_strcmp0 (((PsDir *) g_ptr_array_index (ui->cfg->dirs, i))->path, path)) { g_ptr_array_remove_index (ui->cfg->dirs, i); break; }
  g_free (path);
  ps_config_prune_items (ui->cfg); ps_config_save (ui->cfg); refresh (ui);
}

static void on_rescan (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b;
  GPtrArray *d = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_dir_free);
  for (guint i = 0; i < ui->cfg->dirs->len; i++) { PsDir *x = g_ptr_array_index (ui->cfg->dirs, i); g_ptr_array_add (d, ps_dir_new (x->path, x->recursive)); }
  start_scan (ui, d, TRUE);
}

static void on_dir_sel (GtkTreeSelection *s, gpointer data) { Ui *ui = data; gtk_widget_set_sensitive (ui->b_remove, !ui->busy && gtk_tree_selection_count_selected_rows (s) > 0); }

static void on_dir_recursive (GtkCellRendererToggle *r, gchar *path, gpointer data) {
  Ui *ui = data; (void) r; GtkTreeIter it;
  if (!gtk_tree_model_get_iter_from_string (GTK_TREE_MODEL (ui->dir_store), &it, path)) return;
  int idx = atoi (path); PsDir *d = g_ptr_array_index (ui->cfg->dirs, idx);
  d->recursive = !d->recursive; ps_config_save (ui->cfg);
  gtk_list_store_set (ui->dir_store, &it, D_RECURSIVE, d->recursive, -1);
}

static void on_item_toggled (GtkCellRendererToggle *r, gchar *path, gpointer data) {
  Ui *ui = data; (void) r; GtkTreeIter it; PsItem *p;
  if (!gtk_tree_model_get_iter_from_string (GTK_TREE_MODEL (ui->item_store), &it, path)) return;
  gtk_tree_model_get (GTK_TREE_MODEL (ui->item_store), &it, C_ITEM, &p, -1);
  if (!p || p->verdict == PE8_VERDICT_NO) return;
  p->enabled = !p->enabled; ps_config_save (ui->cfg); refresh (ui);
}

static void on_lang (GtkComboBox *c, gpointer data) {
  Ui *ui = data; const char *id = gtk_combo_box_get_active_id (c); if (!id) return;
  g_free (ui->cfg->language); ui->cfg->language = g_strdup (id); ps_config_save (ui->cfg);
  ps_set_language (ps_config_language (ui->cfg));
  gtk_label_set_text (GTK_LABEL (ui->notice), _T ("Menu names and the language of the filters change after GIMP is restarted."));
  refresh (ui);
}
static void on_timeout (GtkSpinButton *s, gpointer data) { Ui *ui = data; ui->cfg->probe_timeout_ms = (int) gtk_spin_button_get_value (s) * 1000; ps_config_save (ui->cfg); }
static void on_default_rec (GtkToggleButton *t, gpointer data) { Ui *ui = data; ui->cfg->default_recursive = gtk_toggle_button_get_active (t); ps_config_save (ui->cfg); }

static void on_run (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b; PsItem *p = selected_run_item (ui);
  if (!p || !ui->run_func || !ui->target) return;
  ui->running = TRUE; update_run_sensitivity (ui);
  gboolean applied = ui->run_func (p, GTK_WINDOW (ui->dialog), ui->run_data);
  ui->running = FALSE; update_run_sensitivity (ui);
  if (applied) gtk_dialog_response (GTK_DIALOG (ui->dialog), GTK_RESPONSE_CLOSE);
}
static void on_run_activated (GtkTreeView *v, GtkTreePath *path, GtkTreeViewColumn *c, gpointer data) { (void) v; (void) path; (void) c; on_run (NULL, data); }
static void on_run_sel (GtkTreeSelection *s, gpointer data) { (void) s; update_run_sensitivity (data); }

static gboolean confirm (Ui *ui, const char *text) {
  if (silent) return TRUE;
  GtkWidget *m = gtk_message_dialog_new (GTK_WINDOW (ui->dialog), GTK_DIALOG_MODAL, GTK_MESSAGE_QUESTION, GTK_BUTTONS_YES_NO, "%s", text);
  gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (m), "%s", _T ("Removes entries from this list only. Files on disk are not deleted."));
  int r = gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m); return r == GTK_RESPONSE_YES;
}
static void on_rm_rejected (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b; int n = no_rejected_count (ui); if (!n) return;
  char *q = g_strdup_printf (_T ("Remove %d rejected plug-ins from the list?"), n);
  gboolean yes = confirm (ui, q); g_free (q); if (!yes) return;
  for (guint i = ui->cfg->items->len; i-- > 0;) { PsItem *p = g_ptr_array_index (ui->cfg->items, i); if (p->verdict == PE8_VERDICT_NO) ps_config_ignore_item (ui->cfg, p); }
  ps_config_save (ui->cfg); refresh (ui);
}
static void on_rm_selected (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b; GtkTreeModel *m; GtkTreeIter it; PsItem *p = NULL;
  if (!gtk_tree_selection_get_selected (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->item_view)), &m, &it)) return;
  gtk_tree_model_get (m, &it, C_ITEM, &p, -1); if (!p) return;
  ps_config_ignore_item (ui->cfg, p); ps_config_save (ui->cfg); refresh (ui);
}
static void on_item_sel (GtkTreeSelection *s, gpointer data) { Ui *ui = data; gtk_widget_set_sensitive (ui->b_rm_selected, !ui->busy && gtk_tree_selection_count_selected_rows (s) > 0); }
static void on_restore (GtkButton *b, gpointer data) {
  Ui *ui = data; (void) b; ps_config_clear_ignored (ui->cfg); ps_config_save (ui->cfg);
  if (ui->cfg->dirs->len) on_rescan (NULL, ui); else refresh (ui);
}

void ps_manage_show_tab (GtkWidget *dlg, int page) { Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui"); gtk_notebook_set_current_page (GTK_NOTEBOOK (ui->notebook), page); }
void ps_manage_remove_rejected (GtkWidget *dlg) { on_rm_rejected (NULL, g_object_get_data (G_OBJECT (dlg), "ps-ui")); }
void ps_manage_rescan (GtkWidget *dlg) { on_rescan (NULL, g_object_get_data (G_OBJECT (dlg), "ps-ui")); }
void ps_manage_restore_removed (GtkWidget *dlg) { on_restore (NULL, g_object_get_data (G_OBJECT (dlg), "ps-ui")); }

void ps_manage_set_launcher (GtkWidget *dlg, PsRunFunc func, gpointer data, const char *target) {
  Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui");
  ui->run_func = func; ui->run_data = data; g_free (ui->target); ui->target = g_strdup (target);
  char *t = target ? g_strdup_printf (_T ("Applies to: %s"), target) : g_strdup (_T ("No image is open. Open an image to run a filter."));
  gtk_label_set_text (GTK_LABEL (ui->run_target), t); g_free (t);
  update_run_sensitivity (ui);
}

gboolean ps_manage_needs_restart (GtkWidget *dlg) { Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui"); return ps_registry_needs_restart (ui->cfg); }
void ps_manage_set_restart_hooks (GtkWidget *dlg, PsDirtyFunc dirty, PsRestartFunc restart, gpointer data) {
  Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui"); ui->dirty_func = dirty; ui->restart_func = restart; ui->restart_data = data;
}

/* Asks for consent (never closes GIMP without it) and, if given, starts the restart. Returns TRUE if GIMP was asked to restart. */
static gboolean ask_and_restart (Ui *ui) {
  if (!ui->restart_func) return FALSE;
  gboolean yes;
  char **dirty = ui->dirty_func ? ui->dirty_func (ui->restart_data) : NULL;
  if (auto_restart_answer >= 0) yes = auto_restart_answer == 1;
  else {
    GtkWidget *m = gtk_message_dialog_new (GTK_WINDOW (ui->dialog), GTK_DIALOG_MODAL, dirty ? GTK_MESSAGE_WARNING : GTK_MESSAGE_QUESTION, GTK_BUTTONS_NONE, "%s", _T ("To load the new plug-ins GIMP must be restarted. Restart now?"));
    if (dirty) {
      char *list = g_strjoinv (", ", dirty);
      gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (m), _T ("Unsaved changes in: %s. GIMP will ask whether to save them before closing."), list);
      g_free (list);
    }
    gtk_dialog_add_button (GTK_DIALOG (m), _T ("Later"), GTK_RESPONSE_NO);
    gtk_dialog_add_button (GTK_DIALOG (m), _T ("Restart now"), GTK_RESPONSE_YES);
    gtk_window_set_title (GTK_WINDOW (m), _T ("Restart GIMP"));
    yes = gtk_dialog_run (GTK_DIALOG (m)) == GTK_RESPONSE_YES; gtk_widget_destroy (m);
  }
  g_strfreev (dirty);
  if (!yes) return FALSE;
  char *err = NULL;
  if (!ui->restart_func (&err, ui->restart_data)) {
    if (!silent) {
      GtkWidget *m = gtk_message_dialog_new (GTK_WINDOW (ui->dialog), GTK_DIALOG_MODAL, GTK_MESSAGE_ERROR, GTK_BUTTONS_OK, _T ("Cannot restart GIMP automatically: %s. Close GIMP manually and start it again."), err ? err : "?");
      gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m);
    }
    g_free (err); return FALSE;
  }
  return TRUE;
}

/* --------------------------------------------------------------------------- build */
static GtkWidget *scrolled (GtkWidget *child, int h) {
  GtkWidget *sw = gtk_scrolled_window_new (NULL, NULL);
  gtk_scrolled_window_set_shadow_type (GTK_SCROLLED_WINDOW (sw), GTK_SHADOW_IN); gtk_container_add (GTK_CONTAINER (sw), child);
  if (h > 0) gtk_widget_set_size_request (sw, -1, h);
  return sw;
}
static void add_col (GtkWidget *view, const char *title, int col, int width) {
  GtkCellRenderer *r = gtk_cell_renderer_text_new ();
  g_object_set (r, "ellipsize", PANGO_ELLIPSIZE_END, NULL);
  GtkTreeViewColumn *c = gtk_tree_view_column_new_with_attributes (title, r, "text", col, NULL);
  gtk_tree_view_column_set_resizable (c, TRUE); gtk_tree_view_column_set_sort_column_id (c, col);
  if (width > 0) gtk_tree_view_column_set_fixed_width (c, width);
  gtk_tree_view_append_column (GTK_TREE_VIEW (view), c);
}

GtkWidget *ps_manage_dialog_new (GtkWindow *parent, PsConfig *cfg) {
  Ui *ui = g_new0 (Ui, 1); ui->cfg = cfg; ui->runner = ps_runner_path ();
  ps_set_language (ps_config_language (cfg));
  GtkWidget *dlg = gtk_dialog_new (); ui->dialog = dlg;
  gtk_window_set_title (GTK_WINDOW (dlg), _T ("PSHost - Photoshop plug-ins"));
  if (parent) gtk_window_set_transient_for (GTK_WINDOW (dlg), parent);
  gtk_window_set_default_size (GTK_WINDOW (dlg), 980, 720);
  gtk_dialog_add_button (GTK_DIALOG (dlg), _T ("Restart GIMP..."), 100);
  gtk_dialog_add_button (GTK_DIALOG (dlg), _T ("Close"), GTK_RESPONSE_CLOSE);
  g_object_set_data_full (G_OBJECT (dlg), "ps-ui", ui, NULL);

  GtkWidget *outer = gtk_dialog_get_content_area (GTK_DIALOG (dlg));
  gtk_container_set_border_width (GTK_CONTAINER (outer), 12); gtk_box_set_spacing (GTK_BOX (outer), 8);
  ui->notebook = gtk_notebook_new (); gtk_box_pack_start (GTK_BOX (outer), ui->notebook, TRUE, TRUE, 0);
  GtkWidget *box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 8);    /* "Manage" page */
  gtk_container_set_border_width (GTK_CONTAINER (box), 8);
  /* "Filters" page: launcher */
  GtkWidget *lp = gtk_box_new (GTK_ORIENTATION_VERTICAL, 8);
  gtk_container_set_border_width (GTK_CONTAINER (lp), 8);
  ui->run_hint = gtk_label_new (""); gtk_label_set_xalign (GTK_LABEL (ui->run_hint), 0); gtk_label_set_line_wrap (GTK_LABEL (ui->run_hint), TRUE);
  ui->run_store = gtk_tree_store_new (R_N, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_POINTER);
  ui->run_view = gtk_tree_view_new_with_model (GTK_TREE_MODEL (ui->run_store));
  add_col (ui->run_view, _T ("Name"), R_NAME, 380); add_col (ui->run_view, _T ("File"), R_FILE, 220); add_col (ui->run_view, _T ("Result"), R_NOTE, 0);
  g_signal_connect (ui->run_view, "row-activated", G_CALLBACK (on_run_activated), ui);
  g_signal_connect (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->run_view)), "changed", G_CALLBACK (on_run_sel), ui);
  ui->run_target = gtk_label_new (""); gtk_label_set_xalign (GTK_LABEL (ui->run_target), 0);
  ui->b_run = gtk_button_new_with_label (_T ("Run on current layer")); gtk_widget_set_halign (ui->b_run, GTK_ALIGN_END);
  g_signal_connect (ui->b_run, "clicked", G_CALLBACK (on_run), ui);
  GtkWidget *lb = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
  gtk_box_pack_start (GTK_BOX (lb), ui->run_target, TRUE, TRUE, 0); gtk_box_pack_end (GTK_BOX (lb), ui->b_run, FALSE, FALSE, 0);
  gtk_box_pack_start (GTK_BOX (lp), ui->run_hint, FALSE, FALSE, 0); gtk_box_pack_start (GTK_BOX (lp), scrolled (ui->run_view, 300), TRUE, TRUE, 0); gtk_box_pack_start (GTK_BOX (lp), lb, FALSE, FALSE, 0);
  gtk_notebook_append_page (GTK_NOTEBOOK (ui->notebook), lp, gtk_label_new (_T ("Filters")));
  gtk_notebook_append_page (GTK_NOTEBOOK (ui->notebook), box, gtk_label_new (_T ("Manage")));
  GtkWidget *outer_box = outer;

  /* directories */
  GtkWidget *f1 = gtk_frame_new (_T ("Plug-in directories")), *h1 = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8), *bv = gtk_box_new (GTK_ORIENTATION_VERTICAL, 6);
  gtk_container_set_border_width (GTK_CONTAINER (h1), 8);
  ui->dir_store = gtk_list_store_new (D_N, G_TYPE_STRING, G_TYPE_BOOLEAN);
  ui->dir_view = gtk_tree_view_new_with_model (GTK_TREE_MODEL (ui->dir_store));
  add_col (ui->dir_view, _T ("Directory"), D_PATH, 0);
  gtk_tree_view_column_set_expand (gtk_tree_view_get_column (GTK_TREE_VIEW (ui->dir_view), 0), TRUE);
  GtkCellRenderer *tr = gtk_cell_renderer_toggle_new ();
  g_signal_connect (tr, "toggled", G_CALLBACK (on_dir_recursive), ui);
  gtk_tree_view_append_column (GTK_TREE_VIEW (ui->dir_view), gtk_tree_view_column_new_with_attributes (_T ("Subfolders"), tr, "active", D_RECURSIVE, NULL));
  g_signal_connect (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->dir_view)), "changed", G_CALLBACK (on_dir_sel), ui);
  ui->b_add = gtk_button_new_with_label (_T ("Add directory...")); ui->b_remove = gtk_button_new_with_label (_T ("Remove")); ui->b_rescan = gtk_button_new_with_label (_T ("Rescan"));
  g_signal_connect (ui->b_add, "clicked", G_CALLBACK (on_add), ui); g_signal_connect (ui->b_remove, "clicked", G_CALLBACK (on_remove), ui); g_signal_connect (ui->b_rescan, "clicked", G_CALLBACK (on_rescan), ui);
  gtk_box_pack_start (GTK_BOX (bv), ui->b_add, FALSE, FALSE, 0); gtk_box_pack_start (GTK_BOX (bv), ui->b_remove, FALSE, FALSE, 0); gtk_box_pack_start (GTK_BOX (bv), ui->b_rescan, FALSE, FALSE, 0);
  ui->c_recursive = gtk_check_button_new_with_label (_T ("Include subfolders when adding"));
  gtk_toggle_button_set_active (GTK_TOGGLE_BUTTON (ui->c_recursive), cfg->default_recursive);
  g_signal_connect (ui->c_recursive, "toggled", G_CALLBACK (on_default_rec), ui);
  gtk_box_pack_start (GTK_BOX (bv), ui->c_recursive, FALSE, FALSE, 6);
  gtk_box_pack_start (GTK_BOX (h1), scrolled (ui->dir_view, 90), TRUE, TRUE, 0); gtk_box_pack_start (GTK_BOX (h1), bv, FALSE, FALSE, 0);
  gtk_container_add (GTK_CONTAINER (f1), h1); gtk_box_pack_start (GTK_BOX (box), f1, FALSE, FALSE, 0);

  /* plug-ins */
  GtkWidget *f2 = gtk_frame_new (_T ("Found plug-ins")), *v2 = gtk_box_new (GTK_ORIENTATION_VERTICAL, 6);
  gtk_container_set_border_width (GTK_CONTAINER (v2), 8);
  ui->item_store = gtk_list_store_new (C_N, G_TYPE_BOOLEAN, G_TYPE_BOOLEAN, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_POINTER);
  ui->item_view = gtk_tree_view_new_with_model (GTK_TREE_MODEL (ui->item_store));
  gtk_tree_view_set_tooltip_column (GTK_TREE_VIEW (ui->item_view), C_TOOLTIP);
  GtkCellRenderer *et = gtk_cell_renderer_toggle_new ();
  g_signal_connect (et, "toggled", G_CALLBACK (on_item_toggled), ui);
  gtk_tree_view_append_column (GTK_TREE_VIEW (ui->item_view), gtk_tree_view_column_new_with_attributes (_T ("Use"), et, "active", C_ENABLED, "activatable", C_ACTIVATABLE, "sensitive", C_ACTIVATABLE, NULL));
  add_col (ui->item_view, _T ("Name"), C_NAME, 230); add_col (ui->item_view, _T ("Category"), C_CATEGORY, 110); add_col (ui->item_view, _T ("File"), C_FILE, 170);
  add_col (ui->item_view, _T ("Result"), C_RESULT, 110); add_col (ui->item_view, _T ("Reason"), C_REASON, 0);
  gtk_tree_view_column_set_expand (gtk_tree_view_get_column (GTK_TREE_VIEW (ui->item_view), 5), TRUE);
  gtk_box_pack_start (GTK_BOX (v2), scrolled (ui->item_view, 230), TRUE, TRUE, 0);
  ui->summary = gtk_label_new (""); gtk_label_set_xalign (GTK_LABEL (ui->summary), 0); gtk_label_set_line_wrap (GTK_LABEL (ui->summary), TRUE);
  gtk_box_pack_start (GTK_BOX (v2), ui->summary, FALSE, FALSE, 0);
  {
    GtkWidget *rb = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
    ui->b_rm_rejected = gtk_button_new_with_label (_T ("Remove rejected")); ui->b_rm_selected = gtk_button_new_with_label (_T ("Remove selected")); ui->b_restore = gtk_button_new_with_label (_T ("Restore removed"));
    gtk_widget_set_tooltip_text (ui->b_rm_rejected, _T ("Removes entries from this list only. Files on disk are not deleted."));
    gtk_widget_set_tooltip_text (ui->b_rm_selected, _T ("Removes entries from this list only. Files on disk are not deleted."));
    g_signal_connect (ui->b_rm_rejected, "clicked", G_CALLBACK (on_rm_rejected), ui); g_signal_connect (ui->b_rm_selected, "clicked", G_CALLBACK (on_rm_selected), ui); g_signal_connect (ui->b_restore, "clicked", G_CALLBACK (on_restore), ui);
    g_signal_connect (gtk_tree_view_get_selection (GTK_TREE_VIEW (ui->item_view)), "changed", G_CALLBACK (on_item_sel), ui);
    gtk_box_pack_start (GTK_BOX (rb), ui->b_rm_rejected, FALSE, FALSE, 0); gtk_box_pack_start (GTK_BOX (rb), ui->b_rm_selected, FALSE, FALSE, 0); gtk_box_pack_end (GTK_BOX (rb), ui->b_restore, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (v2), rb, FALSE, FALSE, 0);
  }
  GtkWidget *ex = gtk_expander_new (_T ("Details"));
  ui->details = gtk_text_view_new (); gtk_text_view_set_editable (GTK_TEXT_VIEW (ui->details), FALSE); gtk_text_view_set_wrap_mode (GTK_TEXT_VIEW (ui->details), GTK_WRAP_WORD_CHAR);
  gtk_container_add (GTK_CONTAINER (ex), scrolled (ui->details, 130));
  gtk_box_pack_start (GTK_BOX (v2), ex, FALSE, FALSE, 0);
  ui->progress = gtk_progress_bar_new (); gtk_progress_bar_set_show_text (GTK_PROGRESS_BAR (ui->progress), TRUE);
  gtk_box_pack_start (GTK_BOX (v2), ui->progress, FALSE, FALSE, 0);
  gtk_container_add (GTK_CONTAINER (f2), v2); gtk_box_pack_start (GTK_BOX (box), f2, TRUE, TRUE, 0);

  /* settings */
  GtkWidget *f3 = gtk_frame_new (_T ("Settings")), *g = gtk_grid_new ();
  gtk_grid_set_column_spacing (GTK_GRID (g), 10); gtk_grid_set_row_spacing (GTK_GRID (g), 6); gtk_container_set_border_width (GTK_CONTAINER (g), 8);
  ui->lang_combo = gtk_combo_box_text_new ();
  gtk_combo_box_text_append (GTK_COMBO_BOX_TEXT (ui->lang_combo), "auto", _T ("Automatic")); gtk_combo_box_text_append (GTK_COMBO_BOX_TEXT (ui->lang_combo), "pl", "Polski"); gtk_combo_box_text_append (GTK_COMBO_BOX_TEXT (ui->lang_combo), "en", "English");
  gtk_combo_box_set_active_id (GTK_COMBO_BOX (ui->lang_combo), cfg->language);
  g_signal_connect (ui->lang_combo, "changed", G_CALLBACK (on_lang), ui);
  ui->spin_timeout = gtk_spin_button_new_with_range (3, 120, 1); gtk_spin_button_set_value (GTK_SPIN_BUTTON (ui->spin_timeout), cfg->probe_timeout_ms / 1000);
  g_signal_connect (ui->spin_timeout, "value-changed", G_CALLBACK (on_timeout), ui);
  GtkWidget *l1 = gtk_label_new (_T ("Language:")), *l2 = gtk_label_new (_T ("Test time limit (s):"));
  gtk_label_set_xalign (GTK_LABEL (l1), 0); gtk_label_set_xalign (GTK_LABEL (l2), 0);
  gtk_grid_attach (GTK_GRID (g), l1, 0, 0, 1, 1); gtk_grid_attach (GTK_GRID (g), ui->lang_combo, 1, 0, 1, 1);
  gtk_grid_attach (GTK_GRID (g), l2, 2, 0, 1, 1); gtk_grid_attach (GTK_GRID (g), ui->spin_timeout, 3, 0, 1, 1);
  ui->notice = gtk_label_new (_T ("Menu names and the language of the filters change after GIMP is restarted."));
  gtk_label_set_xalign (GTK_LABEL (ui->notice), 0); gtk_label_set_line_wrap (GTK_LABEL (ui->notice), TRUE);
  gtk_grid_attach (GTK_GRID (g), ui->notice, 0, 1, 4, 1);
  gtk_container_add (GTK_CONTAINER (f3), g); gtk_box_pack_start (GTK_BOX (box), f3, FALSE, FALSE, 0);

  GtkWidget *warn = gtk_label_new (_T ("Adding a plug-in runs third-party code during the test. Add only plug-ins from sources you trust."));
  gtk_label_set_xalign (GTK_LABEL (warn), 0); gtk_label_set_line_wrap (GTK_LABEL (warn), TRUE);
  GtkWidget *info = gtk_label_new (_T ("New filters appear in the Filters menu after GIMP is restarted."));
  gtk_label_set_xalign (GTK_LABEL (info), 0);
  ui->restart_label = gtk_label_new (_T ("The filter list changed. Restart GIMP to apply the changes."));
  gtk_label_set_xalign (GTK_LABEL (ui->restart_label), 0); gtk_widget_set_no_show_all (ui->restart_label, TRUE);
  gtk_box_pack_start (GTK_BOX (outer_box), ui->restart_label, FALSE, FALSE, 0);
  gtk_box_pack_start (GTK_BOX (outer_box), warn, FALSE, FALSE, 0); gtk_box_pack_start (GTK_BOX (outer_box), info, FALSE, FALSE, 0);

  gtk_widget_show_all (outer); gtk_widget_set_visible (ui->progress, FALSE);
  refresh (ui);
  return dlg;
}

void ps_manage_dialog_run (GtkWidget *dlg) {
  Ui *ui = g_object_get_data (G_OBJECT (dlg), "ps-ui");
  for (;;) {
    int r = gtk_dialog_run (GTK_DIALOG (dlg));
    if (r == 100) { if (ask_and_restart (ui)) break; continue; }       /* explicit "Restart GIMP..." */
    if (ui->restart_func && ps_registry_needs_restart (ui->cfg)) ask_and_restart (ui);   /* closing with pending changes */
    break;
  }
  gtk_widget_destroy (dlg);
}
