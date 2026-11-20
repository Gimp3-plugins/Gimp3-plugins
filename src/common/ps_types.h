/* PSHost - minimal, independently written definitions of the Photoshop filter plug-in ABI (Win64).
 *
 * These are NOT the Adobe SDK headers. Field order and sizes were derived from the public,
 * MIT-licensed host implementation PSFilterPdn (github.com/0xC0000054/PSFilterPdn, src/PSApi) which
 * itself documents binary compatibility with the SDK, and are verified by running real third-party
 * 64-bit plug-ins. Only the parts needed to host 8-bit RGB filters are described. */
#ifndef PS_TYPES_H
#define PS_TYPES_H

#include <stdint.h>
#include <stddef.h>

typedef unsigned char PSBoolean;
typedef int32_t       Fixed16;                /* 16.16 */
typedef struct PSHandleRec *PSHandle;         /* opaque to plug-ins; use HandleProcs */

typedef struct { int16_t v, h; } Point16;                      /* vertical first */
typedef struct { int16_t top, left, bottom, right; } Rect16;
typedef struct { uint16_t red, green, blue; } PSRGBColor;
typedef struct { Fixed16 gamma, redX, redY, greenX, greenY, blueX, blueY, whiteX, whiteY, ambient; } PlugInMonitor;
typedef struct { void *hwnd; } PlatformData;                   /* Windows: parent HWND */
typedef struct { uint8_t data[256]; } PStr255;                 /* Pascal string */

enum { ps_selAbout = 0, ps_selParameters = 1, ps_selPrepare = 2, ps_selStart = 3, ps_selContinue = 4, ps_selFinish = 5 };
enum { ps_modeRGB = 3 };
enum { ps_FlatImageNoSelection = 1, ps_FlatImageWithSelection = 2 };

#define PS_SIG_8BIM 0x3842494Du               /* '8BIM' as host signature */
#define PS_ERR_NONE 0
#define PS_ERR_USER_CANCELED (-128)
#define PS_ERR_HOST_INSUFFICIENT (-30)        /* assumed values, see docs/ustalenia.md */
#define PS_ERR_PROPERTY_UNDEFINED (-31)
#define PS_ERR_MEMORY_FULL (-108)

/* --- callback tables (natural alignment) --- */
typedef struct {
  int16_t version, count;
  int16_t (*allocateProc) (int32_t size, void **bufferID);
  void *  (*lockProc)     (void *bufferID, PSBoolean moveHigh);
  void    (*unlockProc)   (void *bufferID);
  void    (*freeProc)     (void *bufferID);
  int32_t (*spaceProc)    (void);
} PSBufferProcs;

typedef struct {
  int16_t version, count;
  PSHandle (*newProc)      (int32_t size);
  void     (*disposeProc)  (PSHandle h);
  int32_t  (*getSizeProc)  (PSHandle h);
  int16_t  (*setSizeProc)  (PSHandle h, int32_t newSize);
  void *   (*lockProc)     (PSHandle h, PSBoolean moveHigh);
  void     (*unlockProc)   (PSHandle h);
  void     (*recoverSpaceProc) (int32_t size);
  void     (*disposeRegularHandleProc) (PSHandle h);
} PSHandleProcs;

typedef struct {
  int16_t version, count;
  int16_t  (*countProc)  (uint32_t type);
  PSHandle (*getProc)    (uint32_t type, int16_t index);
  void     (*deleteProc) (uint32_t type, int16_t index);
  int16_t  (*addProc)    (uint32_t type, PSHandle data);
} PSResourceProcs;

typedef struct {
  int16_t version, count;
  int16_t (*getPropertyProc) (uint32_t signature, uint32_t key, int32_t index, intptr_t *simple, PSHandle *complex_);
  int16_t (*setPropertyProc) (uint32_t signature, uint32_t key, int32_t index, intptr_t simple, PSHandle complex_);
} PSPropertyProcs;

