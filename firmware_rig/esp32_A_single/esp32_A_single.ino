// Washroom Caretaker - ESP32 A (ROOM BOARD) for this rig
// Sensors: MQ-135 gas (GPIO 36), DHT temperature/humidity (GPIO 4), ultrasonic water level (Trig 19, Echo 18),
// optional OLED (SDA 21, SCL 22), optional door magnet. Plug this board into the laptop by USB.
// It tells ESP32 B (MAC 6C:C8:40:87:9B:FC) by radio when to run the fan, light the LED and sound the buzzer.
//
// ABOVE 37 C: fan ON (built-in rule "Fan when hot"), LED ON and buzzer beeping on ESP32 B.
//             Everything clears below 36 C (the fan keeps its minimum run time).
// Serial Monitor: 115200 baud. CLOSE the Serial Monitor before starting the laptop program.
//
// Libraries (Arduino IDE > Library Manager): Adafruit SSD1306, Adafruit GFX Library,
// DHT sensor library (by Adafruit). Choose "Install all" when asked about dependencies.

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_now.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
// ===== room logic (was room_logic.h, now inside this one file) =====
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

// ===== end of room logic =====

// ---------- settings: change these to match your rig ----------
#define DHT_TYPE DHT11            // DHT11 (blue) or DHT22 (white)
#define DOOR_CLOSED_LEVEL LOW     // what the door pin reads when the magnet is near (from room_test)
#define USE_RADIO true            // true: fan, LED and buzzer are on ESP32 B
#define RELAY_ON_LEVEL LOW        // only used when USE_RADIO is false
#define SENSOR_TO_BOTTOM_MM 300   // ultrasonic sensor to the bottom of the bucket. Or type ZERO with the bucket empty
#define AUTO_HUMIDITY_LINES true  // true: at start, set "fan on" 10 % above the room's own humidity and "fan off" 5 % above
#define PIN_BUZZER -1             // the buzzer is on ESP32 B (D21), so -1 here
#define PIN_LED -1                // the LED is on ESP32 B (D19), so -1 here
#define PIN_DOOR_SENSOR -1        // GPIO of the door magnet sensor, or -1 if you have none
#define HOT_ON_C10 370            // 37.0 C: alarm on
#define HOT_OFF_C10 360           // 36.0 C: alarm off
#define HEAT_RULE true            // true: install the built-in rule "Fan when hot" (fan on above 37 C) in slot 8
#define BUZZER_ON_LEVEL HIGH      // HIGH for a buzzer that sounds when the pin is high
// --------------------------------
#define FIRMWARE "0.2"
#define PROTOCOL 1

const int PIN_SDA = 21, PIN_SCL = 22, PIN_DHT = 4, PIN_DOOR = PIN_DOOR_SENSOR, PIN_TRIG = 19, PIN_ECHO = 18, PIN_GAS = 36, PIN_RELAY = 26;

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
DHT dht(PIN_DHT, DHT_TYPE);
Preferences prefs;
RoomLogic logic;

bool oledOk = false;
int sensorToBottom = SENSOR_TO_BOTTOM_MM;
int hum10 = -1, temp10 = -1, lastDistMm = -1;
bool humLinesSet = false;
unsigned long lastTick = 0, lastDht = 0;
char lastEventText[80] = "Starting";
int beepsLeft = 0;                // short beeps still to play
unsigned long beepAt = 0;
bool beepOn = false;

// ----- the last 50 events, for LOG? -----
struct Ev { unsigned long ms, seq; const char *code; long a, b; };
Ev evLog[50];
int evCount = 0, evNext = 0;

