/* PSHost - static analysis of Photoshop plug-in (.8bf) files (PE parsing, PiPL, JSON PiPL).
 * Pure C, no code of the plug-in is executed. */
#ifndef PE8BF_H
#define PE8BF_H

#include <stddef.h>

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
  PE8_R_MISSING_DEP          /* imported DLL cannot be found */
} Pe8Reason;

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

void pe8_free (Pe8File *f);

const char *pe8_reason_key  (Pe8Reason r);   /* stable ASCII key, e.g. "32bit" */
const char *pe8_verdict_key (Pe8Verdict v);  /* "OK" / "WARN" / "NO" */

#endif
