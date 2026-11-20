/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - restart GIMP (helper process + clean quit request). */
#ifndef PS_RESTART_H
#define PS_RESTART_H

#include <glib.h>

/* NULL-terminated array of names of images with unsaved changes (g_strfreev), or NULL when none. */
char   **ps_dirty_image_names (void);

/* Starts the helper (waits for GIMP to exit, then starts it again) and asks GIMP to quit through the same path as
 * File > Quit (GIMP itself asks about unsaved images; if the user cancels, the helper times out and does nothing).
 * GIMP is never killed. On failure *error is set and nothing was started or closed.
 * Test overrides: PSHOST_GIMP_EXE_OVERRIDE, PSHOST_GIMP_ARGS, PSHOST_NO_QUIT=1. */
gboolean ps_restart_gimp (char **error);

#endif