typedef struct { void *data; Rect16 bounds; int32_t rowBytes, colBytes; } PSImagePlane;
typedef struct {
  int16_t version, count;
  int16_t (*interpolate1DProc) (PSImagePlane *src, PSImagePlane *dst, Rect16 *area, Fixed16 *coords, int16_t method);
  int16_t (*interpolate2DProc) (PSImagePlane *src, PSImagePlane *dst, Rect16 *area, Fixed16 *coords, int16_t method);
} PSImageServicesProcs;

/* --- FilterRecord: SDK uses 4-byte struct packing on Windows --- */
#pragma pack(push, 4)
typedef struct FilterRecord {
  int32_t  serial;
  PSBoolean (*abortProc) (void);
  void      (*progressProc) (int32_t done, int32_t total);
  PSHandle parameters;
  Point16  imageSize;
  int16_t  planes;
  Rect16   filterRect;
  PSRGBColor background, foreground;
  int32_t  maxSpace;
  int32_t  bufferSpace;
  Rect16   inRect;
  int16_t  inLoPlane, inHiPlane;
  Rect16   outRect;
  int16_t  outLoPlane, outHiPlane;
  void    *inData;  int32_t inRowBytes;
  void    *outData; int32_t outRowBytes;
  PSBoolean isFloating, haveMask, autoMask;
  Rect16   maskRect;
  void    *maskData; int32_t maskRowBytes;
  uint8_t  backColor[4], foreColor[4];
  uint32_t hostSig;
  void   (*hostProcs) (int16_t selector, void *data);
  int16_t  imageMode;
  Fixed16  imageHRes, imageVRes;
  Point16  floatCoord, wholeSize;
  PlugInMonitor monitor;
  PlatformData *platformData;
  PSBufferProcs *bufferProcs;
  PSResourceProcs *resourceProcs;
  void   (*processEvent) (void *event);
  void   (*displayPixels) (const void *dstPixels, const Rect16 *dstRect, int32_t dstRow, int32_t dstCol, const void *srcPixels);
  PSHandleProcs *handleProcs;
  /* 3.0 */
  PSBoolean supportsDummyChannels, supportsAlternateLayouts;
  int16_t  wantLayout, filterCase, dummyPlaneValue;
  void    *premiereHook;
  int16_t (*advanceState) (void);
  PSBoolean supportsAbsolute, wantsAbsolute;
  void    *getPropertyObsolete;
  PSBoolean cannotUndo, supportsPadding;
  int16_t  inputPadding, outputPadding, maskPadding;
  uint8_t  samplingSupport, reservedByte;
  Fixed16  inputRate, maskRate;
  int16_t (*colorServices) (void *info);
  int16_t  inLayerPlanes, inTransparencyMask, inLayerMasks, inInvertedLayerMasks, inNonLayerPlanes;
  int16_t  outLayerPlanes, outTransparencyMask, outLayerMasks, outInvertedLayerMasks, outNonLayerPlanes;
  int16_t  absLayerPlanes, absTransparencyMask, absLayerMasks, absInvertedLayerMasks, absNonLayerPlanes;
  int16_t  inPreDummyPlanes, inPostDummyPlanes, outPreDummyPlanes, outPostDummyPlanes;
  int32_t  inColumnBytes, inPlaneBytes, outColumnBytes, outPlaneBytes;
  /* 3.0.4 */
  PSImageServicesProcs *imageServicesProcs;
  PSPropertyProcs *propertyProcs;
  int16_t  inTileHeight, inTileWidth;  Point16 inTileOrigin;
  int16_t  absTileHeight, absTileWidth; Point16 absTileOrigin;
  int16_t  outTileHeight, outTileWidth; Point16 outTileOrigin;
  int16_t  maskTileHeight, maskTileWidth; Point16 maskTileOrigin;
  /* 4.0 */
  void    *descriptorParameters;
  PStr255 *errorString;
  void    *channelPortProcs;
  void    *documentInfo;
  /* 5.0 */
  void    *sSPBasic;
  void    *plugInRef;
  int32_t  depth;
  /* 6.0 */
  PSHandle iccProfileData;
  int32_t  iccProfileSize, canUseICCProfiles;
  uint8_t  reserved[54];
} FilterRecord;
#pragma pack(pop)

typedef void (*PSPluginMain) (int16_t selector, FilterRecord *fr, intptr_t *data, int16_t *result);

#endif
