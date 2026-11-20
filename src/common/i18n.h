/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - runtime translation using standard gettext catalogs (.po -> .mo, domain "pshost").
 *
 * Why not libintl directly: the language must be switchable at run time (Auto / Polski / English) independently
 * of the locale of the host process, so the .mo reader is built in. Source strings are English msgids, marked
 * with _T() / N_() / ps_tr_lang() so that `xgettext` can extract them (see po/Makefile-less workflow in docs).
 * Catalogs are looked up in <dir>/<lang>/LC_MESSAGES/pshost.mo (dir: env PSHOST_LOCALE_DIR, else "locale" next to
 * the executable) and fall back to a catalog embedded in the binary. */
#ifndef PS_I18N_H
#define PS_I18N_H

#include <stddef.h>

typedef enum { PE8_LANG_EN = 0, PE8_LANG_PL = 1 } Pe8Lang;

void        ps_i18n_set_language (Pe8Lang l);
Pe8Lang     ps_i18n_get_language (void);
/* Translate an English msgid into the current language (returns msgid if there is no translation). */
const char *ps_tr (const char *msgid);
/* Same for an explicit language (used by code that formats messages for a chosen language). */
const char *ps_tr_lang (Pe8Lang lang, const char *msgid);
/* Number of messages in the catalog of `lang` (0 for English / missing); for tests. */
size_t      ps_i18n_catalog_size (Pe8Lang lang);

#define N_(s) (s)          /* mark for extraction only */
#define _T(s) ps_tr (s)

#endif
