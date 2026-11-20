/* PSHost - directory scanning (file collection + static/dynamic checks). Thread-safe: no GTK, no shared config. */
#ifndef PS_SCAN_H
#define PS_SCAN_H

#include "config.h"

typedef void (*PsScanProgress) (const char *current_file, int done, int total, gpointer user);

/* Recursively (optionally) collect *.8bf files; UTF-8 paths. */
GPtrArray *ps_collect_files (const char *dir, gboolean recursive);

/* Analyze + probe every file; returns new PsItem* entries (verdict, reason, enabled default). */
GPtrArray *ps_scan_files (GPtrArray *files, const char *runner, int timeout_ms, PsScanProgress cb, gpointer user);

/* Replace the entries located under `dir` by `fresh` (takes ownership of fresh's items), keeping the user's
 * "enabled" choice for entries that already existed. */
void ps_config_merge_scan (PsConfig *c, const char *dir, GPtrArray *fresh);

/* Path of pshost_runner.exe next to the running plug-in (override: env PSHOST_RUNNER). */
char *ps_runner_path (void);

/* Sentence for the user about one item, e.g. "Wtyczka »X« zostanie użyta w GIMP-ie." */
void ps_item_sentence (const PsItem *it, Pe8Lang lang, char *buf, size_t n);

#endif
