// What the room board decides. Plain C++ with no Arduino calls, so the same file
// is checked on a laptop against contract/room_logic.py (see firmware/host_check).
// Thresholds are starting values to tune on the real rig, not measured facts.
#ifndef ROOM_LOGIC_H
#define ROOM_LOGIC_H
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ----- caretaker rules (same meaning as contract/rules.py) -----
enum { S_DOOR, S_LEVEL, S_RATE, S_GAS, S_HUM, S_TEMP, S_USES, S_OCC_S, S_FREE_S, S_COUNT };
static const char *const SENSOR_CODES[S_COUNT] = {"DOOR", "LEVEL", "RATE", "GAS", "HUM", "TEMP", "USES", "OCC_S", "FREE_S"};
enum { OP_LT, OP_GT, OP_EQ };
enum { ACT_FAN_ON = 1, ACT_FAN_OFF = 2, ACT_JOB = 3 };
static const int MAX_RULES = 8;

struct RuleCond { int sensor; int op; long value; };
struct Rule {
  bool used = false;
  int priority = 5, holdS = 0, forS = 0, action = 0, n = 0;
  bool matchAll = true, onEvent = false;
  char event[16] = "";
  char name[44] = "";
  char text[64] = "";
  RuleCond c[3];
  // run-time state
  double trueSince = -1, activeUntil = 0;
  bool hasUntil = false, active = false, armed = true;
};

struct RoomCfg {
  int LOW_MM = 40;             // below this the tank counts as empty
  int MIN_USE_S = 3;           // door must stay closed this long to count as a use
  int SLOPE_WINDOW_S = 20;     // window for the water-level slope
  int TAP_RATE = 6;            // mm/min of fall that counts as "water running"
  int TAP_SUSPECT_S = 15, TAP_CONFIRM_S = 45, TAP_CLEAR_S = 10;
  int GAS_BAD_PCT = 125, GAS_OK_PCT = 112, GAS_BAD_S = 10;
  int BASELINE_STABLE_S = 60;  // quiet time before the gas sensor's normal level is learned
  int STEAM_RISE = 50;         // humidity rise (x10) inside the window that means steam
  int STEAM_WINDOW_S = 30, STEAM_SETTLE = 30, STEAM_MAX_S = 900;
  int HUM_ON = 750, HUM_OFF = 680, FAN_MIN_ON_S = 20;
  int VERIFY_S = 60;           // how long after the fan starts before it is judged
  int VERIFY_HUM_DROP = 80;    // humidity (x10) must fall this much
  int VERIFY_GAS_DROP = 5;     // air percent must fall this much
  int CLEAN_USES = 5;
  int SENSOR_TIMEOUT_S = 3, LINK_TIMEOUT_S = 3;
};

typedef void (*RoomEmit)(double t, unsigned long seq, const char *code, long a, long b);

class RoomLogic {
 public:
  RoomCfg cfg;
  RoomEmit onEvent = nullptr;
  unsigned long seq = 0;
  const char *state = "FREE";
  bool fan = false;
  int uses = 0, levelRate = 0, gasPct = 0;
  int manual = -1;             // -1 automatic, 0 forced off, 1 forced on
  bool hasBaseline = false, tapSuspected = false, lowWater = false, gate = false, airBad = false;
  bool needsCleaning = false, drainCheck = false, fault = false, linkLost = false;
  double baseline = 0;

  Rule rules[MAX_RULES + 1];   // slots 1 to 8

  void cleaned(double t) {
    uses = 0; needsCleaning = false; drainCheck = false; cleanLogged = false; fault = false;
    emit(t, "CLEANED");
    ruleEvent(t, "CLEANED");
  }