// ----- radio link to the service board -----
struct CmdPacket { uint32_t magic; uint32_t n; uint8_t fan; uint8_t led; uint8_t alarm; uint8_t beepSeq; };
struct AckPacket { uint32_t magic; uint32_t n; uint8_t relay; };
const uint32_t MAGIC_CMD = 0x57434D32, MAGIC_ACK = 0x57434131;
uint8_t EVERYONE[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t BOARD_B[6] = {0x6C, 0xC8, 0x40, 0x87, 0x9B, 0xFC};   // ESP32 B (fan, LED, buzzer)
bool hot = false;                 // above 37 C
uint8_t beepSeq = 0;              // goes up by one for each event that needs 3 short beeps on B
volatile unsigned long lastAckMs = 0;
volatile uint32_t lastAckN = 0;
uint32_t cmdN = 0;
unsigned long cmdSentMs = 0, roundTripMs = 0;

void handleAck(const uint8_t *data, int len) {
  if (len != (int)sizeof(AckPacket)) return;
  AckPacket a;
  memcpy(&a, data, sizeof(a));
  if (a.magic != MAGIC_ACK) return;
  lastAckMs = millis();
  lastAckN = a.n;
}
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) { (void)info; handleAck(data, len); }
#else
void onReceive(const uint8_t *mac, const uint8_t *data, int len) { (void)mac; handleAck(data, len); }
#endif

// ----- events: one protocol line, one line for people, and the OLED text -----
void describe(const char *code, long a, long b, char *out, size_t n) {
  if (!strcmp(code, "BOOT")) snprintf(out, n, "Started");
  else if (!strcmp(code, "USE_START")) snprintf(out, n, "In use");
  else if (!strcmp(code, "USE_END")) snprintf(out, n, "Use ended after %ld s. Uses: %ld", a, b);
  else if (!strcmp(code, "TAP_SUSPECTED")) snprintf(out, n, "Tap suspected: water falling %ld mm/min, nobody inside", a);
  else if (!strcmp(code, "TAP_CONFIRMED")) snprintf(out, n, "Tap left running or leak: %ld mm lost", b);
  else if (!strcmp(code, "TAP_CLEARED")) snprintf(out, n, "Water stopped falling");
  else if (!strcmp(code, "LOW_WATER")) snprintf(out, n, "No water: level %ld mm", a);
  else if (!strcmp(code, "WATER_OK")) snprintf(out, n, "Water is back: %ld mm", a);
  else if (!strcmp(code, "STEAM_GATE_ON")) snprintf(out, n, "Steam noticed. Air alarm on hold");
  else if (!strcmp(code, "STEAM_GATE_OFF")) snprintf(out, n, "Steam has cleared");
  else if (!strcmp(code, "AIR_SUPPRESSED")) snprintf(out, n, "Air reads %ld%% but it is steam: no alarm", a);
  else if (!strcmp(code, "AIR_BAD")) snprintf(out, n, "Air is bad: %ld%% of normal", a);
  else if (!strcmp(code, "AIR_OK")) snprintf(out, n, "Air is back to normal");
  else if (!strcmp(code, "FAN_ON")) snprintf(out, n, "Fan on (%s)", a == 1 ? "humidity" : a == 2 ? "air" : a == 3 ? "rule" : "manual");
  else if (!strcmp(code, "FAN_OFF")) snprintf(out, n, "Fan off after %ld s", a);
  else if (!strcmp(code, "FAN_VERIFIED")) snprintf(out, n, "Fan verified: the reading came down");
  else if (!strcmp(code, "FAN_FAULT")) snprintf(out, n, "FAN FAULT, or the source is still present");
  else if (!strcmp(code, "CLEAN_DUE")) snprintf(out, n, "Clean now: %ld uses%s", a, b == 2 ? " and bad air" : "");
  else if (!strcmp(code, "DRAIN_CHECK")) snprintf(out, n, "Check the drain: bad air with no uses");
  else if (!strcmp(code, "CLEANED")) snprintf(out, n, "Marked as cleaned");
  else if (!strcmp(code, "SENSOR_FAULT")) snprintf(out, n, "Sensor fault: %s", a == 1 ? "ultrasonic" : a == 3 ? "humidity" : "sensor");
  else if (!strcmp(code, "SENSOR_OK")) snprintf(out, n, "Sensor is back");
  else if (!strcmp(code, "LINK_LOST")) snprintf(out, n, "Lost the service board");
  else if (!strcmp(code, "LINK_OK")) snprintf(out, n, "Service board is back");
  else if (!strcmp(code, "RULE_FIRED")) snprintf(out, n, "Rule fired: %s", (a >= 1 && a <= MAX_RULES) ? logic.rules[a].name : "?");
  else if (!strcmp(code, "RULE_ADDED")) snprintf(out, n, "Rule saved in slot %ld: %s", a, (a >= 1 && a <= MAX_RULES) ? logic.rules[a].name : "?");
  else if (!strcmp(code, "RULE_DELETED")) snprintf(out, n, "Rule deleted from slot %ld", a);
  else snprintf(out, n, "%s", code);
}

