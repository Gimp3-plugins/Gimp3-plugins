/* PSHost - GIMP 3 plug-in hosting 64-bit Photoshop (.8bf) filters.
 * Procedures: pshost-about, pshost-manage (Filters > Photoshop). Dynamic filters are added in stage 6. */
#include <libgimp/gimp.h>
#include <libgimp/gimpui.h>
#include "config.h"
#include "ui.h"
#include "filter.h"

#define PROC_ABOUT  "pshost-about"
#define PROC_MANAGE "pshost-manage"
#define PROC_RUN    "pshost-run-filter"

typedef struct { GimpPlugIn parent_instance; } PSHost;
typedef struct { GimpPlugInClass parent_class; } PSHostClass;
#define PSHOST_TYPE (pshost_get_type ())
G_DEFINE_TYPE (PSHost, pshost, GIMP_TYPE_PLUG_IN)
GIMP_MAIN (PSHOST_TYPE)

static void load_language (void) { PsConfig *c = ps_config_load (); ps_set_language (ps_config_language (c)); ps_config_free (c); }

static GimpValueArray *
about_run (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gimp_ui_init ("pshost"); load_language ();
  GtkWidget *dlg = gtk_message_dialog_new (NULL, GTK_DIALOG_MODAL, GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s",
                     "PSHost 0.5\n\nHost for 64-bit Photoshop (.8bf) plug-ins.\nHost 64-bitowych wtyczek Photoshop (.8bf).");
  gtk_dialog_run (GTK_DIALOG (dlg)); gtk_widget_destroy (dlg);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
}

typedef struct { GimpImage *image; GimpDrawable *drawable; } Target;

static void launch_filter (const PsItem *item, GtkWindow *parent, gpointer data)
{
  Target *t = data; char *err = NULL;
  PsRunStatus st = ps_filter_run (item, t->image, t->drawable, parent, TRUE, &err);
  if (st == PS_RUN_ERROR)
    {
      GtkWidget *m = gtk_message_dialog_new (parent, GTK_DIALOG_MODAL, GTK_MESSAGE_ERROR, GTK_BUTTONS_OK, "%s", err ? err : "?");
      gtk_window_set_title (GTK_WINDOW (m), _T ("Filter error"));
      gtk_dialog_run (GTK_DIALOG (m)); gtk_widget_destroy (m);
    }
  g_free (err);
}

static GimpValueArray *
manage_run (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gimp_ui_init ("pshost");
  PsConfig *cfg = ps_config_load ();
  GtkWidget *dlg = ps_manage_dialog_new (NULL, cfg);
  Target tgt = { image, (drawables && drawables[0]) ? drawables[0] : NULL };
  if (image && tgt.drawable)
    {
      gchar *iname = gimp_image_get_name (image), *lname = gimp_item_get_name (GIMP_ITEM (tgt.drawable));
      gchar *desc = g_strdup_printf ("%s / %s", iname, lname);
      ps_manage_set_launcher (dlg, launch_filter, &tgt, desc);
      g_free (desc); g_free (iname); g_free (lname);
    }
  else ps_manage_set_launcher (dlg, launch_filter, &tgt, NULL);
  ps_manage_dialog_run (dlg);
  ps_config_free (cfg);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
}

/* Scriptable entry point (no menu): pshost-run-filter(run-mode, image, drawables, filter, interactive).
 * `filter` matches a configured entry by procedure name, file path or filter name. */
static GimpValueArray *
run_filter_proc (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gchar *filter = NULL; gboolean interactive = FALSE;
  g_object_get (config, "filter", &filter, "interactive", &interactive, NULL);
  if (interactive) gimp_ui_init ("pshost");
  PsConfig *cfg = ps_config_load ();
  ps_set_language (ps_config_language (cfg));
  const PsItem *found = NULL;
  for (guint i = 0; i < cfg->items->len && filter; i++)
    {
      PsItem *it = g_ptr_array_index (cfg->items, i);
      if (it->verdict == PE8_VERDICT_NO || !it->enabled) continue;
      if (!g_strcmp0 (it->proc_name, filter) || !g_strcmp0 (it->path, filter) || !g_strcmp0 (it->name, filter)) { found = it; break; }
    }
  GimpValueArray *ret;
  if (!found)
    ret = gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 1, "filter not found or not usable"));
  else if (!drawables || !drawables[0])
    ret = gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 2, "no drawable"));
  else
    {
      char *err = NULL;
      PsRunStatus st = ps_filter_run (found, image, drawables[0], NULL, interactive, &err);
      if (st == PS_RUN_ERROR) ret = gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 3, err ? err : "error"));
      else ret = gimp_procedure_new_return_values (procedure, st == PS_RUN_CANCELLED ? GIMP_PDB_CANCEL : GIMP_PDB_SUCCESS, NULL);
      g_free (err);
    }
  g_free (filter); ps_config_free (cfg);
  return ret;
}

static GList *pshost_init_procedures (GimpPlugIn *p) { return g_list_append (g_list_append (g_list_append (NULL, g_strdup (PROC_MANAGE)), g_strdup (PROC_RUN)), g_strdup (PROC_ABOUT)); }

static GimpProcedure *
pshost_create_procedure (GimpPlugIn *plug_in, const gchar *name)
{
  GimpProcedure *proc = NULL;
  load_language ();   /* menu labels follow the configured language (takes effect after a GIMP restart) */
  if (g_strcmp0 (name, PROC_ABOUT) == 0)
    {
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, about_run, NULL, NULL);
      gimp_procedure_set_menu_label (proc, _T ("About / O wtyczce"));
      gimp_procedure_set_documentation (proc, "About PSHost", "Shows information about PSHost.", NULL);
    }
  else if (g_strcmp0 (name, PROC_MANAGE) == 0)
    {
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, manage_run, NULL, NULL);
      gimp_procedure_set_menu_label (proc, _T ("Manage plug-ins..."));
      gimp_procedure_set_documentation (proc, "Manage Photoshop plug-ins", "Add directories with Photoshop (.8bf) plug-ins, test them and choose which ones to use.", NULL);
    }
  else if (g_strcmp0 (name, PROC_RUN) == 0)
    {
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, run_filter_proc, NULL, NULL);
      gimp_procedure_set_image_types (proc, "*");
      gimp_procedure_set_sensitivity_mask (proc, GIMP_PROCEDURE_SENSITIVE_DRAWABLE);
      gimp_procedure_set_documentation (proc, "Run a Photoshop filter", "Runs a configured Photoshop filter on the selected layer (selection respected, one undo step).", NULL);
      gimp_procedure_set_attribution (proc, "PSHost", "PSHost", "2026");
      gimp_procedure_add_string_argument (proc, "filter", "Filter", "Procedure name, file path or name of the filter", NULL, G_PARAM_READWRITE);
      gimp_procedure_add_boolean_argument (proc, "interactive", "Interactive", "Let the filter show its own window", FALSE, G_PARAM_READWRITE);
      return proc;
    }
  if (proc)
    {
      gimp_procedure_set_image_types (proc, "*");
      gimp_procedure_set_sensitivity_mask (proc, GIMP_PROCEDURE_SENSITIVE_ALWAYS);
      gimp_procedure_add_menu_path (proc, "<Image>/Filters/Photoshop");
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
