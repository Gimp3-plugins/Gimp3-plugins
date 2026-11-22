"""Reviewed export templates. SPDX-License-Identifier: GPL-2.0-or-later."""

from bimp_model import new_step

PROFILES = ["Własne ustawienia", "WWW — JPEG 1600 px", "Druk — TIFF 300 ppi", "Archiwum — XCF"]


def export_profile(index):
    resize, fmt = new_step("resize"), new_step("changeformat")
    options = {"metadata": "strip-gps", "color_profile": True, "output_color": "preserve"}
    if index == 1:
        resize["settings"].update(
            resize_mode_width=1, resize_mode_height=1, new_w_px=1600, new_h_px=1600, stretch_mode=1
        )
        fmt["settings"].update(format=3, arguments={"quality": 0.85, "progressive": True})
        options["output_color"] = "srgb"
        return [resize, fmt], options
    if index == 2:
        resize["settings"].update(
            resize_mode_width=2, resize_mode_height=2, change_res=True, new_res_x=300.0, new_res_y=300.0
        )
        fmt["settings"].update(format=6, arguments={"compression": "lzw", "include-thumbnail": False})
        return [resize, fmt], options
    if index == 3:
        fmt["settings"].update(format=11, arguments={})
        options["metadata"] = "preserve"
        return [fmt], options
    return [], options
