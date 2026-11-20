/* pshost_check [--lang pl|en] [--runner FILE] [--timeout-ms N] [--no-probe] PATH...
 * PATH = .8bf file or directory (searched recursively). One line per plug-in entry:
 *   VERDICT<TAB>reason-key<TAB>path<TAB>sentence */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/common/pe8bf.h"

static Pe8Lang lang = PE8_LANG_EN; static const char *runner = "pshost_runner.exe"; static int timeout_ms = 10000, do_probe = 1;
static int n_ok, n_warn, n_no;

static void check_file (const char *path) {
  Pe8File f; pe8_analyze_file (path, &f); pe8_check_dependencies (&f, path);
  if (do_probe) pe8_probe_all (&f, runner, timeout_ms);
  char buf[1024];
  if (!f.count) {
    Pe8Plugin p; memset (&p, 0, sizeof p); p.name = (char *) path; p.reason = f.file_reason; p.verdict = PE8_VERDICT_NO;
    pe8_summary (&p, lang, buf, sizeof buf);
    printf ("NO\t%s\t%s\t%s\n", pe8_reason_key (f.file_reason), path, buf); n_no++;
  }
  for (size_t i = 0; i < f.count; i++) {
    pe8_summary (&f.items[i], lang, buf, sizeof buf);
    printf ("%s\t%s\t%s\t%s\n", pe8_verdict_key (f.items[i].verdict), pe8_reason_key (f.items[i].reason), path, buf);
    if (f.items[i].verdict == PE8_VERDICT_OK) n_ok++; else if (f.items[i].verdict == PE8_VERDICT_WARN) n_warn++; else n_no++;
  }
  pe8_free (&f);
}

static void walk (const char *path) {
  DWORD a = GetFileAttributesA (path);
  if (a == INVALID_FILE_ATTRIBUTES) { printf ("NO\tunreadable\t%s\t?\n", path); return; }
  if (!(a & FILE_ATTRIBUTE_DIRECTORY)) { check_file (path); return; }
  char pat[1024]; snprintf (pat, sizeof pat, "%s\\*", path);
  WIN32_FIND_DATAA fd; HANDLE h = FindFirstFileA (pat, &fd);
  if (h == INVALID_HANDLE_VALUE) return;
  do {
    if (!strcmp (fd.cFileName, ".") || !strcmp (fd.cFileName, "..")) continue;
    char sub[1024]; snprintf (sub, sizeof sub, "%s\\%s", path, fd.cFileName);
    if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) walk (sub);
    else { size_t l = strlen (fd.cFileName); if (l > 4 && !_stricmp (fd.cFileName + l - 4, ".8bf")) check_file (sub); }
  } while (FindNextFileA (h, &fd));
  FindClose (h);
}

int main (int argc, char **argv) {
  SetConsoleOutputCP (CP_UTF8);
  for (int i = 1; i < argc; i++) {
    if (!strcmp (argv[i], "--lang") && i + 1 < argc) lang = !strcmp (argv[++i], "pl") ? PE8_LANG_PL : PE8_LANG_EN;
    else if (!strcmp (argv[i], "--runner") && i + 1 < argc) runner = argv[++i];
    else if (!strcmp (argv[i], "--timeout-ms") && i + 1 < argc) timeout_ms = atoi (argv[++i]);
    else if (!strcmp (argv[i], "--no-probe")) do_probe = 0;
    else walk (argv[i]);
  }
  printf (lang == PE8_LANG_PL ? "Użyte: %d, z zastrzeżeniami: %d, pominięte: %d\n%s\n" : "Used: %d, with reservations: %d, skipped: %d\n%s\n", n_ok, n_warn, n_no, pe8_caveat (lang));
  return 0;
}