  // Reads "RULE,slot,priority,ALL|ANY,hold_s,action,for_s,trigger,n,(sensor,op,value)xn,name".
  // Returns the slot (1 to 8) or 0 with a reason in err.
  int parseRule(const char *line, Rule &r, char *err, size_t errLen) const {
    char buf[200];
    strncpy(buf, line, sizeof(buf) - 1); buf[sizeof(buf) - 1] = 0;
    char *f[24]; int nf = 0;
    for (char *p = buf; nf < 24; ) {
      f[nf++] = p;
      char *comma = strchr(p, ',');
      if (!comma) break;
      *comma = 0; p = comma + 1;
    }
    if (nf < 10 || strcmp(f[0], "RULE")) { snprintf(err, errLen, "not a rule line"); return 0; }
    int slot = atoi(f[1]);
    if (slot < 1 || slot > MAX_RULES) { snprintf(err, errLen, "slot must be 1 to 8"); return 0; }
    r = Rule();
    r.priority = atoi(f[2]);
    if (r.priority < 1 || r.priority > 8) { snprintf(err, errLen, "priority must be 1 to 8"); return 0; }
    if (!strcmp(f[3], "ALL")) r.matchAll = true; else if (!strcmp(f[3], "ANY")) r.matchAll = false;
    else { snprintf(err, errLen, "match must be ALL or ANY"); return 0; }
    r.holdS = atoi(f[4]);
    if (!strcmp(f[5], "FAN_ON")) r.action = ACT_FAN_ON;
    else if (!strcmp(f[5], "FAN_OFF")) r.action = ACT_FAN_OFF;
    else if (!strncmp(f[5], "JOB:", 4)) { r.action = ACT_JOB; strncpy(r.text, f[5] + 4, sizeof(r.text) - 1); }
    else { snprintf(err, errLen, "unknown action"); return 0; }
    r.forS = atoi(f[6]);
    if (!strcmp(f[7], "WHILE")) r.onEvent = false;
    else if (!strncmp(f[7], "ON:", 3)) { r.onEvent = true; strncpy(r.event, f[7] + 3, sizeof(r.event) - 1); }
    else { snprintf(err, errLen, "unknown trigger"); return 0; }
    r.n = atoi(f[8]);
    if (r.n < 0 || r.n > 3 || nf != 10 + 3 * r.n) { snprintf(err, errLen, "wrong number of fields"); return 0; }
    for (int i = 0; i < r.n; i++) {
      const char *sc = f[9 + 3 * i], *op = f[10 + 3 * i];
      int s = -1;
      for (int k = 0; k < S_COUNT; k++) if (!strcmp(sc, SENSOR_CODES[k])) s = k;
      if (s < 0) { snprintf(err, errLen, "unknown sensor %s", sc); return 0; }
      int o = !strcmp(op, "LT") ? OP_LT : !strcmp(op, "GT") ? OP_GT : !strcmp(op, "EQ") ? OP_EQ : -1;
      if (o < 0) { snprintf(err, errLen, "unknown comparison %s", op); return 0; }
      r.c[i] = {s, o, atol(f[11 + 3 * i])};
    }
    if (!r.onEvent && r.n == 0) { snprintf(err, errLen, "a WHILE rule needs a condition"); return 0; }
    if (r.onEvent && r.action != ACT_JOB && r.forS <= 0) { snprintf(err, errLen, "an event fan rule needs for_s"); return 0; }
    strncpy(r.name, f[9 + 3 * r.n], sizeof(r.name) - 1);
    r.used = true;
    return slot;
  }

  void addRule(double t, int slot, const Rule &r, bool announce = true) {
    rules[slot] = r;
    rules[slot].used = true;
    if (announce) emit(t, "RULE_ADDED", slot);
  }

  void deleteRule(double t, int slot) {
    if (slot < 1 || slot > MAX_RULES || !rules[slot].used) return;
    rules[slot] = Rule();
    emit(t, "RULE_DELETED", slot);
  }

