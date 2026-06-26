// Main sketch for the per-pack BMS monitor module.
//
// Flow on each loop iteration:
//   1. Pump any pending BMS UART bytes through the frame parser.
//   2. Every SEND_INTERVAL_MS, build a JSON payload from the latest
//      decoded frame and POST it to the server.
//
// Two safety nets:
//   - HW watchdog (ESP8266 reset if we ever lock up for > 8 s)
//   - WiFi reconnect: if WiFi drops we kick a reconnect; the parser
//     keeps running so we don't lose BMS data while offline.

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ArduinoOTA.h>
#include <WiFiClient.h>
#include <SoftwareSerial.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>

#include "config.h"
#include "secrets.h"
#include "jk_bms.h"

SoftwareSerial bmsSerial(BMS_RX_PIN, BMS_TX_PIN);
WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);

unsigned long lastFrameMs   = 0;
unsigned long lastSendMs    = 0;
unsigned long lastPublishMs = 0;
char mqttTopic[64];   // home/bms/<pack_id>/snapshot

void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);             // don't wear flash on every boot
    WiFi.setAutoReconnect(true);
    // Pin to a known IP so the server-side dashboards and OTA upload
    // commands can target this BMS module by IP without DHCP roulette.
    WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    Serial.print(F("WiFi: connecting"));
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
        delay(250);
        Serial.print('.');
        ESP.wdtFeed();
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\nWiFi: connected, ip=%s rssi=%d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
        Serial.println(F("\nWiFi: connect timeout, will retry in loop()"));
    }
}

void otaSetup() {
    // mDNS hostname per PACK_ID so each BMS in the fleet has a unique
    // bms-<pack>.local; the OTA password keeps random LAN clients from
    // flashing us.
    String hostname = String("bms-") + PACK_ID;
    ArduinoOTA.setHostname(hostname.c_str());
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() {
        Serial.println(F("OTA start"));
        // SoftwareSerial keeps emitting interrupts that starve the
        // OTA UDP packet handler and the flash session times out
        // mid-transfer. Stop it for the duration of the upload; the
        // ESP reboots into the new image so re-init isn't needed.
        bmsSerial.end();
    });
    ArduinoOTA.onEnd  ([]() { Serial.println(F("OTA done"));  });
    ArduinoOTA.onError([](ota_error_t e) {
        Serial.printf("OTA error %u\n", (unsigned)e);
    });
    // begin(false) disables mDNS — its periodic broadcasts hammer the
    // ESP8266 with interrupts that drop bytes on the 115200 BMS UART.
    // We push OTA by raw IP (192.168.1.22) instead of bms-<pack>.local.
    ArduinoOTA.begin(false);
    Serial.printf("OTA ready as %s\n", hostname.c_str());
}

void mqttEnsure() {
    if (mqtt.connected()) return;
    if (WiFi.status() != WL_CONNECTED) return;
    // Build a unique client id per pack so two BMSes don't kick each
    // other off the broker — the connect will keep retrying on
    // failure, but we only attempt once per loop iteration to avoid
    // blocking the parser.
    static unsigned long lastTry = 0;
    if (millis() - lastTry < 5000) return;
    lastTry = millis();

    String cid = String("bms-") + PACK_ID;
    if (mqtt.connect(cid.c_str())) {
        Serial.printf("MQTT connected as %s\n", cid.c_str());
    } else {
        Serial.printf("MQTT connect failed rc=%d\n", mqtt.state());
    }
}

void publishMqtt() {
    if (!mqtt.connected()) return;
    // Reuse the same payload as the HTTP POST so the web tile sees
    // the exact set of fields it gets from the InfluxDB snapshot.
    StaticJsonDocument<3072> doc;
    bool savedDebug = DEBUG_HEX_DUMP;
    // Never ship raw_recent over MQTT — the message would exceed
    // PubSubClient's default buffer cap and just gets dropped.
    if (savedDebug) {
        // Tiny scope hack: build the payload without the raw blob.
        // We avoid touching the const flag by guarding inside
        // buildPayload — see DEBUG_HEX_DUMP check there.
    }
    buildPayload(doc);
    doc.remove("raw_recent");

    char body[2048];
    size_t n = serializeJson(doc, body, sizeof(body));
    if (n == 0 || n >= sizeof(body)) {
        Serial.printf("MQTT payload too big (%u B), dropped\n", (unsigned)n);
        return;
    }
    // QoS 0, retain=true so a freshly-loaded /battery.html sees the
    // last snapshot the moment it subscribes instead of waiting up
    // to MQTT_PUBLISH_MS for the next sample.
    bool ok = mqtt.publish(mqttTopic, (const uint8_t*)body, n, true);
    if (!ok) Serial.println(F("MQTT publish returned false"));
}

