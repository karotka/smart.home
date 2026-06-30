#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <U8g2lib.h>
#include <ESP8266WiFi.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "config.h"
#include <debugutil.h>

WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);
unsigned long lastDisplayMs = 0;
unsigned long lastPublishMs = 0;
// Latest measurement — refreshed every DISPLAY_INTERVAL_MS so both
// the OLED and the next server publish see the same numbers.
float gTemperature = 0;
float gHumidity    = 0;
float gPressure    = 0;
bool  gHaveSample  = false;

Config_t config;

Adafruit_BME280 bme; // use I2C interface
Adafruit_Sensor *bme_temp = bme.getTemperatureSensor();
Adafruit_Sensor *bme_pressure = bme.getPressureSensor();
Adafruit_Sensor *bme_humidity = bme.getHumiditySensor();

// 0.96" / 1.3" OLED on the I2C bus (same wires as BME280, different
// address). Cheap clones answer at 0x3C but split between two
// controllers — SSD1306 with 128x64 1:1 framebuffer, and SH1106
// with a 132x64 frame that you have to write with a 2-px X-offset.
// u8g2 handles the latter case transparently; declaring SH1106
// gracefully covers SSD1306-as-SH1106 mis-clones (the more common
// failure mode) at a small RAM cost. F_ = full framebuffer (1 KB).
U8G2_SH1106_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
bool oledOk = false;

// "Wait for X" loops bail out after this many ms and ESP.restart()
// rather than hanging until a manual power cycle. Long enough to ride
// out a router reboot, short enough to recover within one sample.
// 60 s instead of the old 30 s — in marginal-RSSI spots the ESP8266 can
// take 20-40 s to associate (router being busy, multipath, retransmits)
// and a too-tight timeout sends the chip into a restart loop that drains
// the battery far faster than a slow handshake would.
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 60000;
const unsigned long HTTP_DEADLINE_MS        = 5000;

// Reason for the most recent reset, captured at boot and shipped with
// the next publish so the server log can tell power-on / WDT / soft
// restart apart. Cleared after that one publish.
String bootReason = "";

void wifiConnect() {

    if (config.ap) {
        WiFi.disconnect();
        WiFi.softAPConfig(
            IPAddress(192,168,5,10),
            IPAddress(192,168,5,1),
            IPAddress(255,255,255,0));
        WiFi.softAP(config.hostname);
        return;
    } else {
        WiFi.mode(WIFI_STA);
    }

    if (!config.dhcp) {
        WiFi.config(config.ip, config.dns, config.gateway, config.subnet);
        SLOGLN("WiFi in static mode");
    } else {
        SLOGLN("WiFi in DHCP mode");
    }

    WiFi.begin(config.ssid.c_str(), config.password.c_str());

    bool st = true;
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_CONNECT_TIMEOUT_MS) {
            SLOGLN("WiFi timeout, rebooting");
            ESP.restart();
        }
        SLOG(".");
        delay(500);
        digitalWrite(LED_BUILTIN, st ? HIGH : LOW);
        st = !st;
    }
    SLOGLN("");
    SLOGLN("WiFi connected: ");
    SLOGF("http://%s/", WiFi.localIP().toString().c_str());
    digitalWrite(LED_BUILTIN, HIGH);   // off (active-low on most boards)
}

void otaSetup() {
    char hostname[32];
    // mDNS hostname uses SENSOR_ID so it stays unique even when two
    // boards share a chip ID.
    snprintf(hostname, sizeof(hostname), "temp-%u", (unsigned)SENSOR_ID);
    ArduinoOTA.setHostname(hostname);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() { SLOGLN("OTA start"); });
    ArduinoOTA.onEnd  ([]() { SLOGLN("OTA done");  });
    ArduinoOTA.onError([](ota_error_t e) {
        SLOGF("OTA error %u", (unsigned)e);
    });
    ArduinoOTA.begin();
    SLOGF("OTA ready as %s", hostname);
}

// Sample the BME280 and refresh the OLED. Called every
// DISPLAY_INTERVAL_MS so the hero number visibly tracks the
// environment, even between the slower server publishes. Mutates
// the gTemperature / gHumidity / gPressure globals so the next
// server-publish tick sees the freshest values without re-reading.
void readSample() {
    float temperature = 0, humidity = 0, pressure = 0;
    sensors_event_t temp_event, pressure_event, humidity_event;

    // Real averaging — N = 5 here (was 10) because we run the read
    // 6× as often now. Total IIR weight over a publish window is
    // still 30 samples.
    const int N = 5;
    for (int i = 0; i < N; i++) {
        bme_temp->getEvent(&temp_event);
        bme_pressure->getEvent(&pressure_event);
        bme_humidity->getEvent(&humidity_event);
        temperature += temp_event.temperature;
        humidity    += humidity_event.relative_humidity;
        pressure    += pressure_event.pressure;
        delay(50);
    }
    gTemperature = temperature / N + TEMP_OFFSET_C;
    gHumidity    = humidity    / N;
    gPressure    = pressure    / N;
    gHaveSample  = true;

    SLOGF("Sample t=%.2f h=%.2f p=%.2f", gTemperature, gHumidity, gPressure);
    renderOled(gTemperature, gHumidity, gPressure);
}

