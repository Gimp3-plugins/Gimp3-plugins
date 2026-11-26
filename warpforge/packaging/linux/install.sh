#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Install (or remove) WarpForge into the newest GIMP 3.x user profile.
#
# Run from the folder where you unpacked the ZIP:
#   ./install.sh               # native GIMP (Linux or macOS)
#   ./install.sh --flatpak     # Flatpak GIMP (org.gimp.GIMP)
#   ./install.sh --uninstall [--flatpak]
set -eu

flatpak=0
uninstall=0
for arg in "$@"; do
    case "$arg" in
        --flatpak) flatpak=1 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '3,8p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

config="${XDG_CONFIG_HOME:-$HOME/.config}/GIMP"
if [ "$flatpak" -eq 1 ]; then
    # Flathub's GIMP 3.2 uses the host's ~/.config/GIMP; older Flatpak builds
    # kept their profile inside ~/.var/app. Look in both.
    bases="$config
$HOME/.var/app/org.gimp.GIMP/config/GIMP"
elif [ "$(uname)" = "Darwin" ]; then
    bases="$HOME/Library/Application Support/GIMP"
else
    bases="$config"
fi

# the newest existing 3.x profile (sorted by version, then by path)
profile=$(printf '%s\n' "$bases" | while IFS= read -r base; do
    for dir in "$base"/3.*; do
        [ -d "$dir" ] && printf '%s\t%s\n' "${dir##*/}" "$dir"
    done
done | sort -t "$(printf '\t')" -k1,1V | tail -n 1 | cut -f2-)
if [ -z "$profile" ]; then
    echo "No GIMP 3 profile found. Start GIMP 3 once (then close it) and run this again." >&2
    exit 1
fi
target="$profile/plug-ins/warpforge"

rm -rf "$target"
if [ "$uninstall" -eq 1 ]; then
    echo "Removed WarpForge from $profile. Restart GIMP."
    exit 0
fi

here=$(cd "$(dirname "$0")" && pwd)
if [ ! -f "$here/warpforge/warpforge.py" ]; then
    echo "warpforge/warpforge.py not found next to this script. Unpack the whole ZIP first." >&2
    exit 1
fi
mkdir -p "$profile/plug-ins"
cp -R "$here/warpforge" "$target"
chmod +x "$target/warpforge.py"
echo "Installed WarpForge into $target"
echo "Restart GIMP, then use Filters > Distorts > WarpForge..."
