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

/* Network locations: UNC paths (\\server\share, //server/share) and, on
 * Windows, mapped network drives.  Touching such a path makes Windows
 * authenticate to the server (NTLM), so paths coming from files (XCF
 * parasites) must not be accessed without the user's consent.
 */
gboolean
rawheic_path_is_remote (const gchar *path)
{
  if (! path || ! *path)
    return FALSE;

  if ((path[0] == '\\' || path[0] == '/') && (path[1] == '\\' || path[1] == '/'))
    return TRUE;

#ifdef G_OS_WIN32
  if (g_ascii_isalpha (path[0]) && path[1] == ':')
    {
      wchar_t root[4] = { (wchar_t) path[0], L':', L'\\', 0 };

      return GetDriveTypeW (root) == DRIVE_REMOTE;
    }
#endif

  return FALSE;
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
                                   _("The original RAW file is on a network location:"));
  gtk_message_dialog_format_secondary_text (GTK_MESSAGE_DIALOG (dialog),
                                            _("%s\n\nThis path was read from the image "
                                              "file. Open it only if you trust where "
                                              "the image came from. Continue?"), path);
  gimp_window_set_transient (GTK_WINDOW (dialog));
  response = gtk_dialog_run (GTK_DIALOG (dialog));
  gtk_widget_destroy (dialog);

  return response == GTK_RESPONSE_YES;
}
