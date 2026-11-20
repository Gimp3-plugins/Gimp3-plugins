# -*- coding: utf-8 -*-
"""
Biblioteka LUT-ów: folder z kopiami plików .cube + indeks JSON.

Układ na dysku (root to zwykle <katalog GIMP-a>/lut-cube):
    root/index.json        – wpisy, kategorie, presety, ustawienia
    root/luts/*            – kopie zaimportowanych plików (.cube, .3dl, Hald .png)
    root/cache/<id>.lutc   – sparsowane LUT-y (format binarny, szybki odczyt)

Moduł nie zależy od GIMP-a.
"""

import datetime
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

import cube_parser
import lut_formats
from cube_parser import CubeError
from lut_i18n import tr  # noqa: E402

EXPORT_INDEX = "lut-cube-biblioteka.json"

INDEX_VERSION = 1
DEFAULT_PREFIX = "Zetmar - Cyfrowy Przyjaciel - "
MAX_RECENT = 5

DEFAULT_SETTINGS = {
    "strip_prefix": True,
    "prefix": DEFAULT_PREFIX,
    "startup_dir": "",          # folder proponowany przy pierwszym imporcie
    "startup_offered": False,   # czy już zaproponowano import startowy
    "last_dir": "",             # ostatni folder w oknach wyboru plików
    "last_lut": "",             # id albo ścieżka ostatniego LUT-a
    "strength": 100.0,
    "color": 100.0,
    "luminance": 100.0,
    "shadows": 100.0,           # maska tonalna (%)
    "midtones": 100.0,
    "highlights": 100.0,
    "interpolation": "tetrahedral",
    "output": "new-layer",      # new-layer / in-place
    "strength_as_opacity": False,
    "preview_mode": "split",    # split / side / toggle
    "split_vertical": False,
    "sort": "name",             # name / date
    "category_filter": "",
    "favorites_only": False,
}


class LibraryError(Exception):
    """Błąd biblioteki z komunikatem po polsku."""


class ImportResult:
    def __init__(self):
        self.added = []        # id nowych wpisów
        self.duplicates = []   # (ścieżka, nazwa istniejącego wpisu)
        self.errors = []       # (ścieżka, komunikat)

    def merge(self, other):
        self.added += other.added
        self.duplicates += other.duplicates
        self.errors += other.errors

    def summary(self):
        """Krótki opis wyniku importu po polsku."""
        lines = [tr("Dodano: %d") % len(self.added)]
        if self.duplicates:
            lines.append(tr("Pominięto duplikaty (ta sama treść pliku): %d")
                         % len(self.duplicates))
        if self.errors:
            lines.append(tr("Błędy: %d") % len(self.errors))
            for path, msg in self.errors[:10]:
                lines.append("  • %s – %s" % (os.path.basename(path), msg))
            if len(self.errors) > 10:
                lines.append(tr("  • … i %d więcej") % (len(self.errors) - 10))
        return "\n".join(lines)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def find_lut_files(folder, recursive=True):
    """
    Pliki LUT w folderze: .cube, .3dl i obrazy Hald CLUT (.png tylko wtedy,
    gdy wymiary pasują do Hald – zwykłe zdjęcia są pomijane).
    """
    found = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames.sort()
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if lut_formats.is_lut_file(path):
                    found.append(path)
    else:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and lut_formats.is_lut_file(path):
                found.append(path)
    return found


find_cube_files = find_lut_files     # dawna nazwa


def short_name(stem, prefix, strip):
    """Nazwa wyświetlana z nazwy pliku – opcjonalnie bez wspólnego prefiksu."""
    if strip and prefix and stem.lower().startswith(prefix.lower()):
        rest = stem[len(prefix):].strip()
        if rest:
            return rest
    return stem


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


