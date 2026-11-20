/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - dynamic probe: runs pshost_runner --mode probe per plug-in entry in a separate process. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pe8bf.h"

static char *xdup (const char *s) { size_t l = strlen (s) + 1; char *r = malloc (l); if (r) memcpy (r, s, l); return r; }

static void set_result (Pe8Plugin *p, Pe8Verdict v, Pe8Reason r, const char *detail) {
  p->verdict = v; p->reason = r; free (p->reason_detail); p->reason_detail = detail ? xdup (detail) : NULL;
}

static void probe_one (Pe8Plugin *p, const wchar_t *runner, int timeout_ms) {
  wchar_t wplug[2048], went[300], cmd[5000], tmpdir[MAX_PATH], tmpfile[MAX_PATH];
  MultiByteToWideChar (CP_UTF8, 0, p->path, -1, wplug, 2048);
  MultiByteToWideChar (CP_UTF8, 0, p->entry ? p->entry : "PluginMain", -1, went, 300);
  swprintf (cmd, 5000, L"\"%ls\" --mode probe --plugin \"%ls\" --entry %ls --timeout-ms %d", runner, wplug, went, timeout_ms);
  GetTempPathW (MAX_PATH, tmpdir); GetTempFileNameW (tmpdir, L"psp", 0, tmpfile);

  SECURITY_ATTRIBUTES sa = { sizeof sa, NULL, TRUE };
  HANDLE out = CreateFileW (tmpfile, GENERIC_WRITE, FILE_SHARE_READ, &sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  HANDLE in = CreateFileW (L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
  STARTUPINFOW si; memset (&si, 0, sizeof si); si.cb = sizeof si; si.dwFlags = STARTF_USESTDHANDLES;
  si.hStdOutput = si.hStdError = out; si.hStdInput = in;
  PROCESS_INFORMATION pi; memset (&pi, 0, sizeof pi);
  HANDLE job = CreateJobObjectW (NULL, NULL);
  if (job) { JOBOBJECT_EXTENDED_LIMIT_INFORMATION li; memset (&li, 0, sizeof li); li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; SetInformationJobObject (job, JobObjectExtendedLimitInformation, &li, sizeof li); }
  BOOL ok = CreateProcessW (NULL, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW | CREATE_SUSPENDED, NULL, NULL, &si, &pi);
  CloseHandle (in);
  if (!ok) { CloseHandle (out); DeleteFileW (tmpfile); if (job) CloseHandle (job); set_result (p, PE8_VERDICT_NO, PE8_R_LOAD_FAILED, "runner"); return; }
  if (job) AssignProcessToJobObject (job, pi.hProcess);
  ResumeThread (pi.hThread);
  DWORD w = WaitForSingleObject (pi.hProcess, (DWORD) timeout_ms + 4000), code = 0;
  int hard_timeout = 0;
  if (w == WAIT_TIMEOUT) { TerminateProcess (pi.hProcess, 124); WaitForSingleObject (pi.hProcess, 2000); hard_timeout = 1; }
  GetExitCodeProcess (pi.hProcess, &code);
  CloseHandle (pi.hThread); CloseHandle (pi.hProcess); CloseHandle (out); if (job) CloseHandle (job);

  char text[16384] = ""; FILE *f = _wfopen (tmpfile, L"rb");
  if (f) { size_t n = fread (text, 1, sizeof text - 1, f); text[n] = 0; fclose (f); }
  DeleteFileW (tmpfile);

  char detail[256] = ""; const char *q;
  if (hard_timeout || code == 124) { set_result (p, PE8_VERDICT_NO, PE8_R_PROBE_TIMEOUT, NULL); return; }
  if (code == 0) {
    char list[256] = ""; int cnt = 0;
    for (q = text; (q = strstr (q, "SUMMARY_UNSUPPORTED ")) != NULL; ) {
      q += 20; size_t l = strcspn (q, "\r\n");
      if (cnt++ < 4 && strlen (list) + l + 3 < sizeof list) { if (list[0]) strcat (list, ", "); strncat (list, q, l); }
    }
    if (cnt) set_result (p, PE8_VERDICT_WARN, PE8_R_UNSUPPORTED_CB, list); else set_result (p, PE8_VERDICT_OK, PE8_R_NONE, NULL);
    return;
  }
  if (code == 3) { q = strstr (text, "LOAD_FAILED win32="); snprintf (detail, sizeof detail, "%lu", q ? strtoul (q + 18, NULL, 10) : 0UL); set_result (p, PE8_VERDICT_NO, PE8_R_LOAD_FAILED, detail); return; }
  if (code == 4) { set_result (p, PE8_VERDICT_NO, PE8_R_NO_ENTRY, p->entry); return; }
  if (code == 2 || code == 7) { q = strstr (text, "RESULT Prepare = "); snprintf (detail, sizeof detail, "%ld", q ? strtol (q + 17, NULL, 10) : 0L); set_result (p, PE8_VERDICT_NO, PE8_R_PROBE_ERROR, detail); return; }
  set_result (p, PE8_VERDICT_NO, PE8_R_PROBE_CRASH, NULL);   /* 0xC0DE0001 or any abnormal exit */
}

void pe8_probe_all (Pe8File *f, const char *runner_utf8, int timeout_ms) {
  wchar_t runner[2048]; MultiByteToWideChar (CP_UTF8, 0, runner_utf8, -1, runner, 2048);
  for (size_t i = 0; i < f->count; i++) if (f->items[i].verdict != PE8_VERDICT_NO) probe_one (&f->items[i], runner, timeout_ms);
}
