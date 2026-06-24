#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <ESP8266WiFi.h>
#include <ArduinoOTA.h>
#include "config.h"
#include <debugutil.h>

Config_t config;

Adafruit_BME280 bme; // use I2C interface
Adafruit_Sensor *bme_temp = bme.getTemperatureSensor();
Adafruit_Sensor *bme_pressure = bme.getPressureSensor();
Adafruit_Sensor *bme_humidity = bme.getHumiditySensor();

// "Wait for X" loops bail out after this many ms and ESP.restart()
// rather than hanging until a manual power cycle. Long enough to ride
// out a router reboot, short enough to recover within one sample.
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 30000;
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

void publishSample() {
    float temperature = 0, humidity = 0, pressure = 0;
    sensors_event_t temp_event, pressure_event, humidity_event;

    // Real averaging: sample inside the loop. The old code called
    // getEvent once outside and summed the same value ten times.
    const int N = 10;
    for (int i = 0; i < N; i++) {
        bme_temp->getEvent(&temp_event);
        bme_pressure->getEvent(&pressure_event);
        bme_humidity->getEvent(&humidity_event);
        temperature += temp_event.temperature;
        humidity += humidity_event.relative_humidity;
        pressure += pressure_event.pressure;
        delay(50);
    }
    temperature /= N;
    humidity /= N;
    pressure /= N;

    WiFiClient client;
    client.setTimeout(HTTP_DEADLINE_MS);

    if (client.connect(SERVER_HOST, SERVER_PORT)) {
        SLOGLN("Sending request");
        // printf instead of String chains so the heap doesn't fragment
        // across thousands of wake cycles.
        if (bootReason.length()) {
            client.printf(
                "GET /sensorTemp?id=%u&t=%.2f&h=%.2f&p=%.2f&r=%s HTTP/1.1\r\n"
                "Host: %s\r\n"
                "Connection: close\r\n"
                "\r\n",
                (unsigned)SENSOR_ID, temperature, humidity, pressure,
                bootReason.c_str(), SERVER_HOST);
            bootReason = "";
        } else {
            client.printf(
                "GET /sensorTemp?id=%u&t=%.2f&h=%.2f&p=%.2f HTTP/1.1\r\n"
                "Host: %s\r\n"
                "Connection: close\r\n"
                "\r\n",
                (unsigned)SENSOR_ID, temperature, humidity, pressure, SERVER_HOST);
        }

        unsigned long start = millis();
        while ((client.connected() || client.available()) &&
               millis() - start < HTTP_DEADLINE_MS) {
            if (client.available()) {
                String line = client.readStringUntil('\n');
                SLOG(line);
            } else {
                yield();   // let the WiFi stack tick so WDT doesn't trip
            }
        }
        client.stop();

    } else {
        SLOG("connection failed!");
        client.stop();
    }

    SLOGF("Temperature = %.2f*C", temperature);
    SLOGF("Humidity = %.2f pct", humidity);
    SLOGF("Pressure = %.2fhPa", pressure);
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

    wifiConnect();
    otaSetup();
}

void loop() {
    publishSample();

    // Keep ArduinoOTA listening just long enough that you can flag a
    // flash from the LAN. Polling at ~20 Hz keeps OTA handshake latency
    // low; CPU draw during this window stays at ESP8266 STA-idle level.
    SLOGF("OTA window %u ms", (unsigned)OTA_WINDOW_MS);
    unsigned long until = millis() + OTA_WINDOW_MS;
    while ((long)(until - millis()) > 0) {
        ArduinoOTA.handle();
        delay(50);
    }

    // Power down for SAMPLE_INTERVAL_MS. Wake reruns setup() from cold,
    // which means a fresh reset reason rides along with the next
    // publish (it shows as 'Deep-Sleep_Wake' in the server log).
    SLOGF("Deep-sleep %u ms", (unsigned)SAMPLE_INTERVAL_MS);
    ESP.deepSleep((uint64_t)SAMPLE_INTERVAL_MS * 1000ULL);
}
