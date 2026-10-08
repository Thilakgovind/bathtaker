// Washroom Caretaker - ESP32 B (SERVICE BOARD) for this rig. This board's MAC: 6C:C8:40:87:9B:FC
// Relay (fan) D18 active-LOW, LED D19, buzzer D21. Listens to ESP32 A by radio (ESP-NOW).
// - Power-on SELF TEST: fan 2 s, LED on, 3 beeps.
// - Fan, LED and buzzer follow ESP32 A. Above 37 C on A: fan on, LED on, buzzer beep-beep.
// - If nothing comes from A for 3 s, everything turns off (safe).
// Serial Monitor: 115200 baud. LOW VOLTAGE ONLY: never connect mains to the relay.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>

// ---------- settings ----------
#define PIN_RELAY       18
#define PIN_LED         19
#define PIN_BUZZER      21
#define RELAY_ON_LEVEL  LOW      // active-LOW relay. If the fan runs when it should be off, use HIGH
#define BUZZER_PASSIVE  false    // true if the buzzer only clicks
// --------------------------------

struct CmdPacket { uint32_t magic; uint32_t n; uint8_t fan; uint8_t led; uint8_t alarm; uint8_t beepSeq; };
struct AckPacket { uint32_t magic; uint32_t n; uint8_t relay; };
const uint32_t MAGIC_CMD = 0x57434D32, MAGIC_ACK = 0x57434131;
uint8_t EVERYONE[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

volatile bool gotCmd = false;
CmdPacket cmd;
unsigned long lastCmdMs = 0, beepAt = 0;
bool relayOn = false, ledOn = false, alarmOn = false, silent = true, beepOn = false, firstCmd = true;
int beepsLeft = 0;
uint8_t lastBeepSeq = 0;

void buzzer(bool on) {
  if (BUZZER_PASSIVE) { if (on) tone(PIN_BUZZER, 2000); else noTone(PIN_BUZZER); }
  else digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
}
void setRelay(bool on) {
  digitalWrite(PIN_RELAY, on ? RELAY_ON_LEVEL : (RELAY_ON_LEVEL == LOW ? HIGH : LOW));
  if (on != relayOn) Serial.println(on ? "fan ON" : "fan OFF");
  relayOn = on;
}
void setLed(bool on) {
  digitalWrite(PIN_LED, on ? HIGH : LOW);
  if (on != ledOn) Serial.println(on ? "LED ON" : "LED OFF");
  ledOn = on;
}
void allOff() { setRelay(false); setLed(false); alarmOn = false; beepsLeft = 0; buzzer(false); }

void handleCmd(const uint8_t *data, int len) {
  if (len != (int)sizeof(CmdPacket)) return;
  CmdPacket c; memcpy(&c, data, sizeof(c));
  if (c.magic != MAGIC_CMD) return;
  cmd = c; gotCmd = true;          // switching happens in loop(), not in the radio callback
}
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) { (void)info; handleCmd(data, len); }
#else
void onReceive(const uint8_t *mac, const uint8_t *data, int len) { (void)mac; handleCmd(data, len); }
#endif

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  allOff();
  Serial.println("\n=== ESP32 B (fan, LED, buzzer) ===");

  Serial.println("SELF TEST: fan 2 s, LED on, 3 beeps");
  setRelay(true); setLed(true);
  for (int i = 0; i < 3; i++) { buzzer(true); delay(200); buzzer(false); delay(200); }
  delay(800);
  allOff();
  Serial.println("SELF TEST done");

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(200);
  Serial.print("This board's MAC: "); Serial.print(WiFi.macAddress());
  Serial.println("  (must be 6C:C8:40:87:9B:FC)");
  if (esp_now_init() != ESP_OK) { Serial.println("ESP-NOW did not start. Press EN."); return; }
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, EVERYONE, 6);
  peer.channel = 0;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  Serial.println("Waiting for ESP32 A...");
}

void loop() {
  if (gotCmd) {
    gotCmd = false;
    lastCmdMs = millis();
    if (silent) { silent = false; Serial.println("ESP32 A heard."); }
    setRelay(cmd.fan == 1);
    setLed(cmd.led == 1);
    if ((cmd.alarm == 1) != alarmOn) { alarmOn = cmd.alarm == 1; Serial.println(alarmOn ? "HEAT ALARM ON" : "heat alarm off"); if (!alarmOn) buzzer(false); }
    if (firstCmd) { lastBeepSeq = cmd.beepSeq; firstCmd = false; }
    else if (cmd.beepSeq != lastBeepSeq) { lastBeepSeq = cmd.beepSeq; beepsLeft = 3; Serial.println("3 beeps (something needs attention)"); }
    AckPacket a = {MAGIC_ACK, cmd.n, (uint8_t)(relayOn ? 1 : 0)};
    esp_now_send(EVERYONE, (const uint8_t *)&a, sizeof(a));
  }

  if (!silent && millis() - lastCmdMs > 3000) {       // fail-safe
    silent = true;
    Serial.println("Nothing from ESP32 A for 3 s: all off for safety.");
    allOff();
  }

  if (alarmOn) {
    buzzer((millis() / 400) % 2 == 0);                // beep-beep while hot
  } else if (beepsLeft > 0 && millis() >= beepAt) {   // 3 short beeps for an event
    beepOn = !beepOn;
    buzzer(beepOn);
    beepAt = millis() + 150;
    if (!beepOn) beepsLeft--;
  }
}
