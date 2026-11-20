/* Dev tool: pe8bf_dump <file.8bf>... — prints static analysis results. */
#include "../src/common/pe8bf.h"
#include <stdio.h>
int main (int argc, char **argv) {
  for (int i = 1; i < argc; i++) {
    Pe8File f; pe8_analyze_file (argv[i], &f); pe8_check_dependencies (&f, argv[i]);
    printf ("%s  machine=0x%X  entries=%zu", argv[i], f.machine, f.count);
    if (!f.count) printf ("  file_reason=%s", pe8_reason_key (f.file_reason));
    printf ("\n");
    for (size_t k = 0; k < f.count; k++) {
      Pe8Plugin *p = &f.items[k];
      printf ("  [%s/%s%s%s] kind=%s name='%s' cat='%s' entry=%s modes=0x%04X %s id=%d\n", pe8_verdict_key (p->verdict), pe8_reason_key (p->reason),
              p->reason_detail ? ":" : "", p->reason_detail ? p->reason_detail : "", p->kind, p->name ? p->name : "", p->category ? p->category : "",
              p->entry ? p->entry : "-", p->modes, p->from_json ? "json" : "pipl", p->resource_id);
    }
    pe8_free (&f);
  }
  return 0;
}
