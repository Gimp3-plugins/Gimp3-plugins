#!/bin/sh
# Build the optional LUT accelerator on Linux or macOS (not verified on these
# systems in this tree). Without it BIMP uses the slower pure-Python path.
set -eu
cd "$(dirname "$0")/bimp3"
case "$(uname -s)" in
    Darwin) library=bimp_lut_native.dylib ;;
    *) library=bimp_lut_native.so ;;
esac
${CC:-cc} -O3 -Wall -Wextra -Werror -shared -fPIC -o "$library" bimp_lut_native.c
# bimp_lut.py loads the library only when it matches this checksum.
if command -v sha256sum >/dev/null 2>&1; then
    digest=$(sha256sum "$library" | cut -d' ' -f1)
else
    digest=$(shasum -a 256 "$library" | cut -d' ' -f1)
fi
printf '%s  %s\n' "$digest" "$library" > "$library.sha256"
echo "OK: $library"