// Push the latest sample to the central HTTP endpoint and to
// the MQTT broker. Both feeds carry the same number so dashboards
// downstream don't have to reconcile two readings.
void publishToServer() {
    if (!gHaveSample) return;

    long rssi = WiFi.RSSI();

    // ---- HTTP ----
    WiFiClient client;
    client.setTimeout(HTTP_DEADLINE_MS);

    if (client.connect(SERVER_HOST, SERVER_PORT)) {
        SLOGLN("Sending HTTP");
        if (bootReason.length()) {
            client.printf(
                "GET /sensorTemp?id=%u&t=%.2f&h=%.2f&p=%.2f&r=%s&s=%ld HTTP/1.1\r\n"
                "Host: %s\r\n"
                "Connection: close\r\n"
                "\r\n",
                (unsigned)SENSOR_ID, gTemperature, gHumidity, gPressure,
                bootReason.c_str(), rssi, SERVER_HOST);
            bootReason = "";
        } else {
            client.printf(
                "GET /sensorTemp?id=%u&t=%.2f&h=%.2f&p=%.2f&s=%ld HTTP/1.1\r\n"
                "Host: %s\r\n"
                "Connection: close\r\n"
                "\r\n",
                (unsigned)SENSOR_ID, gTemperature, gHumidity, gPressure, rssi, SERVER_HOST);
        }

        unsigned long start = millis();
        while ((client.connected() || client.available()) &&
               millis() - start < HTTP_DEADLINE_MS) {
            if (client.available()) {
                String line = client.readStringUntil('\n');
                SLOG(line);
            } else {
                yield();
            }
        }
        client.stop();
    } else {
        SLOG("HTTP connect failed");
        client.stop();
    }

    // ---- MQTT ----
    if (!mqtt.connected()) {
        // Single connect attempt per publish tick; if it fails we
        // just skip MQTT for this round and try again in 30 s.
        char cid[24];
        snprintf(cid, sizeof(cid), "temp-%u", (unsigned)SENSOR_ID);
        if (mqtt.connect(cid)) {
            SLOGF("MQTT connected as %s", cid);
        } else {
            SLOGF("MQTT connect failed rc=%d", mqtt.state());
        }
    }
    if (mqtt.connected()) {
        char payload[128];
        int n = snprintf(payload, sizeof(payload),
            "{\"id\":%u,\"t\":%.2f,\"h\":%.2f,\"p\":%.2f,\"rssi\":%ld}",
            (unsigned)SENSOR_ID, gTemperature, gHumidity, gPressure, rssi);
        if (n > 0 && n < (int)sizeof(payload)) {
            bool ok = mqtt.publish(MQTT_TOPIC, payload, true);  // retained
            SLOGF("MQTT publish %s -> %d", MQTT_TOPIC, (int)ok);
        }
    }
}

