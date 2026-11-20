/* PSHost - GIMP 3 plug-in hosting 64-bit Photoshop (.8bf) filters. Stage 1: About. */
#include <libgimp/gimp.h>
#include <libgimp/gimpui.h>
#include <glib/gi18n.h>

#define PROC_ABOUT "pshost-about"

typedef struct { GimpPlugIn parent_instance; } PSHost;
typedef struct { GimpPlugInClass parent_class; } PSHostClass;
#define PSHOST_TYPE (pshost_get_type ())
G_DEFINE_TYPE (PSHost, pshost, GIMP_TYPE_PLUG_IN)
GIMP_MAIN (PSHOST_TYPE)

static GimpValueArray *
about_run (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image,
           GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gimp_ui_init ("pshost");
  GtkWidget *dlg = gtk_message_dialog_new (NULL, GTK_DIALOG_MODAL, GTK_MESSAGE_INFO,
                     GTK_BUTTONS_OK, "%s", "PSHost 0.1\n\nHost for 64-bit Photoshop (.8bf) plug-ins.\nHost 64-bitowych wtyczek Photoshop (.8bf).");
  gtk_dialog_run (GTK_DIALOG (dlg));
  gtk_widget_destroy (dlg);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
}

static GList *pshost_init_procedures (GimpPlugIn *p) { return g_list_append (NULL, g_strdup (PROC_ABOUT)); }

static GimpProcedure *
pshost_create_procedure (GimpPlugIn *plug_in, const gchar *name)
{
  GimpProcedure *proc = NULL;
  if (g_strcmp0 (name, PROC_ABOUT) == 0)
    {
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, about_run, NULL, NULL);
      gimp_procedure_set_image_types (proc, "*");
      gimp_procedure_set_sensitivity_mask (proc, GIMP_PROCEDURE_SENSITIVE_ALWAYS);
      gimp_procedure_set_menu_label (proc, "About / O wtyczce");
      gimp_procedure_add_menu_path (proc, "<Image>/Filters/Photoshop");
      gimp_procedure_set_documentation (proc, "About PSHost", "Shows information about PSHost.", NULL);
      gimp_procedure_set_attribution (proc, "PSHost", "PSHost", "2026");
    }
  return proc;
}

static void pshost_class_init (PSHostClass *klass)
{
  GimpPlugInClass *pc = GIMP_PLUG_IN_CLASS (klass);
  pc->init_procedures = pshost_init_procedures;
  pc->query_procedures = pshost_init_procedures;
  pc->create_procedure = pshost_create_procedure;
}
static void pshost_init (PSHost *s) {}
