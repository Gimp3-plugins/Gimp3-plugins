/* PSHost - "Manage plug-ins" window (GTK3). */
#ifndef PS_UI_H
#define PS_UI_H

#include <gtk/gtk.h>
#include "config.h"

/* Build the window. cfg is owned by the caller and must outlive the dialog. */
GtkWidget *ps_manage_dialog_new (GtkWindow *parent, PsConfig *cfg);
/* Modal run; saves the configuration on every change. Returns when the user closes the window. */
void       ps_manage_dialog_run (GtkWidget *dlg);

/* Start scanning a directory (also used by the "Add directory" button). */
void       ps_manage_add_directory (GtkWidget *dlg, const char *path, gboolean recursive);
gboolean   ps_manage_is_busy (GtkWidget *dlg);
/* Tests: suppress the modal summary popup. */
void       ps_ui_set_silent (gboolean silent);

#endif
