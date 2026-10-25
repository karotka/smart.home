// Grid meter module: reads the KLEFR 6914 (rebadged Inepro PRO1-Mod) over
// RS485 and publishes it to MQTT.
//
// Why this exists: there is no meter on the house supply, so "how much are
// we taking off the grid" has been answered by closing the energy balance
// from the other side — load + into_battery - PV. That is accurate while
// the inverter is on the grid, because the expression collapses to the
// measured load, but it is still arithmetic. This replaces it with a
// measurement from a MID-certified meter.
//
// ESP32 rather than ESP8266 for one reason: the hardware UART does parity.
// The meter runs 8E1 out of the factory, and neither an ESP8266 software
// serial nor a Raspberry Pi mini-UART can produce an even parity bit.
//
// Two things here exist because this meter is known to be hard to reach:
//
//   * if the configured link settings get no answer, the firmware sweeps
//     baud and parity at boot and uses whatever replies. The result goes
//     into the published payload as "link", so a board behind a cabinet
//     door can be diagnosed from the broker instead of with a laptop and
//     a screwdriver.
//   * the float word order is detected rather than configured, by asking
//     which order makes the voltage register land near mains. It is the
//     one question the meter can answer about itself.

#include <WiFi.h>
#include <ArduinoOTA.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>

#include "config.h"
#include "secrets.h"

WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);

static uint32_t linkBaud   = METER_BAUD;
static uint32_t linkConfig = METER_CONFIG;
static bool     linkFound  = false;
static bool     wordSwap   = false;
static char     linkDesc[32] = "nenavazano";

static unsigned long lastPollMs     = 0;
static unsigned long lastRelinkMs   = 0;
static unsigned long lastPublishOkMs = 0;
static bool          softKicked     = false;
static uint32_t      readOk = 0, readFail = 0;

// ---------------------------------------------------------------- modbus

static uint16_t crc16(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t b = 0; b < 8; b++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}

// Read `count` 16-bit registers into `out`. Returns false on timeout, CRC
// error, or a Modbus exception.
static bool modbusRead(uint16_t reg, uint16_t count, uint16_t* out) {
    uint8_t req[8];
    req[0] = METER_ADDRESS;
    req[1] = 0x03;                      // holding registers
    req[2] = reg >> 8;   req[3] = reg & 0xFF;
    req[4] = count >> 8; req[5] = count & 0xFF;
    uint16_t c = crc16(req, 6);
    req[6] = c & 0xFF;   req[7] = c >> 8;

    while (Serial2.available()) Serial2.read();

    // Hold the driver enabled until the last stop bit is actually on the
    // wire. write() only queues; flush() is what waits. Dropping DE early
    // truncates the frame and the meter answers nothing — which looks
    // exactly like wrong serial settings and sends you hunting elsewhere.
    digitalWrite(RS485_DE_PIN, HIGH);
    Serial2.write(req, sizeof(req));
    Serial2.flush();
    digitalWrite(RS485_DE_PIN, LOW);

    const size_t want = 5 + 2 * count;
    uint8_t resp[64];
    if (want > sizeof(resp)) return false;

    size_t got = 0;
    unsigned long deadline = millis() + MODBUS_TIMEOUT_MS;
    while (got < want && millis() < deadline) {
        if (Serial2.available()) resp[got++] = Serial2.read();
        else delay(1);
    }
    if (got < want) return false;
    if (resp[0] != METER_ADDRESS || resp[1] != 0x03) return false;
    if (crc16(resp, want - 2) != (uint16_t)(resp[want - 2] | (resp[want - 1] << 8)))
        return false;

    for (uint16_t i = 0; i < count; i++)
        out[i] = (resp[3 + 2 * i] << 8) | resp[4 + 2 * i];
    return true;
}

static bool readFloat(uint16_t reg, float* value) {
    uint16_t r[2];
    if (!modbusRead(reg, 2, r)) return false;
    uint32_t bits = wordSwap ? ((uint32_t)r[1] << 16) | r[0]
                             : ((uint32_t)r[0] << 16) | r[1];
    memcpy(value, &bits, sizeof(bits));
    return isfinite(*value);
}

// ------------------------------------------------------------------ link

static void openLink(uint32_t baud, uint32_t cfg) {
    Serial2.end();
    delay(20);
    Serial2.begin(baud, cfg, RS485_RX_PIN, RS485_TX_PIN);
    delay(50);
}

static const char* configName(uint32_t cfg) {
    if (cfg == SERIAL_8E1) return "8E1";
    if (cfg == SERIAL_8N1) return "8N1";
    if (cfg == SERIAL_8O1) return "8O1";
    return "?";
}

// Try both word orders on the voltage register and keep the one that
// produces a plausible mains voltage. The wrong order gives values like
// 3.7e-19, so the test is not subtle.
static bool detectWordOrder() {
    for (int swap = 0; swap < 2; swap++) {
        wordSwap = swap;
        float v;
        if (readFloat(METER_REGISTERS[0].address, &v) && v > 180.0f && v < 280.0f) {
            Serial.printf("poradi slov: %s (napeti %.1f V)\n",
                          swap ? "prohozene" : "prime", v);
            return true;
        }
    }
    return false;
}

