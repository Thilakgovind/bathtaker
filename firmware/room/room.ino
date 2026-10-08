// Washroom Caretaker - ROOM BOARD (the full program)
// Reads the four sensors, decides what is happening, runs the fan, shows the door sign,
// and reports to the laptop. Serial Monitor: 115200 baud.
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
#include "room_logic.h"

// ---------- settings: change these to match your rig ----------
#define DHT_TYPE DHT11            // DHT11 (blue) or DHT22 (white)
#define DOOR_CLOSED_LEVEL LOW     // what the door pin reads when the magnet is near (from room_test)
#define USE_RADIO true            // true: the fan relay is on the service board. false: relay on THIS board, GPIO 26
#define RELAY_ON_LEVEL LOW        // only used when USE_RADIO is false
#define SENSOR_TO_BOTTOM_MM 300   // ultrasonic sensor to the bottom of the bucket. Or type ZERO with the bucket empty
#define AUTO_HUMIDITY_LINES true  // true: at start, set "fan on" 10 % above the room's own humidity and "fan off" 5 % above
#define PIN_BUZZER -1             // GPIO of the buzzer, or -1 if there is none. Free pins: 25, 33, 23, 13
#define PIN_LED -1                // GPIO of the alert LED, or -1 if there is none
#define BUZZER_ON_LEVEL HIGH      // HIGH for a buzzer that sounds when the pin is high
// ---------------------------------------------------------------
#define FIRMWARE "0.2"
#define PROTOCOL 1

const int PIN_SDA = 21, PIN_SCL = 22, PIN_DHT = 4, PIN_DOOR = 32, PIN_TRIG = 19, PIN_ECHO = 18, PIN_GAS = 34, PIN_RELAY = 26;

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
struct CmdPacket { uint32_t magic; uint32_t n; uint8_t fan; };
struct AckPacket { uint32_t magic; uint32_t n; uint8_t relay; };
const uint32_t MAGIC_CMD = 0x57434D31, MAGIC_ACK = 0x57434131;
uint8_t EVERYONE[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
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
  if (needsBeep(code)) beepsLeft = 3;
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
  pinMode(PIN_DOOR, INPUT);
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
  logic.onEvent = onEvent;

  if (USE_RADIO) {
    WiFi.mode(WIFI_STA);
    if (esp_now_init() == ESP_OK) {
      esp_now_register_recv_cb(onReceive);
      esp_now_peer_info_t peer = {};
      memcpy(peer.peer_addr, EVERYONE, 6);
      peer.channel = 0;
      peer.encrypt = false;
      esp_now_add_peer(&peer);
    } else {
      Serial.println("# ESP-NOW did not start");
    }
  }
  Serial.println();
  Serial.printf("H,%d,%s,ROOM\n", PROTOCOL, FIRMWARE);
  Serial.printf("# Room board started. Radio %s. Sensor to bottom %d mm. OLED %s.\n", USE_RADIO ? "on" : "off (relay on this board)", sensorToBottom, oledOk ? "ok" : "NOT FOUND");
  Serial.println("# Type CLEANED, FAN,ON, FAN,OFF, FAN,AUTO, CFG?, LOG?, RULES? or ZERO and press Enter.");
}

void loop() {
  readSerial();
  runBuzzer();
  if (millis() - lastTick < 500) return;
  lastTick = millis();

  bool doorClosed = (digitalRead(PIN_DOOR) == DOOR_CLOSED_LEVEL);
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

  if (PIN_LED >= 0) {                // the LED stays on while a person needs to do something
    bool attention = !strcmp(logic.state, "NEEDS_CLEANING") || !strcmp(logic.state, "NO_WATER") || !strcmp(logic.state, "FAULT") || logic.tapSuspected;
    digitalWrite(PIN_LED, attention ? HIGH : LOW);
  }

  if (USE_RADIO) {
    CmdPacket c = {MAGIC_CMD, ++cmdN, (uint8_t)(logic.fan ? 1 : 0)};
    cmdSentMs = millis();
    esp_now_send(EVERYONE, (const uint8_t *)&c, sizeof(c));
  } else {
    setRelayLocal(logic.fan);
  }

  Serial.printf("D,%lu,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%d\n", millis(), doorClosed ? 1 : 0, levelOk ? levelMm : -1,
                logic.levelRate, gas, logic.gasPct, hum10, temp10, logic.fan ? 1 : 0, logic.state, logic.uses, logic.flags(linkOk));
  drawSign(levelOk ? levelMm : -1, gas);
}
