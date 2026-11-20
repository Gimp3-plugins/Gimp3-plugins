/* PSHost - "Manage plug-ins" window (GTK3). */
#ifndef PS_UI_H
#define PS_UI_H

#include <gtk/gtk.h>
#include "config.h"

/* Build the window. cfg is owned by the caller and must outlive the dialog. */
GtkWidget *ps_manage_dialog_new (GtkWindow *parent, PsConfig *cfg);
/* Modal run; saves the configuration on every change. Returns when the user closes the window. */
void       ps_manage_dialog_run (GtkWidget *dlg);

/* Launcher: called when the user runs a filter from the "Filters" tab. `target` describes what it will be applied to
 * (e.g. "photo.xcf / Layer 1") or is NULL when no image is open (then the Run button is disabled). */
/* Returns TRUE when the filter was applied: the window then closes so the plug-in procedure ends and the result is a
 * normal, immediately undoable step in GIMP (Ctrl+Z). On error/cancel return FALSE: the window stays open. */
typedef gboolean (*PsRunFunc) (const PsItem *item, GtkWindow *parent, gpointer data);
void       ps_manage_set_launcher (GtkWidget *dlg, PsRunFunc func, gpointer data, const char *target);

/* Restart hooks (GIMP side). dirty: NULL-terminated names of images with unsaved changes (g_strfreev) or NULL.
 * restart: starts the helper and asks GIMP to quit; returns FALSE and sets *error on failure. */
typedef char   **(*PsDirtyFunc) (gpointer data);
typedef gboolean (*PsRestartFunc) (char **error, gpointer data);
void       ps_manage_set_restart_hooks (GtkWidget *dlg, PsDirtyFunc dirty, PsRestartFunc restart, gpointer data);
/* TRUE when the filter set / menu language changed since GIMP started (a restart is needed). */
gboolean   ps_manage_needs_restart (GtkWidget *dlg);
/* Test hook: the consent dialog is skipped and counted as "restart now" when TRUE, "later" when FALSE. */
void       ps_ui_set_auto_restart_answer (int answer /* -1 = ask, 0 = later, 1 = restart now */);

/* Start scanning a directory (also used by the "Add directory" button). */
void       ps_manage_add_directory (GtkWidget *dlg, const char *path, gboolean recursive);
gboolean   ps_manage_is_busy (GtkWidget *dlg);
/* Test hooks (same code paths as the buttons). */
void       ps_manage_show_tab (GtkWidget *dlg, int page);
void       ps_manage_remove_rejected (GtkWidget *dlg);
void       ps_manage_rescan (GtkWidget *dlg);
void       ps_manage_restore_removed (GtkWidget *dlg);
/* Tests: suppress the modal summary popup. */
void       ps_ui_set_silent (gboolean silent);

#endif
