// Runs firmware/room/room_logic.h on a laptop against the inputs in trace.txt
// and prints the events in protocol form. Output must equal expected.txt.
#include <cstdio>
#include <cstring>
#include "../room/room_logic.h"

static void emit(double t, unsigned long seq, const char *code, long a, long b) {
  printf("E,%ld,%lu,%s,%ld,%ld\n", (long)(t * 1000), seq, code, a, b);
}

int main(int argc, char **argv) {
  FILE *f = fopen(argc > 1 ? argv[1] : "trace.txt", "r");
  if (!f) { fprintf(stderr, "no trace file\n"); return 2; }
  RoomLogic lg;
  lg.onEvent = emit;
  char kind[4], mode[16];
  double t, last = 0;
  int door, lok, lev, gas, hok, hum, temp, link, slot;
  char rl[220], err[64];
  while (fscanf(f, "%3s", kind) == 1) {
    if (kind[0] == 'U') {
      if (fscanf(f, "%lf %d %d %d %d %d %d %d %d", &t, &door, &lok, &lev, &gas, &hok, &hum, &temp, &link) != 9) break;
      last = t;
      lg.update(t, door, lok, lev, gas, hok, hum, temp, link);
    } else if (kind[0] == 'C') {
      if (fscanf(f, "%lf", &t) != 1) break;
      lg.cleaned(t);
    } else if (kind[0] == 'R') {              // add a rule (spaces were written as ~)
      if (fscanf(f, "%lf %219s", &t, rl) != 2) break;
      for (char *p = rl; *p; p++) if (*p == '~') *p = ' ';
      Rule r;
      slot = lg.parseRule(rl, r, err, sizeof(err));
      if (slot) lg.addRule(t, slot, r); else printf("PARSE ERROR %s\n", err);
    } else if (kind[0] == 'X') {
      if (fscanf(f, "%lf %d", &t, &slot) != 2) break;
      lg.deleteRule(t, slot);
    } else if (kind[0] == 'M') {
      if (fscanf(f, "%15s", mode) != 1) break;
      lg.manual = strcmp(mode, "AUTO") == 0 ? -1 : (strcmp(mode, "ON") == 0 ? 1 : 0);
    }
  }
  (void)last;
  for (int s = 1; s <= MAX_RULES; s++)        // same listing the board gives for RULES?
    if (lg.rules[s].used) { lg.formatRule(s, rl, sizeof(rl)); printf("R,%s\n", rl); }
  fclose(f);
  return 0;
}
