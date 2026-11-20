# -*- coding: utf-8 -*-
"""Źródła obrazu do podglądu: warstwa GIMP-a albo wbudowany obrazek testowy."""

import gimp_ops
import sample_image


# --- źródła obrazu do podglądu ----------------------------------------------------

class ImageSource:
    """Podgląd z warstwy obrazu GIMP-a."""

    def __init__(self, image, layer):
        self.image, self.layer = image, layer
        self.width, self.height = layer.get_width(), layer.get_height()

    def fit(self, max_side):
        data, mask, w, h, _scale = gimp_ops.read_scaled(self.image, self.layer,
                                                        max_side)
        return data, mask, w, h

    def crop(self, cx, cy, w, h):
        data, mask, x, y, w, h = gimp_ops.read_crop(
            self.image, self.layer, int(cx - w / 2), int(cy - h / 2), w, h)
        return data, mask, x, y, w, h


class SampleSource:
    """Wbudowany obrazek testowy (gdy nie ma otwartego obrazu)."""

    W, H = 720, 480

    def __init__(self):
        self.width, self.height = self.W, self.H
        self._data = sample_image.make(self.W, self.H)

    def fit(self, max_side):
        if max_side >= max(self.W, self.H):
            return self._data, None, self.W, self.H
        w = max(1, self.W * max_side // max(self.W, self.H))
        h = max(1, self.H * max_side // max(self.W, self.H))
        return sample_image.make(w, h), None, w, h

    def crop(self, cx, cy, w, h):
        return self._data, None, 0, 0, self.W, self.H
