/* PSHost - run one Photoshop filter on a GIMP layer (shared by the manager window and the Filters menu). */
#ifndef PS_FILTER_H
#define PS_FILTER_H

#include <libgimp/gimp.h>
#include <gtk/gtk.h>
#include "config.h"

typedef enum { PS_RUN_OK, PS_RUN_CANCELLED, PS_RUN_ERROR } PsRunStatus;

/* Runs `item` on `drawable` (selection respected). The filter may show its own window (interactive=TRUE).
 * On PS_RUN_ERROR *error holds a localized message (g_free it). Result is one Undo step. */
PsRunStatus ps_filter_run (const PsItem *item, GimpImage *image, GimpDrawable *drawable, GtkWindow *parent, gboolean interactive, char **error);

#endif