void setup() {
#ifdef DEBUG
    Serial.begin(115200);
#endif
    // Explicit WDT in case the default is generous on whatever SDK
    // this gets built against. 8 s is long enough for I2C + WiFi
    // handshake, tight enough to catch a real hang.
    ESP.wdtEnable(8000);

    bootReason = ESP.getResetReason();
    bootReason.replace(' ', '_');   // URL-friendly

    // Sweep I2C and dump any device's chip-ID register (0xD0 on every
    // Bosch BME/BMP). BME280 returns 0x60, BMP280 returns 0x58/57/56;
    // silence on the bus means the breakout isn't wired right. Cheap
    // diagnostic that runs before we conclude bme.begin() failed.
    Wire.begin();
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() != 0) continue;
        Wire.beginTransmission(addr);
        Wire.write(0xD0);
        Wire.endTransmission();
        Wire.requestFrom(addr, (uint8_t)1);
        uint8_t chipId = Wire.available() ? Wire.read() : 0;
        SLOGF("I2C 0x%02X chipId=0x%02X", addr, chipId);
    }

    // Try both BME280 I2C addresses — boards with SDO tied to GND use
    // 0x76 (Adafruit lib defaults to 0x77, which silently failed on the
    // module flashed for this node).
    if (!bme.begin(0x76) && !bme.begin(0x77)) {
        SLOGLN("Could not find a valid BME280 sensor!");
        // Soft restart so one bad I2C boot doesn't park the node
        // forever; the old while(1)delay(10) wedged here because
        // delay() feeds the watchdog. Long enough for serial to drain.
        delay(2000);
        ESP.restart();
    }
    SLOGLN("BME connected");

    // u8g2 begin() doesn't return success/fail; we trust the I2C
    // scan above already proved 0x3C is alive on the bus.
    oled.setI2CAddress(0x3C << 1);  // u8g2 wants the 8-bit form
    oled.begin();
    oledOk = true;
    SLOGLN("OLED begin() done");

    // Splash so we instantly know if the panel actually drives.
    // First sample lands a few seconds later and replaces this.
    oled.clearBuffer();
    oled.setFont(u8g2_font_logisoso24_tr);
    oled.drawStr(0, 40, "boot");
    oled.sendBuffer();

    wifiConnect();
    otaSetup();

    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    SLOGF("MQTT broker %s:%d topic %s",
          MQTT_BROKER, MQTT_PORT, MQTT_TOPIC);
}

// Repaint the OLED with the latest reading. Layout (128x64, u8g2
// uses y = baseline of the text). No header — the SENSOR_ID is on
// the box, the screen is for the live measurement only.
//   y=30  big   "28.4 C"      (28 px digits + ~24 px C)
//   y=50  med   "47%  975 hPa"
//   y=64  small "192.168.0.11  -67dBm"
void renderOled(float t, float h, float p) {
    if (!oledOk) return;
    char buf[40];

    oled.clearBuffer();

    // Hero number with a unit letter sized to match. logisoso28_tn
    // is digits only, logisoso24_tr carries the C — pick the closest
    // bigger font available without overshooting the 64 px height.
    oled.setFont(u8g2_font_logisoso28_tn);
    snprintf(buf, sizeof(buf), "%.1f", t);
    oled.drawStr(0, 30, buf);
    int xC = oled.getStrWidth(buf);
    oled.setFont(u8g2_font_logisoso24_tr);
    oled.drawStr(xC + 4, 30, "C");

    // Bumping humidity + pressure to 9x15 makes the secondary row
    // ~50 % taller than the 6x10 default, still half the hero size
    // so the visual hierarchy reads at a glance.
    oled.setFont(u8g2_font_9x15_tr);
    snprintf(buf, sizeof(buf), "%.0f%%  %.0fhPa", h, p);
    oled.drawStr(0, 50, buf);

    // Footer keeps the small font — IP + RSSI are diagnostic, not
    // the thing someone walking past should read first.
    oled.setFont(u8g2_font_6x10_tr);
    snprintf(buf, sizeof(buf), "%s  %lddBm",
             WiFi.localIP().toString().c_str(),
             WiFi.RSSI());
    oled.drawStr(0, 64, buf);

    oled.sendBuffer();
}

void loop() {
#if DEEP_SLEEP
    // Battery mode hasn't changed: wake, publish once, OTA-listen
    // briefly, deep-sleep until the next interval.
    readSample();
    publishToServer();
    SLOGF("OTA window %u ms", (unsigned)OTA_WINDOW_MS);
    unsigned long until = millis() + OTA_WINDOW_MS;
    while ((long)(until - millis()) > 0) {
        ArduinoOTA.handle();
        delay(50);
    }
    SLOGF("Deep-sleep %u ms", (unsigned)SAMPLE_INTERVAL_MS);
    ESP.deepSleep((uint64_t)SAMPLE_INTERVAL_MS * 1000ULL);
#else
    // Always-on bench mode. Two timers tick in parallel:
    //   * readSample()       — every DISPLAY_INTERVAL_MS  (5 s)
    //   * publishToServer()  — every PUBLISH_INTERVAL_MS (30 s)
    // ArduinoOTA + mqtt.loop run on every iteration so an OTA
    // invitation or a broker keep-alive lands within milliseconds.
    unsigned long now = millis();

    if (lastDisplayMs == 0 || now - lastDisplayMs >= DISPLAY_INTERVAL_MS) {
        lastDisplayMs = now;
        readSample();
    }
    if (lastPublishMs == 0 || now - lastPublishMs >= PUBLISH_INTERVAL_MS) {
        lastPublishMs = now;
        publishToServer();
    }

    ArduinoOTA.handle();
    mqtt.loop();
    delay(50);
#endif
}
