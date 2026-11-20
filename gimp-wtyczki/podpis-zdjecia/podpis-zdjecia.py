#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Podpis na zdjęciu – wtyczka GIMP 3.x.

Dodaje podpis (tekst albo obraz, np. logo/sygnaturę) jako nową warstwę
na samej górze stosu warstw. Całość to jedna grupa cofania.

Dwie osobne procedury (zamiast jednej z przełącznikiem trybu) – dialogi są
prostsze, a parametry PDB nie zawierają pól bez znaczenia dla danego trybu:
  python-fu-podpis-tekst  – Filtry → Podpis → Podpis tekstowy…
  python-fu-podpis-obraz  – Filtry → Podpis → Podpis z obrazu…

Funkcje obliczeniowe (pozycja, margines, rozmiary) są czystym Pythonem
i nie wymagają GIMP-a – testy: tests/test_position.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from podpis_i18n import tr  # noqa: E402

# ---------------------------------------------------------------------------
# Czyste funkcje (bez GIMP-a) – testowane pytest-em
# ---------------------------------------------------------------------------

POSITIONS = [
    ("top-left", tr("Góra – lewo")),
    ("top-center", tr("Góra – środek")),
    ("top-right", tr("Góra – prawo")),
    ("middle-left", tr("Środek – lewo")),
    ("center", tr("Środek")),
    ("middle-right", tr("Środek – prawo")),
    ("bottom-left", tr("Dół – lewo")),
    ("bottom-center", tr("Dół – środek")),
    ("bottom-right", tr("Dół – prawo")),
]
POSITION_IDS = [p for p, _ in POSITIONS]


def split_position(position):
    """'bottom-right' -> ('bottom', 'right'); 'center' -> ('middle', 'center')."""
    if position not in POSITION_IDS:
        raise ValueError(tr("Nieznana pozycja: %r") % (position,))
    if position == "center":
        return "middle", "center"
    row, col = position.split("-")
    return row, col


def resolve_margin(image_w, image_h, margin_px, margin_percent):
    """Margines w px: margin_px, jeśli > 0, w przeciwnym razie % krótszego boku."""
    if margin_px and margin_px > 0:
        return int(margin_px)
    return int(round(min(image_w, image_h) * margin_percent / 100.0))


def compute_offset(image_w, image_h, layer_w, layer_h, position, margin):
    """
    Zwraca (x, y, clamped). Margines nie działa w osi, w której pozycja to
    „środek”. Ujemne współrzędne są przycinane do 0 (clamped=True).
    """
    row, col = split_position(position)

    if col == "left":
        x = margin
    elif col == "center":
        x = (image_w - layer_w) // 2
    else:
        x = image_w - layer_w - margin

    if row == "top":
        y = margin
    elif row == "middle":
        y = (image_h - layer_h) // 2
    else:
        y = image_h - layer_h - margin

    x, y = int(round(x)), int(round(y))
    clamped = False
    if x < 0:
        x, clamped = 0, True
    if y < 0:
        y, clamped = 0, True
    return x, y, clamped


def font_size_px(image_w, size_mode, size_percent, size_px):
    """Rozmiar fontu w px: % szerokości obrazu albo wprost w px."""
    if size_mode == "percent":
        return max(1.0, image_w * size_percent / 100.0)
    return max(1.0, float(size_px))


def auto_justify(position):
    """Wyrównanie linii z kolumny pozycji: left / center / right."""
    return split_position(position)[1]


def scaled_size(image_w, src_w, src_h, scale_percent):
    """Rozmiar podpisu, którego szerokość = scale_percent % szerokości obrazu."""
    new_w = max(1, int(round(image_w * scale_percent / 100.0)))
    new_h = max(1, int(round(src_h * new_w / float(src_w))))
    return new_w, new_h


def fit_size(image_w, image_h, w, h, position, margin):
    """
    Zmniejsza (w, h) proporcjonalnie, żeby podpis zmieścił się w obrazie
    razem z marginesem (margines liczony tylko w osiach, gdzie obowiązuje).
    Zwraca (w, h, shrunk).
    """
    row, col = split_position(position)
    avail_w = image_w - (0 if col == "center" else margin)
    avail_h = image_h - (0 if row == "middle" else margin)
    if avail_w <= 0:
        avail_w = image_w
    if avail_h <= 0:
        avail_h = image_h
    if w <= avail_w and h <= avail_h:
        return w, h, False
    factor = min(avail_w / float(w), avail_h / float(h))
    return max(1, int(w * factor)), max(1, int(h * factor)), True