// Try the configured settings, then sweep. The meter supports 1200..9600
// and all three parities; sixteen combinations is a couple of seconds.
static bool establishLink() {
    const uint32_t bauds[]   = { METER_BAUD, 9600, 4800, 2400, 1200 };
    const uint32_t configs[] = { METER_CONFIG, SERIAL_8E1, SERIAL_8N1, SERIAL_8O1 };

    for (size_t b = 0; b < sizeof(bauds) / sizeof(bauds[0]); b++) {
        for (size_t c = 0; c < sizeof(configs) / sizeof(configs[0]); c++) {
            openLink(bauds[b], configs[c]);
            uint16_t probe[2];
            if (!modbusRead(METER_REGISTERS[0].address, 2, probe)) {
                if (!METER_AUTODETECT) return false;
                continue;
            }
            linkBaud = bauds[b];
            linkConfig = configs[c];
            if (!detectWordOrder()) continue;
            snprintf(linkDesc, sizeof(linkDesc), "%u %s addr %u",
                     (unsigned)linkBaud, configName(linkConfig),
                     (unsigned)METER_ADDRESS);
            Serial.printf("merak nalezen: %s\n", linkDesc);
            return true;
        }
    }
    snprintf(linkDesc, sizeof(linkDesc), "nenavazano");
    Serial.println(F("merak neodpovida na zadne kombinaci"));
    return false;
}

// --------------------------------------------------------------- network

static void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    Serial.print(F("WiFi: pripojuji"));
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
        delay(250);
        Serial.print('.');
    }
    if (WiFi.status() == WL_CONNECTED)
        Serial.printf("\nWiFi: %s rssi=%d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    else
        Serial.println(F("\nWiFi: timeout, zkusim znovu v loop()"));
}

static void otaSetup() {
    ArduinoOTA.setHostname(MQTT_CLIENT);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.begin();
}

static void mqttEnsure() {
    if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
    static unsigned long lastTry = 0;
    if (millis() - lastTry < 5000) return;
    lastTry = millis();
    if (mqtt.connect(MQTT_CLIENT))
        Serial.println(F("MQTT pripojeno"));
    else
        Serial.printf("MQTT selhalo rc=%d\n", mqtt.state());
}

// --------------------------------------------------------------- publish

static void pollAndPublish() {
    StaticJsonDocument<768> doc;
    doc["meter"] = "grid";
    doc["link"]  = linkDesc;            // diagnosable from the broker alone
    doc["rssi"]  = WiFi.RSSI();

    uint8_t good = 0;
    if (linkFound) {
        for (size_t i = 0; i < METER_REGISTER_COUNT; i++) {
            float v;
            if (readFloat(METER_REGISTERS[i].address, &v)) {
                doc[METER_REGISTERS[i].field] = v * METER_REGISTERS[i].scale;
                good++;
            }
        }
    }
    if (good) readOk++; else readFail++;
    // A register the meter does not implement answers with an exception,
    // so a partial read is normal rather than a fault. Say how much of the
    // map answered and let the server decide what it trusts.
    doc["registers_ok"] = good;
    doc["read_ok"]   = readOk;
    doc["read_fail"] = readFail;

    if (!mqtt.connected()) return;
    char body[768];
    size_t n = serializeJson(doc, body, sizeof(body));
    if (n == 0 || n >= sizeof(body)) return;
    // Retained, like the BMS snapshots: a freshly loaded page sees the
    // last reading at once instead of waiting for the next poll.
    if (mqtt.publish(MQTT_TOPIC, (const uint8_t*)body, n, true)) {
        lastPublishOkMs = millis();
        softKicked = false;
    }
}

// ------------------------------------------------------------------ main

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println(F("\ngridmeter"));

    pinMode(RS485_DE_PIN, OUTPUT);
    digitalWrite(RS485_DE_PIN, LOW);     // listening until we have something to say

    connectWifi();
    otaSetup();
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
    mqtt.setSocketTimeout(MQTT_SOCKET_TIMEOUT_S);

    linkFound = establishLink();
    lastPublishOkMs = millis();
}

void loop() {
    ArduinoOTA.handle();
    if (WiFi.status() != WL_CONNECTED) connectWifi();
    mqttEnsure();
    mqtt.loop();

    if (millis() - lastPollMs >= POLL_INTERVAL_MS) {
        lastPollMs = millis();
        // Keep retrying the link rather than needing a power cycle: the
        // meter may simply have been unpowered when the board booted.
        // Rate-limited because the sweep blocks for several seconds and
        // running it every poll would starve OTA — which is the one thing
        // that must keep working when the meter does not.
        if (!linkFound && millis() - lastRelinkMs >= RELINK_INTERVAL_MS) {
            lastRelinkMs = millis();
            linkFound = establishLink();
        }
        pollAndPublish();
    }

    unsigned long dead = millis() - lastPublishOkMs;
    if (dead > MQTT_DEAD_HARD_MS) {
        Serial.println(F("sentinel: restart"));
        ESP.restart();
    } else if (dead > MQTT_DEAD_SOFT_MS && !softKicked) {
        Serial.println(F("sentinel: kopnuti do WiFi"));
        softKicked = true;
        mqtt.disconnect();
        WiFi.disconnect();
        connectWifi();
    }
}
