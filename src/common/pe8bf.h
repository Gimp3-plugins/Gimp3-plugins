/* PSHost - static analysis of Photoshop plug-in (.8bf) files (PE parsing, PiPL, JSON PiPL).
 * Pure C, no code of the plug-in is executed. */
#ifndef PE8BF_H
#define PE8BF_H

#include <stddef.h>
#include "i18n.h"

typedef enum {
  PE8_VERDICT_OK = 0,        /* passes static checks */
  PE8_VERDICT_WARN,          /* usable with reservations */
  PE8_VERDICT_NO             /* will not be used */
} Pe8Verdict;

typedef enum {
  PE8_R_NONE = 0,
  PE8_R_UNREADABLE,          /* file cannot be read */
  PE8_R_NOT_PE,              /* not a valid PE file / corrupted */
  PE8_R_32BIT,               /* 32-bit (I386) plug-in */
  PE8_R_WRONG_ARCH,          /* other architecture (e.g. ARM64) */
  PE8_R_NO_PIPL,             /* no PiPL resource (legacy PIMI/PITL or not a plug-in) */
  PE8_R_NOT_FILTER,          /* PiPL kind is not 8BFM */
  PE8_R_HIDDEN,              /* helper filter flagged **Hidden** */
  PE8_R_NO_ENTRY,            /* entry point not found in exports */
  PE8_R_NO_RGB,              /* RGB mode not supported */
  PE8_R_MISSING_DEP,         /* imported DLL cannot be found */
  /* --- dynamic probe results --- */
  PE8_R_LOAD_FAILED,         /* LoadLibrary failed (detail = Windows error code) */
  PE8_R_PROBE_CRASH,         /* plug-in crashed in the probe */
  PE8_R_PROBE_TIMEOUT,       /* plug-in hung / waited for a window in the probe */
  PE8_R_PROBE_ERROR,         /* Prepare returned an error (detail = code) */
  PE8_R_UNSUPPORTED_CB       /* WARN: plug-in asked for host features we do not provide (detail = list) */
} Pe8Reason;

/* Pe8Lang (PE8_LANG_EN / PE8_LANG_PL) comes from i18n.h */

typedef struct {
  char   *path;              /* UTF-8 path of the .8bf */
  char   *name;              /* UTF-8, may be NULL */
  char   *category;          /* UTF-8, may be NULL */
  char   *entry;             /* entry point name, may be NULL */
  char    kind[5];           /* e.g. "8BFM" (NUL-terminated) */
  unsigned modes;            /* PiPL supported-modes mask (0x1000 = RGB, 0x0010 = RGB48) */
  int     modes_known;
  int     from_json;         /* described by JSON PiPL instead of binary PiPL */
  int     resource_id;       /* binary PiPL resource id (or -1) */
  Pe8Verdict verdict;
  Pe8Reason  reason;
  char   *reason_detail;     /* e.g. name of the missing DLL, may be NULL */
} Pe8Plugin;

typedef struct {
  Pe8Plugin *items;
  size_t     count;
  unsigned   machine;        /* IMAGE_FILE_MACHINE_* */
  char     **imports;        /* imported DLL names */
  size_t     n_imports;
  Pe8Verdict file_verdict;   /* verdict when the file yields no plug-in entries */
  Pe8Reason  file_reason;
} Pe8File;

/* Analyze one file. Always returns a filled Pe8File (check items/file_reason). */
void pe8_analyze_file (const char *path_utf8, Pe8File *out);

/* Windows only: verify that imported DLLs can be located (plug-in dir, system dirs, extra_dirs
 * separated by ';' e.g. the GIMP bin dir is NOT included on purpose). Marks items NO/MISSING_DEP. */
void pe8_check_dependencies (Pe8File *f, const char *path_utf8);

/* Dynamic probe (Windows): run `pshost_runner --mode probe` in a separate process for every item that
 * passed the static checks; updates verdict/reason. timeout_ms applies per plug-in. */
void pe8_probe_all (Pe8File *f, const char *runner_path_utf8, int timeout_ms);

/* Messages (UTF-8). */
void pe8_reason_text (Pe8Reason r, const char *detail, Pe8Lang lang, char *buf, size_t n);
/* One-sentence verdict for the user, e.g. "Wtyczka »X« nie zostanie użyta: jest 32-bitowa ..." */
void pe8_summary (const Pe8Plugin *p, Pe8Lang lang, char *buf, size_t n);
/* Notice that "OK" only means the basic test passed. */
const char *pe8_caveat (Pe8Lang lang);

void pe8_free (Pe8File *f);

const char *pe8_reason_key  (Pe8Reason r);   /* stable ASCII key, e.g. "32bit" */
const char *pe8_verdict_key (Pe8Verdict v);  /* "OK" / "WARN" / "NO" */

#endif
