/*
  Belaku Kannu: ESP32 transformer monitor (Wokwi) -> FastAPI backend

  Hardware (unchanged pin map):
    DHT22 GPIO4 | voltage pot GPIO34 | current pot GPIO35 | LCD I2C SDA21/SCL22
    relay GPIO27 | buzzer GPIO14 | green LED GPIO25 | red LED GPIO26

  NOTE: this is a reference sketch written from the pin map and thresholds. If you
  already have your own sketch, keep it and merge only the parts marked "NETWORK":
  the config block, connectWiFi(), syncClock(), postReading() and the call in loop().

  Libraries (Wokwi: Library Manager, or libraries.txt): DHT sensor library, LiquidCrystal I2C
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>

// ───────────────── NETWORK: configuration (edit these 3 lines) ─────────────────
const char* API_BASE_URL    = "https://YOUR-TUNNEL.ngrok-free.app"; // ngrok URL, no trailing slash
const char* DEVICE_API_KEY  = "PASTE_DEVICE_KEY_HERE";              // = DEVICE_API_KEY in backend/.env
const char* TRANSFORMER_ID  = "PASTE_TRANSFORMER_CODE_HERE";        // a transformer_code that exists in your DB
const char* WIFI_SSID       = "Wokwi-GUEST";                        // Wokwi's built-in WiFi
const char* WIFI_PASS       = "";
const unsigned long SEND_INTERVAL_MS = 2000;

// ───────────────── Pins ─────────────────
#define PIN_DHT 4
#define PIN_VOLT 34
#define PIN_CURR 35
#define PIN_RELAY 27
#define PIN_BUZZER 14
#define PIN_LED_GREEN 25
#define PIN_LED_RED 26

DHT dht(PIN_DHT, DHT22);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Demo thresholds (must match backend/services/iot_alerts.py; the backend decides alerts itself)
enum Status { SAFE, WARNING, CRITICAL };
const char* STATUS_NAME[] = {"SAFE", "WARNING", "CRITICAL"};

Status evaluate(float v, float a, float t) {
  if (v < 200 || v > 260 || a > 80 || t > 70) return CRITICAL;
  if (v <= 210 || v >= 250 || a > 65 || t > 65) return WARNING;
  return SAFE;
}

// ───────────────── NETWORK ─────────────────
unsigned long lastWifiAttempt = 0;
bool clockStarted = false;

void connectWiFi() {
  Serial.printf("Connecting to WiFi '%s'...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);  // channel 6 makes Wokwi connect faster
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 10000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected, IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi not connected yet; will keep retrying.");
  }
}

void syncClock() {
  if (!clockStarted && WiFi.status() == WL_CONNECTED) {
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");  // UTC
    clockStarted = true;
  }
}

// Writes an ISO-8601 UTC timestamp, or returns false if the clock is not synced yet.
bool isoTimestamp(char* out, size_t len) {
  struct tm tm;
  if (!getLocalTime(&tm, 0) || tm.tm_year < 120) return false;
  strftime(out, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
  return true;
}

// Returns the HTTP status code (negative = connection error, 0 = skipped).
int postReading(float v, float a, float t, Status st) {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiAttempt > 10000) {   // retry without blocking the loop for long
      lastWifiAttempt = millis();
      Serial.println("WiFi down, reconnecting...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
    }
    Serial.println("POST skipped: no WiFi");
    return 0;
  }
  syncClock();

  char ts[32];
  char body[256];
  if (isoTimestamp(ts, sizeof(ts))) {
    snprintf(body, sizeof(body),
      "{\"transformer_id\":\"%s\",\"voltage_v\":%.1f,\"current_a\":%.1f,\"temperature_c\":%.1f,\"status\":\"%s\",\"timestamp\":\"%s\"}",
      TRANSFORMER_ID, v, a, t, STATUS_NAME[st], ts);
  } else {  // clock not synced yet: omit the timestamp, the server stamps it on arrival
    snprintf(body, sizeof(body),
      "{\"transformer_id\":\"%s\",\"voltage_v\":%.1f,\"current_a\":%.1f,\"temperature_c\":%.1f,\"status\":\"%s\"}",
      TRANSFORMER_ID, v, a, t, STATUS_NAME[st]);
  }

  WiFiClientSecure client;
  client.setInsecure();  // demo only: skips certificate validation for the ngrok HTTPS URL
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/telemetry";
  if (!http.begin(client, url)) {
    Serial.println("HTTP begin() failed (check API_BASE_URL)");
    return -1;
  }
  http.setTimeout(4000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_API_KEY);
  http.addHeader("ngrok-skip-browser-warning", "true");

  int code = http.POST(body);
  if (code > 0) {
    Serial.printf("POST %s -> HTTP %d  %s\n", body, code, http.getString().c_str());
  } else {
    Serial.printf("POST failed: %s (%d)\n", HTTPClient::errorToString(code).c_str(), code);
  }
  http.end();
  return code;
}

// ───────────────── Setup / loop ─────────────────
void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.print("Belaku Kannu");
  lcd.setCursor(0, 1);
  lcd.print("Connecting WiFi");
  connectWiFi();
  syncClock();
}

unsigned long lastSend = 0;

void loop() {
  if (millis() - lastSend < SEND_INTERVAL_MS) return;
  lastSend = millis();

  // Potentiometers: 0..4095 -> 150..300 V and 0..100 A
  float voltage = 150.0 + analogRead(PIN_VOLT) * (150.0 / 4095.0);
  float current = analogRead(PIN_CURR) * (100.0 / 4095.0);
  float temp = dht.readTemperature();

  if (isnan(temp)) {  // sensor read failed: show it, do not send a made-up value
    Serial.println("DHT22 read failed, skipping this cycle");
    lcd.clear();
    lcd.print("DHT22 error");
    return;
  }

  Status st = evaluate(voltage, current, temp);

  // Local indicators (assumed behaviour: relay trips and buzzer sounds on CRITICAL)
  digitalWrite(PIN_LED_GREEN, st == SAFE);
  digitalWrite(PIN_LED_RED, st != SAFE);
  digitalWrite(PIN_BUZZER, st == CRITICAL);
  digitalWrite(PIN_RELAY, st == CRITICAL);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.printf("%3.0fV %4.1fA %2.0fC", voltage, current, temp);
  lcd.setCursor(0, 1);
  lcd.printf("%-8s %s", STATUS_NAME[st], WiFi.status() == WL_CONNECTED ? "WiFi" : "----");

  Serial.printf("V=%.1f A=%.1f T=%.1f -> %s\n", voltage, current, temp, STATUS_NAME[st]);
  postReading(voltage, current, temp, st);
}