// The buzzer sounds only for things a person must act on. Steam never sounds it.
bool needsBeep(const char *code) {
  return !strcmp(code, "AIR_BAD") || !strcmp(code, "TAP_CONFIRMED") || !strcmp(code, "FAN_FAULT") ||
         !strcmp(code, "LOW_WATER") || !strcmp(code, "LINK_LOST") || !strcmp(code, "SENSOR_FAULT");
}

void runBuzzer() {
  if (PIN_BUZZER < 0) return;
  if (beepsLeft > 0 && millis() >= beepAt) {
    beepOn = !beepOn;
    digitalWrite(PIN_BUZZER, beepOn ? BUZZER_ON_LEVEL : (BUZZER_ON_LEVEL == HIGH ? LOW : HIGH));
    beepAt = millis() + 150;
    if (!beepOn) beepsLeft--;
  }
}

void onEvent(double t, unsigned long seq, const char *code, long a, long b) {
  unsigned long ms = (unsigned long)(t * 1000.0);
  Serial.printf("E,%lu,%lu,%s,%ld,%ld\n", ms, seq, code, a, b);
  evLog[evNext] = {ms, seq, code, a, b};
  evNext = (evNext + 1) % 50;
  if (evCount < 50) evCount++;
  describe(code, a, b, lastEventText, sizeof(lastEventText));
  if (needsBeep(code)) { beepsLeft = 3; beepSeq++; }
  Serial.printf("# %s\n", lastEventText);     // lines starting with # are for people; the laptop ignores them
}

// ----- thresholds that can be changed from the laptop with CFG,KEY,value -----
struct CfgKey { const char *name; int *value; };
CfgKey cfgKeys[] = {
  {"LOW_MM", &logic.cfg.LOW_MM}, {"MIN_USE_S", &logic.cfg.MIN_USE_S}, {"SLOPE_WINDOW_S", &logic.cfg.SLOPE_WINDOW_S},
  {"TAP_RATE", &logic.cfg.TAP_RATE}, {"TAP_SUSPECT_S", &logic.cfg.TAP_SUSPECT_S}, {"TAP_CONFIRM_S", &logic.cfg.TAP_CONFIRM_S},
  {"TAP_CLEAR_S", &logic.cfg.TAP_CLEAR_S}, {"GAS_BAD_PCT", &logic.cfg.GAS_BAD_PCT}, {"GAS_OK_PCT", &logic.cfg.GAS_OK_PCT},
  {"GAS_BAD_S", &logic.cfg.GAS_BAD_S}, {"BASELINE_STABLE_S", &logic.cfg.BASELINE_STABLE_S}, {"STEAM_RISE", &logic.cfg.STEAM_RISE},
  {"STEAM_WINDOW_S", &logic.cfg.STEAM_WINDOW_S}, {"STEAM_SETTLE", &logic.cfg.STEAM_SETTLE}, {"STEAM_MAX_S", &logic.cfg.STEAM_MAX_S},
  {"HUM_ON", &logic.cfg.HUM_ON}, {"HUM_OFF", &logic.cfg.HUM_OFF}, {"FAN_MIN_ON_S", &logic.cfg.FAN_MIN_ON_S},
  {"VERIFY_S", &logic.cfg.VERIFY_S}, {"VERIFY_HUM_DROP", &logic.cfg.VERIFY_HUM_DROP}, {"VERIFY_GAS_DROP", &logic.cfg.VERIFY_GAS_DROP},
  {"CLEAN_USES", &logic.cfg.CLEAN_USES}, {"SENSOR_TIMEOUT_S", &logic.cfg.SENSOR_TIMEOUT_S}, {"LINK_TIMEOUT_S", &logic.cfg.LINK_TIMEOUT_S},
};
const int CFG_COUNT = sizeof(cfgKeys) / sizeof(cfgKeys[0]);