class Library:

    def __init__(self, root):
        self.root = root
        self.luts_dir = os.path.join(root, "luts")
        self.cache_dir = os.path.join(root, "cache")
        self.index_path = os.path.join(root, "index.json")
        self.entries = {}          # id -> dict
        self.categories = []
        self.presets = {}          # nazwa -> ustawienia (patrz save_preset)
        self.recent = []           # id ostatnio użytych (najnowszy pierwszy)
        self.settings = dict(DEFAULT_SETTINGS)
        self.load_warning = ""
        self._luts = {}            # id -> CubeLUT (w pamięci)
        self.load()

    # --- zapis / odczyt indeksu ---------------------------------------------

    def ensure_dirs(self):
        try:
            os.makedirs(self.luts_dir, exist_ok=True)
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError as e:
            raise LibraryError(tr("Brak uprawnień do folderu biblioteki %s: %s")
                               % (self.root, e.strerror or e))

    def load(self):
        if not os.path.isfile(self.index_path):
            return
        try:
            with open(self.index_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(tr("zły format"))
        except (OSError, ValueError) as e:
            # Uszkodzony indeks: odkładamy kopię i zaczynamy od nowa.
            backup = self.index_path + ".uszkodzony"
            try:
                shutil.copyfile(self.index_path, backup)
            except OSError:
                pass
            self.load_warning = (tr("Indeks biblioteki był uszkodzony (%s). "
                                 "Kopia: %s") % (e, backup))
            return
        for e in data.get("entries", []):
            if isinstance(e, dict) and e.get("id") and e.get("file"):
                self.entries[e["id"]] = e
        self.categories = [c for c in data.get("categories", [])
                           if isinstance(c, str)]
        self.recent = [i for i in data.get("recent", []) if i in self.entries]
        presets = data.get("presets", {})
        if isinstance(presets, dict):
            self.presets = {k: v for k, v in presets.items()
                            if isinstance(k, str) and isinstance(v, dict)}
        settings = data.get("settings", {})
        if isinstance(settings, dict):
            for k, v in settings.items():
                if k in DEFAULT_SETTINGS and type(v) is type(DEFAULT_SETTINGS[k]):
                    self.settings[k] = v
                elif k in DEFAULT_SETTINGS and isinstance(DEFAULT_SETTINGS[k], float) \
                        and isinstance(v, int):
                    self.settings[k] = float(v)

    def save(self):
        self.ensure_dirs()
        data = {
            "version": INDEX_VERSION,
            "entries": list(self.entries.values()),
            "categories": self.categories,
            "recent": self.recent,
            "presets": self.presets,
            "settings": self.settings,
        }
        tmp = self.index_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.index_path)
        except OSError as e:
            raise LibraryError(tr("Nie można zapisać indeksu biblioteki %s: %s")
                               % (self.index_path, e.strerror or e))

    # --- wpisy ---------------------------------------------------------------

    def _file_path(self, filename):
        """Ścieżka pliku w luts/ – tylko sama nazwa, bez wychodzenia poza folder."""
        name = os.path.basename(filename or "")
        if not name or name != filename or name in (".", ".."):
            raise LibraryError(tr("Niepoprawna nazwa pliku w indeksie biblioteki: %r")
                               % filename)
        return os.path.join(self.luts_dir, name)

    def path(self, lut_id):
        return self._file_path(self.entries[lut_id]["file"])

    def display_name(self, lut_id):
        e = self.entries[lut_id]
        if e.get("name"):
            return e["name"]
        stem = os.path.splitext(e["file"])[0]
        return short_name(stem, self.settings["prefix"],
                          self.settings["strip_prefix"])

    def is_empty(self):
        return not self.entries

    def _find_by_hash(self, sha):
        for i, e in self.entries.items():
            if e.get("sha256") == sha:
                return i
        return None

    def _unique_filename(self, name):
        base, ext = os.path.splitext(name)
        candidate, k = name, 2
        while os.path.exists(os.path.join(self.luts_dir, candidate)):
            candidate = "%s (%d)%s" % (base, k, ext)
            k += 1
        return candidate

    def add_file(self, src, category="", save=True):
        """Kopiuje jeden plik .cube do biblioteki. Zwraca ImportResult."""
        result = ImportResult()
        try:
            sha = file_sha256(src)
        except OSError as e:
            result.errors.append((src, tr("nie można odczytać: %s")
                                  % (e.strerror or e)))
            return result
        existing = self._find_by_hash(sha)
        if existing is not None:
            result.duplicates.append((src, self.display_name(existing)))
            return result
        try:
            lut = lut_formats.load_lut_file(src)
        except CubeError as e:
            result.errors.append((src, str(e)))
            return result
        self.ensure_dirs()
        filename = os.path.basename(src)
        dest = os.path.join(self.luts_dir, filename)
        # Plik o tej samej nazwie i treści już leży w folderze (np. po usunięciu
        # „tylko z listy”) – używamy go zamiast robić kopię „(2)”.
        reuse = os.path.isfile(dest) and file_sha256(dest) == sha
        if not reuse:
            filename = self._unique_filename(filename)
            dest = os.path.join(self.luts_dir, filename)
            try:
                shutil.copyfile(src, dest)
            except OSError as e:
                result.errors.append((src, tr("nie można skopiować: %s")
                                      % (e.strerror or e)))
                return result
        lut_id = sha[:16]
        self.entries[lut_id] = {
            "id": lut_id,
            "file": filename,
            "name": "",
            "title": lut.title,
            "category": category if category in self.categories else "",
            "favorite": False,
            "added": _now(),
            "size": lut.grid_size,
            "kind": lut.kind,
            "sha256": sha,
        }
        self._luts[lut_id] = lut
        self._write_cache(lut_id, lut)
        result.added.append(lut_id)
        if save:
            self.save()
        return result

    def add_files(self, paths, category=""):
        result = ImportResult()
        for p in paths:
            result.merge(self.add_file(p, category, save=False))
        if result.added:
            self.save()
        return result

    def add_folder(self, folder, recursive=True, category=""):
        try:
            files = find_lut_files(folder, recursive)
        except OSError as e:
            raise LibraryError(tr("Nie można odczytać folderu %s: %s")
                               % (folder, e.strerror or e))
        return self.add_files(files, category)

    def rename(self, lut_id, name):
        self.entries[lut_id]["name"] = name.strip()
        self.save()

    def set_category(self, lut_id, category):
        if category and category not in self.categories:
            self.categories.append(category)
        self.entries[lut_id]["category"] = category
        self.save()

    def set_favorite(self, lut_id, favorite):
        self.entries[lut_id]["favorite"] = bool(favorite)
        self.save()

    def remove(self, lut_id, delete_file=False):
        """Usuwa wpis z listy; opcjonalnie także plik z folderu biblioteki."""
        file_path = self.path(lut_id)          # walidacja przed zmianami
        self.entries.pop(lut_id)
        self._luts.pop(lut_id, None)
        if lut_id in self.recent:
            self.recent.remove(lut_id)
        for path in (self._cache_path(lut_id),
                     file_path if delete_file else None):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as err:
                    self.save()
                    raise LibraryError(tr("Nie można usunąć pliku %s: %s")
                                       % (path, err.strerror or err))
        self.save()

    def orphan_files(self):
        """Pliki w luts/, których nie ma w indeksie (np. usunięte z listy)."""
        used = {os.path.basename(e["file"]).lower() for e in self.entries.values()}
        try:
            names = sorted(os.listdir(self.luts_dir))
        except OSError:
            return []
        return [os.path.join(self.luts_dir, n) for n in names
                if n.lower() not in used
                and os.path.isfile(os.path.join(self.luts_dir, n))]

    def remove_orphans(self):
        """Usuwa pliki-sieroty z luts/. Zwraca listę usuniętych ścieżek."""
        removed = []
        for path in self.orphan_files():
            try:
                os.remove(path)
                removed.append(path)
            except OSError as e:
                raise LibraryError(tr("Nie można usunąć pliku %s: %s")
                                   % (path, e.strerror or e))
        return removed

    # --- presety ---------------------------------------------------------------

    PRESET_KEYS = ("strength", "color", "luminance", "interpolation",
                   "shadows", "midtones", "highlights")

    def save_preset(self, name, lut_key, values):
        """
        Zapisuje preset: LUT (id z biblioteki albo "file:<ścieżka>") i ustawienia
        (siła, kolor, jasność, interpolacja, cienie/półtony/światła w %).
        """
        name = name.strip()
        if not name:
            raise LibraryError(tr("Nazwa presetu nie może być pusta."))
        preset = {k: values[k] for k in self.PRESET_KEYS if k in values}
        preset["lut"] = lut_key
        self.presets[name] = preset
        self.save()

    def delete_preset(self, name):
        self.presets.pop(name, None)
        self.save()

    def preset_lut_available(self, name):
        key = self.presets.get(name, {}).get("lut", "")
        if key.startswith("file:"):
            return os.path.isfile(key[5:])
        return key in self.entries

    # --- eksport / import całej biblioteki ------------------------------------

    def export_zip(self, path):
        """
        Zapisuje bibliotekę do jednego pliku .zip: pliki LUT-ów, nazwy,
        kategorie, ulubione i presety. Zwraca liczbę LUT-ów.
        """
        data = {"version": INDEX_VERSION, "entries": [], "categories": self.categories,
                "presets": {k: v for k, v in self.presets.items()
                            if not v.get("lut", "").startswith("file:")}}
        tmp = path + ".tmp"
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for lut_id, e in self.entries.items():
                    src = self.path(lut_id)
                    if not os.path.isfile(src):
                        continue
                    z.write(src, "luts/" + os.path.basename(src))
                    data["entries"].append({k: e.get(k) for k in (
                        "id", "file", "name", "category", "favorite", "added", "sha256")})
                z.writestr(EXPORT_INDEX, json.dumps(data, ensure_ascii=False, indent=1))
            os.replace(tmp, path)
        except OSError as e:
            raise LibraryError(tr("Nie można zapisać pliku %s: %s") % (path, e.strerror or e))
        return len(data["entries"])

    def import_zip(self, path):
        """
        Wczytuje bibliotekę z pliku .zip (z export_zip). Duplikaty (ta sama
        treść) są pomijane; nazwy, kategorie, ulubione i presety są przenoszone.
        """
        result = ImportResult()
        try:
            z = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as e:
            raise LibraryError(tr("To nie jest poprawny plik biblioteki (.zip): %s") % e)
        with z, tempfile.TemporaryDirectory() as tmpdir:
            try:
                data = json.loads(z.read(EXPORT_INDEX).decode("utf-8"))
            except (KeyError, ValueError) as e:
                raise LibraryError(tr("W pliku brak indeksu biblioteki (%s).") % e)
            id_map = {}
            for e in data.get("entries", []):
                name = os.path.basename(str(e.get("file", "")))   # bez ścieżek
                if not name:
                    continue
                try:
                    blob = z.read("luts/" + name)
                except KeyError:
                    result.errors.append((name, tr("brak pliku w archiwum")))
                    continue
                src = os.path.join(tmpdir, name)
                with open(src, "wb") as f:
                    f.write(blob)
                r = self.add_file(src, save=False)
                result.merge(r)
                new_id = r.added[0] if r.added else self._find_by_hash(file_sha256(src))
                if new_id is None:
                    continue
                id_map[e.get("id")] = new_id
                if r.added:
                    cat = e.get("category") or ""
                    if cat and cat not in self.categories:
                        self.categories.append(cat)
                    target = self.entries[new_id]
                    target["name"] = e.get("name") or ""
                    target["category"] = cat
                    target["favorite"] = bool(e.get("favorite"))
            for cat in data.get("categories", []):
                if isinstance(cat, str) and cat not in self.categories:
                    self.categories.append(cat)
            for pname, preset in (data.get("presets") or {}).items():
                if pname in self.presets or not isinstance(preset, dict):
                    continue
                if preset.get("lut") in id_map:
                    preset = dict(preset, lut=id_map[preset["lut"]])
                    self.presets[pname] = preset
        self.save()
        return result

    def mark_used(self, lut_id):
        if lut_id not in self.entries:
            return
        if lut_id in self.recent:
            self.recent.remove(lut_id)
        self.recent.insert(0, lut_id)
        del self.recent[MAX_RECENT:]
        self.entries[lut_id]["last_used"] = _now()
        self.save()

    # --- kategorie -----------------------------------------------------------

    def add_category(self, name):
        name = name.strip()
        if not name:
            raise LibraryError(tr("Nazwa kategorii nie może być pusta."))
        if name in self.categories:
            raise LibraryError(tr("Kategoria „%s” już istnieje.") % name)
        self.categories.append(name)
        self.save()

    def rename_category(self, old, new):
        new = new.strip()
        if not new:
            raise LibraryError(tr("Nazwa kategorii nie może być pusta."))
        if new != old and new in self.categories:
            raise LibraryError(tr("Kategoria „%s” już istnieje.") % new)
        self.categories[self.categories.index(old)] = new
        for e in self.entries.values():
            if e.get("category") == old:
                e["category"] = new
        if self.settings["category_filter"] == old:
            self.settings["category_filter"] = new
        self.save()

    def remove_category(self, name):
        """Usuwa kategorię; LUT-y z niej trafiają do „bez kategorii”."""
        self.categories.remove(name)
        for e in self.entries.values():
            if e.get("category") == name:
                e["category"] = ""
        if self.settings["category_filter"] == name:
            self.settings["category_filter"] = ""
        self.save()

    # --- wyszukiwanie --------------------------------------------------------

    def query(self, text="", category="", favorites_only=False, sort="name"):
        """
        Lista id pasujących LUT-ów. Na górze ulubione, potem ostatnio użyte,
        potem reszta – posortowana po nazwie albo dacie dodania (najnowsze).
        """
        text = text.strip().lower()
        ids = []
        for i, e in self.entries.items():
            if favorites_only and not e.get("favorite"):
                continue
            if category and e.get("category") != category:
                continue
            if text and text not in self.display_name(i).lower() \
                    and text not in e["file"].lower():
                continue
            ids.append(i)

        def ordered(items):
            items = sorted(items, key=lambda i: self.display_name(i).lower())
            if sort == "date":   # najnowsze najpierw, przy remisie po nazwie
                items.sort(key=lambda i: self.entries[i].get("added", ""),
                           reverse=True)
            return items

        favs = ordered(i for i in ids if self.entries[i].get("favorite"))
        recent = [i for i in self.recent if i in ids and i not in favs]
        rest = ordered(i for i in ids if i not in favs and i not in recent)
        return favs + recent + rest

    # --- wczytywanie LUT-ów (z cache) ----------------------------------------

    def _cache_path(self, lut_id):
        return os.path.join(self.cache_dir, lut_id + ".lutc")

    def _write_cache(self, lut_id, lut):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cube_parser.save_binary(lut, self._cache_path(lut_id))
        except (OSError, CubeError):
            pass   # cache jest tylko przyspieszeniem

    def load_lut(self, lut_id):
        """Zwraca CubeLUT (z pamięci, cache binarnego albo pliku .cube)."""
        lut = self._luts.get(lut_id)
        if lut is not None:
            return lut
        src = self.path(lut_id)
        cache = self._cache_path(lut_id)
        lut = None
        try:
            if os.path.getmtime(cache) >= os.path.getmtime(src):
                lut = cube_parser.load_binary(cache)
        except (OSError, CubeError):
            lut = None
        if lut is None:
            if not os.path.isfile(src):
                raise CubeError(tr("Brak pliku LUT-a w bibliotece: %s") % src)
            lut = lut_formats.load_lut_file(src)
            self._write_cache(lut_id, lut)
        self._luts[lut_id] = lut
        return lut


def suggested_startup_dir(settings, plugin_dir, home=None):
    """
    Folder proponowany do importu startowego: z ustawień, z pliku
    startup-dir.txt obok wtyczki (zapisuje go install.ps1), albo typowe
    miejsca w katalogu domowym (LUTS / LUTs / Luts – na Windows wielkość
    liter nie ma znaczenia). Zwraca "" gdy nic nie znaleziono.
    """
    if settings.get("startup_dir") and os.path.isdir(settings["startup_dir"]):
        return settings["startup_dir"]
    hint = os.path.join(plugin_dir, "startup-dir.txt")
    try:
        with open(hint, encoding="utf-8-sig") as f:
            path = f.read().strip()
        if path and os.path.isdir(path):
            return path
    except OSError:
        pass
    home = home or os.path.expanduser("~")
    for sub in ("", "Pictures", "Obrazy", "Documents", "Dokumenty"):
        base = os.path.join(home, sub) if sub else home
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            if name.lower() == "luts" and os.path.isdir(os.path.join(base, name)):
                return os.path.join(base, name)
    return ""
