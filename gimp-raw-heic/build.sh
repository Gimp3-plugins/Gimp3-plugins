#!/bin/sh
# Build gimp-raw-heic on Linux and optionally install it for the current user.
#   ./build.sh            # configure + build + unit tests
#   ./build.sh install    # also copy to ~/.config/GIMP/<3.x>/plug-ins/gimp-raw-heic
# Needs: meson, ninja, a C/C++ compiler, gettext and the development packages
# of gimp-3.0, libraw, libheif, lcms2, gexiv2 and lensfun
# (Debian/Ubuntu: libgimp-3.0-dev libraw-dev libheif-dev liblcms2-dev
#  libgexiv2-dev liblensfun-dev; Fedora: gimp-devel LibRaw-devel
#  libheif-devel lcms2-devel libgexiv2-devel lensfun-devel).
set -eu
cd "$(dirname "$0")"

[ -f build-linux/build.ninja ] || meson setup build-linux
meson compile -C build-linux
meson test -C build-linux --print-errorlogs

[ "${1:-}" = install ] || exit 0

cfg="${XDG_CONFIG_HOME:-$HOME/.config}/GIMP"
ver=$(ls "$cfg" 2>/dev/null | grep -E '^3\.[0-9]+$' | sort -V | tail -1)
[ -n "$ver" ] || { echo "No GIMP 3 profile in $cfg: start GIMP once first." >&2; exit 1; }

dest="$cfg/$ver/plug-ins/gimp-raw-heic"
rm -rf "$dest"
mkdir -p "$dest"
install -m 755 build-linux/gimp-raw-heic "$dest/"
for mo in build-linux/po/*.mo; do
  [ -e "$mo" ] || continue
  lang=$(basename "$mo" .mo)
  mkdir -p "$dest/locale/$lang/LC_MESSAGES"
  cp "$mo" "$dest/locale/$lang/LC_MESSAGES/gimp-raw-heic.mo"
done
echo "Installed to $dest (lens database: the system's lensfun data)"
