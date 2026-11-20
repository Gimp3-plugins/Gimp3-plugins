/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - which filters are (to be) registered in GIMP's Filters menu, and whether a GIMP restart is needed.
 * No libgimp dependency (usable from the headless tests). */
#ifndef PS_REGISTRY_H
#define PS_REGISTRY_H

#include "config.h"

typedef struct {
  char *proc;       /* "pshost-filter-<hash>" */
  char *label;      /* menu label (unique inside its menu path) */
  char *menu;       /* "<Image>/Filters/Photoshop/<Category>" */
  const PsItem *item;   /* not owned */
} PsReg;

/* Filters that should be registered: usable (OK / with reservations), enabled, file present. Sorted by menu, label. */
GPtrArray *ps_registry_build (const PsConfig *c);
void       ps_registry_free (GPtrArray *regs);
char      *ps_registry_signature (const GPtrArray *regs, Pe8Lang lang);

/* State of what was registered at GIMP start (written from init_procedures). */
gboolean   ps_registry_write_state (const GPtrArray *regs, Pe8Lang lang);
char      *ps_registry_read_signature (void);      /* NULL when no state exists */
/* TRUE when the configuration now differs from what the running GIMP registered. */
gboolean   ps_registry_needs_restart (const PsConfig *c);
/* GIMP menu labels treat "_" as a mnemonic marker: double it. */
char      *ps_escape_mnemonic (const char *s);

#endif