void loadSettings() {
  prefs.begin("caretaker", false);
  sensorToBottom = prefs.getInt("bottom", SENSOR_TO_BOTTOM_MM);
  char k[6];
  for (int i = 0; i < CFG_COUNT; i++) {
    snprintf(k, sizeof(k), "c%d", i);
    *cfgKeys[i].value = prefs.getInt(k, *cfgKeys[i].value);
  }
}

// ----- caretaker rules: kept in the board's own storage so they survive a power cut -----
void saveRule(int slot) {
  char key[4], line[220];
  snprintf(key, sizeof(key), "r%d", slot);
  if (logic.rules[slot].used) {
    int n = snprintf(line, sizeof(line), "RULE,");
    logic.formatRule(slot, line + n, sizeof(line) - n);
    prefs.putString(key, line);
  } else {
    prefs.remove(key);
  }
}

void loadRules() {
  char key[4], err[48];
  int count = 0;
  for (int slot = 1; slot <= MAX_RULES; slot++) {
    snprintf(key, sizeof(key), "r%d", slot);
    String line = prefs.getString(key, "");
    if (line.length() == 0) continue;
    Rule r;
    if (logic.parseRule(line.c_str(), r, err, sizeof(err)) == slot) { logic.addRule(0, slot, r, false); count++; }
  }
  Serial.printf("# %d saved rule%s loaded.\n", count, count == 1 ? "" : "s");
}

// ----- sensors -----
float pingCm() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(3);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);
  if (us == 0) return -1;
  return us * 0.0343f / 2.0f;
}

int distanceMm() {                 // middle value of five pings; -1 if none came back
  float v[5];
  int n = 0;
  for (int i = 0; i < 5; i++) {
    float d = pingCm();
    if (d > 0) v[n++] = d;
    delay(50);
  }
  if (n == 0) return -1;
  for (int i = 0; i < n; i++)
    for (int j = i + 1; j < n; j++)
      if (v[j] < v[i]) { float t = v[i]; v[i] = v[j]; v[j] = t; }
  return (int)(v[n / 2] * 10.0f + 0.5f);
}

int gasRaw() {
  long sum = 0;
  for (int i = 0; i < 16; i++) sum += analogRead(PIN_GAS);
  return (int)(sum / 16);
}

void setRelayLocal(bool on) {
  digitalWrite(PIN_RELAY, on ? RELAY_ON_LEVEL : (RELAY_ON_LEVEL == LOW ? HIGH : LOW));
}

// ----- door sign -----
const char *signText(const char *state) {
  if (!strcmp(state, "FREE")) return "FREE";
  if (!strcmp(state, "IN_USE")) return "IN USE";
  if (!strcmp(state, "VENTILATING")) return "FAN ON";
  if (!strcmp(state, "NEEDS_CLEANING")) return "CLEAN ME";
  if (!strcmp(state, "NO_WATER")) return "NO WATER";
  return "FAULT";
}

