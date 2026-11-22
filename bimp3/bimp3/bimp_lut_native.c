/* SPDX-License-Identifier: GPL-2.0-or-later
 * Plain C ABI: no Python, GIMP, GEGL or third-party runtime dependencies.
 * gcc -O3 -shared -static-libgcc -o bimp_lut_native.dll bimp_lut_native.c
 */
#include <stddef.h>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
EXPORT void bimp_lut(float *pixels, size_t count, const float *table,
                     int size, int dimension, const float *low,
                     const float *high, float mix)
{
    for (size_t pixel = 0; pixel < count; pixel++) {
        float *rgb = pixels + pixel * 4;
        int base[3]; float f[3]; float result[3] = {0, 0, 0};
        for (int c = 0; c < 3; c++) {
            float x = (rgb[c] - low[c]) / (high[c] - low[c]);
            if (!(x >= 0)) x = 0;
            if (x > 1) x = 1;
            x *= size - 1;
            base[c] = (int)x;
            if (base[c] >= size - 1) base[c] = size - 2;
            f[c] = x - base[c];
        }
        if (dimension == 1) {
            for (int c = 0; c < 3; c++)
                result[c] = table[base[c] * 3 + c] * (1-f[c]) + table[(base[c]+1) * 3 + c] * f[c];
        } else {
            for (int b = 0; b < 2; b++) for (int g = 0; g < 2; g++) for (int r = 0; r < 2; r++) {
                float weight = (r ? f[0] : 1-f[0]) * (g ? f[1] : 1-f[1]) * (b ? f[2] : 1-f[2]);
                int index = ((base[2]+b)*size*size + (base[1]+g)*size + base[0]+r)*3;
                for (int c = 0; c < 3; c++) result[c] += table[index+c] * weight;
            }
        }
        for (int c = 0; c < 3; c++) rgb[c] += mix * (result[c] - rgb[c]);
    }
}
