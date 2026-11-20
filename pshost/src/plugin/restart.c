/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
#include "restart.h"
#include "scan.h"
#include "config.h"
#include <libgimp/gimp.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <tlhelp32.h>
#endif

char **ps_dirty_image_names (void) {
  GimpImage **imgs = gimp_get_images (); GPtrArray *names = g_ptr_array_new ();
  for (int i = 0; imgs && imgs[i]; i++) if (gimp_image_is_dirty (imgs[i])) g_ptr_array_add (names, gimp_image_get_name (imgs[i]));
  g_free (imgs);
  if (!names->len) { g_ptr_array_free (names, TRUE); return NULL; }
  g_ptr_array_add (names, NULL);
  return (char **) g_ptr_array_free (names, FALSE);
}

#ifdef _WIN32
/* The GIMP process is our parent: its pid and its real executable path (no guessing of install locations). */
static gboolean find_gimp (DWORD *pid, char **exe) {
  DWORD me = GetCurrentProcessId (), parent = 0;
  HANDLE snap = CreateToolhelp32Snapshot (TH32CS_SNAPPROCESS, 0);
  if (snap == INVALID_HANDLE_VALUE) return FALSE;
  PROCESSENTRY32W e; e.dwSize = sizeof e;
  for (BOOL ok = Process32FirstW (snap, &e); ok; ok = Process32NextW (snap, &e)) if (e.th32ProcessID == me) { parent = e.th32ParentProcessID; break; }
  CloseHandle (snap);
  if (!parent) return FALSE;
  HANDLE h = OpenProcess (PROCESS_QUERY_LIMITED_INFORMATION, FALSE, parent);
  if (!h) return FALSE;
  wchar_t w[2048]; DWORD n = 2048; gboolean ok = QueryFullProcessImageNameW (h, 0, w, &n); CloseHandle (h);
  if (!ok) return FALSE;
  *exe = g_utf16_to_utf8 ((gunichar2 *) w, -1, NULL, NULL, NULL); *pid = parent;
  return *exe != NULL;
}
#endif

gboolean ps_restart_gimp (char **error) {
  *error = NULL;
#ifndef _WIN32
  *error = g_strdup ("unsupported platform"); return FALSE;
#else
  DWORD pid = 0; char *exe = NULL;
  if (!find_gimp (&pid, &exe)) { *error = g_strdup (_T ("cannot find the GIMP process")); return FALSE; }
  const char *ov = g_getenv ("PSHOST_GIMP_EXE_OVERRIDE");
  if (ov && *ov) { g_free (exe); exe = g_strdup (ov); }
  const char *gargs = g_getenv ("PSHOST_GIMP_ARGS");
  char *runner = ps_runner_path (), *cdir = ps_config_dir (), *log = g_build_filename (cdir, "restart.log", NULL);
  g_mkdir_with_parents (cdir, 0700);
  char *cmd = g_strdup_printf ("\"%s\" --mode restart --pid %lu --exe \"%s\" --wait-ms 180000 --log \"%s\"%s%s%s", runner, (unsigned long) pid, exe, log,
                               gargs && *gargs ? " --args \"" : "", gargs && *gargs ? gargs : "", gargs && *gargs ? "\"" : "");
  gunichar2 *wcmd = g_utf8_to_utf16 (cmd, -1, NULL, NULL, NULL);
  STARTUPINFOW si; memset (&si, 0, sizeof si); si.cb = sizeof si;
  PROCESS_INFORMATION pi; memset (&pi, 0, sizeof pi);
  /* the helper must outlive GIMP: detach it and try to leave GIMP's job object (if any) */
  BOOL ok = CreateProcessW (NULL, (wchar_t *) wcmd, NULL, NULL, FALSE, DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB, NULL, NULL, &si, &pi);
  if (!ok && GetLastError () == ERROR_ACCESS_DENIED)
    ok = CreateProcessW (NULL, (wchar_t *) wcmd, NULL, NULL, FALSE, DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, NULL, NULL, &si, &pi);
  gboolean res = TRUE;
  if (!ok) { *error = g_strdup_printf ("CreateProcess: %lu", GetLastError ()); res = FALSE; }
  else {
    CloseHandle (pi.hThread); CloseHandle (pi.hProcess);
    const char *nq = g_getenv ("PSHOST_NO_QUIT");
    if (!(nq && *nq == '1')) {
      GimpProcedure *q = gimp_pdb_lookup_procedure (gimp_get_pdb (), "gimp-quit");
      if (q) { GimpValueArray *r = gimp_procedure_run (q, "force", FALSE, NULL); if (r) gimp_value_array_unref (r); }
      else { *error = g_strdup (_T ("GIMP does not offer a clean quit")); res = FALSE; }
    }
  }
  g_free (wcmd); g_free (cmd); g_free (runner); g_free (cdir); g_free (log); g_free (exe);
  return res;
#endif
}