  // Writes the rule back as the fields after "RULE," (used for the RULES? listing and for saving).
  void formatRule(int slot, char *out, size_t n) const {
    const Rule &r = rules[slot];
    char act[72], trig[24];
    if (r.action == ACT_JOB) snprintf(act, sizeof(act), "JOB:%s", r.text);
    else snprintf(act, sizeof(act), "%s", r.action == ACT_FAN_ON ? "FAN_ON" : "FAN_OFF");
    if (r.onEvent) snprintf(trig, sizeof(trig), "ON:%s", r.event); else snprintf(trig, sizeof(trig), "WHILE");
    int len = snprintf(out, n, "%d,%d,%s,%d,%s,%d,%s,%d", slot, r.priority, r.matchAll ? "ALL" : "ANY", r.holdS, act, r.forS, trig, r.n);
    for (int i = 0; i < r.n && len < (int)n; i++)
      len += snprintf(out + len, n - len, ",%s,%s,%ld", SENSOR_CODES[r.c[i].sensor], r.c[i].op == OP_LT ? "LT" : r.c[i].op == OP_GT ? "GT" : "EQ", r.c[i].value);
    if (len < (int)n) snprintf(out + len, n - len, ",%s", r.name);
  }

  int flags(bool linkOk) const {
    return (gate ? 1 : 0) | (hasBaseline ? 2 : 0) | ((linkOk && !linkLost) ? 4 : 0) |
           (manual >= 0 ? 8 : 0) | (tapSuspected ? 16 : 0) | (airBad ? 32 : 0);
  }

