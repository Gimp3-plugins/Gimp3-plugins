/* gimp-raw-heic -- shared declarations
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef RAWHEIC_H
#define RAWHEIC_H

#include <libgimp/gimp.h>
#include <glib/gi18n-lib.h>

#define RAW_LOAD_PROC        "file-raw-heic-raw-load"
#define RAW_THUMB_PROC       "file-raw-heic-raw-load-thumb"
#define HEIF_LOAD_PROC       "file-raw-heic-heif-load"
#define HEIF_THUMB_PROC      "file-raw-heic-heif-load-thumb"
#define REDEVELOP_PROC       "plug-in-raw-heic-redevelop"
#define BATCH_PROC           "plug-in-raw-heic-batch-open"
#define ADJUST_PROC          "plug-in-raw-heic-quick-adjust"
#define ABOUT_PROC           "plug-in-raw-heic-about"

#define SOURCE_PARASITE      "gimp-raw-heic-source"
#define LAYER_PARASITE       "gimp-raw-heic-layer"

/* Hard limits for untrusted input: refuse anything larger. */
#define MAX_DIMENSION        65000
#define MAX_PIXELS           ((gint64) 600 * 1000 * 1000)

typedef enum
{
  WB_CAMERA,
  WB_AUTO,
  WB_MANUAL,
  WB_SPOT
} WbMode;

typedef enum
{
  HL_CLIP,
  HL_UNCLIP,
  HL_BLEND,
  HL_REBUILD
} HighlightMode;

typedef enum
{
  CS_SRGB,
  CS_ADOBE,
  CS_DISPLAY_P3,
  CS_PROPHOTO,
  CS_REC2020,
  CS_N
} ColorSpace;

typedef enum
{
  DEPTH_U8,
  DEPTH_U16,
  DEPTH_FLOAT
} OutputDepth;

typedef struct
{
  WbMode        wb_mode;
  gdouble       wb_temperature;   /* K   */
  gdouble       wb_tint;          /* -100 (green) .. +100 (magenta) */
  gdouble       spot[4];          /* x, y, w, h in 0..1 of the oriented image */
  gdouble       exposure;         /* EV, -2 .. +3 */
  gdouble       exposure_preserve;/* 0 .. 1 */
  HighlightMode highlight;
  gint          rebuild_level;    /* 3 .. 9 */
  gboolean      highlight_compensate; /* undo LibRaw's darkening in recovery modes */
  gdouble       brightness;       /* 0.25 .. 4 */
  gboolean      auto_bright;
  gint          demosaic;         /* LibRaw user_qual */
  gdouble       denoise;          /* wavelet threshold, 0 = off */
  gint          fbdd;             /* 0, 1, 2 */
  gdouble       ca_red;           /* scale, 1 = off */
  gdouble       ca_blue;
  gboolean      hot_pixels;
  gint          median_passes;
  ColorSpace    color_space;
  gboolean      linear;
  OutputDepth   depth;
  gboolean      half_size;
  gboolean      auto_rotate;
  gboolean      camera_crop;
  gboolean      lens_vignetting;
  gboolean      lens_distortion;
  gboolean      lens_tca;
} RawSettings;

#define RAWHEIC_LENS_VIGNETTING (1 << 0)
#define RAWHEIC_LENS_DISTORTION (1 << 1)
#define RAWHEIC_LENS_TCA        (1 << 2)

/* What lensfun needs to find the lens, taken from the RAW metadata. */
typedef struct
{
  gchar   camera_make[64];
  gchar   camera_model[64];
  gchar   lens_make[128];
  gchar   lens[128];
  gfloat  focal;
  gfloat  focal35;
  gfloat  aperture;
} LensInfo;

/* Developed image, linear RGB in the requested primaries: either float
 * (previews, scaled output) or, for full-size loads, LibRaw's own 16-bit
 * buffer to avoid a second full-size copy.
 */
typedef struct
{
  gint      width;
  gint      height;
  gfloat   *pixels;     /* width * height * 3, or NULL      */
  guint16  *pixels16;   /* width * height * 3, or NULL      */
  gpointer  mem;        /* libraw_processed_image_t owning pixels16 */
  gchar    *camera;     /* "Make Model" */
  gchar    *lens;       /* lens name from the file, or NULL */
  gboolean  lens_known; /* found in the lensfun database */
  gint      lens_done;  /* RAWHEIC_LENS_* corrections applied */
} RawImage;

typedef gboolean (* RawProgressFunc) (gdouble fraction, gpointer data);

/* settings.c */
void              raw_settings_defaults        (RawSettings          *s);
void              raw_settings_from_config     (RawSettings          *s,
                                                GimpProcedureConfig  *config);
void              raw_settings_to_config       (const RawSettings    *s,
                                                GimpProcedureConfig  *config);
void              raw_settings_add_arguments   (GimpProcedure        *procedure);
gchar           * raw_settings_serialize       (const RawSettings    *s,
                                                const gchar          *source_path);
gboolean          raw_settings_deserialize     (RawSettings          *s,
                                                const gchar          *text,
                                                gchar               **source_path);
const gchar     * raw_settings_wb_nick         (WbMode                mode);
void              raw_batch_session_begin      (const RawSettings    *s,
                                                gchar               **files);
void              raw_batch_session_end        (void);
gboolean          raw_batch_session_lookup     (const gchar          *path,
                                                RawSettings          *s);

