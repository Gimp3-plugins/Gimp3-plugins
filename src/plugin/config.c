#include "config.h"
#include <json-glib/json-glib.h>
#include <string.h>
#include <gio/gio.h>

#ifdef PSHOST_STANDALONE
static char *base_dir (void) { return g_build_filename (g_get_user_config_dir (), "GIMP", "3.2", NULL); }
#else
#include <libgimp/gimp.h>
static char *base_dir (void) { return g_strdup (gimp_directory ()); }
#endif

char *ps_config_dir (void) {
  const char *o = g_getenv ("PSHOST_CONFIG_DIR");
  if (o && *o) return g_strdup (o);
  char *b = base_dir (), *d = g_build_filename (b, "pshost", NULL); g_free (b); return d;
}

PsDir *ps_dir_new (const char *path, gboolean recursive) { PsDir *d = g_new0 (PsDir, 1); d->path = g_strdup (path); d->recursive = recursive; return d; }
void ps_dir_free (PsDir *d) { if (d) { g_free (d->path); g_free (d); } }
void ps_item_free (PsItem *i) {
  if (!i) return;
  g_free (i->path); g_free (i->name); g_free (i->category); g_free (i->entry); g_free (i->kind); g_free (i->detail); g_free (i->proc_name); g_free (i);
}

char *ps_item_proc_name (const char *path, const char *entry, const char *name) {
  char *key = g_strdup_printf ("%s|%s|%s", path ? path : "", entry ? entry : "", name ? name : "");
  char *h = g_compute_checksum_for_string (G_CHECKSUM_MD5, key, -1);
  char *r = g_strdup_printf ("pshost-filter-%.12s", h);
  g_free (key); g_free (h); return r;
}

static void ignored_free (PsIgnored *i) { if (i) { g_free (i->path); g_free (i->name); g_free (i); } }

static PsConfig *defaults (void) {
  PsConfig *c = g_new0 (PsConfig, 1);
  c->dirs = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_dir_free);
  c->items = g_ptr_array_new_with_free_func ((GDestroyNotify) ps_item_free);
  c->ignored = g_ptr_array_new_with_free_func ((GDestroyNotify) ignored_free);
  c->language = g_strdup ("auto"); c->probe_timeout_ms = 10000; c->default_recursive = TRUE;
  return c;
}

void ps_config_free (PsConfig *c) {
  if (!c) return;
  g_ptr_array_free (c->dirs, TRUE); g_ptr_array_free (c->items, TRUE); g_ptr_array_free (c->ignored, TRUE); g_free (c->language); g_free (c);
}

static Pe8Verdict verdict_from (const char *s) { return !g_strcmp0 (s, "OK") ? PE8_VERDICT_OK : !g_strcmp0 (s, "WARN") ? PE8_VERDICT_WARN : PE8_VERDICT_NO; }
static Pe8Reason reason_from (const char *s) {
  for (int r = 0; r <= PE8_R_UNSUPPORTED_CB; r++) if (!g_strcmp0 (pe8_reason_key ((Pe8Reason) r), s)) return (Pe8Reason) r;
  return PE8_R_NONE;
}
static const char *obj_str (JsonObject *o, const char *k) { return json_object_has_member (o, k) ? json_object_get_string_member (o, k) : NULL; }