  // Call twice a second. levelOk / humOk are false when that sensor gave no valid reading.
  // temp is degrees C x 10, or negative when there is no reading.
  void update(double t, bool doorClosed, bool levelOk, int levelMm, int gasRaw, bool humOk, int hum, int temp, bool linkOk) {
    const RoomCfg &c = cfg;
    inLevelOk = levelOk; inLevel = levelMm; inHumOk = humOk; inHum = hum; inTemp = temp;
    if (first) { first = false; openedAt = t; emit(t, "BOOT"); }
    sensor(t, 1, levelOk);
    sensor(t, 3, humOk);

    // door and uses
    if (doorClosed && !door) { closedAt = t; useStarted = false; }
    if (doorClosed && !useStarted && t - closedAt >= c.MIN_USE_S) { useStarted = true; emit(t, "USE_START"); door = true; snapshot(t); ruleEvent(t, "USE_START"); }
    if (!doorClosed && door) { openedAt = t; levN = 0; }   // water used while occupied must not count as a tap left running
    bool ended = !doorClosed && door && useStarted;
    door = doorClosed;
    if (ended) { useStarted = false; uses++; emit(t, "USE_END", (long)(t - closedAt), uses); snapshot(t); ruleEvent(t, "USE_END"); }

    // water level and slope
    if (levelOk) {
      push(levT, levV, levN, t, levelMm);
      while (levN && t - levT[0] > c.SLOPE_WINDOW_S) pop(levT, levV, levN);
    }
    levelRate = levelOk ? slope() : 0;

    // tap left running: water falling while the room is free
    bool running = !doorClosed && levelOk && levelRate <= -c.TAP_RATE;
    if (running) {
      tapClearSince = -1;
      if (tapSince < 0) { tapSince = t; tapLevel0 = levelMm; }
      if (!tapSuspected && t - tapSince >= c.TAP_SUSPECT_S) { tapSuspected = true; emit(t, "TAP_SUSPECTED", -levelRate); }
      if (tapSuspected && !tapConfirmed && t - tapSince >= c.TAP_CONFIRM_S) {
        tapConfirmed = true; emit(t, "TAP_CONFIRMED", -levelRate, tapLevel0 - levelMm);
        snapshot(t); ruleEvent(t, "TAP_CONFIRMED");
      }
    } else {
      if (tapSuspected) {
        if (tapClearSince < 0) tapClearSince = t;
        if (doorClosed || t - tapClearSince >= c.TAP_CLEAR_S) {
          tapSuspected = false; tapConfirmed = false; tapSince = -1; emit(t, "TAP_CLEARED");
        }
      } else {
        tapSince = -1;
      }
    }

    // low water
    if (levelOk) {
      if (levelMm < c.LOW_MM) {
        if (lowSince < 0) lowSince = t;
        if (!lowWater && t - lowSince >= 5) { lowWater = true; emit(t, "LOW_WATER", levelMm); snapshot(t); ruleEvent(t, "LOW_WATER"); }
      } else {
        lowSince = -1;
        if (lowWater && levelMm >= c.LOW_MM + 10) { lowWater = false; emit(t, "WATER_OK", levelMm); }
      }
    }

    // steam gate: a fast humidity rise means steam, so the air alarm is held back
    bool humStable = false;
    if (humOk) {
      push(humT, humV, humN, t, hum);
      while (humN && t - humT[0] > c.STEAM_WINDOW_S) pop(humT, humV, humN);
      int lo = humV[0], hi = humV[0];
      for (int i = 1; i < humN; i++) { if (humV[i] < lo) lo = humV[i]; if (humV[i] > hi) hi = humV[i]; }
      humStable = (hi - lo) < 20;
      if (!gate && hum - lo >= c.STEAM_RISE) {
        gate = true; gateRef = lo; gateAt = t; gateSettle = -1; suppressedLogged = false;
        emit(t, "STEAM_GATE_ON", hum);
      } else if (gate) {
        if (hum <= gateRef + c.STEAM_SETTLE) { if (gateSettle < 0) gateSettle = t; }
        else gateSettle = -1;
        if ((gateSettle >= 0 && t - gateSettle >= 10) || t - gateAt >= c.STEAM_MAX_S) { gate = false; emit(t, "STEAM_GATE_OFF", hum); }
      }
    }

    // gas sensor: learn its normal level only in quiet moments
    bool quiet = !doorClosed && !fan && !gate && humStable && (!hasBaseline || gasPct < c.GAS_OK_PCT);
    if (quiet) {
      if (baseSince < 0) { baseSince = t; baseSum = 0; baseN = 0; }
      baseSum += gasRaw; baseN++;
      if (t - baseSince >= c.BASELINE_STABLE_S) {
        double mean = baseSum / baseN;
        baseline = hasBaseline ? 0.8 * baseline + 0.2 * mean : mean;
        hasBaseline = baseline > 0;
        baseSince = -1;
      }
    } else {
      baseSince = -1;
    }
    gasPct = hasBaseline ? (int)rint(100.0 * gasRaw / baseline) : 0;

    // air alarm
    if (hasBaseline && gasPct >= c.GAS_BAD_PCT) {
      gasLoSince = -1;
      if (gasHiSince < 0) gasHiSince = t;
      if (t - gasHiSince >= c.GAS_BAD_S) {
        if (gate) {
          if (!suppressedLogged) { suppressedLogged = true; emit(t, "AIR_SUPPRESSED", gasPct); }
        } else if (!airBad) {
          airBad = true; emit(t, "AIR_BAD", gasPct, uses);
          snapshot(t); ruleEvent(t, "AIR_BAD");
          if (uses > 0) {
            if (!cleanLogged) { needsCleaning = true; cleanLogged = true; emit(t, "CLEAN_DUE", uses, 2); }
          } else if (!drainCheck) {
            drainCheck = true; emit(t, "DRAIN_CHECK", gasPct);
          }
        }
      }
    } else {
      gasHiSince = -1;
      if (airBad && hasBaseline && gasPct <= c.GAS_OK_PCT) {
        if (gasLoSince < 0) gasLoSince = t;
        if (t - gasLoSince >= c.GAS_BAD_S) { airBad = false; emit(t, "AIR_OK", gasPct); }
      } else {
        gasLoSince = -1;
      }
    }

    // cleaning due by number of uses
    if (uses >= c.CLEAN_USES && !cleanLogged) { needsCleaning = true; cleanLogged = true; emit(t, "CLEAN_DUE", uses, 1); }

    // caretaker rules
    snapshot(t);
    int ruleFan = runRules(t);     // -1 no rule has a say, 0 off, 1 on

    // fan: manual override beats rules, rules beat the automatic humidity / air control
    if (humOk) { if (hum >= c.HUM_ON) humLatch = true; else if (hum <= c.HUM_OFF) humLatch = false; }
    int reason = manual >= 0 ? 4 : ruleFan >= 0 ? 3 : humLatch ? 1 : airBad ? 2 : 0;
    bool want = manual >= 0 ? (manual == 1) : ruleFan >= 0 ? (ruleFan == 1) : (humLatch || airBad);
    if (fan && !want && manual < 0 && t - fanOnAt < c.FAN_MIN_ON_S) want = true;   // minimum run time
    if (want && !fan) {
      fan = true; fanOnAt = t; fanReason = reason;
      emit(t, "FAN_ON", reason);
      verifyKind = (reason == 1 && humOk) ? 1 : (reason == 2 ? 2 : 0);
      verifyV0 = verifyKind == 1 ? hum : gasPct;
    } else if (fan && !want) {
      fan = false; emit(t, "FAN_OFF", (long)(t - fanOnAt));
      if (verifyKind) { verifyKind = 0; fault = false; emit(t, "FAN_VERIFIED", 0, (long)(t - fanOnAt)); }
    }
    // act, then verify
    if (fan && verifyKind && t - fanOnAt >= c.VERIFY_S) {
      int kind = verifyKind;
      bool nowOk = kind == 1 ? humOk : true;
      int now = kind == 1 ? hum : gasPct;
      int need = kind == 1 ? c.VERIFY_HUM_DROP : c.VERIFY_GAS_DROP;
      verifyKind = 0;
      if (nowOk && verifyV0 - now >= need) { fault = false; emit(t, "FAN_VERIFIED", verifyV0 - now, c.VERIFY_S); }
      else { fault = true; emit(t, "FAN_FAULT", fanReason, nowOk ? verifyV0 - now : 0); }
    }

    // link to the service board
    if (linkOk) {
      linkBadSince = -1;
      if (linkLost) { linkLost = false; emit(t, "LINK_OK"); }
    } else {
      if (linkBadSince < 0) linkBadSince = t;
      if (!linkLost && t - linkBadSince >= c.LINK_TIMEOUT_S) { linkLost = true; emit(t, "LINK_LOST"); }
    }

    // one state for the door sign, most serious first
    if (fault || sensorFault[1] || sensorFault[3] || linkLost) state = "FAULT";
    else if (lowWater) state = "NO_WATER";
    else if (needsCleaning || drainCheck) state = "NEEDS_CLEANING";
    else if (fan) state = "VENTILATING";
    else if (doorClosed) state = "IN_USE";
    else state = "FREE";
  }

