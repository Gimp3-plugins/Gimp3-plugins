/* PSHost - user-facing verdict messages (Polish / English).
 * Kept as a table (not gettext) because the language must be switchable at run time independently of the
 * process locale; all other UI strings go through gettext (see po/). */
#include "pe8bf.h"
#include <stdio.h>
#include <string.h>

typedef struct { const char *en, *pl; } Msg;

static const Msg reasons[] = {
  /* NONE */           { "", "" },
  /* UNREADABLE */     { "the file cannot be read", "nie można odczytać pliku" },
  /* NOT_PE */         { "the file is damaged or is not a Windows plug-in", "plik jest uszkodzony lub nie jest wtyczką systemu Windows" },
  /* 32BIT */          { "it is a 32-bit plug-in (GIMP 3 needs 64-bit)", "jest 32-bitowa (GIMP 3 wymaga wtyczek 64-bitowych)" },
  /* WRONG_ARCH */     { "it was built for an unsupported processor architecture", "jest zbudowana dla nieobsługiwanej architektury procesora" },
  /* NO_PIPL */        { "it has no PiPL description (old or unsupported plug-in format)", "brak opisu PiPL (stary lub nieobsługiwany format wtyczki)" },
  /* NOT_FILTER */     { "it is not a filter (only filters are supported)", "to nie jest filtr (obsługiwane są tylko filtry)" },
  /* HIDDEN */         { "it is a hidden helper filter of another plug-in", "to ukryty, pomocniczy filtr innej wtyczki" },
  /* NO_ENTRY */       { "its entry point '%s' was not found", "nie znaleziono jej funkcji wejściowej „%s”" },
  /* NO_RGB */         { "it does not support RGB images", "nie obsługuje obrazów RGB" },
  /* MISSING_DEP */    { "the library %s is missing", "brakuje biblioteki %s" },
  /* LOAD_FAILED */    { "it could not be loaded (Windows error %s)", "nie udało się jej załadować (kod błędu Windows %s)" },
  /* PROBE_CRASH */    { "it crashed during the compatibility test", "uległa awarii podczas testu zgodności" },
  /* PROBE_TIMEOUT */  { "it did not respond during the test (it hung or waits for a window)", "nie odpowiedziała w czasie testu (zawiesiła się lub czeka na okno)" },
  /* PROBE_ERROR */    { "it reported an error during the test (code %s)", "zgłosiła błąd podczas testu (kod %s)" },
  /* UNSUPPORTED_CB */ { "it requests host features that are not supported yet: %s", "wymaga funkcji hosta, które nie są jeszcze obsługiwane: %s" },
};

void pe8_reason_text (Pe8Reason r, const char *detail, Pe8Lang lang, char *buf, size_t n) {
  if ((size_t) r >= sizeof reasons / sizeof *reasons) { snprintf (buf, n, "?"); return; }
  const char *t = lang == PE8_LANG_PL ? reasons[r].pl : reasons[r].en;
  if (strstr (t, "%s")) snprintf (buf, n, t, detail ? detail : "?"); else snprintf (buf, n, "%s", t);
}

void pe8_summary (const Pe8Plugin *p, Pe8Lang lang, char *buf, size_t n) {
  char why[512]; const char *name = p->name ? p->name : "?";
  pe8_reason_text (p->reason, p->reason_detail, lang, why, sizeof why);
  int pl = lang == PE8_LANG_PL;
  switch (p->verdict) {
    case PE8_VERDICT_OK:
      snprintf (buf, n, pl ? "Wtyczka »%s« zostanie użyta w GIMP-ie." : "Plug-in \xE2\x80\x98%s\xE2\x80\x99 will be used in GIMP.", name); break;
    case PE8_VERDICT_WARN:
      snprintf (buf, n, pl ? "Wtyczka »%s« zostanie użyta z zastrzeżeniami: %s." : "Plug-in \xE2\x80\x98%s\xE2\x80\x99 will be used with reservations: %s.", name, why); break;
    default:
      snprintf (buf, n, pl ? "Wtyczka »%s« nie zostanie użyta: %s." : "Plug-in \xE2\x80\x98%s\xE2\x80\x99 will not be used: %s.", name, why); break;
  }
}

const char *pe8_caveat (Pe8Lang lang) {
  return lang == PE8_LANG_PL
    ? "„Zostanie użyta” oznacza, że wtyczka przeszła test podstawowy, a nie że na pewno zadziała w każdej sytuacji."
    : "\"Will be used\" means the plug-in passed the basic test, not that it is guaranteed to work in every situation.";
}