void drawSign(int levelMm, int gas) {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(0, 0);
  oled.println(signText(logic.state));
  oled.setTextSize(1);
  oled.setCursor(0, 22);
  if ((millis() / 3000) % 2 == 0) {
    oled.printf("Water %d mm  Uses %d\n", levelMm, logic.uses);
    oled.printf("Air %d%%  Hum %d%%\n", logic.gasPct, hum10 < 0 ? 0 : hum10 / 10);
    oled.printf("Fan %s  Link %s\n", logic.fan ? "ON" : "off", logic.linkLost ? "LOST" : "ok");
    (void)gas;
  } else {
    oled.println("Last event:");
    oled.println(lastEventText);
  }
  oled.display();
}

// ----- commands from the laptop -----
char lineBuf[220];
int lineLen = 0;

void handleCommand(char *line) {
  double t = millis() / 1000.0;
  if (!strncmp(line, "RULE,", 5)) {              // RULE,slot,priority,ALL|ANY,hold_s,action,for_s,trigger,n,...,name
    Rule r;
    char err[48];
    int slot = logic.parseRule(line, r, err, sizeof(err));
    if (slot) { logic.addRule(t, slot, r); saveRule(slot); Serial.printf("A,RULE,OK,%d\n", slot); }
    else Serial.printf("A,RULE,ERR,%s\n", err);
    return;
  }
  char *cmd = strtok(line, ",");
  if (!cmd) return;
  if (!strcmp(cmd, "PING")) Serial.println("A,PING,OK");
  else if (!strcmp(cmd, "HELLO?")) Serial.printf("H,%d,%s,ROOM\n", PROTOCOL, FIRMWARE);
  else if (!strcmp(cmd, "CLEANED")) { logic.cleaned(t); Serial.println("A,CLEANED,OK"); }
  else if (!strcmp(cmd, "FAN")) {
    char *m = strtok(NULL, ",");
    if (m && !strcmp(m, "AUTO")) { logic.manual = -1; Serial.println("A,FAN,OK,AUTO"); }
    else if (m && !strcmp(m, "ON")) { logic.manual = 1; Serial.println("A,FAN,OK,ON"); }
    else if (m && !strcmp(m, "OFF")) { logic.manual = 0; Serial.println("A,FAN,OK,OFF"); }
    else Serial.println("A,FAN,ERR,use AUTO ON or OFF");
  }
  else if (!strcmp(cmd, "CFG")) {
    char *key = strtok(NULL, ","), *val = strtok(NULL, ",");
    bool done = false;
    for (int i = 0; key && val && i < CFG_COUNT; i++) {
      if (!strcmp(key, cfgKeys[i].name)) {
        *cfgKeys[i].value = atoi(val);
        char k[6];
        snprintf(k, sizeof(k), "c%d", i);
        prefs.putInt(k, *cfgKeys[i].value);
        Serial.printf("A,CFG,OK,%s,%d\n", key, *cfgKeys[i].value);
        done = true;
      }
    }
    if (!done) Serial.println("A,CFG,ERR,unknown key");
  }
  else if (!strcmp(cmd, "CFG?")) {
    Serial.print("A,CFG,OK,");
    for (int i = 0; i < CFG_COUNT; i++) Serial.printf("%s=%d%s", cfgKeys[i].name, *cfgKeys[i].value, i < CFG_COUNT - 1 ? ";" : "\n");
  }
  else if (!strcmp(cmd, "LOG?")) {
    int start = (evNext - evCount + 50) % 50;
    for (int i = 0; i < evCount; i++) {
      Ev &e = evLog[(start + i) % 50];
      Serial.printf("E,%lu,%lu,%s,%ld,%ld\n", e.ms, e.seq, e.code, e.a, e.b);
    }
    Serial.printf("A,LOG,OK,%d\n", evCount);
  }
  else if (!strcmp(cmd, "ZERO")) {            // type this with the bucket EMPTY: it measures the sensor-to-bottom distance
    if (lastDistMm > 0) { sensorToBottom = lastDistMm; prefs.putInt("bottom", sensorToBottom); Serial.printf("A,ZERO,OK,%d\n", sensorToBottom); }
    else Serial.println("A,ZERO,ERR,no echo");
  }
  else if (!strcmp(cmd, "DEL")) {
    char *sl = strtok(NULL, ",");
    int slot = sl ? atoi(sl) : 0;
    if (slot >= 1 && slot <= MAX_RULES) { logic.deleteRule(t, slot); saveRule(slot); Serial.printf("A,DEL,OK,%d\n", slot); }
    else Serial.println("A,DEL,ERR,slot must be 1 to 8");
  }
  else if (!strcmp(cmd, "RULES?")) {
    char line2[220];
    int count = 0;
    for (int slot = 1; slot <= MAX_RULES; slot++) {
      if (!logic.rules[slot].used) continue;
      logic.formatRule(slot, line2, sizeof(line2));
      Serial.printf("R,%s\n", line2);
      count++;
    }
    Serial.printf("A,RULES,OK,%d\n", count);
  }
  else Serial.printf("A,%s,ERR,unknown command\n", cmd);
}

