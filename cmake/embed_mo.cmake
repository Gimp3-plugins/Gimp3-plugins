# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 PSHost contributors
# Usage: cmake -DMO=<file.mo> -DOUT=<file.c> -P embed_mo.cmake   (embeds a .mo catalog as a C array)
file(READ "${MO}" hex HEX)
string(LENGTH "${hex}" hexlen)
math(EXPR last "${hexlen} - 2")
set(arr "")
foreach(i RANGE 0 ${last} 2)
  string(SUBSTRING "${hex}" ${i} 2 byte)
  string(APPEND arr "0x${byte},")
endforeach()
file(SIZE "${MO}" len)
file(WRITE "${OUT}" "#include <stddef.h>\nconst unsigned char ps_embedded_pl_mo[] = {${arr}0};\nconst size_t ps_embedded_pl_mo_len = ${len};\n")