void buildPayload(JsonDocument& doc) {
    const BmsData& d = jkGetLast();

    doc["pack_id"]      = PACK_ID;
    doc["uptime_s"]     = millis() / 1000;
    doc["wifi_rssi"]    = WiFi.RSSI();
    doc["bms_age_ms"]   = millis() - lastFrameMs;
    doc["valid"]        = d.valid;

    if (!d.valid) return;

    doc["cell_count"]   = d.cellCount;
    doc["cell_min_mv"]  = d.cellMinMv;
    doc["cell_max_mv"]  = d.cellMaxMv;
    doc["cell_avg_mv"]  = d.cellAvgMv;
    doc["cell_delta_mv"]= d.cellDeltaMv;

    JsonArray cells = doc.createNestedArray("cells_mv");
    for (uint8_t c = 0; c < d.cellCount && c < MAX_CELLS; c++) {
        cells.add(d.cellMv[c]);
    }

    doc["total_mv"]     = d.totalMv;
    doc["current_ma"]   = d.currentMa;
    doc["soc"]          = d.soc;

    JsonArray temps = doc.createNestedArray("temps_dC");
    for (uint8_t t = 0; t < d.tempCount; t++) temps.add(d.tempDeciC[t]);

    doc["cycle_count"]      = d.cycleCount;
    doc["cycle_cap_mah"]    = d.cycleCapacityMah;
    doc["remain_mah"]       = d.remainCapacityMah;
    doc["charge_mos"]       = d.chargeMosOn;
    doc["discharge_mos"]    = d.dischargeMosOn;
    doc["balancing"]        = d.balancing;

    // Rolling raw-byte capture — server logs it so we can reverse-
    // engineer frame layouts (temperatures, current, MOS state) without
    // a serial cable. Drop the field when DEBUG_HEX_DUMP is off so the
    // POST payload stays small in steady-state operation.
    if (DEBUG_HEX_DUMP) {
        static char hexBuf[1100];
        jkRecentBytes(hexBuf, sizeof(hexBuf));
        doc["raw_recent"] = hexBuf;
    }
}

void postToServer() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("WiFi not connected, skipping POST"));
        return;
    }

    StaticJsonDocument<4096> doc;
    buildPayload(doc);

    String body;
    serializeJson(doc, body);

    WiFiClient client;
    HTTPClient http;
    http.setTimeout(5000);

    if (!http.begin(client, SERVER_URL)) {
        Serial.println(F("http.begin failed"));
        return;
    }
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(body);
    Serial.printf("POST %s -> %d (body %u B)\n", SERVER_URL, code, body.length());
    http.end();
}

void setup() {
    Serial.begin(115200);
    delay(50);
    Serial.println();
    Serial.printf("bms.monitor boot, pack_id=%s, free heap=%u\n",
                  PACK_ID, ESP.getFreeHeap());

    bmsSerial.begin(BMS_BAUD);
    // INPUT_PULLUP holds the line idle-high if the BMS TX ever
    // momentarily tri-states; without it SoftwareSerial floats and
    // misframes every byte. Costs nothing.
    pinMode(BMS_RX_PIN, INPUT_PULLUP);
    // BMS_TX_PIN intentionally left as default; we don't transmit.

    connectWifi();
    otaSetup();

    // MQTT broker setup — default PubSubClient buffer is 256 B which
    // truncates our 14-cell snapshot; bump it before connecting.
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setBufferSize(2048);
    snprintf(mqttTopic, sizeof(mqttTopic), "home/bms/%s/snapshot", PACK_ID);
    Serial.printf("MQTT topic: %s\n", mqttTopic);

    ESP.wdtEnable(8000);   // 8 s watchdog
    lastSendMs = millis() - SEND_INTERVAL_MS;  // send immediately after first frame
}

void loop() {
    ESP.wdtFeed();
    // Service OTA every iteration so a flash request lands within
    // milliseconds, not at the next 30 s POST tick.
    ArduinoOTA.handle();

    // Drain whatever the BMS has pushed since last loop. Raw dump
    // gated on DEBUG_HEX_DUMP so we can flip it on for a bring-up
    // session (cell temp probes just got plugged in — need to spot
    // the new bytes the BMS started broadcasting) and back off for
    // steady-state operation.
    while (bmsSerial.available()) {
        uint8_t b = bmsSerial.read();
        if (DEBUG_HEX_DUMP) {
            static uint8_t rawCol = 0;
            Serial.printf("%02X ", b);
            if (++rawCol == 32) { Serial.println(); rawCol = 0; }
        }
        if (jkFeedByte(b)) {
            lastFrameMs = millis();
            if (DEBUG_HEX_DUMP) jkDumpLastFrame(Serial);
            const BmsData& d = jkGetLast();
            if (d.valid) {
                Serial.printf("BMS: %u cells, total=%.2fV, I=%.2fA, SOC=%u%%, min=%u mV max=%u mV delta=%u mV\n",
                              d.cellCount,
                              d.totalMv / 1000.0f,
                              d.currentMa / 1000.0f,
                              d.soc,
                              d.cellMinMv, d.cellMaxMv, d.cellDeltaMv);
            }
        }
    }

    if (WiFi.status() != WL_CONNECTED) {
        static uint32_t lastReconnectAttempt = 0;
        if (millis() - lastReconnectAttempt > 10000) {
            lastReconnectAttempt = millis();
            Serial.println(F("WiFi lost, reconnecting"));
            WiFi.reconnect();
        }
    }

    // Live MQTT feed — runs at MQTT_PUBLISH_MS so the dashboard
    // updates near-real-time. Reconnect logic is gentle (one attempt
    // per 5 s when disconnected) so a broker hiccup doesn't block
    // the BMS read loop.
    mqttEnsure();
    mqtt.loop();
    if (millis() - lastPublishMs >= MQTT_PUBLISH_MS) {
        lastPublishMs = millis();
        publishMqtt();
    }

    // Long-term history — same payload, much slower, sent to Influx
    // via the /bms HTTP endpoint.
    if (millis() - lastSendMs >= SEND_INTERVAL_MS) {
        lastSendMs = millis();
        postToServer();
    }

    delay(5);   // gentle yield, lets ESP8266 service WiFi stack
}
