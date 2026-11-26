#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""GIMP 3 launcher for WarpForge.

GIMP loads plug-ins from ``plug-ins/<name>/<name>.py``. The package itself is
installed next to this file in ``lib/``; ``tools/install.py --dev`` rewrites
``LIB_DIR`` to point at a source checkout instead.
"""

import os
import sys

LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB_DIR)

from warpforge.plugin import main  # noqa: E402

sys.exit(main(sys.argv))
