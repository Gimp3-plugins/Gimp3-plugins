/* PSHost - user configuration (%APPDATA%\GIMP\3.2\pshost\config.json) and scan-result cache. */
#ifndef PS_CONFIG_H
#define PS_CONFIG_H

#include <glib.h>
#include "../common/pe8bf.h"
#include "../common/i18n.h"

typedef struct { char *path; gboolean recursive; } PsDir;

typedef struct {
  char *path, *name, *category, *entry, *kind;
  Pe8Verdict verdict; Pe8Reason reason; char *detail;
  gboolean enabled;            /* user switch; only meaningful when verdict != NO */
  gint64 mtime, size;          /* of the .8bf when scanned */
  char *proc_name;             /* "pshost-filter-<hash>" */
} PsItem;

typedef struct { char *path, *name; } PsIgnored;   /* entries the user removed from the list */

typedef struct {
  GPtrArray *dirs;             /* PsDir* */
  GPtrArray *items;            /* PsItem* (all scanned entries incl. rejected) */
  GPtrArray *ignored;          /* PsIgnored*: hidden by the user, skipped by scans */
  char *language;              /* "auto" | "pl" | "en" */
  int probe_timeout_ms;
  gboolean default_recursive;
} PsConfig;

char     *ps_config_dir (void);                 /* %APPDATA%\GIMP\3.2\pshost (override: env PSHOST_CONFIG_DIR) */
PsConfig *ps_config_load (void);                /* never NULL: defaults if the file is missing/corrupt */
gboolean  ps_config_save (const PsConfig *c);
void      ps_config_free (PsConfig *c);

PsDir  *ps_dir_new (const char *path, gboolean recursive);
void    ps_dir_free (PsDir *d);
void    ps_item_free (PsItem *i);
char   *ps_item_proc_name (const char *path, const char *entry, const char *name);
PsItem *ps_config_find_item (const PsConfig *c, const char *path, const char *entry, const char *name);
gboolean ps_config_is_ignored (const PsConfig *c, const char *path, const char *name);
/* Remove the item from the list and remember it so rescans do not bring it back. Never touches files on disk. */
void     ps_config_ignore_item (PsConfig *c, const PsItem *it);
void     ps_config_clear_ignored (PsConfig *c);
/* Keep only items located under one of the configured directories. */
void    ps_config_prune_items (PsConfig *c);
gboolean ps_path_is_under (const char *path, const char *dir);

/* Language: resolves "auto" using the system/GIMP locale. Returns PE8_LANG_PL or PE8_LANG_EN. */
Pe8Lang ps_config_language (const PsConfig *c);
#define ps_set_language(l) ps_i18n_set_language (l)
#define ps_get_language() ps_i18n_get_language ()

#endif
