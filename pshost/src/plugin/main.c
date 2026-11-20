/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 PSHost contributors */
/* PSHost - GIMP 3 plug-in hosting 64-bit Photoshop (.8bf) filters.
 *
 * Static procedures (query_procedures):  pshost-manage, pshost-about, pshost-run-filter, pshost-restart
 * Dynamic procedures (init_procedures, every GIMP start): one "pshost-filter-<hash>" per enabled, usable filter,
 * placed in <Image>/Filters/Photoshop/<Category>. A restart of GIMP is needed to change that set. */
#include <libgimp/gimp.h>
#include <libgimp/gimpui.h>
#include "config.h"
#include "ui.h"
#include "filter.h"
#include "registry.h"
#include "restart.h"

#define PROC_ABOUT   "pshost-about"
#define PROC_MANAGE  "pshost-manage"
#define PROC_RUN     "pshost-run-filter"
#define PROC_RESTART "pshost-restart"
#define PROC_FILTER_PREFIX "pshost-filter-"

typedef struct { GimpPlugIn parent_instance; } PSHost;
typedef struct { GimpPlugInClass parent_class; } PSHostClass;
#define PSHOST_TYPE (pshost_get_type ())
G_DEFINE_TYPE (PSHost, pshost, GIMP_TYPE_PLUG_IN)
GIMP_MAIN (PSHOST_TYPE)

static PsConfig  *g_cfg  = NULL;
static GPtrArray *g_regs = NULL;

static void ensure_config (void)
{
  if (g_cfg) return;
  g_cfg = ps_config_load ();
  ps_set_language (ps_config_language (g_cfg));
  g_regs = ps_registry_build (g_cfg);
}

/* ----------------------------------------------------------------------------------------- about */
static GimpValueArray *
about_run (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gimp_ui_init ("pshost"); ensure_config ();
  GtkWidget *dlg = gtk_message_dialog_new (NULL, GTK_DIALOG_MODAL, GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "%s",
                     "PSHost " PSHOST_VERSION "\n\nHost for 64-bit Photoshop (.8bf) plug-ins.\nHost 64-bitowych wtyczek Photoshop (.8bf).\n\nGPL-3.0-or-later");
  gtk_dialog_run (GTK_DIALOG (dlg)); gtk_widget_destroy (dlg);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
}

/* ---------------------------------------------------------------------------------------- manage */
typedef struct { GimpImage *image; GimpDrawable *drawable; } Target;

static gboolean launch_filter (const PsItem *item, GtkWindow *parent, gpointer data)
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
  return st == PS_RUN_OK;
}

static char **dirty_hook (gpointer data) { return ps_dirty_image_names (); }
static gboolean restart_hook (char **error, gpointer data) { return ps_restart_gimp (error); }

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
  ps_manage_set_restart_hooks (dlg, dirty_hook, restart_hook, NULL);
  ps_manage_dialog_run (dlg);
  ps_config_free (cfg);
  return gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL);
}

/* ------------------------------------------------------------------------------ scriptable runner */
/* pshost-run-filter(run-mode, image, drawables, filter, interactive): `filter` = procedure name, file path or filter name. */
static GimpValueArray *
run_filter_proc (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  gchar *filter = NULL; gboolean interactive = FALSE;
  g_object_get (config, "filter", &filter, "interactive", &interactive, NULL);
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

/* -------------------------------------------------------------------------------- menu filters */
/* run_data = procedure name; the entry is looked up in the configuration of the process that runs. */
static GimpValueArray *
menu_filter_run (GimpProcedure *procedure, GimpRunMode run_mode, GimpImage *image, GimpDrawable **drawables, GimpProcedureConfig *config, gpointer data)
{
  const char *pname = data;
  PsConfig *cfg = ps_config_load ();
  ps_set_language (ps_config_language (cfg));
  const PsItem *item = NULL;
  for (guint i = 0; i < cfg->items->len; i++) { PsItem *it = g_ptr_array_index (cfg->items, i); if (!g_strcmp0 (it->proc_name, pname)) { item = it; break; } }
  GimpValueArray *ret;
  if (!item || !drawables || !drawables[0])
    ret = gimp_procedure_new_return_values (procedure, GIMP_PDB_CALLING_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 1, item ? "no drawable" : "filter not found (restart GIMP?)"));
  else
    {
      char *err = NULL;
      /* interactive = from the menu; "repeat last" (WITH_LAST_VALS) re-runs with the saved parameters */
      PsRunStatus st = ps_filter_run (item, image, drawables[0], NULL, run_mode != GIMP_RUN_WITH_LAST_VALS && run_mode != GIMP_RUN_NONINTERACTIVE, &err);
      if (st == PS_RUN_ERROR) ret = gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 3, err ? err : "error"));
      else ret = gimp_procedure_new_return_values (procedure, st == PS_RUN_CANCELLED ? GIMP_PDB_CANCEL : GIMP_PDB_SUCCESS, NULL);
      g_free (err);
    }
  ps_config_free (cfg);
  return ret;
}

