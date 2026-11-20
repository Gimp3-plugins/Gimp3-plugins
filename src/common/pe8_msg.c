/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - user-facing verdict messages. English msgids, translated through the gettext catalog (see i18n.h). */
#include "pe8bf.h"
#include <stdio.h>
#include <string.h>

/* Indexed by Pe8Reason. */
static const char *const reasons[] = {
  /* NONE */           "",
  /* UNREADABLE */     N_("the file cannot be read"),
  /* NOT_PE */         N_("the file is damaged or is not a Windows plug-in"),
  /* 32BIT */          N_("it is a 32-bit plug-in (GIMP 3 needs 64-bit)"),
  /* WRONG_ARCH */     N_("it was built for an unsupported processor architecture"),
  /* NO_PIPL */        N_("it has no PiPL description (old or unsupported plug-in format)"),
  /* NOT_FILTER */     N_("it is not a filter (only filters are supported)"),
  /* HIDDEN */         N_("it is a hidden helper filter of another plug-in"),
  /* NO_ENTRY */       N_("its entry point '%s' was not found"),
  /* NO_RGB */         N_("it does not support RGB images"),
  /* MISSING_DEP */    N_("the library %s is missing"),
  /* LOAD_FAILED */    N_("it could not be loaded (Windows error %s)"),
  /* PROBE_CRASH */    N_("it crashed during the compatibility test"),
  /* PROBE_TIMEOUT */  N_("it did not respond during the test (it hung or waits for a window)"),
  /* PROBE_ERROR */    N_("it reported an error during the test (code %s)"),
  /* UNSUPPORTED_CB */ N_("it requests host features that are not supported yet: %s"),
};

void pe8_reason_text (Pe8Reason r, const char *detail, Pe8Lang lang, char *buf, size_t n) {
  if ((size_t) r >= sizeof reasons / sizeof *reasons) { snprintf (buf, n, "?"); return; }
  const char *t = ps_tr_lang (lang, reasons[r]);
  if (strstr (t, "%s")) snprintf (buf, n, t, detail ? detail : "?"); else snprintf (buf, n, "%s", t);
}

void pe8_summary (const Pe8Plugin *p, Pe8Lang lang, char *buf, size_t n) {
  char why[512]; const char *name = p->name ? p->name : "?";
  pe8_reason_text (p->reason, p->reason_detail, lang, why, sizeof why);
  switch (p->verdict) {
    case PE8_VERDICT_OK:
      snprintf (buf, n, ps_tr_lang (lang, N_("Plug-in \xE2\x80\x98%s\xE2\x80\x99 will be used in GIMP.")), name); break;
    case PE8_VERDICT_WARN:
      snprintf (buf, n, ps_tr_lang (lang, N_("Plug-in \xE2\x80\x98%s\xE2\x80\x99 will be used with reservations: %s.")), name, why); break;
    default:
      snprintf (buf, n, ps_tr_lang (lang, N_("Plug-in \xE2\x80\x98%s\xE2\x80\x99 will not be used: %s.")), name, why); break;
  }
}

const char *pe8_caveat (Pe8Lang lang) {
  return ps_tr_lang (lang, N_("\"Will be used\" means the plug-in passed the basic test, not that it is guaranteed to work in every situation."));
}