 private:
  static const int CAP = 96;
  bool first = true, door = false, useStarted = false, tapConfirmed = false, suppressedLogged = false;
  bool cleanLogged = false, humLatch = false;
  bool sensorFault[5] = {false, false, false, false, false};
  double sensorBadSince[5] = {-1, -1, -1, -1, -1};
  double closedAt = 0, openedAt = 0, tapSince = -1, tapClearSince = -1, lowSince = -1;
  double gateAt = 0, gateSettle = -1, baseSince = -1, baseSum = 0, gasHiSince = -1, gasLoSince = -1;
  double fanOnAt = 0, linkBadSince = -1;
  int tapLevel0 = 0, gateRef = 0, baseN = 0, fanReason = 0, verifyKind = 0, verifyV0 = 0;
  double levT[CAP], humT[CAP];
  int levV[CAP], humV[CAP];
  int levN = 0, humN = 0;

  bool inLevelOk = false, inHumOk = false;
  int inLevel = 0, inHum = 0, inTemp = -1;
  bool valHas[S_COUNT] = {false};
  double val[S_COUNT] = {0};

  // The values rules are judged on, in the board's own units (HUM and TEMP are x 10).
  void snapshot(double t) {
    valHas[S_DOOR] = true; val[S_DOOR] = door ? 1 : 0;
    valHas[S_LEVEL] = inLevelOk; val[S_LEVEL] = inLevel;
    valHas[S_RATE] = true; val[S_RATE] = levelRate;
    valHas[S_GAS] = gasPct != 0; val[S_GAS] = gasPct;
    valHas[S_HUM] = inHumOk; val[S_HUM] = inHum;
    valHas[S_TEMP] = inTemp >= 0; val[S_TEMP] = inTemp;
    valHas[S_USES] = true; val[S_USES] = uses;
    valHas[S_OCC_S] = true; val[S_OCC_S] = door ? (t - closedAt) : 0;
    valHas[S_FREE_S] = true; val[S_FREE_S] = door ? 0 : (t - openedAt);
  }
  bool conditions(const Rule &r) const {
    if (r.n == 0) return true;
    bool all = true, any = false;
    for (int i = 0; i < r.n; i++) {
      int s = r.c[i].sensor;
      if (!valHas[s]) return false;          // a rule never fires on a missing reading
      double v = val[s], x = (double)r.c[i].value;
      bool ok = r.c[i].op == OP_LT ? v < x : r.c[i].op == OP_GT ? v > x : v == x;
      all = all && ok; any = any || ok;
    }
    return r.matchAll ? all : any;
  }
  void ruleEvent(double t, const char *code) {
    for (int s = 1; s <= MAX_RULES; s++) {
      Rule &r = rules[s];
      if (r.used && r.onEvent && !strcmp(r.event, code) && conditions(r)) {
        r.active = true; r.activeUntil = t + r.forS; r.hasUntil = true;
        emit(t, "RULE_FIRED", s);
      }
    }
  }
  int runRules(double t) {
    for (int s = 1; s <= MAX_RULES; s++) {
      Rule &r = rules[s];
      if (!r.used) continue;
      if (r.onEvent) { if (r.active && t >= r.activeUntil) r.active = false; continue; }
      if (!conditions(r)) { r.trueSince = -1; r.active = false; r.armed = true; continue; }
      if (r.trueSince < 0) r.trueSince = t;
      if (!r.active && r.armed && t - r.trueSince >= r.holdS) {
        r.active = true; r.armed = false;
        r.hasUntil = r.forS > 0; r.activeUntil = t + r.forS;
        emit(t, "RULE_FIRED", s);
      }
      if (r.active && r.hasUntil && t >= r.activeUntil) r.active = false;   // off until the condition goes false and true again
    }
    int bestPr = 99, best = -1;
    for (int s = 1; s <= MAX_RULES; s++) {
      const Rule &r = rules[s];
      if (!r.used || !r.active || r.action == ACT_JOB) continue;
      int want = r.action == ACT_FAN_ON ? 1 : 0;
      if (r.priority < bestPr || (r.priority == bestPr && want == 0)) { bestPr = r.priority; best = want; }   // on a tie, off wins
    }
    return best;
  }