/* presets.c */
GList           * raw_presets_list             (void);
gboolean          raw_presets_load             (const gchar          *name,
                                                RawSettings          *s);
gboolean          raw_presets_save             (const gchar          *name,
                                                const RawSettings    *s,
                                                GError              **error);
gboolean          raw_presets_delete           (const gchar          *name);
gboolean          raw_presets_is_builtin       (const gchar          *name);
gchar           * raw_presets_file_name        (const gchar          *name);

/* raw-develop.c */
typedef struct _RawSession RawSession;
RawSession      * raw_session_open             (const gchar          *path,
                                                GError              **error);
RawImage        * raw_session_develop          (RawSession           *ses,
                                                const RawSettings    *s,
                                                gint                  max_size,
                                                RawProgressFunc       progress,
                                                gpointer              progress_data,
                                                GError              **error);
RawImage        * raw_session_develop_region   (RawSession           *ses,
                                                const RawSettings    *s,
                                                const gdouble         region[4],
                                                GError              **error);
void              raw_session_size             (RawSession           *ses,
                                                const RawSettings    *s,
                                                gint                 *width,
                                                gint                 *height);
const gchar     * raw_session_camera           (RawSession           *ses);
void              raw_session_free             (RawSession           *ses);
RawImage        * raw_develop                  (const gchar          *path,
                                                const RawSettings    *s,
                                                gint                  max_size,
                                                RawProgressFunc       progress,
                                                gpointer              progress_data,
                                                GError              **error);
void              raw_image_free               (RawImage             *img);
GBytes          * raw_extract_thumbnail        (const gchar          *path,
                                                gint                 *out_width,
                                                gint                 *out_height,
                                                gint                 *flip,
                                                gboolean             *is_jpeg,
                                                gint                 *bmp_w,
                                                gint                 *bmp_h,
                                                GError              **error);
gboolean          raw_probe                    (const gchar          *path,
                                                gchar               **camera,
                                                gint                 *width,
                                                gint                 *height,
                                                GError              **error);

/* denoise.c */
gboolean          rawheic_wavelet_denoise      (guint16              *rgb,
                                                gint                  width,
                                                gint                  height,
                                                gdouble               threshold);

gboolean          rawheic_wavelet_denoise_banded (guint16            *rgb,
                                                gint                  width,
                                                gint                  height,
                                                gdouble               threshold,
                                                gint                  band);

/* lens.c */
gboolean          rawheic_lens_db_available    (void);
gchar           * rawheic_lens_describe        (const LensInfo       *info);
gint              rawheic_lens_correct         (gfloat               *rgb,
                                                gint                  w,
                                                gint                  h,
                                                gint                  full_w,
                                                gint                  full_h,
                                                gint                  off_x,
                                                gint                  off_y,
                                                const LensInfo       *info,
                                                gint                  flags);

/* profiles.c */
GimpColorProfile* rawheic_profile_new          (ColorSpace            cs,
                                                gboolean              linear);
GimpColorProfile* rawheic_profile_rec2100_linear (void);

/* image.c */
GimpImage       * rawheic_image_from_raw       (RawImage             *img,
                                                const RawSettings    *s,
                                                GFile                *file,
                                                GError              **error);
void              rawheic_mark_layer           (GimpLayer            *layer);
void              rawheic_attach_source        (GimpImage            *image,
                                                const RawSettings    *s,
                                                const gchar          *path);

/* raw-load.c */
GimpProcedure   * raw_load_procedure_new       (GimpPlugIn           *plug_in,
                                                const gchar          *name);
GimpProcedure   * raw_thumb_procedure_new      (GimpPlugIn           *plug_in,
                                                const gchar          *name);

/* raw-dialog.c */
gboolean          raw_dialog_run               (GimpProcedure        *procedure,
                                                GimpProcedureConfig  *config,
                                                const gchar          *path,
                                                const gchar          *title);

/* redevelop.c */
GimpProcedure   * redevelop_procedure_new      (GimpPlugIn           *plug_in,
                                                const gchar          *name);
GimpProcedure   * batch_procedure_new          (GimpPlugIn           *plug_in,
                                                const gchar          *name);

/* adjust.c */
GimpProcedure   * adjust_procedure_new         (GimpPlugIn           *plug_in,
                                                const gchar          *name);

/* heif-load.c */
GimpProcedure   * heif_load_procedure_new      (GimpPlugIn           *plug_in,
                                                const gchar          *name);

/* image.c (internal) */
gboolean          rawheic_write_layer          (GimpDrawable         *drawable,
                                                const RawImage       *img,
                                                ColorSpace            cs,
                                                gboolean              undoable,
                                                GError              **error);

/* heif-load.c (Apple HDR gain maps) */
gboolean          rawheic_apple_hdr_tags       (const guint8         *note,
                                                gsize                 len,
                                                gdouble              *maker33,
                                                gdouble              *maker48);
gdouble           rawheic_apple_headroom       (gdouble               maker33,
                                                gdouble               maker48);

/* util.c */
gchar           * rawheic_file_path            (GFile                *file);
gboolean          rawheic_shift_pressed        (void);
gboolean          rawheic_path_is_remote       (const gchar          *path);
gboolean          rawheic_confirm_remote       (const gchar          *path);

#endif
