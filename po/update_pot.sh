#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 PSHost contributors
# Regenerates po/pshost.pot from the sources and merges it into every po/*.po (MSYS2 UCRT64 gettext-tools).
#   MSYSTEM=UCRT64 C:\msys64\usr\bin\bash.exe -l po/update_pot.sh
set -e
cd "$(dirname "$0")/.."
xgettext --from-code=UTF-8 --language=C --add-comments=TRANSLATORS \
  -k_T -kN_ -kps_tr -kps_tr_lang:2 \
  --package-name=PSHost --package-version=0.7 --msgid-bugs-address=none \
  -o po/pshost.pot src/plugin/*.c src/common/*.c
shopt -s nullglob
for l in po/*.po; do msgmerge --update --backup=none --quiet "$l" po/pshost.pot; done
echo "pot: $(grep -c '^msgid' po/pshost.pot) msgids"