void readSerial() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (lineLen > 0) { lineBuf[lineLen] = 0; handleCommand(lineBuf); lineLen = 0; }
    } else if (lineLen < (int)sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = ch;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(600);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  if (PIN_DOOR >= 0) pinMode(PIN_DOOR, INPUT_PULLUP);
  analogReadResolution(12);
  if (!USE_RADIO) { pinMode(PIN_RELAY, OUTPUT); setRelayLocal(false); }

  Wire.begin(PIN_SDA, PIN_SCL);
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (!oledOk) oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3D);
  dht.begin();
  if (PIN_BUZZER >= 0) { pinMode(PIN_BUZZER, OUTPUT); digitalWrite(PIN_BUZZER, BUZZER_ON_LEVEL == HIGH ? LOW : HIGH); }
  if (PIN_LED >= 0) { pinMode(PIN_LED, OUTPUT); digitalWrite(PIN_LED, LOW); }
  loadSettings();
  loadRules();
  if (HEAT_RULE && !logic.rules[8].used) {          // built-in: fan on while above 37 C
    Rule r; char err[48];
    char heat[80];
    snprintf(heat, sizeof(heat), "RULE,8,1,ANY,0,FAN_ON,0,WHILE,1,TEMP,GT,%d,Fan when hot", HOT_ON_C10);
    if (logic.parseRule(heat, r, err, sizeof(err)) == 8) { logic.addRule(0, 8, r, false); saveRule(8); Serial.println("# Built-in rule added: Fan when hot (above 37 C)."); }
    else Serial.printf("# Built-in heat rule not added: %s\n", err);
  }
  logic.onEvent = onEvent;

  if (USE_RADIO) {
    WiFi.mode(WIFI_STA);
    if (esp_now_init() == ESP_OK) {
      esp_now_register_recv_cb(onReceive);
      esp_now_peer_info_t peer = {};
      memcpy(peer.peer_addr, BOARD_B, 6);
      peer.channel = 0;
      peer.encrypt = false;
      if (esp_now_add_peer(&peer) != ESP_OK) Serial.println("# Could not add ESP32 B as a peer");
    } else {
      Serial.println("# ESP-NOW did not start");
    }
  }
  Serial.println();
  Serial.printf("H,%d,%s,ROOM\n", PROTOCOL, FIRMWARE);
  Serial.print("# This board (A) MAC: "); Serial.println(WiFi.macAddress());
  Serial.println("# Sending to ESP32 B at 6C:C8:40:87:9B:FC");
  Serial.printf("# Room board started. Radio %s. Sensor to bottom %d mm. OLED %s.\n", USE_RADIO ? "on" : "off (relay on this board)", sensorToBottom, oledOk ? "ok" : "NOT FOUND");
  Serial.println("# Type CLEANED, FAN,ON, FAN,OFF, FAN,AUTO, CFG?, LOG?, RULES? or ZERO and press Enter.");
}

