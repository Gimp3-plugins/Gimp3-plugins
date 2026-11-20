#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 PSHost contributors
# Build in MSYS2 UCRT64: MSYSTEM=UCRT64 C:\msys64\usr\bin\bash.exe -l build.sh
set -e
export PKG_CONFIG_PATH="/c/gimp3/lib/pkgconfig:$PKG_CONFIG_PATH"   # C:\gimp3 = junction to GIMP install (path without spaces)
cd "$(dirname "$0")"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
