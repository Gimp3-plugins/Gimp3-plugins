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
typedef void (*PsRunFunc) (const PsItem *item, GtkWindow *parent, gpointer data);
void       ps_manage_set_launcher (GtkWidget *dlg, PsRunFunc func, gpointer data, const char *target);

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