void loop() {
  readSerial();
  runBuzzer();
  if (millis() - lastTick < 500) return;
  lastTick = millis();

  bool doorClosed = PIN_DOOR >= 0 && (digitalRead(PIN_DOOR) == DOOR_CLOSED_LEVEL);
  lastDistMm = distanceMm();                              // about a quarter of a second
  int levelMm = sensorToBottom - lastDistMm;
  bool levelOk = lastDistMm > 0 && levelMm > -30;
  if (levelOk && levelMm < 0) levelMm = 0;
  int gas = gasRaw();

  if (millis() - lastDht >= 2000 || lastDht == 0) {
    lastDht = millis();
    float h = dht.readHumidity(), tc = dht.readTemperature();
    if (!isnan(h) && !isnan(tc)) { hum10 = (int)(h * 10 + 0.5f); temp10 = (int)(tc * 10 + 0.5f); }
    else { hum10 = -1; temp10 = -1; }
    if (AUTO_HUMIDITY_LINES && !humLinesSet && hum10 >= 0) {     // a fixed 75 % line is useless in a humid city
      humLinesSet = true;
      logic.cfg.HUM_ON = min(hum10 + 100, 950);
      logic.cfg.HUM_OFF = min(hum10 + 50, 900);
      Serial.printf("# Room humidity is %d %%. Fan turns on above %d %% and off below %d %%. Start the board in a dry room, not a steamy one.\n",
                    hum10 / 10, logic.cfg.HUM_ON / 10, logic.cfg.HUM_OFF / 10);
    }
  }

  bool linkOk = true;
  if (USE_RADIO) {
    unsigned long ack = lastAckMs;
    linkOk = ack != 0 && millis() - ack < 3000;
    if (lastAckN == cmdN && ack >= cmdSentMs) roundTripMs = ack - cmdSentMs;
  }

  logic.update(millis() / 1000.0, doorClosed, levelOk, levelMm, gas, hum10 >= 0, hum10, temp10, linkOk);

  // heat alarm with a gap between on and off, so it does not flicker at 37 C
  if (temp10 >= 0) {
    if (!hot && temp10 > HOT_ON_C10) { hot = true; beepsLeft = 3; Serial.printf("# HOT: %d.%d C. Fan, LED and buzzer on.\n", temp10 / 10, temp10 % 10); }
    else if (hot && temp10 < HOT_OFF_C10) { hot = false; Serial.println("# Temperature back below 36 C."); }
  }
  // the LED stays on while a person needs to do something, or while it is hot
  bool attention = hot || !strcmp(logic.state, "NEEDS_CLEANING") || !strcmp(logic.state, "NO_WATER") || !strcmp(logic.state, "FAULT") || logic.tapSuspected;
  if (PIN_LED >= 0) digitalWrite(PIN_LED, attention ? HIGH : LOW);

  if (USE_RADIO) {
    CmdPacket c = {MAGIC_CMD, ++cmdN, (uint8_t)(logic.fan ? 1 : 0), (uint8_t)(attention ? 1 : 0), (uint8_t)(hot ? 1 : 0), beepSeq};
    cmdSentMs = millis();
    esp_now_send(BOARD_B, (const uint8_t *)&c, sizeof(c));
  } else {
    setRelayLocal(logic.fan);
  }

  Serial.printf("D,%lu,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%d\n", millis(), doorClosed ? 1 : 0, levelOk ? levelMm : -1,
                logic.levelRate, gas, logic.gasPct, hum10, temp10, logic.fan ? 1 : 0, logic.state, logic.uses, logic.flags(linkOk));
  drawSign(levelOk ? levelMm : -1, gas);
}