  void emit(double t, const char *code, long a = 0, long b = 0) {
    seq++;
    if (onEvent) onEvent(t, seq, code, a, b);
  }
  static void push(double *T, int *V, int &n, double t, int v) {
    if (n == CAP) pop(T, V, n);
    T[n] = t; V[n] = v; n++;
  }
  static void pop(double *T, int *V, int &n) {
    for (int i = 1; i < n; i++) { T[i - 1] = T[i]; V[i - 1] = V[i]; }
    n--;
  }
  int slope() const {          // least-squares slope of the water level, mm per minute
    if (levN < 6) return 0;
    double t0 = levT[0], span = levT[levN - 1] - t0;
    if (span < cfg.SLOPE_WINDOW_S * 0.6) return 0;
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (int i = 0; i < levN; i++) { double x = levT[i] - t0; sx += x; sy += levV[i]; sxx += x * x; sxy += x * levV[i]; }
    double den = levN * sxx - sx * sx;
    if (den == 0) return 0;
    return (int)rint((levN * sxy - sx * sy) / den * 60.0);
  }
  void sensor(double t, int id, bool ok) {
    if (ok) {
      sensorBadSince[id] = -1;
      if (sensorFault[id]) { sensorFault[id] = false; emit(t, "SENSOR_OK", id); }
    } else {
      if (sensorBadSince[id] < 0) sensorBadSince[id] = t;
      if (t - sensorBadSince[id] >= cfg.SENSOR_TIMEOUT_S && !sensorFault[id]) { sensorFault[id] = true; emit(t, "SENSOR_FAULT", id); }
    }
  }
};
#endif
