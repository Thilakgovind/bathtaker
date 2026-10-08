// Washroom Caretaker - SERVICE BOARD (the full program)
// Listens for the room board by radio and switches the fan relay.
// If it hears nothing for 3 seconds it turns the fan off by itself.
// Serial Monitor: 115200 baud.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>

// ---------- settings: use what you found with service_test ----------
#define RELAY_ON_LEVEL LOW          // LOW or HIGH, whichever switched your relay ON
#define RELAY_OFF_BY_FLOATING false // true only if the relay would not switch off
// ---------------------------------------------------------------------

const int PIN_RELAY = 26;
struct CmdPacket { uint32_t magic; uint32_t n; uint8_t fan; };
struct AckPacket { uint32_t magic; uint32_t n; uint8_t relay; };
const uint32_t MAGIC_CMD = 0x57434D31, MAGIC_ACK = 0x57434131;
uint8_t EVERYONE[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

volatile bool gotCmd = false;
volatile uint32_t cmdN = 0;
volatile uint8_t cmdFan = 0;
unsigned long lastCmdMs = 0;
bool relayOn = false, silent = true;

void setRelay(bool on) {
  if (!on && RELAY_OFF_BY_FLOATING) {
    pinMode(PIN_RELAY, INPUT);
  } else {
    pinMode(PIN_RELAY, OUTPUT);
    digitalWrite(PIN_RELAY, on ? RELAY_ON_LEVEL : (RELAY_ON_LEVEL == LOW ? HIGH : LOW));
  }
  if (on != relayOn) Serial.println(on ? "fan ON" : "fan OFF");
  relayOn = on;
}

void handleCmd(const uint8_t *data, int len) {
  if (len != (int)sizeof(CmdPacket)) return;
  CmdPacket c;
  memcpy(&c, data, sizeof(c));
  if (c.magic != MAGIC_CMD) return;
  cmdN = c.n;
  cmdFan = c.fan;
  gotCmd = true;                    // the switching happens in loop(), not inside the radio callback
}
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) { (void)info; handleCmd(data, len); }
#else
void onReceive(const uint8_t *mac, const uint8_t *data, int len) { (void)mac; handleCmd(data, len); }
#endif

void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println();
  Serial.println("=== SERVICE BOARD ===");
  setRelay(false);
  WiFi.mode(WIFI_STA);
  Serial.print("This board's address: ");
  Serial.println(WiFi.macAddress());
  if (esp_now_init() != ESP_OK) { Serial.println("ESP-NOW did not start. Press EN to restart."); return; }
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, EVERYONE, 6);
  peer.channel = 0;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  Serial.println("Waiting for the room board...");
}

void loop() {
  if (gotCmd) {
    gotCmd = false;
    lastCmdMs = millis();
    if (silent) { silent = false; Serial.println("Room board heard."); }
    setRelay(cmdFan == 1);
    AckPacket a = {MAGIC_ACK, cmdN, (uint8_t)(relayOn ? 1 : 0)};
    esp_now_send(EVERYONE, (const uint8_t *)&a, sizeof(a));
  }
  if (!silent && millis() - lastCmdMs > 3000) {       // fail-safe
    silent = true;
    Serial.println("Nothing heard for 3 seconds: fan switched off for safety.");
    setRelay(false);
  }
}