def default_text(real_name):
    """Domyślny podpis: „© Imię Nazwisko” z konta systemowego albo samo „©”."""
    name = (real_name or "").strip()
    if not name or name.lower() in ("unknown", "nieznany"):
        return "©"
    return "© " + name


# --- szablony podpisów ---------------------------------------------------------

# Ustawienia zapisywane w szablonie (nazwy argumentów procedur).
TEMPLATE_KEYS = {
    "text": ["text", "font", "size-mode", "font-size-percent", "font-size-px",
             "color", "justify"],
    "image": ["file", "scale-mode", "scale-percent"],
}
COMMON_TEMPLATE_KEYS = ["opacity", "position", "margin-percent", "margin",
                        "layer-name"]


def load_templates(path):
    """{nazwa: {"kind": "text"/"image", "values": {...}}}; brak pliku = {}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and v.get("kind") in TEMPLATE_KEYS
            and isinstance(v.get("values"), dict)}


def save_template(path, name, kind, values):
    """Dopisuje (albo nadpisuje) szablon i zapisuje plik atomowo."""
    name = (name or "").strip()
    if not name:
        raise ValueError(tr("Nazwa szablonu nie może być pusta."))
    allowed = TEMPLATE_KEYS[kind] + COMMON_TEMPLATE_KEYS
    templates = load_templates(path)
    templates[name] = {"kind": kind,
                       "values": {k: v for k, v in values.items() if k in allowed}}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def find_template(templates, name, kind):
    """Szablon danego rodzaju po nazwie (bez względu na wielkość liter)."""
    wanted = (name or "").strip().lower()
    for key, tpl in templates.items():
        if key.lower() == wanted and tpl["kind"] == kind:
            return tpl["values"]
    return None


# ---------------------------------------------------------------------------
# Część GIMP-owa
# ---------------------------------------------------------------------------

try:
    import gi
    gi.require_version("Gimp", "3.0")
    gi.require_version("GimpUi", "3.0")
    gi.require_version("Gegl", "0.4")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gimp, GimpUi, Gegl, Gio, GLib, GObject, Gtk
    HAVE_GIMP = True
except (ImportError, ValueError):
    HAVE_GIMP = False

PLUG_IN_BINARY = "podpis-zdjecia"
PROC_TEXT = "python-fu-podpis-tekst"
PROC_IMAGE = "python-fu-podpis-obraz"


class PodpisError(Exception):
    """Błąd z komunikatem dla użytkownika (po polsku)."""


if HAVE_GIMP:

    def _choice(items):
        choice = Gimp.Choice.new()
        for i, (nick, label) in enumerate(items):
            choice.add(nick, i, label, "")
        return choice

    def _str_values(*values):
        return Gimp.ValueArray.new_from_values(
            [GObject.Value(GObject.TYPE_STRING, v) for v in values])

    def _add_common_arguments(procedure):
        rw = GObject.ParamFlags.READWRITE
        procedure.add_double_argument(
            "opacity", tr("Krycie (%)"), tr("Krycie warstwy podpisu 0–100 %"),
            0.0, 100.0, 70.0, rw)
        procedure.add_choice_argument(
            "position", tr("Położenie"), tr("Położenie podpisu na zdjęciu"),
            _choice(POSITIONS), "bottom-right", rw)
        procedure.add_double_argument(
            "margin-percent", tr("Margines (% krótszego boku)"),
            tr("Margines jako % krótszego boku obrazu – używany, gdy margines w px = 0"),
            0.0, 25.0, 3.0, rw)
        procedure.add_int_argument(
            "margin", tr("Margines (px, 0 = użyj %)"),
            tr("Margines w pikselach; 0 oznacza: licz z procentu"),
            0, 1000, 0, rw)
        procedure.add_string_argument(
            "layer-name", tr("Nazwa warstwy"), tr("Nazwa nowej warstwy"), tr("Podpis"), rw)
        procedure.add_string_argument(
            "template", tr("Wczytaj szablon"),
            tr("Nazwa zapisanego szablonu; jego ustawienia zastępują te z okna "
            "(puste = bez szablonu)"), "", rw)
        procedure.add_string_argument(
            "save-template", tr("Zapisz jako szablon"),
            tr("Po udanym podpisie zapisz bieżące ustawienia pod tą nazwą "
            "(puste = nie zapisuj)"), "", rw)

    # --- szablony: ustawienia <-> JSON -----------------------------------------

    def _templates_path():
        return os.path.join(Gimp.directory(), "podpis-zdjecia", "szablony.json")

    def _config_values(config, kind):
        """Ustawienia z config jako wartości JSON (font/kolor/plik po nazwie)."""
        values = {}
        for key in TEMPLATE_KEYS[kind] + COMMON_TEMPLATE_KEYS:
            v = config.get_property(key)
            if key == "font":
                v = v.get_name() if v is not None else None
            elif key == "color":
                v = list(v.get_rgba()) if v is not None else None
            elif key == "file":
                v = v.get_path() if v is not None else None
            if v is not None:
                values[key] = v
        return values

    def _apply_values(config, values):
        """Wpisuje wartości szablonu do config."""
        for key, v in values.items():
            if key == "font":
                v = Gimp.Font.get_by_name(v)
                if v is None:
                    continue          # fontu nie ma – zostaje bieżący
            elif key == "color":
                color = Gegl.Color.new("white")
                color.set_rgba(*v)
                v = color
            elif key == "file":
                v = Gio.File.new_for_path(v)
            config.set_property(key, v)

    def _templates_label():
        names = sorted(load_templates(_templates_path()))
        if not names:
            return tr("Brak zapisanych szablonów.")
        return tr("Zapisane szablony: ") + ", ".join(names)

    def _common_setup(procedure, menu_label, blurb):
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE
            | Gimp.ProcedureSensitivityMask.DRAWABLES
            | Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        procedure.set_menu_label(menu_label)
        procedure.add_menu_path("<Image>/Filters/" + tr("Podpis"))
        procedure.set_documentation(blurb, blurb, None)
        procedure.set_attribution("Marek Zettel", "Marek Zettel", "2026")

    def _place_layer(image, layer, config, warnings):
        """Wstawia gotową warstwę: krycie, nazwa, pozycja."""
        W, H = image.get_width(), image.get_height()
        position = config.get_property("position")
        m = resolve_margin(W, H, config.get_property("margin"),
                           config.get_property("margin-percent"))
        x, y, clamped = compute_offset(W, H, layer.get_width(),
                                       layer.get_height(), position, m)
        if clamped:
            warnings.append(tr("Podpis jest większy niż zdjęcie – został "
                            "przyciągnięty do krawędzi obrazu."))
        layer.set_offsets(x, y)
        layer.set_opacity(float(config.get_property("opacity")))
        name = (config.get_property("layer-name") or "").strip() or tr("Podpis")
        layer.set_name(name)

    def _build_text_layer(image, config, warnings):
        text = config.get_property("text") or ""
        if not text.strip():
            raise PodpisError(tr("Tekst podpisu jest pusty – wpisz tekst."))
        text = text.rstrip("\r\n")

        font = config.get_property("font")
        if font is None:
            font = Gimp.Font.get_by_name("Sans-serif") or Gimp.context_get_font()

        size = font_size_px(image.get_width(),
                            config.get_property("size-mode"),
                            config.get_property("font-size-percent"),
                            config.get_property("font-size-px"))

        layer = Gimp.TextLayer.new(image, text, font, size, Gimp.Unit.pixel())
        if layer is None:
            raise PodpisError(tr("Nie udało się utworzyć warstwy tekstowej."))
        image.insert_layer(layer, None, 0)

        # GIMP 3.2 nie przekazuje domyślnej wartości argumentu-koloru (przychodzi
        # kolor w pełni przezroczysty) – taki kolor traktujemy jak „nieustawiony”.
        color = config.get_property("color")
        if color is None or color.get_rgba()[3] == 0:
            color = Gegl.Color.new("white")
        layer.set_color(color)
        layer.set_antialias(True)

        justify = config.get_property("justify")
        if justify == "auto":
            justify = auto_justify(config.get_property("position"))
        layer.set_justification({
            "left": Gimp.TextJustification.LEFT,
            "center": Gimp.TextJustification.CENTER,
            "right": Gimp.TextJustification.RIGHT,
        }[justify])
        return layer

    def _build_image_layer(image, config, warnings):
        gfile = config.get_property("file")
        if gfile is None:
            raise PodpisError(tr("Nie wybrano pliku z podpisem."))
        if not gfile.query_exists(None):
            raise PodpisError(tr("Plik podpisu nie istnieje:\n%s")
                              % (gfile.get_path() or gfile.get_uri()))

        try:
            layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, gfile)
        except GLib.Error as e:
            layer = None
            load_error = e.message
        else:
            load_error = None
        if layer is None:
            hint = ""
            if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
                hint = (tr("\nObraz jest indeksowany – przekonwertuj go do RGB "
                        "(Obraz → Tryb → RGB) i spróbuj ponownie."))
            raise PodpisError(tr("Nie udało się wczytać pliku podpisu "
                              "(nieobsługiwany lub uszkodzony format):\n%s%s%s")
                              % (gfile.get_path() or gfile.get_uri(),
                                 ("\n" + load_error) if load_error else "", hint))

        image.insert_layer(layer, None, 0)
        if not layer.has_alpha():
            layer.add_alpha()

        W, H = image.get_width(), image.get_height()
        w, h = layer.get_width(), layer.get_height()
        if config.get_property("scale-mode") == "percent-width":
            w, h = scaled_size(W, w, h, config.get_property("scale-percent"))

        m = resolve_margin(W, H, config.get_property("margin"),
                           config.get_property("margin-percent"))
        w, h, shrunk = fit_size(W, H, w, h, config.get_property("position"), m)
        if shrunk:
            warnings.append(tr("Podpis był większy niż zdjęcie – zmniejszono go "
                            "proporcjonalnie do %d×%d px.") % (w, h))

        if (w, h) != (layer.get_width(), layer.get_height()):
            down = w < layer.get_width()
            Gimp.context_set_interpolation(
                Gimp.InterpolationType.LOHALO if down
                else Gimp.InterpolationType.NOHALO)
            layer.scale(w, h, False)
        return layer

    def _run_dialog(procedure, config, title, text_mode):
        GimpUi.init(PLUG_IN_BINARY)
        dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config,
                                        title=title)
        if text_mode:
            dialog.get_widget("text", Gtk.TextView)
            dialog.set_sensitive_if_in("font-size-percent", None, "size-mode",
                                       _str_values("percent"), True)
            dialog.set_sensitive_if_in("font-size-px", None, "size-mode",
                                       _str_values("pixels"), True)
            order = ["text", "font", "size-mode", "font-size-percent",
                     "font-size-px", "color", "justify"]
        else:
            dialog.set_sensitive_if_in("scale-percent", None, "scale-mode",
                                       _str_values("percent-width"), True)
            order = ["file", "scale-mode", "scale-percent"]
        order += ["opacity", "position", "margin-percent", "margin", "layer-name"]
        dialog.get_label("templates-info", _templates_label(), False, False)
        order = ["template", "templates-info"] + order + ["save-template"]
        dialog.fill(order)
        ok = dialog.run()
        dialog.destroy()
        return ok

    def _execute(procedure, run_mode, image, config, text_mode, title):
        if image is None:
            return _error(procedure, tr("Brak otwartego obrazu – otwórz zdjęcie "
                                     "i spróbuj ponownie."))
        if run_mode == Gimp.RunMode.INTERACTIVE:
            if not _run_dialog(procedure, config, title, text_mode):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                                   None)

        kind = "text" if text_mode else "image"
        tpl_name = (config.get_property("template") or "").strip()
        if tpl_name:
            values = find_template(load_templates(_templates_path()), tpl_name, kind)
            if values is None:
                return _error(procedure, tr("Nie ma szablonu „%s” dla podpisu %s. %s")
                              % (tpl_name, tr("tekstowego") if text_mode
                                 else tr("z obrazu"), _templates_label()))
            _apply_values(config, values)

        warnings = []
        layer = None
        Gimp.context_push()
        image.undo_group_start()
        try:
            try:
                if text_mode:
                    layer = _build_text_layer(image, config, warnings)
                else:
                    layer = _build_image_layer(image, config, warnings)
                _place_layer(image, layer, config, warnings)
            except Exception:
                # Nic nie zostawiamy po nieudanej operacji.
                if layer is not None and layer.is_valid():
                    try:
                        image.remove_layer(layer)
                    except Exception:
                        pass
                raise
        except PodpisError as e:
            return _error(procedure, str(e))
        except Exception as e:  # noqa – żadnych niezłapanych wyjątków
            return _error(procedure, tr("Nieoczekiwany błąd wtyczki Podpis: %s") % e)
        finally:
            image.undo_group_end()
            Gimp.context_pop()

        Gimp.displays_flush()
        save_name = (config.get_property("save-template") or "").strip()
        if save_name:
            try:
                save_template(_templates_path(), save_name, kind,
                              _config_values(config, kind))
                warnings.append(tr("Zapisano szablon „%s”.") % save_name)
            except (OSError, ValueError) as e:
                warnings.append(tr("Nie udało się zapisać szablonu: %s") % e)
        # Szablon działa jednorazowo – przy następnym otwarciu okna pola są puste.
        config.set_property("template", "")
        config.set_property("save-template", "")
        if warnings:
            Gimp.message("\n".join(warnings))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

    def _error(procedure, message):
        # GIMP sam wyświetla komunikat z GLib.Error – bez dodatkowego
        # Gimp.message(), żeby nie było dwóch okienek z tym samym tekstem.
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(message))

    class PodpisPlugin(Gimp.PlugIn):

        def do_query_procedures(self):
            return [PROC_TEXT, PROC_IMAGE]

        def do_set_i18n(self, name):
            return False

        def do_create_procedure(self, name):
            Gegl.init(None)
            rw = GObject.ParamFlags.READWRITE

            if name == PROC_TEXT:
                procedure = Gimp.ImageProcedure.new(
                    self, name, Gimp.PDBProcType.PLUGIN, self.run_text, None)
                _common_setup(procedure, tr("Podpis tekstowy…"),
                              tr("Dodaje podpis tekstowy jako nową, edytowalną "
                              "warstwę tekstową."))
                procedure.add_string_argument(
                    "text", tr("Tekst"), tr("Treść podpisu"),
                    default_text(GLib.get_real_name()), rw)
                procedure.add_font_argument(
                    "font", tr("Font"), tr("Font podpisu"), False, None, True, rw)
                procedure.add_choice_argument(
                    "size-mode", tr("Tryb rozmiaru"), tr("Jak liczyć rozmiar fontu"),
                    _choice([("percent", tr("% szerokości obrazu")),
                             ("pixels", tr("Piksele"))]),
                    "percent", rw)
                procedure.add_double_argument(
                    "font-size-percent", tr("Rozmiar (% szerokości obrazu)"),
                    tr("Rozmiar fontu jako % szerokości obrazu"),
                    0.5, 50.0, 4.0, rw)
                procedure.add_double_argument(
                    "font-size-px", tr("Rozmiar (px)"), tr("Rozmiar fontu w pikselach"),
                    4.0, 2000.0, 48.0, rw)
                procedure.add_color_argument(
                    "color", tr("Kolor"), tr("Kolor tekstu"), False,
                    Gegl.Color.new("white"), rw)
                procedure.add_choice_argument(
                    "justify", tr("Wyrównanie linii"),
                    tr("Wyrównanie linii w bloku tekstu"),
                    _choice([("auto", tr("Automatycznie (wg położenia)")),
                             ("left", tr("Do lewej")),
                             ("center", tr("Do środka")),
                             ("right", tr("Do prawej"))]),
                    "auto", rw)
                _add_common_arguments(procedure)
                return procedure

            if name == PROC_IMAGE:
                procedure = Gimp.ImageProcedure.new(
                    self, name, Gimp.PDBProcType.PLUGIN, self.run_image, None)
                _common_setup(procedure, tr("Podpis z obrazu…"),
                              tr("Dodaje podpis z pliku graficznego (logo, "
                              "sygnatura) jako nową warstwę."))
                procedure.add_file_argument(
                    "file", tr("Plik podpisu"),
                    tr("PNG z przezroczystością, JPG, WebP, SVG…"),
                    Gimp.FileChooserAction.OPEN, True, None, rw)
                procedure.add_choice_argument(
                    "scale-mode", tr("Tryb skali"), tr("Jak skalować podpis"),
                    _choice([("percent-width", tr("% szerokości obrazu")),
                             ("original", tr("Oryginalny rozmiar"))]),
                    "percent-width", rw)
                procedure.add_double_argument(
                    "scale-percent", tr("Skala (% szerokości obrazu)"),
                    tr("Szerokość podpisu jako % szerokości obrazu"),
                    1.0, 100.0, 15.0, rw)
                _add_common_arguments(procedure)
                return procedure

            return None

        def run_text(self, procedure, run_mode, image, drawables, config, data):
            return _execute(procedure, run_mode, image, config, True,
                            tr("Podpis tekstowy"))

        def run_image(self, procedure, run_mode, image, drawables, config, data):
            return _execute(procedure, run_mode, image, config, False,
                            tr("Podpis z obrazu"))


if __name__ == "__main__":
    Gimp.main(PodpisPlugin.__gtype__, sys.argv)