/* ------------------------------------------------------------------------------------- restart */
static GimpValueArray *
restart_run (GimpProcedure *procedure, GimpProcedureConfig *config, gpointer data)
{
  char *err = NULL;
  gboolean ok = ps_restart_gimp (&err);
  GimpValueArray *ret = ok ? gimp_procedure_new_return_values (procedure, GIMP_PDB_SUCCESS, NULL)
                           : gimp_procedure_new_return_values (procedure, GIMP_PDB_EXECUTION_ERROR, g_error_new_literal (g_quark_from_static_string ("pshost"), 4, err ? err : "restart failed"));
  g_free (err);
  return ret;
}

/* ------------------------------------------------------------------------------ registration */
static GList *pshost_query_procedures (GimpPlugIn *p)
{
  GList *l = NULL;
  l = g_list_append (l, g_strdup (PROC_MANAGE)); l = g_list_append (l, g_strdup (PROC_RUN));
  l = g_list_append (l, g_strdup (PROC_RESTART)); l = g_list_append (l, g_strdup (PROC_ABOUT));
  return l;
}

static GList *pshost_init_procedures (GimpPlugIn *p)
{
  ensure_config ();
  GList *l = NULL;
  for (guint i = 0; i < g_regs->len; i++) l = g_list_append (l, g_strdup (((PsReg *) g_ptr_array_index (g_regs, i))->proc));
  ps_registry_write_state (g_regs, ps_config_language (g_cfg));   /* what this GIMP session has registered */
  return l;
}

static GimpProcedure *
pshost_create_procedure (GimpPlugIn *plug_in, const gchar *name)
{
  ensure_config ();
  GimpProcedure *proc = NULL;

  if (g_str_has_prefix (name, PROC_FILTER_PREFIX))
    {
      const PsReg *reg = NULL;
      for (guint i = 0; i < g_regs->len; i++) { const PsReg *r = g_ptr_array_index (g_regs, i); if (!g_strcmp0 (r->proc, name)) { reg = r; break; } }
      if (!reg) return NULL;
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, menu_filter_run, g_strdup (name), g_free);
      gchar *mdoc = g_strdup_printf ("Photoshop filter: %s", reg->item->path);
      gchar *mlabel = ps_escape_mnemonic (reg->label);
      gimp_procedure_set_menu_label (proc, mlabel); g_free (mlabel);
      gimp_procedure_set_documentation (proc, mdoc, "Runs a Photoshop (.8bf) filter on the selected layer (selection respected, one undo step).", NULL);
      gimp_procedure_set_image_types (proc, "RGB*");
      gimp_procedure_set_sensitivity_mask (proc, GIMP_PROCEDURE_SENSITIVE_DRAWABLE);
      gimp_procedure_add_menu_path (proc, reg->menu);
      gimp_procedure_set_attribution (proc, "PSHost", "PSHost", "2026");
      g_free (mdoc);
      return proc;
    }
  if (g_strcmp0 (name, PROC_ABOUT) == 0)
    {
      proc = gimp_image_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, about_run, NULL, NULL);
      gimp_procedure_set_menu_label (proc, _T ("About PSHost..."));
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
  else if (g_strcmp0 (name, PROC_RESTART) == 0)
    {
      proc = gimp_procedure_new (plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN, restart_run, NULL, NULL);
      gimp_procedure_set_documentation (proc, "Restart GIMP", "Starts a helper that relaunches GIMP once it has exited, then asks GIMP to quit cleanly.", NULL);
      gimp_procedure_set_attribution (proc, "PSHost", "PSHost", "2026");
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

/* Localization is done by PSHost itself (language chosen in the window: Auto / Polski / English), so GIMP's own
 * per-language lookup of our msgids is disabled; otherwise a manual "English" choice would be overridden. */
static gboolean pshost_set_i18n (GimpPlugIn *plug_in, const gchar *procedure_name, gchar **gettext_domain, gchar **catalog_dir)
{
  return FALSE;
}

static void pshost_class_init (PSHostClass *klass)
{
  GimpPlugInClass *pc = GIMP_PLUG_IN_CLASS (klass);
  pc->query_procedures = pshost_query_procedures;
  pc->init_procedures = pshost_init_procedures;
  pc->create_procedure = pshost_create_procedure;
  pc->set_i18n = pshost_set_i18n;
}
static void pshost_init (PSHost *s) {}
