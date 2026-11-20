/* gimp-raw-heic -- small helpers
 * Copyright (C) 2026 Marek Zettel
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "config.h"

#include <glib.h>

#ifdef G_OS_WIN32
#include <windows.h>
#else
#include <gdk/gdk.h>
#endif

#include <libgimp/gimpui.h>

#include "rawheic.h"

gchar *
rawheic_file_path (GFile *file)
{
  return file ? g_file_get_path (file) : NULL;
}

/* Is Shift held right now?  Used to invert the "show dialog" choice. */
gboolean
rawheic_shift_pressed (void)
{
#ifdef G_OS_WIN32
  return (GetAsyncKeyState (VK_SHIFT) & 0x8000) != 0;
#else
  GdkDisplay *display = gdk_display_get_default ();

  if (! display)
    return FALSE;

  return (gdk_keymap_get_modifier_state (gdk_keymap_get_for_display (display)) &
          GDK_SHIFT_MASK) != 0;
#endif
}

/* Is @path anything other than a plain local file path?
 *
 * Touching a network path makes Windows authenticate to that server
 * (NTLM), so paths read from files (XCF parasites) must not be accessed
 * without the user's consent.  This is an allow-list: on Windows only a
 * fully qualified "X:\..." path on a local drive (fixed, removable,
 * optical, RAM disk) is trusted, after normalisation.  UNC paths, device
 * and NT namespaces (\\?\, \\.\, \??\), relative paths and network drives
 * are all reported as remote.
 */
gboolean
rawheic_path_is_remote (const gchar *path)
{
  if (! path || ! *path)
    return TRUE;

#ifdef G_OS_WIN32
  {
    gunichar2 *wpath = g_utf8_to_utf16 (path, -1, NULL, NULL, NULL);
    wchar_t    full[MAX_PATH * 4];
    DWORD      len;
    gboolean   remote = TRUE;

    /* only "X:\" or "X:/" absolute paths are candidates */
    if (wpath &&
        g_ascii_isalpha (path[0]) && path[1] == ':' &&
        (path[2] == '\\' || path[2] == '/'))
      {
        len = GetFullPathNameW ((const wchar_t *) wpath, G_N_ELEMENTS (full), full, NULL);

        if (len > 3 && len < G_N_ELEMENTS (full) &&
            iswalpha (full[0]) && full[1] == L':' && full[2] == L'\\')
          {
            wchar_t root[4] = { full[0], L':', L'\\', 0 };

            switch (GetDriveTypeW (root))
              {
              case DRIVE_FIXED:
              case DRIVE_REMOVABLE:
              case DRIVE_CDROM:
              case DRIVE_RAMDISK:
                remote = FALSE;
                break;
              default:   /* DRIVE_REMOTE, DRIVE_NO_ROOT_DIR, DRIVE_UNKNOWN */
                remote = TRUE;
                break;
              }
          }
      }

    g_free (wpath);
    return remote;
  }
#else
  /* local absolute path; "//host/share" style is treated as remote */
  return ! (path[0] == '/' && path[1] != '/');
#endif
}

/* Ask before opening a network path that came from an image file. */
gboolean
rawheic_confirm_remote (const gchar *path)
{
  GtkWidget *dialog;
  gint       response;

  gimp_ui_init (PLUGIN_NAME);

  dialog = gtk_message_dialog_new (NULL, GTK_DIALOG_MODAL, GTK_MESSAGE_WARNING,
                                   GTK_BUTTONS_YES_NO,
                                   _("The original RAW file is not on a local disk:"));
  gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (dialog),
                                            _("%s\n\nThis path was read from the image "
                                              "file. Open it only if you trust where "
                                              "the image came from. Continue?"), path);
  gimp_window_set_transient (GTK_WINDOW (dialog));
  response = gtk_dialog_run (GTK_DIALOG (dialog));
  gtk_widget_destroy (dialog);

  return response == GTK_RESPONSE_YES;
}
