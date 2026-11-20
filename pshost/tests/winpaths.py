# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 PSHost contributors
"""Known-folder lookup that does not depend on environment variables (the MSYS shell used by ctest does not set them)."""
import ctypes, os

def _folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf)
    return buf.value

def appdata():       return os.environ.get("APPDATA") or _folder(0x1A)          # %APPDATA%      (Roaming)
def localappdata():  return os.environ.get("LOCALAPPDATA") or _folder(0x1C)    # %LOCALAPPDATA%