PsConfig *ps_config_load (void) {
  PsConfig *c = defaults ();
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "config.json", NULL);
  JsonParser *p = json_parser_new ();
  GError *err = NULL;
  if (json_parser_load_from_file (p, file, &err)) {
    JsonNode *root = json_parser_get_root (p);
    if (root && JSON_NODE_HOLDS_OBJECT (root)) {
      JsonObject *o = json_node_get_object (root);
      const char *s;
      if ((s = obj_str (o, "language")) && (!strcmp (s, "pl") || !strcmp (s, "en") || !strcmp (s, "auto"))) { g_free (c->language); c->language = g_strdup (s); }
      if (json_object_has_member (o, "probe_timeout_ms")) { int t = (int) json_object_get_int_member (o, "probe_timeout_ms"); if (t >= 1000 && t <= 300000) c->probe_timeout_ms = t; }
      if (json_object_has_member (o, "default_recursive")) c->default_recursive = json_object_get_boolean_member (o, "default_recursive");
      JsonArray *a;
      if (json_object_has_member (o, "directories") && (a = json_object_get_array_member (o, "directories")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = json_array_get_object_element (a, i);
          if (d && obj_str (d, "path")) g_ptr_array_add (c->dirs, ps_dir_new (obj_str (d, "path"), !json_object_has_member (d, "recursive") || json_object_get_boolean_member (d, "recursive")));
        }
      if (json_object_has_member (o, "ignored") && (a = json_object_get_array_member (o, "ignored")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = json_array_get_object_element (a, i);
          if (d && obj_str (d, "path")) { PsIgnored *ig = g_new0 (PsIgnored, 1); ig->path = g_strdup (obj_str (d, "path")); ig->name = g_strdup (obj_str (d, "name") ? obj_str (d, "name") : ""); g_ptr_array_add (c->ignored, ig); }
        }
      if (json_object_has_member (o, "plugins") && (a = json_object_get_array_member (o, "plugins")))
        for (guint i = 0; i < json_array_get_length (a); i++) {
          JsonObject *d = json_array_get_object_element (a, i);
          if (!d || !obj_str (d, "path")) continue;
          PsItem *it = g_new0 (PsItem, 1);
          it->path = g_strdup (obj_str (d, "path")); it->name = g_strdup (obj_str (d, "name")); it->category = g_strdup (obj_str (d, "category"));
          it->entry = g_strdup (obj_str (d, "entry")); it->kind = g_strdup (obj_str (d, "kind")); it->detail = g_strdup (obj_str (d, "detail"));
          it->verdict = verdict_from (obj_str (d, "verdict")); it->reason = reason_from (obj_str (d, "reason"));
          it->enabled = json_object_has_member (d, "enabled") ? json_object_get_boolean_member (d, "enabled") : (it->verdict != PE8_VERDICT_NO);
          it->mtime = json_object_has_member (d, "mtime") ? json_object_get_int_member (d, "mtime") : 0;
          it->size = json_object_has_member (d, "size") ? json_object_get_int_member (d, "size") : 0;
          it->proc_name = ps_item_proc_name (it->path, it->entry, it->name);
          g_ptr_array_add (c->items, it);
        }
    }
  } else if (err && !g_error_matches (err, G_FILE_ERROR, G_FILE_ERROR_NOENT)) {
    g_printerr ("pshost: cannot read config (%s), using defaults\n", err->message);
  }
  g_clear_error (&err); g_object_unref (p); g_free (file); g_free (dir);
  return c;
}

gboolean ps_config_save (const PsConfig *c) {
  JsonBuilder *b = json_builder_new ();
  json_builder_begin_object (b);
  json_builder_set_member_name (b, "version"); json_builder_add_int_value (b, 1);
  json_builder_set_member_name (b, "language"); json_builder_add_string_value (b, c->language);
  json_builder_set_member_name (b, "probe_timeout_ms"); json_builder_add_int_value (b, c->probe_timeout_ms);
  json_builder_set_member_name (b, "default_recursive"); json_builder_add_boolean_value (b, c->default_recursive);
  json_builder_set_member_name (b, "directories"); json_builder_begin_array (b);
  for (guint i = 0; i < c->dirs->len; i++) {
    PsDir *d = g_ptr_array_index (c->dirs, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, d->path);
    json_builder_set_member_name (b, "recursive"); json_builder_add_boolean_value (b, d->recursive);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_set_member_name (b, "ignored"); json_builder_begin_array (b);
  for (guint i = 0; i < c->ignored->len; i++) {
    PsIgnored *ig = g_ptr_array_index (c->ignored, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, ig->path);
    json_builder_set_member_name (b, "name"); json_builder_add_string_value (b, ig->name);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_set_member_name (b, "plugins"); json_builder_begin_array (b);
  for (guint i = 0; i < c->items->len; i++) {
    PsItem *it = g_ptr_array_index (c->items, i);
    json_builder_begin_object (b);
    json_builder_set_member_name (b, "path"); json_builder_add_string_value (b, it->path);
    json_builder_set_member_name (b, "name"); json_builder_add_string_value (b, it->name ? it->name : "");
    json_builder_set_member_name (b, "category"); json_builder_add_string_value (b, it->category ? it->category : "");
    json_builder_set_member_name (b, "entry"); json_builder_add_string_value (b, it->entry ? it->entry : "");
    json_builder_set_member_name (b, "kind"); json_builder_add_string_value (b, it->kind ? it->kind : "");
    json_builder_set_member_name (b, "verdict"); json_builder_add_string_value (b, pe8_verdict_key (it->verdict));
    json_builder_set_member_name (b, "reason"); json_builder_add_string_value (b, pe8_reason_key (it->reason));
    json_builder_set_member_name (b, "detail"); json_builder_add_string_value (b, it->detail ? it->detail : "");
    json_builder_set_member_name (b, "enabled"); json_builder_add_boolean_value (b, it->enabled);
    json_builder_set_member_name (b, "mtime"); json_builder_add_int_value (b, it->mtime);
    json_builder_set_member_name (b, "size"); json_builder_add_int_value (b, it->size);
    json_builder_end_object (b);
  }
  json_builder_end_array (b);
  json_builder_end_object (b);
  JsonGenerator *g = json_generator_new ();
  JsonNode *root = json_builder_get_root (b);
  json_generator_set_root (g, root); json_generator_set_pretty (g, TRUE);
  char *dir = ps_config_dir (), *file = g_build_filename (dir, "config.json", NULL), *tmp = g_strconcat (file, ".tmp", NULL);
  g_mkdir_with_parents (dir, 0700);
  gboolean ok = json_generator_to_file (g, tmp, NULL);
  if (ok) { GFile *a = g_file_new_for_path (tmp), *z = g_file_new_for_path (file); ok = g_file_move (a, z, G_FILE_COPY_OVERWRITE, NULL, NULL, NULL, NULL); g_object_unref (a); g_object_unref (z); }
  json_node_unref (root); g_object_unref (g); g_object_unref (b); g_free (tmp); g_free (file); g_free (dir);
  return ok;
}

PsItem *ps_config_find_item (const PsConfig *c, const char *path, const char *entry, const char *name) {
  for (guint i = 0; i < c->items->len; i++) {
    PsItem *it = g_ptr_array_index (c->items, i);
    if (!g_strcmp0 (it->path, path) && !g_strcmp0 (it->entry, entry) && !g_strcmp0 (it->name, name)) return it;
  }
  return NULL;
}

gboolean ps_config_is_ignored (const PsConfig *c, const char *path, const char *name) {
  for (guint i = 0; i < c->ignored->len; i++) {
    PsIgnored *ig = g_ptr_array_index (c->ignored, i);
    if (!g_ascii_strcasecmp (ig->path, path) && !g_strcmp0 (ig->name, name ? name : "")) return TRUE;
  }
  return FALSE;
}
void ps_config_ignore_item (PsConfig *c, const PsItem *it) {
  if (!ps_config_is_ignored (c, it->path, it->name)) {
    PsIgnored *ig = g_new0 (PsIgnored, 1); ig->path = g_strdup (it->path); ig->name = g_strdup (it->name ? it->name : ""); g_ptr_array_add (c->ignored, ig);
  }
  for (guint i = 0; i < c->items->len; i++) if (g_ptr_array_index (c->items, i) == it) { g_ptr_array_remove_index (c->items, i); break; }
}
void ps_config_clear_ignored (PsConfig *c) { g_ptr_array_set_size (c->ignored, 0); }

gboolean ps_path_is_under (const char *path, const char *dir) {
  size_t n = strlen (dir);
  while (n > 0 && (dir[n - 1] == '\\' || dir[n - 1] == '/')) n--;
  if (g_ascii_strncasecmp (path, dir, n) != 0) return FALSE;
  return path[n] == '\\' || path[n] == '/';
}

void ps_config_prune_items (PsConfig *c) {
  for (guint i = c->items->len; i-- > 0;) {
    PsItem *it = g_ptr_array_index (c->items, i); gboolean keep = FALSE;
    for (guint k = 0; k < c->dirs->len && !keep; k++) keep = ps_path_is_under (it->path, ((PsDir *) g_ptr_array_index (c->dirs, k))->path);
    if (!keep) g_ptr_array_remove_index (c->items, i);
  }
}

/* ------------------------------------------------------------------ language & translations */
static Pe8Lang cur_lang = PE8_LANG_EN;

Pe8Lang ps_config_language (const PsConfig *c) {
  if (!g_strcmp0 (c->language, "pl")) return PE8_LANG_PL;
  if (!g_strcmp0 (c->language, "en")) return PE8_LANG_EN;
  const char *const *names = g_get_language_names ();
  for (int i = 0; names[i]; i++) { if (g_str_has_prefix (names[i], "pl")) return PE8_LANG_PL; if (g_str_has_prefix (names[i], "en")) return PE8_LANG_EN; }
  return PE8_LANG_EN;
}
void ps_set_language (Pe8Lang l) { cur_lang = l; }
Pe8Lang ps_get_language (void) { return cur_lang; }

typedef struct { const char *en, *pl; } Tr;
static const Tr table[] = {
  { "Manage plug-ins...", "Zarządzaj wtyczkami..." },
  { "About / O wtyczce", "O wtyczce / About" },
  { "PSHost - Photoshop plug-ins", "PSHost - wtyczki Photoshop" },
  { "Plug-in directories", "Katalogi z wtyczkami" },
  { "Directory", "Katalog" },
  { "Subfolders", "Podkatalogi" },
  { "Add directory...", "Dodaj katalog..." },
  { "Remove", "Usuń" },
  { "Rescan", "Skanuj ponownie" },
  { "Include subfolders when adding", "Uwzględnij podkatalogi przy dodawaniu" },
  { "Found plug-ins", "Znalezione wtyczki" },
  { "Use", "Użyj" },
  { "Name", "Nazwa" },
  { "Category", "Kategoria" },
  { "File", "Plik" },
  { "Result", "Wynik" },
  { "Reason", "Powód" },
  { "OK", "OK" },
  { "With reservations", "Z zastrzeżeniami" },
  { "No", "NIE" },
  { "Details", "Szczegóły" },
  { "Settings", "Ustawienia" },
  { "Language:", "Język:" },
  { "Automatic", "Automatyczny" },
  { "Test time limit (s):", "Limit czasu testu (s):" },
  { "Menu names and the language of the filters change after GIMP is restarted.", "Nazwy w menu zmienią się po ponownym uruchomieniu GIMP-a." },
  { "Adding a plug-in runs third-party code during the test. Add only plug-ins from sources you trust.", "Dodanie wtyczki uruchamia obcy kod podczas testu. Dodawaj tylko wtyczki z zaufanych źródeł." },
  { "New filters appear in the Filters menu after GIMP is restarted.", "Nowe filtry pojawią się w menu Filtry po ponownym uruchomieniu GIMP-a." },
  { "Choose a directory with Photoshop plug-ins (.8bf)", "Wybierz katalog z wtyczkami Photoshop (.8bf)" },
  { "Scanning...", "Skanowanie..." },
  { "Used: %d, with reservations: %d, skipped: %d", "Użyte: %d, z zastrzeżeniami: %d, pominięte: %d" },
  { "No plug-ins found yet. Add a directory.", "Nie znaleziono jeszcze wtyczek. Dodaj katalog." },
  { "Scan result", "Wynik skanowania" },
  { "No .8bf files were found in this directory.", "W tym katalogu nie znaleziono plików .8bf." },
  { "This directory is already on the list.", "Ten katalog jest już na liście." },
  { "Close", "Zamknij" },
  { "The plug-in is disabled", "Wtyczka jest wyłączona" },
  { "Filters", "Filtry" },
  { "Manage", "Zarządzanie" },
  { "Run on current layer", "Uruchom na bieżącej warstwie" },
  { "Select a filter and click Run to apply it to the active layer (double-click also works).", "Wybierz filtr i kliknij Uruchom, aby zastosować go na aktywnej warstwie (działa też dwuklik)." },
  { "No filters yet. Add a directory with plug-ins in the Manage tab.", "Brak filtrów. Dodaj katalog z wtyczkami na karcie Zarządzanie." },
  { "Applies to: %s", "Zastosowane zostanie do: %s" },
  { "No image is open. Open an image to run a filter.", "Nie ma otwartego obrazu. Otwórz obraz, aby uruchomić filtr." },
  { "Remove rejected", "Usuń odrzucone" },
  { "Remove selected", "Usuń zaznaczone" },
  { "Restore removed", "Przywróć usunięte" },
  { "Removes entries from this list only. Files on disk are not deleted.", "Usuwa wpisy tylko z tej listy. Pliki na dysku nie są kasowane." },
  { "Remove %d rejected plug-ins from the list?", "Usunąć z listy odrzucone wtyczki (%d)?" },
  { "The plug-in file no longer exists.", "Plik wtyczki już nie istnieje." },
  { "Layers larger than 32000 pixels are not supported.", "Warstwy większe niż 32000 pikseli nie są obsługiwane." },
  { "The selection does not overlap the layer.", "Zaznaczenie nie przecina się z warstwą." },
  { "Cannot create a temporary directory.", "Nie można utworzyć katalogu tymczasowego." },
  { "Cannot write the temporary image.", "Nie można zapisać obrazu tymczasowego." },
  { "Cannot start the filter process", "Nie można uruchomić procesu filtra" },
  { "The filter did not produce a valid result.", "Filtr nie zwrócił poprawnego wyniku." },
  { "The filter did not finish in time and was stopped. The image was not changed.", "Filtr nie zakończył pracy w czasie i został zatrzymany. Obraz nie został zmieniony." },
  { "The filter crashed. The image was not changed.", "Filtr uległ awarii. Obraz nie został zmieniony." },
  { "The plug-in could not be loaded (Windows error %s).", "Nie udało się załadować wtyczki (kod błędu Windows %s)." },
  { "The filter reported an error", "Filtr zgłosił błąd" },
  { "The filter reported an error (code %s).", "Filtr zgłosił błąd (kod %s)." },
  { "The filter process ended unexpectedly (code %u).", "Proces filtra zakończył się nieoczekiwanie (kod %u)." },
  { "Filter error", "Błąd filtra" },
  { "Restart GIMP...", "Uruchom ponownie GIMP-a..." },
  { "Restart GIMP", "Restart GIMP-a" },
  { "To load the new plug-ins GIMP must be restarted. Restart now?", "Aby załadować nowe wtyczki, GIMP musi zostać uruchomiony ponownie. Uruchomić teraz?" },
  { "Restart now", "Uruchom ponownie teraz" },
  { "Later", "Później" },
  { "Unsaved changes in: %s. GIMP will ask whether to save them before closing.", "Niezapisane zmiany w obrazach: %s. GIMP zapyta o ich zapisanie przed zamknięciem." },
  { "The filter list changed. Restart GIMP to apply the changes.", "Lista filtrów się zmieniła. Uruchom ponownie GIMP-a, aby zastosować zmiany." },
  { "Cannot restart GIMP automatically: %s. Close GIMP manually and start it again.", "Nie można automatycznie uruchomić GIMP-a ponownie: %s. Zamknij GIMP-a ręcznie i uruchom go ponownie." },
  { "cannot find the GIMP process", "nie znaleziono procesu GIMP-a" },
  { "GIMP does not offer a clean quit", "GIMP nie udostępnia czystego zamknięcia" },
};
const char *ps_tr (const char *en) {
  if (cur_lang == PE8_LANG_EN) return en;
  for (size_t i = 0; i < G_N_ELEMENTS (table); i++) if (!strcmp (table[i].en, en)) return table[i].pl;
  return en;
}
