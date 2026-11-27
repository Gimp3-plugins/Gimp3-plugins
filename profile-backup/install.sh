#!/usr/bin/env bash
# Instaluje wtyczkę „Profile Backup" w profilu GIMP 3 (Linux / macOS).
# Installs the "Profile Backup" plug-in into the GIMP 3 profile (Linux / macOS).
#
#   ./install.sh                 # wykryj profil / auto-detect the profile
#   ./install.sh /path/to/3.0    # wskaż profil / explicit profile folder
#   ./install.sh -f              # nadpisz bez pytania / overwrite without asking
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="$here/plug-ins/profile-backup"
force=0
profile=""
for a in "$@"; do
  case "$a" in
    -f|--force) force=1 ;;
    *) profile="$a" ;;
  esac
done

if [ -z "$profile" ]; then
  if command -v python3 >/dev/null 2>&1; then
    # The same detection function the plug-in uses.
    mapfile -t cands < <(python3 "$src/pb_core.py" detect --json 2>/dev/null |
      python3 -c 'import json,sys; d=json.load(sys.stdin); [print(c["path"]+"\t"+c["source"]) for c in d["candidates"]]; [print("LEGACY\t"+l, file=sys.stderr) for l in d["legacy"]]' || true)
    if [ "${#cands[@]}" -gt 1 ]; then
      echo "Znaleziono kilka profili / Several profiles found:"
      for i in "${!cands[@]}"; do echo "  [$i] ${cands[$i]}"; done
      read -r -p "Numer / Number [0]: " sel
      sel="${sel:-0}"
      profile="${cands[$sel]%%$'\t'*}"
    elif [ "${#cands[@]}" -eq 1 ]; then
      profile="${cands[0]%%$'\t'*}"
    fi
  fi
fi
if [ -z "$profile" ]; then
  # Fallback without Python.
  for d in "${GIMP3_DIRECTORY:-}" "${XDG_CONFIG_HOME:-$HOME/.config}/GIMP/3."* \
           "$HOME/.var/app/org.gimp.GIMP/config/GIMP/3."* \
           "$HOME/snap/gimp/current/.config/GIMP/3."* \
           "$HOME/Library/Application Support/GIMP/3."*; do
    if [ -n "$d" ] && [ -d "$d" ]; then profile="$d"; fi
  done
fi
if [ -z "$profile" ] || [ ! -d "$profile" ]; then
  echo "Nie znaleziono profilu GIMP 3. Uruchom GIMP 3 raz albo podaj ścieżkę." >&2
  echo "No GIMP 3 profile found. Start GIMP 3 once or pass the path." >&2
  exit 1
fi

target="$profile/plug-ins/profile-backup"
echo "Profil / Profile: $profile"
echo "Cel / Target:     $target"
if [ -d "$target" ] && [ "$force" -ne 1 ]; then
  read -r -p "Wtyczka już istnieje. Nadpisać? / Already installed. Overwrite? [t/y/N] " ans
  case "$ans" in t|tak|y|yes) ;; *) echo "Przerwano / Aborted."; exit 1 ;; esac
fi
mkdir -p "$target"
for f in profile-backup.py pb_core.py pb_i18n.py; do
  cp -f "$src/$f" "$target/$f"
done
chmod 755 "$target/profile-backup.py"
chmod 644 "$target/pb_core.py" "$target/pb_i18n.py"
echo "Zainstalowano. Uruchom ponownie GIMP-a: Plik > Kopia profilu."
echo "Installed. Restart GIMP: File > Profile Backup."
